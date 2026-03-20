import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

const OPENAI_API_KEY = Deno.env.get("OPENAI_API_KEY") ?? "";
const EMBEDDING_MODEL = "text-embedding-3-small";
const BATCH_SIZE = 50;

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
  // Sort by index to maintain order
  return result.data.sort((a, b) => a.index - b.index).map((d) => d.embedding);
}

/** Strip SRT/VTT timestamp lines and sequence numbers, returning plain dialogue text. */
function stripSrt(text: string): string {
  return text
    .replace(/^\d+\s*$/gm, "")                                                          // sequence numbers on their own line
    .replace(/\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}.*/gm, "") // timestamp lines
    .replace(/\n{3,}/g, "\n\n")                                                          // collapse blank lines
    .trim();
}

function buildEmbeddingText(article: {
  title: string | null;
  slug: string;
  author: string | null;
  description: string | null;
  transcript: string | null;
}): string {
  const parts: string[] = [];
  if (article.title) parts.push(article.title);
  if (article.author) parts.push(`by ${article.author}`);
  // Add slug as fallback context (slugs often contain descriptive words)
  parts.push(article.slug.replace(/-/g, " "));
  // Include description and transcript for richer embeddings (YouTube videos)
  if (article.description) parts.push(article.description);
  if (article.transcript) {
    // Strip SRT timestamps before embedding to maximise semantic signal
    const plainText = stripSrt(article.transcript);
    // text-embedding-3-small supports ~8192 tokens (~32K chars); use 20K (~5K tokens) for transcript,
    // leaving headroom for title/author/slug/description
    const truncated = plainText.slice(0, 20000);
    parts.push(truncated);
  }
  return parts.join(". ");
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

  // Require authentication
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
    const forceAll = url.searchParams.get("force") === "true";

    // Fetch articles that need embeddings
    let query = supabase
      .from("links")
      .select("id, slug, title, author, description, transcript")
      .order("published_at", { ascending: false, nullsFirst: false });

    if (!forceAll) {
      query = query.is("embedding", null);
    }

    const { data: articles, error: fetchError } = await query;
    if (fetchError) throw fetchError;

    if (!articles || articles.length === 0) {
      return new Response(
        JSON.stringify({ message: "No articles need embedding", embedded: 0 }),
        {
          headers: { "Content-Type": "application/json", ...corsHeaders },
        },
      );
    }

    let totalEmbedded = 0;

    // Process in batches
    for (let i = 0; i < articles.length; i += BATCH_SIZE) {
      const batch = articles.slice(i, i + BATCH_SIZE);
      const texts = batch.map(buildEmbeddingText);

      const embeddings = await generateEmbeddings(texts);

      // Update each article with its embedding
      for (let j = 0; j < batch.length; j++) {
        const { error: updateError } = await supabase
          .from("links")
          .update({ embedding: JSON.stringify(embeddings[j]) })
          .eq("id", batch[j].id);

        if (updateError) {
          console.error(
            `Error updating embedding for ${batch[j].slug}:`,
            updateError,
          );
          continue;
        }
        totalEmbedded++;
      }
    }

    return new Response(
      JSON.stringify({
        message: `Embedded ${totalEmbedded} articles`,
        embedded: totalEmbedded,
        total_articles: articles.length,
      }),
      {
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  } catch (error) {
    console.error("Embedding error:", error);
    return new Response(JSON.stringify({ error: String(error) }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
});
