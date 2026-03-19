import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

const SUBSTACK_URL = "https://trilogyai.substack.com";

interface SitemapEntry {
  url: string;
  lastmod: string | null;
}

interface ApiPost {
  slug: string;
  title: string;
  canonical_url?: string;
  publishedBylines?: Array<{ name?: string }>;
}

async function fetchSitemapEntries(): Promise<SitemapEntry[]> {
  const resp = await fetch(`${SUBSTACK_URL}/sitemap.xml`);
  const xml = await resp.text();

  const entries: SitemapEntry[] = [];
  const urlBlockRegex = /<url>([\s\S]*?)<\/url>/g;
  let block;
  while ((block = urlBlockRegex.exec(xml)) !== null) {
    const locMatch = block[1].match(/<loc>([^<]*\/p\/[^<]*)<\/loc>/);
    if (locMatch) {
      const lastmodMatch = block[1].match(/<lastmod>([^<]*)<\/lastmod>/);
      entries.push({
        url: locMatch[1],
        lastmod: lastmodMatch ? lastmodMatch[1] : null,
      });
    }
  }
  return entries;
}

async function fetchAllPostMeta(): Promise<Map<string, ApiPost>> {
  const posts = new Map<string, ApiPost>();
  let offset = 0;
  while (true) {
    const resp = await fetch(`${SUBSTACK_URL}/api/v1/posts?limit=50&offset=${offset}`, {
      headers: { "User-Agent": "Mozilla/5.0" },
    });
    if (!resp.ok) break;
    const batch = (await resp.json()) as ApiPost[];
    if (!batch.length) break;
    for (const post of batch) posts.set(post.slug, post);
    offset += 50;
  }
  return posts;
}

async function authenticateRequest(req: Request): Promise<boolean> {
  const authHeader = req.headers.get("Authorization");
  if (!authHeader?.startsWith("Bearer ")) return false;
  const token = authHeader.slice(7);
  const { data: { user }, error } = await supabase.auth.getUser(token);
  return !error && !!user;
}

Deno.serve(async (req) => {
  // CORS headers for browser requests
  const corsHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  };

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  // Check for force param (manual trigger)
  const url = new URL(req.url);
  const force = url.searchParams.get("force") === "true";

  // If Authorization header is present, validate it
  const authHeader = req.headers.get("Authorization");
  if (authHeader) {
    const isAuthenticated = await authenticateRequest(req);
    if (!isAuthenticated) {
      return new Response(JSON.stringify({ error: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      });
    }
  }

  try {
    const [sitemapEntries, postMeta] = await Promise.all([
      fetchSitemapEntries(),
      fetchAllPostMeta(),
    ]);

    const { data: existingLinks } = await supabase
      .from("links")
      .select("id, slug, title, author, published_at, destination_url, last_synced_at");
    const existingBySlug = new Map(
      (existingLinks || []).map((l) => [l.slug, l]),
    );
    // Also index by destination_url (normalised without trailing slash) so we
    // can detect custom links that point to the same Substack article URL but
    // were created with a random slug via "als shorten".
    const existingByUrl = new Map(
      (existingLinks || []).map((l) => [l.destination_url.replace(/\/+$/, ""), l]),
    );

    const { data: personSources, error: sourcesError } = await supabase
      .from("person_sources")
      .select("person_id, utm_source, utm_medium, utm_content, utm_term");
    if (sourcesError) throw sourcesError;

    const { data: people, error: peopleError } = await supabase.from("people").select("id, slug");
    if (peopleError) throw peopleError;
    const peopleById = new Map((people || []).map((p) => [p.id, p.slug]));

    const created: string[] = [];
    const updated: string[] = [];
    const skipped: string[] = [];
    const now = new Date().toISOString();

    for (const entry of sitemapEntries) {
      const slug = entry.url.split("/p/").pop()?.replace(/\/$/, "") || "";

      // Skip restacks: only the Substack posts API returns original posts.
      // Any sitemap slug not found in postMeta is a restack (someone else's
      // post reshared to the trilogyai feed) and should not be imported.
      if (!postMeta.has(slug)) {
        skipped.push(slug);
        continue;
      }

      const meta = postMeta.get(slug);
      const newTitle = meta?.title || slug;
      const newAuthor = meta?.publishedBylines?.[0]?.name || null;
      const newPublishedAt = entry.lastmod || null;
      const newDestUrl = meta?.canonical_url || entry.url;

      const existing = existingBySlug.get(slug);
      // Check if a link already exists for this URL under a different slug
      // (e.g. created via "als shorten" with a random slug).
      const urlNorm = newDestUrl.replace(/\/+$/, "");
      const existingByUrlMatch = !existing ? existingByUrl.get(urlNorm) : null;

      if (!existing && !existingByUrlMatch) {
        // INSERT new article — no match by slug or URL
        const insertData: Record<string, unknown> = {
          slug,
          destination_url: newDestUrl,
          title: newTitle,
          author: newAuthor,
          last_synced_at: now,
        };
        if (newPublishedAt) insertData.published_at = newPublishedAt;

        const { data: linkData, error: linkError } = await supabase
          .from("links")
          .insert(insertData)
          .select()
          .single();
        if (linkError) {
          console.error(`Error creating link ${slug}:`, linkError);
          continue;
        }

        created.push(slug);

        // Create tracking variants for all person sources
        for (const source of personSources || []) {
          const ref = peopleById.get(source.person_id);
          if (!ref) continue;
          const { error } = await supabase.rpc("ensure_tracking_variant", {
            p_link_id: linkData.id,
            p_ref: ref,
            p_source: source.utm_source,
            p_medium: source.utm_medium,
            p_content: source.utm_content,
            p_term: source.utm_term,
          });
          if (error) {
            console.error(`Error creating variant for ${slug}/${ref}:`, error);
          }
        }
      } else if (existingByUrlMatch && !existing) {
        // A link exists for this URL but under a different slug (custom link).
        // Update its metadata with Substack info so it becomes a "proper" synced article.
        const changes: Record<string, unknown> = { last_synced_at: now };
        if (existingByUrlMatch.title !== newTitle) changes.title = newTitle;
        if (existingByUrlMatch.author !== newAuthor) changes.author = newAuthor;
        if (newPublishedAt && existingByUrlMatch.published_at !== newPublishedAt) {
          changes.published_at = newPublishedAt;
        }

        const { error: updateError } = await supabase
          .from("links")
          .update(changes)
          .eq("id", existingByUrlMatch.id);
        if (updateError) {
          console.error(`Error updating custom link for ${slug}:`, updateError);
          continue;
        }

        const hasMetadataChanges = Object.keys(changes).length > 1;
        if (hasMetadataChanges) {
          updated.push(slug);
        }

        // Ensure tracking variants exist for the custom link too
        for (const source of personSources || []) {
          const ref = peopleById.get(source.person_id);
          if (!ref) continue;
          const { error } = await supabase.rpc("ensure_tracking_variant", {
            p_link_id: existingByUrlMatch.id,
            p_ref: ref,
            p_source: source.utm_source,
            p_medium: source.utm_medium,
            p_content: source.utm_content,
            p_term: source.utm_term,
          });
          if (error) {
            console.error(`Error creating variant for ${slug}/${ref}:`, error);
          }
        }
      } else if (existing && (force || !existing.last_synced_at)) {
        // UPDATE existing article if metadata changed
        const changes: Record<string, unknown> = {};

        if (existing.title !== newTitle) changes.title = newTitle;
        if (existing.author !== newAuthor) changes.author = newAuthor;
        if (existing.destination_url !== newDestUrl) changes.destination_url = newDestUrl;
        if (newPublishedAt && existing.published_at !== newPublishedAt) {
          changes.published_at = newPublishedAt;
        }

        // Always update last_synced_at
        changes.last_synced_at = now;

        const hasMetadataChanges = Object.keys(changes).length > 1; // more than just last_synced_at

        const { error: updateError } = await supabase
          .from("links")
          .update(changes)
          .eq("id", existing.id);
        if (updateError) {
          console.error(`Error updating link ${slug}:`, updateError);
          continue;
        }

        if (hasMetadataChanges) {
          updated.push(slug);
        }
      }
    }

    return new Response(JSON.stringify({
      message: `Created ${created.length}, updated ${updated.length} links (skipped ${skipped.length} restacks)`,
      created,
      updated,
      skipped,
      checked: sitemapEntries.length,
    }), {
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  } catch (error) {
    console.error("Sync error:", error);
    return new Response(JSON.stringify({ error: String(error) }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
});
