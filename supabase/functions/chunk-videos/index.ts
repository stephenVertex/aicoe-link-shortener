import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

const OPENAI_API_KEY = Deno.env.get("OPENAI_API_KEY") ?? "";
const EMBEDDING_MODEL = "text-embedding-3-small";

const CHUNK_DURATION = 60;
const CHUNK_OVERLAP = 10;
const MAX_CHUNK_CHARS = 8000;

interface TranscriptSegment {
  text: string;
  start: number;
  duration: number;
}

interface EmbeddingResponse {
  data: Array<{ embedding: number[]; index: number }>;
  usage: { prompt_tokens: number; total_tokens: number };
}

async function generateEmbeddings(texts: string[]): Promise<number[][]> {
  const response = await fetch("https://api.openai.com/v1/embeddings", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${OPENAI_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: EMBEDDING_MODEL,
      input: texts,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`OpenAI API error (${response.status}): ${error}`);
  }

  const result: EmbeddingResponse = await response.json();
  return result.data.sort((a, b) => a.index - b.index).map((d) => d.embedding);
}

function parseTranscript(transcript: string): TranscriptSegment[] {
  const segments: TranscriptSegment[] = [];
  
  const srtRegex = /(\d+)\n(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})\n([\s\S]*?)(?=\n\d+\n|\n*$)/g;
  let match;
  
  while ((match = srtRegex.exec(transcript)) !== null) {
    const text = match[4]
      .replace(/<[^>]+>/g, "")
      .replace(/\n/g, " ")
      .trim();
    if (text) {
      const startTime = parseTimestamp(match[2]);
      const endTime = parseTimestamp(match[3]);
      segments.push({
        text,
        start: startTime,
        duration: endTime - startTime,
      });
    }
  }
  
  if (segments.length === 0) {
    const plainText = transcript
      .replace(/^\d+\s*$/gm, "")
      .replace(/\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}.*/gm, "")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
    if (plainText) {
      const words = plainText.split(/\s+/);
      const wordsPerMinute = 150;
      const totalMinutes = words.length / wordsPerMinute;
      segments.push({
        text: plainText,
        start: 0,
        duration: Math.ceil(totalMinutes * 60),
      });
    }
  }
  
  return segments;
}

function parseTimestamp(ts: string): number {
  const match = ts.match(/(\d{2}):(\d{2}):(\d{2})[,.](\d{3})/);
  if (!match) return 0;
  const [, h, m, s, ms] = match;
  return parseInt(h) * 3600 + parseInt(m) * 60 + parseInt(s) + parseInt(ms) / 1000;
}

function createChunks(segments: TranscriptSegment[]): Array<{
  text: string;
  startTime: number;
  endTime: number;
}> {
  if (segments.length === 0) return [];
  
  const totalDuration = segments[segments.length - 1].start + segments[segments.length - 1].duration;
  if (totalDuration === 0) {
    const text = segments.map(s => s.text).join(" ");
    return [{
      text: text.slice(0, MAX_CHUNK_CHARS),
      startTime: 0,
      endTime: CHUNK_DURATION,
    }];
  }
  
  const chunks: Array<{ text: string; startTime: number; endTime: number }> = [];
  
  for (let start = 0; start < totalDuration; start += CHUNK_DURATION - CHUNK_OVERLAP) {
    const end = Math.min(start + CHUNK_DURATION, totalDuration);
    
    const chunkSegments = segments.filter(
      s => s.start < end && s.start + s.duration > start
    );
    
    if (chunkSegments.length === 0) continue;
    
    const text = chunkSegments.map(s => s.text).join(" ");
    
    if (text.trim()) {
      chunks.push({
        text: text.slice(0, MAX_CHUNK_CHARS),
        startTime: Math.floor(start),
        endTime: Math.floor(end),
      });
    }
    
    if (end >= totalDuration) break;
  }
  
  return chunks;
}

async function authenticateRequest(req: Request): Promise<boolean> {
  const authHeader = req.headers.get("Authorization");
  if (!authHeader?.startsWith("Bearer ")) return false;
  const token = authHeader.slice(7);
  const { data: { user }, error } = await supabase.auth.getUser(token);
  return !error && !!user;
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

  const authHeader = req.headers.get("Authorization");
  if (authHeader) {
    const isAuthenticated = await authenticateRequest(req);
    if (!isAuthenticated) {
      return new Response(JSON.stringify({ error: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      });
    }
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
    const url = new URL(req.url);
    const force = url.searchParams.get("force") === "true";
    const limitParam = url.searchParams.get("limit");
    const limit = limitParam ? parseInt(limitParam, 10) : 0;

    let query = supabase
      .from("links")
      .select("id, slug, title, transcript, destination_url")
      .eq("content_type", "video")
      .not("transcript", "is", null)
      .order("published_at", { ascending: false, nullsFirst: false });

    if (!force) {
      const { data: chunkedVideos } = await supabase
        .from("video_chunks")
        .select("link_id");
      const alreadyChunked = new Set((chunkedVideos || []).map(c => c.link_id));
      
      const { data: allVideos } = await query;
      const toChunk = (allVideos || []).filter(v => !alreadyChunked.has(v.id));
      
      if (toChunk.length === 0) {
        return new Response(
          JSON.stringify({ message: "All videos already chunked", chunked: 0 }),
          {
            headers: { "Content-Type": "application/json", ...corsHeaders },
          },
        );
      }
      
      query = supabase
        .from("links")
        .select("id, slug, title, transcript, destination_url")
        .in("id", toChunk.slice(0, limit || toChunk.length).map(v => v.id));
    } else {
      if (limit > 0) {
        query = query.limit(limit);
      }
    }

    const { data: videos, error: fetchError } = await query;
    if (fetchError) throw fetchError;

    if (!videos || videos.length === 0) {
      return new Response(
        JSON.stringify({ message: "No videos to chunk", chunked: 0 }),
        {
          headers: { "Content-Type": "application/json", ...corsHeaders },
        },
      );
    }

    let totalChunks = 0;
    let totalVideos = 0;
    const batchEmbedSize = 50;

    for (const video of videos) {
      if (!video.transcript) continue;

      const segments = parseTranscript(video.transcript);
      if (segments.length === 0) continue;

      const chunks = createChunks(segments);
      if (chunks.length === 0) continue;

      await supabase
        .from("video_chunks")
        .delete()
        .eq("link_id", video.id);

      for (let i = 0; i < chunks.length; i += batchEmbedSize) {
        const batch = chunks.slice(i, i + batchEmbedSize);
        const texts = batch.map(c => c.text);
        
        const embeddings = await generateEmbeddings(texts);

        const chunkRecords = batch.map((chunk, j) => ({
          link_id: video.id,
          chunk_index: i + j,
          start_time: chunk.startTime,
          end_time: chunk.endTime,
          text: chunk.text,
          embedding: JSON.stringify(embeddings[j]),
        }));

        const { error: insertError } = await supabase
          .from("video_chunks")
          .insert(chunkRecords);

        if (insertError) {
          console.error(`Error inserting chunks for ${video.slug}:`, insertError);
          continue;
        }

        totalChunks += batch.length;
      }

      totalVideos++;
    }

    return new Response(
      JSON.stringify({
        message: `Chunked ${totalVideos} videos into ${totalChunks} segments`,
        videos: totalVideos,
        chunks: totalChunks,
      }),
      {
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  } catch (error) {
    console.error("Chunking error:", error);
    return new Response(JSON.stringify({ error: String(error) }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
});
