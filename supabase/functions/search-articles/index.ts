import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

const OPENAI_API_KEY = Deno.env.get("OPENAI_API_KEY") ?? "";
const EMBEDDING_MODEL = "text-embedding-3-small";

interface EmbeddingResponse {
  data: Array<{ embedding: number[]; index: number }>;
  usage: { prompt_tokens: number; total_tokens: number };
}

async function generateQueryEmbedding(query: string): Promise<number[]> {
  const response = await fetch("https://api.openai.com/v1/embeddings", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${OPENAI_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: EMBEDDING_MODEL,
      input: query,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`OpenAI API error (${response.status}): ${error}`);
  }

  const result: EmbeddingResponse = await response.json();
  return result.data[0].embedding;
}

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

  if (!OPENAI_API_KEY) {
    return new Response(
      JSON.stringify({ error: "OPENAI_API_KEY not configured" }),
      {
        status: 500,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  try {
    // Accept query from URL param or POST body
    let query = "";
    let matchThreshold = 0.3;
    let matchCount = 20;

    if (req.method === "POST") {
      const body = await req.json();
      query = body.query || "";
      if (body.match_threshold !== undefined) {
        matchThreshold = body.match_threshold;
      }
      if (body.match_count !== undefined) matchCount = body.match_count;
    } else {
      const url = new URL(req.url);
      query = url.searchParams.get("q") || "";
      const th = url.searchParams.get("threshold");
      if (th) matchThreshold = parseFloat(th);
      const ct = url.searchParams.get("count");
      if (ct) matchCount = parseInt(ct, 10);
    }

    if (!query.trim()) {
      return new Response(
        JSON.stringify({ error: "Query parameter 'q' is required" }),
        {
          status: 400,
          headers: { "Content-Type": "application/json", ...corsHeaders },
        },
      );
    }

    // Generate embedding for the search query
    const queryEmbedding = await generateQueryEmbedding(query);

    // Use the match_articles function for similarity search
    const { data: results, error: searchError } = await supabase.rpc(
      "match_articles",
      {
        query_embedding: JSON.stringify(queryEmbedding),
        match_threshold: matchThreshold,
        match_count: matchCount,
      },
    );

    if (searchError) throw searchError;

    return new Response(
      JSON.stringify({
        query,
        results: results || [],
        count: (results || []).length,
      }),
      {
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  } catch (error) {
    console.error("Search error:", error);
    return new Response(JSON.stringify({ error: String(error) }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
});
