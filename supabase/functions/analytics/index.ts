import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

const DOMAIN = "aicoe.fit";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-api-key",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

interface PersonInfo {
  id: string;
  name: string;
  slug: string;
  email: string;
}

interface LinkRecord {
  id: string;
  slug: string;
  destination_url: string;
  title: string | null;
  author: string | null;
  created_at: string | null;
  published_at: string | null;
  last_synced_at: string | null;
}

async function validateApiKey(apiKey: string): Promise<PersonInfo | null> {
  const { data, error } = await supabase.rpc("validate_api_key", {
    p_api_key: apiKey,
  });
  if (error || !data) return null;
  return data as PersonInfo;
}

async function findLink(
  articleUrl: string,
): Promise<LinkRecord | null> {
  const cols =
    "id, slug, destination_url, title, author, created_at, published_at, last_synced_at";

  const { data: bySlug } = await supabase
    .from("links")
    .select(cols)
    .eq("slug", articleUrl)
    .maybeSingle();
  if (bySlug) return bySlug;

  const { data: byUrl } = await supabase
    .from("links")
    .select(cols)
    .eq("destination_url", articleUrl)
    .maybeSingle();
  if (byUrl) return byUrl;

  const urlVariant = articleUrl.endsWith("/")
    ? articleUrl.slice(0, -1)
    : articleUrl + "/";
  const { data: byUrlVariant } = await supabase
    .from("links")
    .select(cols)
    .eq("destination_url", urlVariant)
    .maybeSingle();
  if (byUrlVariant) return byUrlVariant;

  const substackMatch = articleUrl.match(/\/p\/([^/?#]+)/);
  if (substackMatch) {
    const { data: byExtracted } = await supabase
      .from("links")
      .select(cols)
      .eq("slug", substackMatch[1])
      .maybeSingle();
    if (byExtracted) return byExtracted;
  }

  return null;
}

function normalizeReferrer(referer: string | null): string {
  const value = (referer || "").trim();
  if (!value) return "Direct / Unknown";
  try {
    const url = new URL(value);
    return url.hostname.replace(/^www\./, "") || value;
  } catch {
    return value;
  }
}

async function handleLinkAnalytics(params: {
  slug: string;
  interval?: string;
  startDate?: string;
  endDate?: string;
  comparisonLimit?: number;
}): Promise<Response> {
  const {
    slug,
    interval = "day",
    startDate,
    endDate,
    comparisonLimit = 8,
  } = params;

  if (!slug) {
    return jsonResponse({ error: "slug parameter required" }, 400);
  }

  const link = await findLink(slug);
  if (!link) {
    return jsonResponse({ error: `No article found for: ${slug}` }, 404);
  }

  const rangeStart = startDate ? new Date(startDate) : null;
  const rangeEnd = endDate ? new Date(endDate) : null;
  if (rangeStart && Number.isNaN(rangeStart.getTime())) {
    return jsonResponse({ error: "Invalid start_date" }, 400);
  }
  if (rangeEnd && Number.isNaN(rangeEnd.getTime())) {
    return jsonResponse({ error: "Invalid end_date" }, 400);
  }

  const intervalValue = ["hour", "day", "week", "month"].includes(interval)
    ? interval
    : "day";

  const { data: seriesData, error: seriesError } = await supabase.rpc(
    "get_click_analytics",
    {
      p_interval: intervalValue,
      p_link_id: link.id,
      p_start_date: rangeStart?.toISOString() ?? null,
      p_end_date: rangeEnd?.toISOString() ?? null,
    },
  );
  if (seriesError) throw seriesError;

  let clickQuery = supabase
    .from("click_log")
    .select("id, variant_id, clicked_at, referer, country_code")
    .eq("link_id", link.id)
    .order("clicked_at", { ascending: false });

  if (rangeStart) {
    clickQuery = clickQuery.gte("clicked_at", rangeStart.toISOString());
  }
  if (rangeEnd) {
    clickQuery = clickQuery.lt("clicked_at", rangeEnd.toISOString());
  }

  const { data: clickRows, error: clickError } = await clickQuery;
  if (clickError) throw clickError;

  const clicks = clickRows || [];
  const variantIds = [...new Set(clicks.map((row) => row.variant_id).filter(Boolean))];

  let variantRows:
    | Array<{
      id: string;
      suffix: string;
      ref: string | null;
      utm_source: string | null;
      utm_medium: string | null;
      utm_campaign: string | null;
      utm_content: string | null;
      utm_term: string | null;
    }>
    | null = null;

  if (variantIds.length > 0) {
    const { data, error } = await supabase
      .from("tracking_variants")
      .select(
        "id, suffix, ref, utm_source, utm_medium, utm_campaign, utm_content, utm_term",
      )
      .in("id", variantIds);
    if (error) throw error;
    variantRows = data;
  }

  const variantsById = new Map((variantRows || []).map((variant) => [variant.id, variant]));
  const variantClickCounts = new Map<string, number>();
  const referrerCounts = new Map<string, number>();
  const countryCounts = new Map<string, number>();

  for (const click of clicks) {
    const variantId = click.variant_id || "__direct__";
    variantClickCounts.set(variantId, (variantClickCounts.get(variantId) || 0) + 1);

    const referrer = normalizeReferrer(click.referer);
    referrerCounts.set(referrer, (referrerCounts.get(referrer) || 0) + 1);

    const country = (click.country_code || "").trim().toUpperCase() || "Unknown";
    countryCounts.set(country, (countryCounts.get(country) || 0) + 1);
  }

  const variantBreakdown = Array.from(variantClickCounts.entries())
    .map(([variantId, count]) => {
      if (variantId === "__direct__") {
        return {
          id: null,
          suffix: null,
          short_url: `https://${DOMAIN}/${link.slug}`,
          ref: null,
          utm_source: null,
          utm_medium: null,
          utm_campaign: null,
          utm_content: null,
          utm_term: null,
          clicks: count,
          label: "Direct",
        };
      }

      const variant = variantsById.get(variantId);
      return {
        id: variantId,
        suffix: variant?.suffix || null,
        short_url: variant?.suffix
          ? `https://${DOMAIN}/${link.slug}-${variant.suffix}`
          : `https://${DOMAIN}/${link.slug}`,
        ref: variant?.ref || null,
        utm_source: variant?.utm_source || null,
        utm_medium: variant?.utm_medium || null,
        utm_campaign: variant?.utm_campaign || null,
        utm_content: variant?.utm_content || null,
        utm_term: variant?.utm_term || null,
        clicks: count,
        label: variant?.utm_source || variant?.suffix || variantId,
      };
    })
    .sort((a, b) => b.clicks - a.clicks);

  const referrers = Array.from(referrerCounts.entries())
    .map(([referrer, count]) => ({ referrer, clicks: count }))
    .sort((a, b) => b.clicks - a.clicks);

  const countries = Array.from(countryCounts.entries())
    .map(([country, count]) => ({ country, clicks: count }))
    .sort((a, b) => b.clicks - a.clicks);

  const { data: comparisonLinks, error: comparisonError } = await supabase
    .from("links")
    .select("id, slug, title, author, destination_url, created_at")
    .neq("id", link.id)
    .order("created_at", { ascending: false })
    .limit(Math.max(comparisonLimit, 1));
  if (comparisonError) throw comparisonError;

  const comparisonIds = (comparisonLinks || []).map((item) => item.id);
  let comparisonClickRows: Array<{ link_id: string }> = [];
  if (comparisonIds.length > 0) {
    let comparisonQuery = supabase
      .from("click_log")
      .select("link_id")
      .in("link_id", comparisonIds);

    if (rangeStart) {
      comparisonQuery = comparisonQuery.gte("clicked_at", rangeStart.toISOString());
    }
    if (rangeEnd) {
      comparisonQuery = comparisonQuery.lt("clicked_at", rangeEnd.toISOString());
    }

    const { data, error } = await comparisonQuery;
    if (error) throw error;
    comparisonClickRows = data || [];
  }

  const comparisonCounts = new Map<string, number>();
  for (const row of comparisonClickRows) {
    comparisonCounts.set(row.link_id, (comparisonCounts.get(row.link_id) || 0) + 1);
  }

  const comparisons = (comparisonLinks || [])
    .map((item) => ({
      id: item.id,
      slug: item.slug,
      title: item.title,
      author: item.author,
      destination_url: item.destination_url,
      created_at: item.created_at,
      short_url: `https://${DOMAIN}/${item.slug}`,
      clicks: comparisonCounts.get(item.id) || 0,
    }))
    .sort((a, b) => b.clicks - a.clicks);

  return jsonResponse({
    link: {
      ...link,
      short_url: `https://${DOMAIN}/${link.slug}`,
    },
    interval: intervalValue,
    total_clicks: clicks.length,
    total_variants: variantRows?.length || 0,
    clicks_over_time: (seriesData || []).map((row: { period: string; clicks: number }) => ({
      period: row.period,
      clicks: row.clicks,
    })),
    variant_breakdown: variantBreakdown,
    referrers,
    countries,
    comparisons,
    range: {
      start: rangeStart?.toISOString() ?? null,
      end: rangeEnd?.toISOString() ?? null,
    },
  });
}

async function handleArticleStats(params: {
  slug: string;
  days?: number;
  everybody?: boolean;
}): Promise<Response> {
  const { slug, days = 30, everybody = false } = params;

  if (!slug) {
    return jsonResponse(
      { error: "slug or article_url parameter required" },
      400,
    );
  }

  const link = await findLink(slug);
  if (!link) {
    return jsonResponse({ error: `No article found for: ${slug}` }, 404);
  }

  const { count: totalClicks, error: clickCountError } = await supabase
    .from("click_log")
    .select("id", { count: "exact", head: true })
    .eq("link_id", link.id);

  if (clickCountError) throw clickCountError;

  const startDate = new Date();
  startDate.setDate(startDate.getDate() - days);

  const { data: dailyClicks, error: dailyError } = await supabase.rpc(
    "get_click_analytics",
    {
      p_interval: "day",
      p_link_id: link.id,
      p_start_date: startDate.toISOString(),
    },
  );

  if (dailyError) throw dailyError;

  const { data: variantClicks, error: variantClicksError } = await supabase
    .from("click_log")
    .select("variant_id")
    .eq("link_id", link.id);

  if (variantClicksError) throw variantClicksError;

  const variantCounts: Record<string, number> = {};
  for (const row of variantClicks || []) {
    const vid = row.variant_id || "__direct__";
    variantCounts[vid] = (variantCounts[vid] || 0) + 1;
  }

  const variantIds = Object.keys(variantCounts).filter(
    (v) => v !== "__direct__",
  );
  let variantDetails: Record<
    string,
    { suffix: string; utm_source: string; ref: string }
  > = {};
  if (variantIds.length > 0) {
    const { data: variants } = await supabase
      .from("tracking_variants")
      .select("id, suffix, utm_source, ref")
      .in("id", variantIds);

    for (const v of variants || []) {
      variantDetails[v.id] = {
        suffix: v.suffix,
        utm_source: v.utm_source || "",
        ref: v.ref || "",
      };
    }
  }

  const byVariant = Object.entries(variantCounts)
    .map(([vid, count]) => {
      if (vid === "__direct__") {
        return { label: "direct (no variant)", clicks: count };
      }
      const detail = variantDetails[vid];
      if (detail) {
        return {
          label: detail.utm_source
            ? `${detail.utm_source} (ref=${detail.ref})`
            : detail.suffix,
          suffix: detail.suffix,
          utm_source: detail.utm_source,
          ref: detail.ref,
          clicks: count,
        };
      }
      return { label: vid, clicks: count };
    })
    .sort((a, b) => b.clicks - a.clicks);

  const { count: variantCount, error: variantCountError } = await supabase
    .from("tracking_variants")
    .select("id", { count: "exact", head: true })
    .eq("link_id", link.id);

  if (variantCountError) throw variantCountError;

  const sourceCounts: Record<string, number> = {};
  for (const row of variantClicks || []) {
    let source = "direct";
    if (row.variant_id && variantDetails[row.variant_id]?.utm_source) {
      source = variantDetails[row.variant_id].utm_source;
    }
    sourceCounts[source] = (sourceCounts[source] || 0) + 1;
  }

  const bySource = Object.entries(sourceCounts)
    .map(([source, clicks]) => ({ source, clicks }))
    .sort((a, b) => b.clicks - a.clicks);

  let byPerson: { ref: string; name: string; clicks: number }[] = [];
  if (everybody) {
    const { data: allPeople, error: peopleError } = await supabase
      .from("people")
      .select("slug, name");

    if (peopleError) throw peopleError;

    const refClicks: Record<string, number> = {};
    for (const row of variantClicks || []) {
      if (row.variant_id && variantDetails[row.variant_id]?.ref) {
        const ref = variantDetails[row.variant_id].ref;
        refClicks[ref] = (refClicks[ref] || 0) + 1;
      }
    }

    byPerson = (allPeople || [])
      .map((p) => ({
        ref: p.slug,
        name: p.name || p.slug,
        clicks: refClicks[p.slug] || 0,
      }))
      .sort((a, b) => b.clicks - a.clicks);
  }

  const response: Record<string, unknown> = {
    article: {
      slug: link.slug,
      title: link.title,
      author: link.author,
      url: link.destination_url,
      short_url: `https://${DOMAIN}/${link.slug}`,
      published_at: link.published_at,
      created_at: link.created_at,
      last_synced_at: link.last_synced_at,
    },
    total_clicks: totalClicks ?? 0,
    tracking_variants: variantCount ?? 0,
    daily_clicks: (dailyClicks || []).map(
      (row: { period: string; clicks: number }) => ({
        date: row.period.slice(0, 10),
        clicks: row.clicks,
      }),
    ),
    by_variant: byVariant,
    by_source: bySource,
    days,
  };

  if (everybody) {
    response.by_person = byPerson;
  }

  return jsonResponse(response);
}

async function handleListCustomLinks(params: {
  apiKey: string;
  count?: number;
  all?: boolean;
}): Promise<Response> {
  const { apiKey, count = 10, all = false } = params;

  if (!apiKey) {
    return jsonResponse(
      {
        error:
          "API key required. Pass via x-api-key header or api_key parameter.",
      },
      401,
    );
  }

  const person = await validateApiKey(apiKey);
  if (!person) {
    return jsonResponse({ error: "Invalid API key" }, 401);
  }

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
    return jsonResponse({ error: "Failed to fetch custom links" }, 500);
  }

  const linkIds = (links || []).map((l: { id: string }) => l.id);

  const { data: personSources } = await supabase
    .from("person_sources")
    .select("utm_source, utm_medium, utm_content, utm_term, label")
    .eq("person_id", person.id);

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

  return jsonResponse({
    results,
    person: { name: person.name, slug: person.slug },
    total: results.length,
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  try {
    let action = "article-stats";
    let slug = "";
    let days = 30;
    let everybody = false;
    let apiKey = req.headers.get("x-api-key") || "";
    let count = 10;
    let all = false;
    let interval = "day";
    let startDate = "";
    let endDate = "";
    let comparisonLimit = 8;

    if (req.method === "POST") {
      const body = await req.json();
      action = body.action || "article-stats";
      apiKey = apiKey || body.api_key || "";
      slug = body.slug || body.article_url || body.url || "";
      days = body.days ?? 30;
      everybody = body.everybody === true;
      if (body.count !== undefined) count = Number(body.count);
      if (body.all !== undefined) all = Boolean(body.all);
      if (body.interval !== undefined) interval = String(body.interval);
      if (body.start_date !== undefined) startDate = String(body.start_date || "");
      if (body.end_date !== undefined) endDate = String(body.end_date || "");
      if (body.comparison_limit !== undefined) {
        comparisonLimit = Number(body.comparison_limit) || 8;
      }
    } else {
      const url = new URL(req.url);
      action = url.searchParams.get("action") || "article-stats";
      apiKey = apiKey || url.searchParams.get("api_key") || "";
      slug = url.searchParams.get("slug") || url.searchParams.get("url") || "";
      days = parseInt(url.searchParams.get("days") || "30", 10) || 30;
      everybody = url.searchParams.get("everybody") === "true";
      const countParam = url.searchParams.get("count");
      if (countParam) count = Number(countParam);
      const allParam = url.searchParams.get("all");
      if (allParam === "true" || allParam === "1") all = true;
      interval = url.searchParams.get("interval") || "day";
      startDate = url.searchParams.get("start_date") || "";
      endDate = url.searchParams.get("end_date") || "";
      const comparisonLimitParam = url.searchParams.get("comparison_limit");
      if (comparisonLimitParam) comparisonLimit = Number(comparisonLimitParam) || 8;
    }

    if (action === "article-stats") {
      return await handleArticleStats({ slug, days, everybody });
    } else if (action === "link-analytics") {
      return await handleLinkAnalytics({
        slug,
        interval,
        startDate,
        endDate,
        comparisonLimit,
      });
    } else if (action === "list-custom-links") {
      return await handleListCustomLinks({ apiKey, count, all });
    } else {
      return jsonResponse(
        {
          error:
            `Unknown action '${action}'. Valid actions: article-stats, link-analytics, list-custom-links`,
        },
        400,
      );
    }
  } catch (error) {
    console.error("Analytics error:", error);
    const errorMessage =
      error instanceof Error
        ? error.message
        : typeof error === "string"
          ? error
          : JSON.stringify(error);
    return jsonResponse({ error: errorMessage }, 500);
  }
});
