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
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

function jsonResponse(body: Record<string, unknown>, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  if (req.method !== "POST") {
    return jsonResponse({ error: "Method not allowed" }, 405);
  }

  try {
    const { api_key, url } = await req.json();

    if (!api_key || !url) {
      return jsonResponse({ error: "api_key and url are required" }, 400);
    }

    // Validate api_key against people table
    const { data: person, error: personError } = await supabase
      .from("people")
      .select("id, slug, name")
      .eq("api_key", api_key)
      .single();

    if (personError || !person) {
      return jsonResponse({ error: "Invalid API key" }, 401);
    }

    // Extract slug from URL: split on /p/ for Substack URLs, or use raw value
    let slug: string;
    if (url.includes("/p/")) {
      slug = url.split("/p/").pop()?.replace(/\/$/, "") || "";
    } else {
      slug = url;
    }

    if (!slug) {
      return jsonResponse({ error: "Could not extract slug from URL" }, 400);
    }

    // Look up the link by slug
    const { data: link, error: linkError } = await supabase
      .from("links")
      .select("id, slug, title, author")
      .eq("slug", slug)
      .single();

    if (linkError || !link) {
      return jsonResponse({ error: `Link not found for slug: ${slug}` }, 404);
    }

    // Find existing tracking variant for this person + link (first match)
    const { data: variants, error: variantError } = await supabase
      .from("tracking_variants")
      .select("id, suffix")
      .eq("link_id", link.id)
      .eq("ref", person.slug)
      .limit(1);

    if (variantError) {
      return jsonResponse({ error: "Error looking up variant" }, 500);
    }

    let short_url: string;
    if (variants && variants.length > 0) {
      short_url = `https://${DOMAIN}/${link.slug}-${variants[0].suffix}`;
    } else {
      short_url = `https://${DOMAIN}/${link.slug}`;
    }

    return jsonResponse({
      short_url,
      title: link.title,
      author: link.author,
    });
  } catch (error) {
    console.error("get-link error:", error);
    return jsonResponse({ error: String(error) }, 500);
  }
});
