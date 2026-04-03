import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? ""
);

function hashIP(ip: string): string {
  let hash = 0;
  for (let i = 0; i < ip.length; i++) {
    const char = ip.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash;
  }
  return Math.abs(hash).toString(36);
}

async function logClick(
  linkId: string,
  variantId: string | null,
  req: Request
): Promise<void> {
  const ip = req.headers.get("x-forwarded-for") || req.headers.get("x-real-ip") || "unknown";
  const ipHash = hashIP(ip);
  const userAgent = req.headers.get("user-agent") || "";
  const referer = req.headers.get("referer") || "";

  await supabase.from("click_log").insert({
    link_id: linkId,
    variant_id: variantId,
    ip_hash: ipHash,
    user_agent: userAgent,
    referer: referer,
  });
}

Deno.serve(async (req: Request) => {
  const url = new URL(req.url);
  const path = url.pathname.replace(/^\/redirect\//, "").replace(/^\//, "").replace(/\/$/, "");

  if (!path) {
    return new Response("Not found", { status: 404 });
  }

  const { data: exactLink } = await supabase
    .from("links")
    .select("id, destination_url")
    .eq("slug", path)
    .maybeSingle();

  if (exactLink) {
    const _logPromise = logClick(exactLink.id, null, req);
    return new Response(null, {
      status: 302,
      headers: {
        Location: exactLink.destination_url,
        "X-Link-Id": exactLink.id,
      },
    });
  }

  const lastDashIndex = path.lastIndexOf("-");
  if (lastDashIndex > 0) {
    const slug = path.substring(0, lastDashIndex);
    const suffix = path.substring(lastDashIndex + 1);

    const { data: variant } = await supabase
      .from("tracking_variants")
      .select("id, link_id, utm_source, utm_medium, utm_campaign, utm_content, utm_term, ref, expires_at, links!inner(destination_url)")
      .eq("suffix", suffix)
      .eq("links.slug", slug)
      .maybeSingle();

    if (variant) {
      const linkData = variant.links as { destination_url: string };
      const now = new Date();

      if (variant.expires_at && new Date(variant.expires_at) < now) {
        return new Response("This link has expired", {
          status: 410,
          headers: {
            "X-Link-Id": variant.link_id,
            "X-Variant-Id": variant.id,
            "X-Expires-At": variant.expires_at,
          },
        });
      }

      const destUrl = new URL(linkData.destination_url);
      if (variant.utm_source) destUrl.searchParams.set("utm_source", variant.utm_source);
      if (variant.utm_medium) destUrl.searchParams.set("utm_medium", variant.utm_medium);
      if (variant.utm_campaign) destUrl.searchParams.set("utm_campaign", variant.utm_campaign);
      if (variant.utm_content) destUrl.searchParams.set("utm_content", variant.utm_content);
      if (variant.utm_term) destUrl.searchParams.set("utm_term", variant.utm_term);
      if (variant.ref) destUrl.searchParams.set("ref", variant.ref);

      const _logPromise = logClick(variant.link_id, variant.id, req);
      return new Response(null, {
        status: 302,
        headers: {
          Location: destUrl.toString(),
          "X-Link-Id": variant.link_id,
          "X-Variant-Id": variant.id,
          "X-Expires-At": variant.expires_at || "",
        },
      });
    }
  }

  return new Response("Not found", { status: 404 });
});