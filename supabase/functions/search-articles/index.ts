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

function dedupeChunksByText(
  chunks: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  const seen = new Map<string, Record<string, unknown>>();
  for (const c of chunks) {
    const key = `${c.start_time ?? ""}|${(c.text as string || "").trim()}`;
    const existing = seen.get(key);
    if (!existing || (c.similarity as number) > (existing.similarity as number)) {
      seen.set(key, c);
    }
  }
  return Array.from(seen.values()).sort(
    (a, b) => (b.similarity as number) - (a.similarity as number),
  );
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

    const shouldSearchChunks = !contentType || contentType === "video";

    const [articlesResult, chunksResult] = await Promise.all([
      supabase.rpc("match_articles", rpcParams),
      shouldSearchChunks
        ? supabase.rpc("search_video_chunks", {
            query_embedding: JSON.stringify(queryEmbedding),
            match_threshold: matchThreshold,
            match_count: matchCount,
            dedupe_videos: true,
          })
        : Promise.resolve({ data: null, error: null }),
    ]);

    if (articlesResult.error) throw articlesResult.error;
    if (chunksResult.error) throw chunksResult.error;

    const articles = (articlesResult.data || []) as Array<Record<string, unknown>>;
    const rawChunks = (chunksResult.data || []) as Array<Record<string, unknown>>;

    const chunks = dedupeChunksByText(rawChunks);

    let merged: Array<Record<string, unknown>>;

    if (shouldSearchChunks && chunks.length > 0) {
      const chunkVideoIds = new Set(
        chunks.map((c) => c.link_id as string),
      );

      const nonVideoArticles = articles.filter(
        (a) => !chunkVideoIds.has(a.id as string),
      ).map((a) => ({
        ...a,
        match_type: "article",
      }));

      const chunkResults = chunks.map((c) => {
        const baseUrl = (c.video_url as string) || "";
        const startTime = c.start_time as number | null;
        const timestampParam = startTime != null ? `&t=${startTime}` : "";
        const ytMatch = baseUrl.match(/[?&]v=([^&]+)/);
        const videoUrlWithTs = ytMatch
          ? `https://www.youtube.com/watch?v=${ytMatch[1]}${timestampParam}`
          : baseUrl;

        return {
          id: c.link_id,
          slug: c.video_slug,
          title: c.video_title,
          author: null,
          destination_url: c.video_url,
          video_url: videoUrlWithTs,
          published_at: null,
          created_at: null,
          similarity: c.similarity,
          start_time: c.start_time,
          end_time: c.end_time,
          text: c.text,
          match_type: "transcript",
        };
      });

      merged = [...nonVideoArticles, ...chunkResults].sort(
        (a, b) => (b.similarity as number) - (a.similarity as number),
      );
    } else {
      merged = articles.map((a) => {
        const destUrl = (a.destination_url as string) || "";
        const ytMatch = destUrl.match(/[?&]v=([^&]+)/);
        return {
          ...a,
          match_type: "article",
          video_url: ytMatch
            ? `https://www.youtube.com/watch?v=${ytMatch[1]}`
            : null,
        };
      });
    }

    const finalResults = merged.slice(0, matchCount);

    return new Response(
      JSON.stringify({
        query,
        results: finalResults,
        count: finalResults.length,
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
