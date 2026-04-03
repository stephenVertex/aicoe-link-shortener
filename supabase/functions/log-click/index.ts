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

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }

  let body: { slug?: string; link_id?: string; variant_id?: string | null };
  try {
    body = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const { slug, link_id, variant_id } = body;
  if (!slug && !link_id) {
    return new Response(JSON.stringify({ error: "slug or link_id required" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  let resolvedLinkId = link_id;
  let resolvedVariantId = variant_id;

  if (!resolvedLinkId && slug) {
    const lastDashIndex = slug.lastIndexOf("-");
    if (lastDashIndex > 0) {
      const baseSlug = slug.substring(0, lastDashIndex);
      const suffix = slug.substring(lastDashIndex + 1);

      const { data: variant } = await supabase
        .from("tracking_variants")
        .select("id, link_id, links!inner(slug)")
        .eq("suffix", suffix)
        .eq("links.slug", baseSlug)
        .maybeSingle();

      if (variant) {
        resolvedLinkId = variant.link_id;
        resolvedVariantId = variant.id;
      }
    }

    if (!resolvedLinkId) {
      const { data: link } = await supabase
        .from("links")
        .select("id")
        .eq("slug", slug)
        .maybeSingle();

      if (link) {
        resolvedLinkId = link.id;
      }
    }
  }

  if (!resolvedLinkId) {
    return new Response(JSON.stringify({ logged: false, reason: "not found" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  const ip = req.headers.get("x-forwarded-for") || req.headers.get("x-real-ip") || "unknown";
  const ipHash = hashIP(ip);
  const userAgent = req.headers.get("user-agent") || "";
  const referer = req.headers.get("referer") || "";

  await supabase.from("click_log").insert({
    link_id: resolvedLinkId,
    variant_id: resolvedVariantId,
    ip_hash: ipHash,
    user_agent: userAgent,
    referer: referer,
  });

  return new Response(JSON.stringify({ logged: true }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});