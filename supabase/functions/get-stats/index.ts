import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

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

  // Extract API key
  let apiKey = req.headers.get("x-api-key") || "";
  let days = 7;

  if (req.method === "POST") {
    try {
      const body = await req.json();
      apiKey = apiKey || body.api_key || "";
      days = body.days ?? 7;
    } catch {
      // Use defaults
    }
  } else {
    const url = new URL(req.url);
    apiKey = apiKey || url.searchParams.get("api_key") || "";
    days = parseInt(url.searchParams.get("days") || "7", 10) || 7;
  }

  // Validate API key
  if (!apiKey) {
    return new Response(
      JSON.stringify({ error: "API key required." }),
      { status: 401, headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

  const person = await validateApiKey(apiKey);
  if (!person) {
    return new Response(
      JSON.stringify({ error: "Invalid API key" }),
      { status: 401, headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

  // Gather stats in parallel
  const since = new Date(Date.now() - days * 86400000).toISOString();

  const [
    linksResult,
    peopleResult,
    totalClicksResult,
    recentClicksResult,
    variantsResult,
  ] = await Promise.all([
    supabase.from("links").select("id, slug, title, author", { count: "exact" }),
    supabase.from("people").select("id", { count: "exact" }),
    supabase.from("click_log").select("id", { count: "exact" }),
    supabase.from("click_log").select("id", { count: "exact" }).gte("clicked_at", since),
    supabase.from("tracking_variants").select("id", { count: "exact" }),
  ]);

  const articleCount = linksResult.count ?? 0;
  const peopleCount = peopleResult.count ?? 0;
  const totalClicks = totalClicksResult.count ?? 0;
  const recentClicks = recentClicksResult.count ?? 0;
  const variantCount = variantsResult.count ?? 0;

  // Count distinct authors
  const authors = new Set<string>();
  if (linksResult.data) {
    for (const link of linksResult.data) {
      if (link.author) authors.add(link.author);
    }
  }

  // Get top articles by clicks in the recent period
  // Fetch recent clicks with link_id to aggregate client-side
  const { data: recentClickData } = await supabase
    .from("click_log")
    .select("link_id")
    .gte("clicked_at", since);

  const clicksByLink: Record<string, number> = {};
  if (recentClickData) {
    for (const c of recentClickData) {
      clicksByLink[c.link_id] = (clicksByLink[c.link_id] || 0) + 1;
    }
  }

  // Sort by clicks descending and take top 5
  const topLinkIds = Object.entries(clicksByLink)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);

  // Resolve link titles
  const linkMap: Record<string, { slug: string; title: string | null }> = {};
  if (linksResult.data) {
    for (const link of linksResult.data) {
      linkMap[link.id] = { slug: link.slug, title: link.title };
    }
  }

  const topArticles = topLinkIds.map(([linkId, clicks]) => ({
    slug: linkMap[linkId]?.slug ?? linkId,
    title: linkMap[linkId]?.title ?? null,
    clicks,
  }));

  // Get the authenticated user's personal stats
  const { data: myVariants } = await supabase
    .from("tracking_variants")
    .select("id")
    .eq("ref", person.slug);

  const myVariantIds = (myVariants || []).map((v: { id: string }) => v.id);
  let myClicks = 0;
  let myRecentClicks = 0;

  if (myVariantIds.length > 0) {
    const { count: myTotal } = await supabase
      .from("click_log")
      .select("id", { count: "exact" })
      .in("variant_id", myVariantIds);
    myClicks = myTotal ?? 0;

    const { count: myRecent } = await supabase
      .from("click_log")
      .select("id", { count: "exact" })
      .in("variant_id", myVariantIds)
      .gte("clicked_at", since);
    myRecentClicks = myRecent ?? 0;
  }

  return new Response(
    JSON.stringify({
      overview: {
        articles: articleCount,
        authors: authors.size,
        people: peopleCount,
        tracking_variants: variantCount,
        total_clicks: totalClicks,
        recent_clicks: recentClicks,
        recent_days: days,
      },
      top_articles: topArticles,
      your_stats: {
        name: person.name,
        slug: person.slug,
        total_clicks: myClicks,
        recent_clicks: myRecentClicks,
        tracking_variants: myVariantIds.length,
      },
    }),
    { headers: { "Content-Type": "application/json", ...corsHeaders } },
  );
});
