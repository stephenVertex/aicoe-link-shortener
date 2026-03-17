import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

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

  try {
    // Fetch article count and distinct author count from links table
    const { data: linksData, error: linksError } = await supabase
      .from("links")
      .select("id, author");

    if (linksError) throw linksError;

    const articleCount = (linksData || []).length;
    const distinctAuthors = new Set(
      (linksData || [])
        .map((r) => (r.author as string | null)?.trim())
        .filter((a): a is string => !!a),
    );
    const authorCount = distinctAuthors.size;

    // Fetch total click count from click_log
    const { count: totalClicks, error: clickError } = await supabase
      .from("click_log")
      .select("id", { count: "exact", head: true });

    if (clickError) throw clickError;

    // Fetch person count
    const { count: personCount, error: personError } = await supabase
      .from("people")
      .select("id", { count: "exact", head: true });

    if (personError) throw personError;

    // Fetch tracking variant count
    const { count: variantCount, error: variantError } = await supabase
      .from("tracking_variants")
      .select("id", { count: "exact", head: true });

    if (variantError) throw variantError;

    return new Response(
      JSON.stringify({
        articles: articleCount,
        authors: authorCount,
        clicks: totalClicks ?? 0,
        people: personCount ?? 0,
        tracking_variants: variantCount ?? 0,
      }),
      {
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  } catch (error) {
    console.error("Error fetching stats:", error);
    const errorMessage =
      error instanceof Error
        ? error.message
        : typeof error === "string"
          ? error
          : JSON.stringify(error);
    return new Response(JSON.stringify({ error: errorMessage }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
});
