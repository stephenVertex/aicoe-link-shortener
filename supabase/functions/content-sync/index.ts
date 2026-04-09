import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

async function authenticateRequest(req: Request): Promise<boolean> {
  const authHeader = req.headers.get("Authorization");
  if (!authHeader?.startsWith("Bearer ")) return false;
  const token = authHeader.slice(7);
  const { data: { user }, error } = await supabase.auth.getUser(token);
  return !error && !!user;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  const url = new URL(req.url);
  const action = url.searchParams.get("action") || "substack";
  const force = url.searchParams.get("force") === "true";

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

  const { data: syncLog } = await supabase
    .from("sync_operations")
    .insert({ source: action, status: "running", force })
    .select("id")
    .single();
  const syncLogId = syncLog?.id;

  try {
    let result: Response;
    switch (action) {
      case "substack":
        result = await handleSyncSubstack(force);
        break;
      case "youtube":
        result = await handleSyncYoutube(url.searchParams.get("limit"), force);
        break;
      case "embed":
        result = await handleEmbedArticles(force);
        break;
      case "chunk":
        result = await handleChunkVideos(url.searchParams.get("limit"), force);
        break;
      default:
        result = new Response(
          JSON.stringify({ error: `Unknown action '${action}'. Valid actions: substack, youtube, embed, chunk` }),
          { status: 400, headers: { "Content-Type": "application/json", ...corsHeaders } },
        );
    }

    if (syncLogId) {
      result.clone().json().then((body) => {
        supabase
          .from("sync_operations")
          .update({
            status: "success",
            completed_at: new Date().toISOString(),
            items_checked: body.checked ?? null,
            items_created: body.created?.length ?? null,
            items_updated: body.updated?.length ?? null,
            details: body,
          })
          .eq("id", syncLogId)
          .then(() => {}, () => {});
      }).catch(() => {});
    }

    return result;
  } catch (error) {
    if (syncLogId) {
      const errorMessage = error instanceof Error ? error.message : String(error);
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
    console.error(`Content-sync error (${action}):`, error);
    return new Response(JSON.stringify({ error: String(error) }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
});

async function handleSyncSubstack(force: boolean): Promise<Response> {
  const SUBSTACK_URL = "https://trilogyai.substack.com";

  interface SitemapEntry {
    url: string;
    lastmod: string | null;
  }

  interface ApiPost {
    slug: string;
    title: string;
    canonical_url?: string;
    publishedBylines?: Array<{ name?: string }>;
  }

  async function fetchSitemapEntries(): Promise<SitemapEntry[]> {
    const resp = await fetch(`${SUBSTACK_URL}/sitemap.xml`);
    const xml = await resp.text();

    const entries: SitemapEntry[] = [];
    const urlBlockRegex = /<url>([\s\S]*?)<\/url>/g;
    let block;
    while ((block = urlBlockRegex.exec(xml)) !== null) {
      const locMatch = block[1].match(/<loc>([^<]*\/p\/[^<]*)<\/loc>/);
      if (locMatch) {
        const lastmodMatch = block[1].match(/<lastmod>([^<]*)<\/lastmod>/);
        entries.push({
          url: locMatch[1],
          lastmod: lastmodMatch ? lastmodMatch[1] : null,
        });
      }
    }
    return entries;
  }

  async function fetchAllPostMeta(): Promise<Map<string, ApiPost>> {
    const posts = new Map<string, ApiPost>();
    let offset = 0;
    while (true) {
      const resp = await fetch(`${SUBSTACK_URL}/api/v1/posts?limit=50&offset=${offset}`, {
        headers: { "User-Agent": "Mozilla/5.0" },
      });
      if (!resp.ok) break;
      const batch = (await resp.json()) as ApiPost[];
      if (!batch.length) break;
      for (const post of batch) posts.set(post.slug, post);
      offset += 50;
    }
    return posts;
  }

  const [sitemapEntries, postMeta] = await Promise.all([
    fetchSitemapEntries(),
    fetchAllPostMeta(),
  ]);

  const { data: existingLinks } = await supabase
    .from("links")
    .select("id, slug, title, author, published_at, destination_url, last_synced_at");
  const existingBySlug = new Map(
    (existingLinks || []).map((l) => [l.slug, l]),
  );
  const existingByUrl = new Map(
    (existingLinks || []).map((l) => [l.destination_url.replace(/\/+$/, ""), l]),
  );

  const { data: personSources, error: sourcesError } = await supabase
    .from("person_sources")
    .select("person_id, utm_source, utm_medium, utm_content, utm_term");
  if (sourcesError) throw sourcesError;

  const { data: people, error: peopleError } = await supabase.from("people").select("id, slug");
  if (peopleError) throw peopleError;
  const peopleById = new Map((people || []).map((p) => [p.id, p.slug]));

  const created: string[] = [];
  const updated: string[] = [];
  const skipped: string[] = [];
  const now = new Date().toISOString();

  for (const entry of sitemapEntries) {
    const slug = entry.url.split("/p/").pop()?.replace(/\/$/, "") || "";

    if (!postMeta.has(slug)) {
      skipped.push(slug);
      continue;
    }

    const meta = postMeta.get(slug);
    const newTitle = meta?.title || slug;
    const newAuthor = meta?.publishedBylines?.[0]?.name || null;
    const newPublishedAt = entry.lastmod || null;
    const newDestUrl = meta?.canonical_url || entry.url;

    const existing = existingBySlug.get(slug);
    const urlNorm = newDestUrl.replace(/\/+$/, "");
    const existingByUrlMatch = !existing ? existingByUrl.get(urlNorm) : null;

    if (!existing && !existingByUrlMatch) {
      const insertData: Record<string, unknown> = {
        slug,
        destination_url: newDestUrl,
        title: newTitle,
        author: newAuthor,
        last_synced_at: now,
      };
      if (newPublishedAt) insertData.published_at = newPublishedAt;

      const { data: linkData, error: linkError } = await supabase
        .from("links")
        .insert(insertData)
        .select()
        .single();
      if (linkError) {
        console.error(`Error creating link ${slug}:`, linkError);
        continue;
      }

      created.push(slug);

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
          console.error(`Error creating variant for ${slug}/${ref}:`, error);
        }
      }
    } else if (existingByUrlMatch && !existing) {
      const changes: Record<string, unknown> = { last_synced_at: now };
      if (existingByUrlMatch.title !== newTitle) changes.title = newTitle;
      if (existingByUrlMatch.author !== newAuthor) changes.author = newAuthor;
      if (newPublishedAt && existingByUrlMatch.published_at !== newPublishedAt) {
        changes.published_at = newPublishedAt;
      }

      const { error: updateError } = await supabase
        .from("links")
        .update(changes)
        .eq("id", existingByUrlMatch.id);
      if (updateError) {
        console.error(`Error updating custom link for ${slug}:`, updateError);
        continue;
      }

      const hasMetadataChanges = Object.keys(changes).length > 1;
      if (hasMetadataChanges) {
        updated.push(slug);
      }

      for (const source of personSources || []) {
        const ref = peopleById.get(source.person_id);
        if (!ref) continue;
        const { error } = await supabase.rpc("ensure_tracking_variant", {
          p_link_id: existingByUrlMatch.id,
          p_ref: ref,
          p_source: source.utm_source,
          p_medium: source.utm_medium,
          p_content: source.utm_content,
          p_term: source.utm_term,
        });
        if (error) {
          console.error(`Error creating variant for ${slug}/${ref}:`, error);
        }
      }
    } else if (existing && (force || !existing.last_synced_at)) {
      const changes: Record<string, unknown> = {};

      if (existing.title !== newTitle) changes.title = newTitle;
      if (existing.author !== newAuthor) changes.author = newAuthor;
      if (existing.destination_url !== newDestUrl) changes.destination_url = newDestUrl;
      if (newPublishedAt && existing.published_at !== newPublishedAt) {
        changes.published_at = newPublishedAt;
      }

      changes.last_synced_at = now;

      const hasMetadataChanges = Object.keys(changes).length > 1;

      const { error: updateError } = await supabase
        .from("links")
        .update(changes)
        .eq("id", existing.id);
      if (updateError) {
        console.error(`Error updating link ${slug}:`, updateError);
        continue;
      }

      if (hasMetadataChanges) {
        updated.push(slug);
      }
    }
  }

  return new Response(JSON.stringify({
    message: `Created ${created.length}, updated ${updated.length} links (skipped ${skipped.length} restacks)`,
    created,
    updated,
    skipped,
    checked: sitemapEntries.length,
  }), {
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

async function handleSyncYoutube(limitParam: string | null, force: boolean): Promise<Response> {
  const YOUTUBE_API_KEY = Deno.env.get("YOUTUBE_API_KEY") ?? "";
  const YOUTUBE_CHANNEL_ID = Deno.env.get("YOUTUBE_CHANNEL_ID") ?? "UCxD6pUEKE3bAiZGYuRUhgew";
  const AYSP_TRANSCRIPT_API_URL = Deno.env.get("AYSP_TRANSCRIPT_API_URL") ?? "";
  const AYSP_TRANSCRIPT_API_KEY = Deno.env.get("AYSP_TRANSCRIPT_API_KEY") ?? "";
  const limit = limitParam ? parseInt(limitParam, 10) : 0;

  if (!YOUTUBE_API_KEY) {
    return new Response(
      JSON.stringify({ error: "YOUTUBE_API_KEY not configured" }),
      { status: 500, headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

  const uploadsPlaylistId = await getUploadsPlaylistId(YOUTUBE_CHANNEL_ID, YOUTUBE_API_KEY);
  const videos = await fetchAllVideos(uploadsPlaylistId, YOUTUBE_API_KEY);

  const { data: existingLinks } = await supabase
    .from("links")
    .select("id, slug, title, author, destination_url, last_synced_at, content_type");
  const existingByUrl = new Map(
    (existingLinks || []).map((l) => [
      l.destination_url.replace(/\/+$/, ""),
      l,
    ]),
  );

  const { data: personSources } = await supabase
    .from("person_sources")
    .select("person_id, utm_source, utm_medium, utm_content, utm_term");

  const { data: people } = await supabase.from("people").select("id, slug");
  const peopleById = new Map((people || []).map((p) => [p.id, p.slug]));

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
      const { transcript } = await fetchTranscriptWithFallback(
        video.videoId,
        AYSP_TRANSCRIPT_API_URL,
        AYSP_TRANSCRIPT_API_KEY,
      );
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
        if (linkError.code === "23505") {
          insertData.slug = `${slug}-${video.videoId}`;
          const { data: retryData, error: retryError } = await supabase
            .from("links")
            .insert(insertData)
            .select()
            .single();
          if (retryError) {
            console.error(`Error creating link for ${video.videoId}:`, retryError);
            continue;
          }
          created.push(insertData.slug as string);
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
          console.error(`Error creating link for ${video.videoId}:`, linkError);
        }
        continue;
      }

      created.push(slug);

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
          console.error(`Error creating variant for ${slug}/${ref}:`, error);
        }
      }
    } else if (force || !existing.last_synced_at) {
      const changes: Record<string, unknown> = { last_synced_at: now };

      if (existing.title !== video.title) changes.title = video.title;
      if (existing.content_type !== "video") changes.content_type = "video";

      const { data: fullLink } = await supabase
        .from("links")
        .select("transcript, description")
        .eq("id", existing.id)
        .single();

      if (force || !fullLink?.transcript) {
        const { transcript } = await fetchTranscriptWithFallback(
          video.videoId,
          AYSP_TRANSCRIPT_API_URL,
          AYSP_TRANSCRIPT_API_KEY,
        );
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
        console.error(`Error updating video ${video.videoId}:`, updateError);
        continue;
      }

      if (hasMetadataChanges) {
        updated.push(existing.slug);
      }
    }
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
    { headers: { "Content-Type": "application/json", ...corsHeaders } },
  );
}

async function handleEmbedArticles(force: boolean): Promise<Response> {
  const OPENAI_API_KEY = Deno.env.get("OPENAI_API_KEY") ?? "";
  const EMBEDDING_MODEL = "text-embedding-3-small";
  const BATCH_SIZE = 50;

  if (!OPENAI_API_KEY) {
    return new Response(
      JSON.stringify({ error: "OPENAI_API_KEY not configured" }),
      { status: 500, headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

  let query = supabase
    .from("links")
    .select("id, slug, title, author, description, transcript")
    .order("published_at", { ascending: false, nullsFirst: false });

  if (!force) {
    query = query.is("embedding", null);
  }

  const { data: articles, error: fetchError } = await query;
  if (fetchError) throw fetchError;

  if (!articles || articles.length === 0) {
    return new Response(
      JSON.stringify({ message: "No articles need embedding", embedded: 0 }),
      { headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

  let totalEmbedded = 0;

  for (let i = 0; i < articles.length; i += BATCH_SIZE) {
    const batch = articles.slice(i, i + BATCH_SIZE);
    const texts = batch.map(buildEmbeddingText);

    const embeddings = await generateEmbeddings(texts, OPENAI_API_KEY, EMBEDDING_MODEL);

    for (let j = 0; j < batch.length; j++) {
      const { error: updateError } = await supabase
        .from("links")
        .update({ embedding: JSON.stringify(embeddings[j]) })
        .eq("id", batch[j].id);

      if (updateError) {
        console.error(`Error updating embedding for ${batch[j].slug}:`, updateError);
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
    { headers: { "Content-Type": "application/json", ...corsHeaders } },
  );
}

async function handleChunkVideos(limitParam: string | null, force: boolean): Promise<Response> {
  const OPENAI_API_KEY = Deno.env.get("OPENAI_API_KEY") ?? "";
  const EMBEDDING_MODEL = "text-embedding-3-small";
  const CHUNK_DURATION = 60;
  const CHUNK_OVERLAP = 10;
  const MAX_CHUNK_CHARS = 8000;
  const limit = limitParam ? parseInt(limitParam, 10) : 0;

  if (!OPENAI_API_KEY) {
    return new Response(
      JSON.stringify({ error: "OPENAI_API_KEY not configured" }),
      { status: 500, headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

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
        { headers: { "Content-Type": "application/json", ...corsHeaders } },
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
      { headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

  let totalChunks = 0;
  let totalVideos = 0;
  const batchEmbedSize = 50;

  for (const video of videos) {
    if (!video.transcript) continue;

    const segments = parseTranscript(video.transcript);
    if (segments.length === 0) continue;

    const chunks = createChunks(segments, CHUNK_DURATION, CHUNK_OVERLAP, MAX_CHUNK_CHARS);
    if (chunks.length === 0) continue;

    await supabase
      .from("video_chunks")
      .delete()
      .eq("link_id", video.id);

    for (let i = 0; i < chunks.length; i += batchEmbedSize) {
      const batch = chunks.slice(i, i + batchEmbedSize);
      const texts = batch.map(c => c.text);

      const embeddings = await generateEmbeddings(texts, OPENAI_API_KEY, EMBEDDING_MODEL);

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
    { headers: { "Content-Type": "application/json", ...corsHeaders } },
  );
}

async function getUploadsPlaylistId(channelId: string, apiKey: string): Promise<string> {
  const url = `https://www.googleapis.com/youtube/v3/channels?part=contentDetails&id=${channelId}&key=${apiKey}`;
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`YouTube channels API error: ${resp.status} ${await resp.text()}`);
  }
  const data = await resp.json();
  if (!data.items?.length) {
    throw new Error(`Channel ${channelId} not found`);
  }
  return data.items[0].contentDetails.relatedPlaylists.uploads;
}

async function fetchAllVideos(playlistId: string, apiKey: string): Promise<any[]> {
  const videos: any[] = [];
  let pageToken: string | undefined;

  do {
    const params = new URLSearchParams({
      part: "snippet",
      playlistId,
      maxResults: "50",
      key: apiKey,
    });
    if (pageToken) params.set("pageToken", pageToken);

    const resp = await fetch(`https://www.googleapis.com/youtube/v3/playlistItems?${params}`);
    if (!resp.ok) {
      throw new Error(`YouTube playlistItems API error: ${resp.status} ${await resp.text()}`);
    }
    const data = await resp.json();

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

async function fetchTranscriptWithFallback(
  videoId: string,
  ayspUrl: string,
  ayspKey: string,
): Promise<{ transcript: string | null; source: string }> {
  if (ayspUrl && ayspKey) {
    try {
      const resp = await fetch(ayspUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": ayspKey,
        },
        body: JSON.stringify({ youtube_video_id: videoId }),
      });

      if (resp.ok) {
        const data = await resp.json();
        if (data.found && data.transcript) {
          return { transcript: data.transcript, source: "aysp" };
        }
      }
    } catch (err) {
      console.error(`Error fetching transcript from AYSP for ${videoId}:`, err);
    }
  }

  const ytTranscript = await fetchTranscript(videoId);
  return { transcript: ytTranscript, source: "youtube" };
}

async function fetchTranscript(videoId: string): Promise<string | null> {
  try {
    const watchResp = await fetch(`https://www.youtube.com/watch?v=${videoId}`, {
      headers: { "User-Agent": "Mozilla/5.0" },
    });
    if (!watchResp.ok) return null;
    const html = await watchResp.text();

    const playerRespMatch = html.match(/ytInitialPlayerResponse\s*=\s*({.+?});(?:\s*var|\s*<\/script>)/);
    if (!playerRespMatch) return null;

    let playerData;
    try {
      playerData = JSON.parse(playerRespMatch[1]);
    } catch {
      return null;
    }

    const captionTracks = playerData?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
    if (!captionTracks?.length) return null;

    const enTrack = captionTracks.find(
      (t: { languageCode: string }) => t.languageCode === "en" || t.languageCode?.startsWith("en"),
    ) || captionTracks[0];

    if (!enTrack?.baseUrl) return null;

    const capsResp = await fetch(enTrack.baseUrl);
    if (!capsResp.ok) return null;
    const capsXml = await capsResp.text();

    const segments: any[] = [];
    const segRegex = /<text\s+start="([^"]*)"(?:\s+dur="([^"]*)")?\s*>([\s\S]*?)<\/text>/g;
    let match;
    while ((match = segRegex.exec(capsXml)) !== null) {
      const text = match[3]
        .replace(/&amp;/g, "&")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/<[^>]+>/g, "")
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

function segmentsToSrt(segments: any[]): string {
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

function generateShortSlug(title: string): string {
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

  const words = title
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length >= 2 && !STOPWORDS.has(w));

  const keyWords = words.slice(0, 4);

  if (keyWords.length === 0) {
    return title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 80) || "video";
  }

  return keyWords.join("-");
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
  parts.push(article.slug.replace(/-/g, " "));
  if (article.description) parts.push(article.description);
  if (article.transcript) {
    const plainText = article.transcript
      .replace(/^\d+\s*$/gm, "")
      .replace(/\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}.*/gm, "")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
    const truncated = plainText.slice(0, 20000);
    parts.push(truncated);
  }
  return parts.join(". ");
}

async function generateEmbeddings(texts: string[], apiKey: string, model: string): Promise<number[][]> {
  const response = await fetch("https://api.openai.com/v1/embeddings", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model,
      input: texts,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`OpenAI API error (${response.status}): ${error}`);
  }

  const result = await response.json();
  return result.data.sort((a: any, b: any) => a.index - b.index).map((d: any) => d.embedding);
}

function parseTranscript(transcript: string): any[] {
  const segments: any[] = [];

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

function createChunks(
  segments: any[],
  chunkDuration: number,
  chunkOverlap: number,
  maxChunkChars: number,
): Array<{ text: string; startTime: number; endTime: number }> {
  if (segments.length === 0) return [];

  const totalDuration = segments[segments.length - 1].start + segments[segments.length - 1].duration;
  if (totalDuration === 0) {
    const text = segments.map(s => s.text).join(" ");
    return [{
      text: text.slice(0, maxChunkChars),
      startTime: 0,
      endTime: chunkDuration,
    }];
  }

  const chunks: Array<{ text: string; startTime: number; endTime: number }> = [];

  for (let start = 0; start < totalDuration; start += chunkDuration - chunkOverlap) {
    const end = Math.min(start + chunkDuration, totalDuration);

    const chunkSegments = segments.filter(
      s => s.start < end && s.start + s.duration > start,
    );

    if (chunkSegments.length === 0) continue;

    const text = chunkSegments.map(s => s.text).join(" ");

    if (text.trim()) {
      chunks.push({
        text: text.slice(0, maxChunkChars),
        startTime: Math.floor(start),
        endTime: Math.floor(end),
      });
    }

    if (end >= totalDuration) break;
  }

  return chunks;
}