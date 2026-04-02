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

  // Extract API key and parameters from request
  let apiKey = req.headers.get("x-api-key") || "";
  let count = 10;
  let all = false;

  if (req.method === "POST") {
    try {
      const body = await req.json();
      apiKey = apiKey || body.api_key || "";
      if (body.count !== undefined) count = Number(body.count);
      if (body.all !== undefined) all = Boolean(body.all);
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
    const countParam = url.searchParams.get("count");
    if (countParam) count = Number(countParam);
    const allParam = url.searchParams.get("all");
    if (allParam === "true" || allParam === "1") all = true;
  }

  // Validate API key
  if (!apiKey) {
    return new Response(
      JSON.stringify({
        error:
          "API key required. Pass via x-api-key header or api_key parameter.",
      }),
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

  // Find custom links: links with no author (not Substack articles) that this
  // person has tracking variants for.
  let query = supabase
    .from("links")
    .select(
      `
      id,
      slug,
      destination_url,
      created_at,
      tracking_variants!inner(id, suffix, utm_source, label:utm_source)
    `,
    )
    .is("author", null)
    .eq("tracking_variants.ref", person.slug)
    .order("created_at", { ascending: false });

  if (!all) {
    query = query.limit(count);
  }

  const { data: links, error: linksError } = await query;

  if (linksError) {
    console.error("Error fetching custom links:", linksError);
    return new Response(
      JSON.stringify({ error: "Failed to fetch custom links" }),
      {
        status: 500,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  const linkIds = (links || []).map((l: { id: string }) => l.id);

  // Get person sources for label lookup
  const { data: personSources } = await supabase
    .from("person_sources")
    .select("utm_source, utm_medium, utm_content, utm_term, label")
    .eq("person_id", person.id);

  // Build composite key for label lookup: "source|medium|content|term"
  const sourceLabels: Record<string, string> = {};
  for (const src of personSources || []) {
    const key = [
      src.utm_source,
      src.utm_medium || "social",
      src.utm_content || "",
      src.utm_term || "",
    ].join("|");
    sourceLabels[key] = src.label;
  }

  const { data: variants } = await supabase
    .from("tracking_variants")
    .select("link_id, suffix, utm_source, utm_medium, utm_content, utm_term")
    .in("link_id", linkIds.length > 0 ? linkIds : ["lnk-0000000000"])
    .eq("ref", person.slug)
    .order("utm_source");

  // Group variants by link_id
  const variantsByLink: Record<
    string,
    Array<{
      suffix: string;
      utm_source: string;
      label: string;
      short_url: string;
    }>
  > = {};
  for (const v of variants || []) {
    if (!variantsByLink[v.link_id]) {
      variantsByLink[v.link_id] = [];
    }
    const key = [
      v.utm_source,
      v.utm_medium || "social",
      v.utm_content || "",
      v.utm_term || "",
    ].join("|");
    const label = sourceLabels[key] || v.utm_source;
    variantsByLink[v.link_id].push({
      suffix: v.suffix,
      utm_source: v.utm_source,
      label,
      short_url: `https://${DOMAIN}/${
        (links || []).find((l: { id: string }) => l.id === v.link_id)?.slug
      }-${v.suffix}`,
    });
  }

  // Build response
  const results = (links || []).map(
    (link: {
      id: string;
      slug: string;
      destination_url: string;
      created_at: string;
    }) => ({
      slug: link.slug,
      url: link.destination_url,
      created_at: link.created_at,
      links: variantsByLink[link.id] || [],
    }),
  );

  return new Response(
    JSON.stringify({
      results,
      person: { name: person.name, slug: person.slug },
      total: results.length,
    }),
    {
      headers: { "Content-Type": "application/json", ...corsHeaders },
    },
  );
});
