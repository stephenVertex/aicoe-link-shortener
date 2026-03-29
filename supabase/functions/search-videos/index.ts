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

function formatTimestamp(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }
  return `${m}:${String(s).padStart(2, '0')}`;
}

function extractYouTubeId(url: string): string | null {
  const match = url.match(/[?&]v=([^&]+)/);
  return match ? match[1] : null;
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
    let query = "";
    let matchThreshold = 0.3;
    let matchCount = 20;
    let dedupeVideos = true;

    if (req.method === "POST") {
      const body = await req.json();
      query = body.query || "";
      if (body.match_threshold !== undefined) matchThreshold = body.match_threshold;
      if (body.match_count !== undefined) matchCount = body.match_count;
      if (body.dedupe_videos !== undefined) dedupeVideos = body.dedupe_videos;
    } else {
      const url = new URL(req.url);
      query = url.searchParams.get("q") || "";
      const th = url.searchParams.get("threshold");
      if (th) matchThreshold = parseFloat(th);
      const ct = url.searchParams.get("count");
      if (ct) matchCount = parseInt(ct, 10);
      const dd = url.searchParams.get("dedupe");
      if (dd) dedupeVideos = dd !== "false";
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

    const { data: results, error: searchError } = await supabase.rpc(
      "search_video_chunks",
      {
        query_embedding: JSON.stringify(queryEmbedding),
        match_threshold: matchThreshold,
        match_count: matchCount,
        dedupe_videos: dedupeVideos,
      },
    );

    if (searchError) throw searchError;

    const enrichedResults = (results || []).map((r: any) => {
      const ytId = extractYouTubeId(r.video_url);
      return {
        ...r,
        timestamp: formatTimestamp(r.start_time),
        thumbnail: ytId ? `https://img.youtube.com/vi/${ytId}/mqdefault.jpg` : null,
        youtube_url: ytId 
          ? `https://www.youtube.com/watch?v=${ytId}&t=${r.start_time}s`
          : r.video_url,
      };
    });

    return new Response(
      JSON.stringify({
        query,
        results: enrichedResults,
        count: enrichedResults.length,
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
