import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

const DOMAIN = "aicoe.fit";

interface LinkInfo {
  id: string;
  slug: string;
  destination_url: string;
  title: string | null;
  author: string | null;
  published_at: string | null;
}

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

async function findLinksBySlugs(slugs: string[]): Promise<Map<string, LinkInfo>> {
  const result = new Map<string, LinkInfo>();
  if (slugs.length === 0) return result;

  const { data, error } = await supabase
    .from("links")
    .select("id, slug, destination_url, title, author, published_at")
    .in("slug", slugs);

  if (error || !data) return result;

  for (const link of data) {
    result.set(link.slug, link);
  }
  return result;
}

async function findLinksByIds(ids: string[]): Promise<Map<string, LinkInfo>> {
  const result = new Map<string, LinkInfo>();
  if (ids.length === 0) return result;

  const { data, error } = await supabase
    .from("links")
    .select("id, slug, destination_url, title, author, published_at")
    .in("id", ids);

  if (error || !data) return result;

  for (const link of data) {
    result.set(link.id, link);
  }
  return result;
}

async function buildTrackingLinksForBatch(
  links: LinkInfo[],
  person: PersonInfo,
  source?: string,
): Promise<Map<string, { article: Record<string, unknown>; links: Array<Record<string, unknown>> }>> {
  const result = new Map<string, { article: Record<string, unknown>; links: Array<Record<string, unknown>> }>();

  if (links.length === 0) return result;

  const { data: sources } = await supabase
    .from("person_sources")
    .select("id, label, utm_source, utm_medium, utm_content, utm_term")
    .eq("person_id", person.id)
    .order("label");

  const personSources = sources || [];

  const filteredSources = source
    ? personSources.filter((s) => s.utm_source === source.toLowerCase())
    : personSources;

  const linkIds = links.map((l) => l.id);

  const { data: existingVariants } = await supabase
    .from("tracking_variants")
    .select("link_id, suffix, utm_source, utm_medium, utm_content, utm_term")
    .in("link_id", linkIds)
    .eq("ref", person.slug);

  const variantsByLink = new Map<string, Array<{ suffix: string; utm_source: string; utm_medium: string | null; utm_content: string | null; utm_term: string | null }>>();
  for (const v of existingVariants || []) {
    if (!variantsByLink.has(v.link_id)) {
      variantsByLink.set(v.link_id, []);
    }
    variantsByLink.get(v.link_id)!.push({
      suffix: v.suffix,
      utm_source: v.utm_source,
      utm_medium: v.utm_medium,
      utm_content: v.utm_content,
      utm_term: v.utm_term,
    });
  }

  for (const link of links) {
    const existingForLink = variantsByLink.get(link.id) || [];
    const trackingLinks: Array<Record<string, unknown>> = [];

    if (filteredSources.length === 0) {
      const defaultSource = source || "linkedin";
      let variant = existingForLink.find(
        (v) => v.utm_source === defaultSource && v.utm_medium === "social" && !v.utm_content && !v.utm_term
      );

      if (!variant) {
        const { data: newVariant, error: variantError } = await supabase.rpc("ensure_tracking_variant", {
          p_link_id: link.id,
          p_ref: person.slug,
          p_source: defaultSource,
          p_medium: "social",
        });

        if (!variantError && newVariant) {
          variant = {
            suffix: newVariant.suffix,
            utm_source: defaultSource,
            utm_medium: "social",
            utm_content: null,
            utm_term: null,
          };
        }
      }

      if (variant) {
        trackingLinks.push({
          source: defaultSource,
          short_url: `https://${DOMAIN}/${link.slug}-${variant.suffix}`,
          suffix: variant.suffix,
        });
      }
    } else {
      for (const src of filteredSources) {
        let variant = existingForLink.find(
          (v) =>
            v.utm_source === src.utm_source &&
            (v.utm_medium || "social") === (src.utm_medium || "social") &&
            (v.utm_content || "") === (src.utm_content || "") &&
            (v.utm_term || "") === (src.utm_term || "")
        );

        if (!variant) {
          const { data: newVariant, error: variantError } = await supabase.rpc("ensure_tracking_variant", {
            p_link_id: link.id,
            p_ref: person.slug,
            p_source: src.utm_source,
            p_medium: src.utm_medium || "social",
            p_content: src.utm_content || null,
            p_term: src.utm_term || null,
          });

          if (!variantError && newVariant) {
            variant = {
              suffix: newVariant.suffix,
              utm_source: src.utm_source,
              utm_medium: src.utm_medium || "social",
              utm_content: src.utm_content || null,
              utm_term: src.utm_term || null,
            };
          }
        }

        if (variant) {
          trackingLinks.push({
            source: src.utm_source,
            label: src.label,
            short_url: `https://${DOMAIN}/${link.slug}-${variant.suffix}`,
            suffix: variant.suffix,
          });
        }
      }
    }

    result.set(link.slug, {
      article: {
        title: link.title,
        author: link.author,
        slug: link.slug,
        url: link.destination_url,
        published_at: link.published_at,
      },
      links: trackingLinks,
    });
  }

  return result;
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

  let apiKey = req.headers.get("x-api-key") || "";
  let slugs: string[] = [];
  let ids: string[] = [];
  let source = "";

  if (req.method === "POST") {
    try {
      const body = await req.json();
      apiKey = apiKey || body.api_key || "";
      slugs = body.slugs || [];
      ids = body.ids || [];
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
    const slugsParam = url.searchParams.get("slugs");
    if (slugsParam) {
      try {
        slugs = JSON.parse(slugsParam);
      } catch {
        slugs = slugsParam.split(",").map((s) => s.trim());
      }
    }
    const idsParam = url.searchParams.get("ids");
    if (idsParam) {
      try {
        ids = JSON.parse(idsParam);
      } catch {
        ids = idsParam.split(",").map((s) => s.trim());
      }
    }
    source = url.searchParams.get("source") || "";
  }

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

  if (slugs.length === 0 && ids.length === 0) {
    return new Response(
      JSON.stringify({ error: "slugs or ids parameter required" }),
      {
        status: 400,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  if (slugs.length > 50 || ids.length > 50) {
    return new Response(
      JSON.stringify({ error: "Maximum 50 slugs/ids per request" }),
      {
        status: 400,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  const linksMap = new Map<string, LinkInfo>();

  if (slugs.length > 0) {
    const found = await findLinksBySlugs(slugs);
    for (const [slug, link] of found) {
      linksMap.set(slug, link);
    }
  }

  if (ids.length > 0) {
    const found = await findLinksByIds(ids);
    for (const [id, link] of found) {
      linksMap.set(id, link);
    }
  }

  const links = Array.from(linksMap.values());
  const trackingData = await buildTrackingLinksForBatch(links, person, source || undefined);

  const results: Record<string, { article: Record<string, unknown>; links: Array<Record<string, unknown>> }> = {};
  for (const [key, data] of trackingData) {
    results[key] = data;
  }

  const notFound: string[] = [];
  for (const slug of slugs) {
    if (!results[slug]) {
      notFound.push(slug);
    }
  }
  for (const id of ids) {
    if (!results[id]) {
      notFound.push(id);
    }
  }

  return new Response(
    JSON.stringify({
      results,
      not_found: notFound.length > 0 ? notFound : undefined,
      person: { name: person.name, slug: person.slug },
    }),
    {
      headers: { "Content-Type": "application/json", ...corsHeaders },
    },
  );
});