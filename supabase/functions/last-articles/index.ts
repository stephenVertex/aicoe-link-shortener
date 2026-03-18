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
      "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  };

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  let count = 10;
  let author: string | null = null;

  if (req.method === "POST") {
    try {
      const body = await req.json();
      if (body.count !== undefined) count = Math.min(Math.max(1, parseInt(body.count, 10)), 100);
      if (body.author && typeof body.author === "string") author = body.author.trim();
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
    const countParam = url.searchParams.get("count");
    if (countParam) count = Math.min(Math.max(1, parseInt(countParam, 10)), 100);
    const authorParam = url.searchParams.get("author");
    if (authorParam) author = authorParam.trim();
  }

  try {
    // Fetch the last N articles ordered by published_at (falling back to created_at)
    let query = supabase
      .from("links")
      .select("id, slug, title, author, destination_url, published_at, created_at")
      .order("published_at", { ascending: false, nullsFirst: false })
      .limit(count);

    if (author) {
      query = query.ilike("author", `%${author}%`);
    }

    const { data: articles, error } = await query;

    if (error) throw error;

    return new Response(
      JSON.stringify({
        results: (articles || []).map((a) => ({
          slug: a.slug,
          title: a.title,
          author: a.author,
          url: a.destination_url,
          published_at: a.published_at,
          created_at: a.created_at,
        })),
        count: (articles || []).length,
      }),
      {
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  } catch (error) {
    console.error("Error fetching last articles:", error);
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
