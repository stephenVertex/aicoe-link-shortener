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

/**
 * Find a link by slug or destination URL (same logic as get-link).
 */
async function findLink(
  articleUrl: string,
): Promise<{
  id: string;
  slug: string;
  destination_url: string;
  title: string | null;
  author: string | null;
  created_at: string | null;
  published_at: string | null;
  last_synced_at: string | null;
} | null> {
  const cols =
    "id, slug, destination_url, title, author, created_at, published_at, last_synced_at";

  // Exact slug match
  const { data: bySlug } = await supabase
    .from("links")
    .select(cols)
    .eq("slug", articleUrl)
    .maybeSingle();
  if (bySlug) return bySlug;

  // Destination URL match
  const { data: byUrl } = await supabase
    .from("links")
    .select(cols)
    .eq("destination_url", articleUrl)
    .maybeSingle();
  if (byUrl) return byUrl;

  // Trailing slash variant
  const urlVariant = articleUrl.endsWith("/")
    ? articleUrl.slice(0, -1)
    : articleUrl + "/";
  const { data: byUrlVariant } = await supabase
    .from("links")
    .select(cols)
    .eq("destination_url", urlVariant)
    .maybeSingle();
  if (byUrlVariant) return byUrlVariant;

  // Extract slug from Substack URL
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

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  try {
    let slug = "";
    let days = 30;

    if (req.method === "POST") {
      const body = await req.json();
      slug = body.slug || body.article_url || body.url || "";
      days = body.days ?? 30;
    } else {
      const url = new URL(req.url);
      slug = url.searchParams.get("slug") || url.searchParams.get("url") || "";
      days = parseInt(url.searchParams.get("days") || "30", 10) || 30;
    }

    if (!slug) {
      return jsonResponse(
        { error: "slug or article_url parameter required" },
        400,
      );
    }

    // Find the article
    const link = await findLink(slug);
    if (!link) {
      return jsonResponse({ error: `No article found for: ${slug}` }, 404);
    }

    // Total click count for this article
    const { count: totalClicks, error: clickCountError } = await supabase
      .from("click_log")
      .select("id", { count: "exact", head: true })
      .eq("link_id", link.id);

    if (clickCountError) throw clickCountError;

    // Click history by day using the analytics RPC
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

    // Clicks per variant (to show which channels drive traffic)
    const { data: variantClicks, error: variantClicksError } = await supabase
      .from("click_log")
      .select("variant_id")
      .eq("link_id", link.id);

    if (variantClicksError) throw variantClicksError;

    // Count by variant_id
    const variantCounts: Record<string, number> = {};
    for (const row of variantClicks || []) {
      const vid = row.variant_id || "__direct__";
      variantCounts[vid] = (variantCounts[vid] || 0) + 1;
    }

    // Resolve variant details
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

    // Build per-variant breakdown
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

    // Count tracking variants for this article
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

    return jsonResponse({
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
    });
  } catch (error) {
    console.error("Error fetching article stats:", error);
    const errorMessage =
      error instanceof Error
        ? error.message
        : typeof error === "string"
          ? error
          : JSON.stringify(error);
    return jsonResponse({ error: errorMessage }, 500);
  }
});
