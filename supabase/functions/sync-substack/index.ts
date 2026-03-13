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

Deno.serve(async () => {
  try {
    const [sitemapEntries, postMeta] = await Promise.all([
      fetchSitemapEntries(),
      fetchAllPostMeta(),
    ]);

    const { data: existingLinks } = await supabase.from("links").select("slug");
    const existingSlugs = new Set((existingLinks || []).map((l) => l.slug));

    const newEntries = sitemapEntries.filter((entry) => {
      const slug = entry.url.split("/p/").pop()?.replace(/\/$/, "") || "";
      return !existingSlugs.has(slug);
    });

    if (newEntries.length === 0) {
      return new Response(JSON.stringify({ message: "No new articles", checked: sitemapEntries.length }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    const { data: personSources, error: sourcesError } = await supabase
      .from("person_sources")
      .select("person_id, utm_source, utm_medium, utm_content, utm_term");
    if (sourcesError) throw sourcesError;

    const { data: people, error: peopleError } = await supabase.from("people").select("id, slug");
    if (peopleError) throw peopleError;
    const peopleById = new Map((people || []).map((p) => [p.id, p.slug]));

    const created: string[] = [];

    for (const entry of newEntries) {
      const slug = entry.url.split("/p/").pop()?.replace(/\/$/, "") || "";
      const meta = postMeta.get(slug);
      const insertData: Record<string, unknown> = {
        slug,
        destination_url: meta?.canonical_url || entry.url,
        title: meta?.title || slug,
        author: meta?.publishedBylines?.[0]?.name || null,
      };
      if (entry.lastmod) insertData.published_at = entry.lastmod;

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
    }

    return new Response(JSON.stringify({
      message: `Created ${created.length} new links`,
      created,
      checked: sitemapEntries.length,
    }), {
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    console.error("Sync error:", error);
    return new Response(JSON.stringify({ error: String(error) }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});
