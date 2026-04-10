import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

const YOUTUBE_API_KEY = Deno.env.get("YOUTUBE_API_KEY") ?? "";
// The AI-First Show channel — override via env var if needed
const YOUTUBE_CHANNEL_ID = Deno.env.get("YOUTUBE_CHANNEL_ID") ?? "UCxD6pUEKE3bAiZGYuRUhgew";

// AYSP transcript API configuration
const AYSP_TRANSCRIPT_API_URL = Deno.env.get("AYSP_TRANSCRIPT_API_URL") ?? "";
const AYSP_TRANSCRIPT_API_KEY = Deno.env.get("AYSP_TRANSCRIPT_API_KEY") ?? "";

interface YouTubeVideo {
  videoId: string;
  title: string;
  description: string;
  publishedAt: string;
}

interface PlaylistItemsResponse {
  nextPageToken?: string;
  items: Array<{
    snippet: {
      resourceId: { videoId: string };
      title: string;
      description: string;
      publishedAt: string;
    };
  }>;
}

interface ChannelResponse {
  items: Array<{
    contentDetails: {
      relatedPlaylists: { uploads: string };
    };
  }>;
}

interface TranscriptSegment {
  text: string;
  start: number;
  duration: number;
}

/** Get the uploads playlist ID for a channel */
async function getUploadsPlaylistId(channelId: string): Promise<string> {
  const url =
    `https://www.googleapis.com/youtube/v3/channels?part=contentDetails&id=${channelId}&key=${YOUTUBE_API_KEY}`;
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`YouTube channels API error: ${resp.status} ${await resp.text()}`);
  }
  const data: ChannelResponse = await resp.json();
  if (!data.items?.length) {
    throw new Error(`Channel ${channelId} not found`);
  }
  return data.items[0].contentDetails.relatedPlaylists.uploads;
}

/** Fetch all videos from the uploads playlist */
async function fetchAllVideos(playlistId: string): Promise<YouTubeVideo[]> {
  const videos: YouTubeVideo[] = [];
  let pageToken: string | undefined;

  do {
    const params = new URLSearchParams({
      part: "snippet",
      playlistId,
      maxResults: "50",
      key: YOUTUBE_API_KEY,
    });
    if (pageToken) params.set("pageToken", pageToken);

    const resp = await fetch(
      `https://www.googleapis.com/youtube/v3/playlistItems?${params}`,
    );
    if (!resp.ok) {
      throw new Error(`YouTube playlistItems API error: ${resp.status} ${await resp.text()}`);
    }
    const data: PlaylistItemsResponse = await resp.json();

    for (const item of data.items) {
      videos.push({
        videoId: item.snippet.resourceId.videoId,
        title: item.snippet.title,
        description: item.snippet.description,
        publishedAt: item.snippet.publishedAt,
      });
    }

    pageToken = data.nextPageToken;
  } while (pageToken);

  return videos;
}

/** Fetch transcript for a video using YouTube's innertube captions */
async function fetchTranscript(videoId: string): Promise<string | null> {
  try {
    // Fetch the watch page to extract caption track URL
    const watchResp = await fetch(`https://www.youtube.com/watch?v=${videoId}`, {
      headers: { "User-Agent": "Mozilla/5.0" },
    });
    if (!watchResp.ok) return null;
    const html = await watchResp.text();

    // Extract captions from ytInitialPlayerResponse
    const playerRespMatch = html.match(
      /ytInitialPlayerResponse\s*=\s*({.+?});(?:\s*var|\s*<\/script>)/,
    );
    if (!playerRespMatch) return null;

    let playerData;
    try {
      playerData = JSON.parse(playerRespMatch[1]);
    } catch {
      return null;
    }

    const captionTracks =
      playerData?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
    if (!captionTracks?.length) return null;

    // Prefer English, fall back to first available track
    const enTrack = captionTracks.find(
      (t: { languageCode: string }) =>
        t.languageCode === "en" || t.languageCode?.startsWith("en"),
    ) || captionTracks[0];

    if (!enTrack?.baseUrl) return null;

    // Fetch the captions XML
    const capsResp = await fetch(enTrack.baseUrl);
    if (!capsResp.ok) return null;
    const capsXml = await capsResp.text();

    // Parse XML segments: <text start="1.2" dur="3.4">caption text</text>
    const segments: TranscriptSegment[] = [];
    const segRegex = /<text\s+start="([^"]*)"(?:\s+dur="([^"]*)")?\s*>([\s\S]*?)<\/text>/g;
    let match;
    while ((match = segRegex.exec(capsXml)) !== null) {
      const text = match[3]
        .replace(/&amp;/g, "&")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/<[^>]+>/g, "") // strip any HTML tags
        .trim();
      if (text) {
        segments.push({
          text,
          start: parseFloat(match[1]),
          duration: parseFloat(match[2] || "0"),
        });
      }
    }

    if (!segments.length) return null;

    return segmentsToSrt(segments);
  } catch (err) {
    console.error(`Error fetching transcript for ${videoId}:`, err);
    return null;
  }
}

/** Fetch transcript from AYSP lookup-transcript API */
async function fetchTranscriptFromAysp(videoId: string): Promise<string | null> {
  if (!AYSP_TRANSCRIPT_API_URL || !AYSP_TRANSCRIPT_API_KEY) {
    return null;
  }

  try {
    const resp = await fetch(AYSP_TRANSCRIPT_API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": AYSP_TRANSCRIPT_API_KEY,
      },
      body: JSON.stringify({ youtube_video_id: videoId }),
    });

    if (!resp.ok) {
      console.error(`AYSP API error for ${videoId}: ${resp.status}`);
      return null;
    }

    const data = await resp.json();
    if (data.found && data.transcript) {
      return data.transcript;
    }
    return null;
  } catch (err) {
    console.error(`Error fetching transcript from AYSP for ${videoId}:`, err);
    return null;
  }
}

/** Convert transcript segments to SRT format */
function segmentsToSrt(segments: TranscriptSegment[]): string {
  return segments
    .map((seg, i) => {
      const startMs = Math.round(seg.start * 1000);
      const endMs = Math.round((seg.start + seg.duration) * 1000);
      const formatTime = (ms: number) => {
        const h = Math.floor(ms / 3600000);
        const m = Math.floor((ms % 3600000) / 60000);
        const s = Math.floor((ms % 60000) / 1000);
        const msRem = ms % 1000;
        return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")},${msRem.toString().padStart(3, "0")}`;
      };
      return `${i + 1}\n${formatTime(startMs)} --> ${formatTime(endMs)}\n${seg.text}`;
    })
    .join("\n\n");
}

/** Fetch transcript, trying AYSP first then falling back to YouTube scraping */
async function fetchTranscriptWithFallback(videoId: string): Promise<{ transcript: string | null; source: string }> {
  const ayspTranscript = await fetchTranscriptFromAysp(videoId);
  if (ayspTranscript) {
    return { transcript: ayspTranscript, source: "aysp" };
  }
  
  const ytTranscript = await fetchTranscript(videoId);
  return { transcript: ytTranscript, source: "youtube" };
}

/** Generate a URL-friendly slug from a video title */
function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

/** Stopwords to filter out when generating short slugs */
const STOPWORDS = new Set([
  "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of",
  "with", "by", "from", "is", "are", "was", "were", "be", "been", "being",
  "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
  "may", "might", "must", "shall", "can", "this", "that", "these", "those",
  "it", "its", "as", "if", "then", "than", "so", "such", "no", "not", "only",
  "own", "same", "very", "just", "also", "now", "here", "there", "when",
  "where", "why", "how", "all", "each", "every", "both", "few", "more", "most",
  "other", "some", "any", "about", "into", "through", "during", "before",
  "after", "above", "below", "between", "under", "again", "further", "once",
  "ai", "show", "episode", "part", "first", "second", "third", "new", "week",
]);

/** Generate a short slug from a video title by extracting key words */
function generateShortSlug(title: string): string {
  const words = title
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length >= 2 && !STOPWORDS.has(w));

  const keyWords = words.slice(0, 4);

  if (keyWords.length === 0) {
    return slugify(title).slice(0, 12) || "video";
  }

  return keyWords.join("-");
}

async function authenticateApiKey(apiKey: string): Promise<boolean> {
  const { data, error } = await supabase
    .from("people")
    .select("id")
    .eq("api_key", apiKey)
    .maybeSingle();
  return !error && !!data;
}

async function authenticateRequest(req: Request): Promise<boolean> {
  // Check x-api-key first (CLI auth)
  const apiKey = req.headers.get("x-api-key");
  if (apiKey) return authenticateApiKey(apiKey);

  // Fall back to Bearer token (browser/JWT auth)
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
      "authorization, x-client-info, apikey, content-type, x-api-key",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  };

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  const url = new URL(req.url);
  const force = url.searchParams.get("force") === "true";
  const limitParam = url.searchParams.get("limit");
  const limit = limitParam ? parseInt(limitParam, 10) : 0;

  // Validate auth if provided
  const authHeader = req.headers.get("Authorization");
  const apiKeyHeader = req.headers.get("x-api-key");
  if (authHeader || apiKeyHeader) {
    const isAuthenticated = await authenticateRequest(req);
    if (!isAuthenticated) {
      return new Response(JSON.stringify({ error: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      });
    }
  }

  if (!YOUTUBE_API_KEY) {
    return new Response(
      JSON.stringify({ error: "YOUTUBE_API_KEY not configured" }),
      {
        status: 500,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  let syncLogId: string | null = null;
  supabase
    .from("sync_operations")
    .insert({ source: "youtube", status: "running", force })
    .select("id")
    .single()
    .then(({ data }) => { if (data?.id) syncLogId = data.id; }, () => {});

  try {
    // 1. Fetch all videos from the AIFS channel
    const uploadsPlaylistId = await getUploadsPlaylistId(YOUTUBE_CHANNEL_ID);
    const videos = await fetchAllVideos(uploadsPlaylistId);

    // 2. Load existing links for dedup
    const { data: existingLinks } = await supabase
      .from("links")
      .select("id, slug, title, author, destination_url, last_synced_at, content_type");
    const existingByUrl = new Map(
      (existingLinks || []).map((l) => [
        l.destination_url.replace(/\/+$/, ""),
        l,
      ]),
    );

    // 3. Load person sources for tracking variant creation
    const { data: personSources, error: sourcesError } = await supabase
      .from("person_sources")
      .select("person_id, utm_source, utm_medium, utm_content, utm_term");
    if (sourcesError) throw sourcesError;

    const { data: people, error: peopleError } = await supabase
      .from("people")
      .select("id, slug");
    if (peopleError) throw peopleError;
    const peopleById = new Map(
      (people || []).map((p) => [p.id, p.slug]),
    );

    const created: string[] = [];
    const updated: string[] = [];
    const transcriptsFetched: string[] = [];
    const now = new Date().toISOString();

    for (const video of videos) {
      if (limit > 0 && created.length >= limit) break;

      const videoUrl = `https://www.youtube.com/watch?v=${video.videoId}`;
      const slug = generateShortSlug(video.title);
      const existing = existingByUrl.get(videoUrl);

      if (!existing) {
        // Fetch transcript for new video (try AYSP first, then YouTube)
        const { transcript } = await fetchTranscriptWithFallback(video.videoId);
        if (transcript) transcriptsFetched.push(video.videoId);

        const insertData: Record<string, unknown> = {
          slug,
          destination_url: videoUrl,
          title: video.title,
          author: "AI-First Show",
          published_at: video.publishedAt,
          last_synced_at: now,
          content_type: "video",
          description: video.description || null,
          transcript: transcript,
        };

        const { data: linkData, error: linkError } = await supabase
          .from("links")
          .insert(insertData)
          .select()
          .single();

        if (linkError) {
          // Slug collision — append video ID
          if (linkError.code === "23505") {
            insertData.slug = `${slug}-${video.videoId}`;
            const { data: retryData, error: retryError } = await supabase
              .from("links")
              .insert(insertData)
              .select()
              .single();
            if (retryError) {
              console.error(
                `Error creating link for ${video.videoId}:`,
                retryError,
              );
              continue;
            }
            created.push(insertData.slug as string);
            // Create tracking variants
            for (const source of personSources || []) {
              const ref = peopleById.get(source.person_id);
              if (!ref) continue;
              await supabase.rpc("ensure_tracking_variant", {
                p_link_id: retryData.id,
                p_ref: ref,
                p_source: source.utm_source,
                p_medium: source.utm_medium,
                p_content: source.utm_content,
                p_term: source.utm_term,
              });
            }
          } else {
            console.error(
              `Error creating link for ${video.videoId}:`,
              linkError,
            );
          }
          continue;
        }

        created.push(slug);

        // Create tracking variants for all person sources
        for (const source of personSources || []) {
          const ref = peopleById.get(source.person_id);
          if (!ref) continue;
          const { error } = await supabase.rpc("ensure_tracking_variant", {
            p_link_id: linkData.id,
            p_ref: ref,
            p_source: source.utm_source,
            p_medium: source.utm_medium,
            p_content: source.utm_content,
            p_term: source.utm_term,
          });
          if (error) {
            console.error(
              `Error creating variant for ${slug}/${ref}:`,
              error,
            );
          }
        }
      } else if (force || !existing.last_synced_at) {
        // Update existing video metadata
        const changes: Record<string, unknown> = { last_synced_at: now };

        if (existing.title !== video.title) changes.title = video.title;
        if (existing.content_type !== "video") changes.content_type = "video";

        // Re-fetch transcript if forced or missing
        const { data: fullLink } = await supabase
          .from("links")
          .select("transcript, description")
          .eq("id", existing.id)
          .single();

        if (force || !fullLink?.transcript) {
          const { transcript } = await fetchTranscriptWithFallback(video.videoId);
          if (transcript) {
            changes.transcript = transcript;
            transcriptsFetched.push(video.videoId);
          }
        }
        if (force || !fullLink?.description) {
          if (video.description) changes.description = video.description;
        }

        const hasMetadataChanges = Object.keys(changes).length > 1;

        const { error: updateError } = await supabase
          .from("links")
          .update(changes)
          .eq("id", existing.id);
        if (updateError) {
          console.error(
            `Error updating video ${video.videoId}:`,
            updateError,
          );
          continue;
        }

        if (hasMetadataChanges) {
          updated.push(existing.slug);
        }
      }
    }

    if (syncLogId) {
      supabase
        .from("sync_operations")
        .update({
          status: "success",
          completed_at: new Date().toISOString(),
          items_checked: videos.length,
          items_created: created.length,
          items_updated: updated.length,
          details: { created, updated, transcripts_fetched: transcriptsFetched.length, checked: videos.length },
        })
        .eq("id", syncLogId)
        .then(() => {}, () => {});
    }

    return new Response(
      JSON.stringify({
        message:
          `Created ${created.length}, updated ${updated.length} videos (${transcriptsFetched.length} transcripts fetched)`,
        created,
        updated,
        transcripts_fetched: transcriptsFetched.length,
        checked: videos.length,
      }),
      {
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  } catch (error) {
    console.error("YouTube sync error:", error);
    const errorMessage = error instanceof Error ? error.message : String(error);
    if (syncLogId) {
      supabase
        .from("sync_operations")
        .update({
          status: "error",
          completed_at: new Date().toISOString(),
          error_message: errorMessage,
        })
        .eq("id", syncLogId)
        .then(() => {}, () => {});
    }
    return new Response(JSON.stringify({ error: errorMessage }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
});
