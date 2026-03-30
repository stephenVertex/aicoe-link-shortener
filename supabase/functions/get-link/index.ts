import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

const DOMAIN = "aicoe.fit";

interface PersonInfo {
  id: string;
  name: string;
  slug: string;
  email: string;
}

/**
 * Validate an API key and return the person info.
 */
async function validateApiKey(apiKey: string): Promise<PersonInfo | null> {
  const { data, error } = await supabase.rpc("validate_api_key", {
    p_api_key: apiKey,
  });
  if (error || !data) return null;
  return data as PersonInfo;
}

/**
 * Find a link by article URL or slug.
 */
async function findLink(
  articleUrl: string,
): Promise<{ id: string; slug: string; destination_url: string; title: string | null; author: string | null; published_at: string | null } | null> {
  // Try exact slug match first
  const { data: bySlug } = await supabase
    .from("links")
    .select("id, slug, destination_url, title, author, published_at")
    .eq("slug", articleUrl)
    .maybeSingle();

  if (bySlug) return bySlug;

  // Try matching by destination URL
  const { data: byUrl } = await supabase
    .from("links")
    .select("id, slug, destination_url, title, author, published_at")
    .eq("destination_url", articleUrl)
    .maybeSingle();

  if (byUrl) return byUrl;

  // Try matching URL with/without trailing slash
  const urlVariant = articleUrl.endsWith("/")
    ? articleUrl.slice(0, -1)
    : articleUrl + "/";
  const { data: byUrlVariant } = await supabase
    .from("links")
    .select("id, slug, destination_url, title, author, published_at")
    .eq("destination_url", urlVariant)
    .maybeSingle();

  if (byUrlVariant) return byUrlVariant;

  // Try extracting slug from a Substack URL pattern: .../p/<slug>
  const substackMatch = articleUrl.match(/\/p\/([^/?#]+)/);
  if (substackMatch) {
    const extractedSlug = substackMatch[1];
    const { data: byExtractedSlug } = await supabase
      .from("links")
      .select("id, slug, destination_url, title, author, published_at")
      .eq("slug", extractedSlug)
      .maybeSingle();

    if (byExtractedSlug) return byExtractedSlug;
  }

  return null;
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

  // Extract API key from header or body
  let apiKey = req.headers.get("x-api-key") || "";
  let articleUrl = "";
  let source = ""; // optional: specific source to get variant for

  if (req.method === "POST") {
    try {
      const body = await req.json();
      apiKey = apiKey || body.api_key || "";
      articleUrl = body.article_url || body.url || body.slug || "";
      source = body.source || "";
    } catch {
      return new Response(
        JSON.stringify({ error: "Invalid JSON body" }),
        {
          status: 400,
          headers: { "Content-Type": "application/json", ...corsHeaders },
        },
      );
    }
  } else {
    const url = new URL(req.url);
    apiKey = apiKey || url.searchParams.get("api_key") || "";
    articleUrl = url.searchParams.get("url") || url.searchParams.get("slug") || "";
    source = url.searchParams.get("source") || "";
  }

  // Validate API key
  if (!apiKey) {
    return new Response(
      JSON.stringify({ error: "API key required. Pass via x-api-key header or api_key parameter." }),
      {
        status: 401,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  const person = await validateApiKey(apiKey);
  if (!person) {
    return new Response(
      JSON.stringify({ error: "Invalid API key" }),
      {
        status: 401,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  // Find the link
  if (!articleUrl) {
    return new Response(
      JSON.stringify({ error: "article_url or slug parameter required" }),
      {
        status: 400,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  const link = await findLink(articleUrl);
  if (!link) {
    return new Response(
      JSON.stringify({ error: `No article found for: ${articleUrl}` }),
      {
        status: 404,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  // Get person's source profiles
  const { data: sources } = await supabase
    .from("person_sources")
    .select("id, label, utm_source, utm_medium, utm_content, utm_term")
    .eq("person_id", person.id)
    .order("label");

  const personSources = sources || [];

  // Filter to specific source if requested
  const filteredSources = source
    ? personSources.filter((s: { utm_source: string }) => s.utm_source === source.toLowerCase())
    : personSources;

  if (filteredSources.length === 0) {
    // Fall back to a default source if none configured
    const defaultSource = source || "linkedin";
    const { data: variant } = await supabase.rpc("ensure_tracking_variant", {
      p_link_id: link.id,
      p_ref: person.slug,
      p_source: defaultSource,
      p_medium: "social",
    });

    const suffix = variant?.suffix;
    const shortUrl = `https://${DOMAIN}/${link.slug}-${suffix}`;

    return new Response(
      JSON.stringify({
        article: {
          title: link.title,
          author: link.author,
          slug: link.slug,
          url: link.destination_url,
          published_at: link.published_at,
        },
        links: [
          {
            source: defaultSource,
            short_url: shortUrl,
            suffix,
          },
        ],
        person: { name: person.name, slug: person.slug },
      }),
      {
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  // Generate/get tracking variants for each source profile
  const links = [];
  for (const src of filteredSources) {
    const { data: variant, error: variantError } = await supabase.rpc(
      "ensure_tracking_variant",
      {
        p_link_id: link.id,
        p_ref: person.slug,
        p_source: src.utm_source,
        p_medium: src.utm_medium || "social",
        p_content: src.utm_content || null,
        p_term: src.utm_term || null,
      },
    );

    if (variantError) {
      console.error(`Error generating variant for ${src.label}:`, variantError);
      continue;
    }

    const suffix = variant?.suffix;
    links.push({
      source: src.utm_source,
      label: src.label,
      short_url: `https://${DOMAIN}/${link.slug}-${suffix}`,
      suffix,
    });
  }

  return new Response(
    JSON.stringify({
      article: {
        title: link.title,
        author: link.author,
        slug: link.slug,
        url: link.destination_url,
        published_at: link.published_at,
      },
      links,
      person: { name: person.name, slug: person.slug },
    }),
    {
      headers: { "Content-Type": "application/json", ...corsHeaders },
    },
  );
});
