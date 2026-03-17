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
    // Fetch distinct non-null authors, with article counts, sorted alphabetically
    const { data, error } = await supabase
      .from("links")
      .select("author")
      .not("author", "is", null)
      .not("author", "eq", "");

    if (error) throw error;

    // Aggregate counts client-side (Supabase JS doesn't support GROUP BY directly)
    const countMap: Record<string, number> = {};
    for (const row of data || []) {
      const author = (row.author as string).trim();
      if (author) {
        countMap[author] = (countMap[author] ?? 0) + 1;
      }
    }

    const authors = Object.entries(countMap)
      .map(([name, article_count]) => ({ name, article_count }))
      .sort((a, b) => a.name.localeCompare(b.name));

    return new Response(
      JSON.stringify({
        authors,
        count: authors.length,
      }),
      {
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  } catch (error) {
    console.error("Error fetching authors:", error);
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
