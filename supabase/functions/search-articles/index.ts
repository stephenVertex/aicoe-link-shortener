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
    let contentType: string | undefined;
    let authorFilter: string | undefined;

    if (req.method === "POST") {
      const body = await req.json();
      query = body.query || "";
      if (body.match_threshold !== undefined) {
        matchThreshold = body.match_threshold;
      }
      if (body.match_count !== undefined) matchCount = body.match_count;
      if (body.content_type !== undefined) contentType = body.content_type;
      if (body.author !== undefined) authorFilter = body.author;
    } else {
      const url = new URL(req.url);
      query = url.searchParams.get("q") || "";
      const th = url.searchParams.get("threshold");
      if (th) matchThreshold = parseFloat(th);
      const ct = url.searchParams.get("count");
      if (ct) matchCount = parseInt(ct, 10);
      const src = url.searchParams.get("content_type");
      if (src) contentType = src;
      const auth = url.searchParams.get("author");
      if (auth) authorFilter = auth;
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

    const queryEmbedding = await generateQueryEmbedding(query);

    const rpcParams: Record<string, unknown> = {
      query_embedding: JSON.stringify(queryEmbedding),
      match_threshold: matchThreshold,
      match_count: matchCount,
    };
    if (contentType) {
      rpcParams.content_type_filter = contentType;
    }
    if (authorFilter) {
      rpcParams.author_filter = authorFilter;
    }

    const { data: results, error: searchError } = await supabase.rpc(
      "match_articles",
      rpcParams,
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
    const errorMessage =
      error instanceof Error
        ? error.message
        : typeof error === "object" && error !== null && "message" in error
          ? (error as { message: string }).message
          : typeof error === "string"
            ? error
            : JSON.stringify(error);
    return new Response(JSON.stringify({ error: errorMessage }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
});
