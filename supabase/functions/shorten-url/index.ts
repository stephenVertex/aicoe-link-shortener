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
 * Generate a random short slug (base36, 6 chars).
 */
function randomSlug(length = 6): string {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  let result = "";
  for (let i = 0; i < length; i++) {
    result += chars[Math.floor(Math.random() * chars.length)];
  }
  return result;
}

/**
 * Find or create a link record for the given URL.
 * If customSlug is provided, use it instead of generating a random one.
 * Returns the link record.
 */
async function findOrCreateLink(url: string, customSlug?: string): Promise<{
  id: string;
  slug: string;
  destination_url: string;
  title: string | null;
  author: string | null;
  published_at: string | null;
  existed: boolean;
} | null> {
  // Normalise URL: strip trailing slash for matching
  const urlNorm = url.replace(/\/+$/, "");
  const urlWithSlash = urlNorm + "/";

  // Try exact match first
  const { data: byExact } = await supabase
    .from("links")
    .select("id, slug, destination_url, title, author, published_at")
    .eq("destination_url", urlNorm)
    .maybeSingle();

  if (byExact) return { ...byExact, existed: true };

  // Try trailing-slash variant
  const { data: bySlash } = await supabase
    .from("links")
    .select("id, slug, destination_url, title, author, published_at")
    .eq("destination_url", urlWithSlash)
    .maybeSingle();

  if (bySlash) return { ...bySlash, existed: true };

  // Determine the slug to use
  let slug = "";

  if (customSlug) {
    // Validate custom slug format
    const validSlug = customSlug.toLowerCase().replace(/[^a-z0-9-]/g, "").replace(/^-+|-+$/g, "");
    if (validSlug !== customSlug.toLowerCase()) {
      return null; // Invalid slug format
    }

    // Check if custom slug is already taken
    const { data: conflict } = await supabase
      .from("links")
      .select("id")
      .eq("slug", validSlug)
      .maybeSingle();

    if (conflict) {
      return null; // Slug already taken
    }
    slug = validSlug;
  } else {
    // Generate a random slug
    let attempts = 0;
    while (attempts < 10) {
      const candidate = randomSlug(6);
      const { data: conflict } = await supabase
        .from("links")
        .select("id")
        .eq("slug", candidate)
        .maybeSingle();
      if (!conflict) {
        slug = candidate;
        break;
      }
      attempts++;
    }
  }

  if (!slug) {
    return null; // Could not generate unique slug
  }

  const { data: created, error } = await supabase
    .from("links")
    .insert({ slug, destination_url: url })
    .select("id, slug, destination_url, title, author, published_at")
    .single();

  if (error || !created) return null;
  return { ...created, existed: false };
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

  // Extract API key and URL from request
  let apiKey = req.headers.get("x-api-key") || "";
  let targetUrl = "";
  let source = "";
  let customSlug = "";

  if (req.method === "POST") {
    try {
      const body = await req.json();
      apiKey = apiKey || body.api_key || "";
      targetUrl = body.url || body.target_url || "";
      source = body.source || "";
      customSlug = body.slug || "";
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
    targetUrl = url.searchParams.get("url") || url.searchParams.get("target_url") || "";
    source = url.searchParams.get("source") || "";
    customSlug = url.searchParams.get("slug") || "";
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

  // Validate URL
  if (!targetUrl) {
    return new Response(
      JSON.stringify({ error: "url parameter required" }),
      {
        status: 400,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  // Basic URL validation
  try {
    new URL(targetUrl);
  } catch {
    return new Response(
      JSON.stringify({ error: `Invalid URL: ${targetUrl}` }),
      {
        status: 400,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  // Find or create the link record
  const link = await findOrCreateLink(targetUrl, customSlug || undefined);
  if (!link) {
    if (customSlug) {
      return new Response(
        JSON.stringify({ error: `Slug '${customSlug}' is already taken or invalid. Choose a different slug.` }),
        {
          status: 409,
          headers: { "Content-Type": "application/json", ...corsHeaders },
        },
      );
    }
    return new Response(
      JSON.stringify({ error: "Failed to create short link. Please try again." }),
      {
        status: 500,
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
    // Fall back to a default linkedin source
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
        url: link.destination_url,
        slug: link.slug,
        existed: link.existed,
        article: link.existed
          ? {
              title: link.title,
              author: link.author,
              published_at: link.published_at,
            }
          : null,
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
      url: link.destination_url,
      slug: link.slug,
      existed: link.existed,
      article: link.existed
        ? {
            title: link.title,
            author: link.author,
            published_at: link.published_at,
          }
        : null,
      links,
      person: { name: person.name, slug: person.slug },
    }),
    {
      headers: { "Content-Type": "application/json", ...corsHeaders },
    },
  );
});
