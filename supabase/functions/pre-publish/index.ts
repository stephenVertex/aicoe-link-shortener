import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

const DOMAIN = "aicoe.fit";
const SUBSTACK_BASE = "https://trilogyai.substack.com/p/";

interface PersonInfo {
  id: string;
  name: string;
  slug: string;
  email: string;
}

async function validateApiKey(apiKey: string): Promise<PersonInfo | null> {
  const { data, error } = await supabase.rpc("validate_api_key", {
    p_api_key: apiKey,
  });
  if (error || !data) return null;
  return data as PersonInfo;
}

Deno.serve(async (req) => {
  const corsHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers":
      "authorization, x-client-info, apikey, content-type, x-api-key",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  };

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  // Parse request
  let apiKey = req.headers.get("x-api-key") || "";
  let slugOrUrl = "";

  if (req.method === "POST") {
    try {
      const body = await req.json();
      apiKey = apiKey || body.api_key || "";
      slugOrUrl = body.slug_or_url || body.url || body.slug || "";
    } catch {
      return new Response(
        JSON.stringify({ error: "Invalid JSON body" }),
        { status: 400, headers: { "Content-Type": "application/json", ...corsHeaders } },
      );
    }
  } else {
    const url = new URL(req.url);
    apiKey = apiKey || url.searchParams.get("api_key") || "";
    slugOrUrl = url.searchParams.get("slug_or_url") || url.searchParams.get("url") || url.searchParams.get("slug") || "";
  }

  // Validate API key
  if (!apiKey) {
    return new Response(
      JSON.stringify({ error: "API key required. Pass via x-api-key header." }),
      { status: 401, headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

  const caller = await validateApiKey(apiKey);
  if (!caller) {
    return new Response(
      JSON.stringify({ error: "Invalid API key" }),
      { status: 401, headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

  if (!slugOrUrl) {
    return new Response(
      JSON.stringify({ error: "slug_or_url parameter required" }),
      { status: 400, headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

  // Extract slug from URL or use as-is
  let slug: string;
  let destinationUrl: string;

  if (slugOrUrl.startsWith("http://") || slugOrUrl.startsWith("https://")) {
    // Validate it's a trilogyai.substack.com/p/ URL
    const match = slugOrUrl.match(/trilogyai\.substack\.com\/p\/([^/?#]+)/);
    if (!match) {
      return new Response(
        JSON.stringify({ error: "URL must be a trilogyai.substack.com/p/<slug> URL" }),
        { status: 400, headers: { "Content-Type": "application/json", ...corsHeaders } },
      );
    }
    slug = match[1].replace(/\/$/, "");
    destinationUrl = slugOrUrl.replace(/\/$/, "");
  } else {
    // Treat as bare slug
    slug = slugOrUrl.replace(/\/$/, "");
    destinationUrl = SUBSTACK_BASE + slug;
  }

  // Check if link already exists by slug
  const { data: existingBySlug } = await supabase
    .from("links")
    .select("id, slug, destination_url, title, author, published_at")
    .eq("slug", slug)
    .maybeSingle();

  if (existingBySlug) {
    // Link already exists - return it with caller's tracking links
    const callerLinks = await getCallerLinks(existingBySlug.id, existingBySlug.slug, caller);
    return new Response(
      JSON.stringify({
        slug: existingBySlug.slug,
        destination_url: existingBySlug.destination_url,
        existed: true,
        article: {
          title: existingBySlug.title,
          author: existingBySlug.author,
          published_at: existingBySlug.published_at,
        },
        caller_links: callerLinks,
        total_variants_created: 0,
        person: { name: caller.name, slug: caller.slug },
      }),
      { headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

  // Check if link exists by URL (e.g. created via als shorten with random slug)
  const urlNorm = destinationUrl.replace(/\/+$/, "");
  const { data: existingByUrl } = await supabase
    .from("links")
    .select("id, slug, destination_url, title, author, published_at")
    .eq("destination_url", urlNorm)
    .maybeSingle();

  if (existingByUrl) {
    const callerLinks = await getCallerLinks(existingByUrl.id, existingByUrl.slug, caller);
    return new Response(
      JSON.stringify({
        slug: existingByUrl.slug,
        destination_url: existingByUrl.destination_url,
        existed: true,
        article: {
          title: existingByUrl.title,
          author: existingByUrl.author,
          published_at: existingByUrl.published_at,
        },
        caller_links: callerLinks,
        total_variants_created: 0,
        person: { name: caller.name, slug: caller.slug },
      }),
      { headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

  // Create the link with the Substack slug (NOT random)
  const { data: linkData, error: linkError } = await supabase
    .from("links")
    .insert({
      slug,
      destination_url: destinationUrl,
      content_type: "article",
    })
    .select("id, slug, destination_url")
    .single();

  if (linkError) {
    console.error("Error creating link:", linkError);
    return new Response(
      JSON.stringify({ error: `Failed to create link: ${linkError.message}` }),
      { status: 500, headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

  // Create tracking variants for ALL people (same as sync-substack)
  const { data: personSources, error: sourcesError } = await supabase
    .from("person_sources")
    .select("person_id, utm_source, utm_medium, utm_content, utm_term");
  if (sourcesError) {
    console.error("Error fetching person_sources:", sourcesError);
  }

  const { data: people, error: peopleError } = await supabase
    .from("people")
    .select("id, slug");
  if (peopleError) {
    console.error("Error fetching people:", peopleError);
  }
  const peopleById = new Map((people || []).map((p) => [p.id, p.slug]));

  let totalVariants = 0;
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
    } else {
      totalVariants++;
    }
  }

  // Get caller's tracking links to display
  const callerLinks = await getCallerLinks(linkData.id, linkData.slug, caller);

  return new Response(
    JSON.stringify({
      slug: linkData.slug,
      destination_url: linkData.destination_url,
      existed: false,
      article: { title: null, author: null, published_at: null },
      caller_links: callerLinks,
      total_variants_created: totalVariants,
      person: { name: caller.name, slug: caller.slug },
    }),
    { headers: { "Content-Type": "application/json", ...corsHeaders } },
  );
});

async function getCallerLinks(
  linkId: string,
  linkSlug: string,
  caller: PersonInfo,
): Promise<Array<{ source: string; label: string; short_url: string; suffix: string }>> {
  const { data: callerSources } = await supabase
    .from("person_sources")
    .select("label, utm_source, utm_medium")
    .eq("person_id", caller.id)
    .order("label");

  const links: Array<{ source: string; label: string; short_url: string; suffix: string }> = [];
  for (const src of callerSources || []) {
    const { data: variant } = await supabase.rpc("ensure_tracking_variant", {
      p_link_id: linkId,
      p_ref: caller.slug,
      p_source: src.utm_source,
      p_medium: src.utm_medium || "social",
    });
    if (variant?.suffix) {
      links.push({
        source: src.utm_source,
        label: src.label || src.utm_source,
        short_url: `https://${DOMAIN}/${linkSlug}-${variant.suffix}`,
        suffix: variant.suffix,
      });
    }
  }
  return links;
}
