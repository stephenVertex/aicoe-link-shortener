import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-api-key",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

interface PersonInfo {
  id: string;
  name: string;
  slug: string;
  email: string;
}

async function validateApiKey(apiKey: string): Promise<PersonInfo | null> {
  const { data, error } = await supabase.rpc("validate_api_key", {
    p_api_key: apiKey,
  });
  if (error || !data) return null;
  return data as PersonInfo;
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-+|-+$)/g, "");
}

async function handleListTags(params: {
  apiKey: string;
  article?: string;
}): Promise<Response> {
  const { apiKey, article: articleSlug } = params;

  if (!apiKey) {
    return jsonResponse(
      { error: "API key required. Pass via x-api-key header or api_key parameter." },
      401,
    );
  }

  const person = await validateApiKey(apiKey);
  if (!person) {
    return jsonResponse({ error: "Invalid API key" }, 401);
  }

  if (articleSlug) {
    const { data: link } = await supabase
      .from("links")
      .select("id, slug, title")
      .eq("slug", articleSlug)
      .maybeSingle();

    if (!link) {
      return jsonResponse({ error: `Article '${articleSlug}' not found` }, 404);
    }

    const { data: articleTags, error: atError } = await supabase
      .from("article_tags")
      .select("tag_id, tags(id, name, slug, created_at)")
      .eq("link_id", link.id);

    if (atError) {
      console.error("Error listing article tags:", atError);
      return jsonResponse({ error: "Failed to list article tags" }, 500);
    }

    const tags = (articleTags || []).map((at: { tags: unknown }) => at.tags);

    return jsonResponse({
      article: { slug: link.slug, title: link.title },
      tags,
      total: tags.length,
    });
  }

  const { data: tags, error: tagError } = await supabase
    .from("tags")
    .select("id, name, slug, created_at")
    .order("name");

  if (tagError) {
    console.error("Error listing tags:", tagError);
    return jsonResponse({ error: "Failed to list tags" }, 500);
  }

  const { data: counts, error: countError } = await supabase
    .from("article_tags")
    .select("tag_id");

  if (countError) {
    console.error("Error counting articles:", countError);
    return jsonResponse({ error: "Failed to count tagged articles" }, 500);
  }

  const countMap: Record<string, number> = {};
  for (const row of counts || []) {
    countMap[row.tag_id] = (countMap[row.tag_id] || 0) + 1;
  }

  const tagsWithCounts = (tags || []).map((t: { id: string; name: string; slug: string; created_at: string }) => ({
    ...t,
    article_count: countMap[t.id] || 0,
  }));

  return jsonResponse({
    tags: tagsWithCounts,
    total: tagsWithCounts.length,
  });
}

async function handleCreateTag(params: {
  apiKey: string;
  name: string;
  slug?: string;
}): Promise<Response> {
  const { apiKey, name: tagName, slug: tagSlug } = params;

  if (!apiKey) {
    return jsonResponse({ error: "API key required" }, 401);
  }

  const person = await validateApiKey(apiKey);
  if (!person) {
    return jsonResponse({ error: "Invalid API key" }, 401);
  }

  if (!tagName) {
    return jsonResponse({ error: "name is required" }, 400);
  }

  const slug = tagSlug || slugify(tagName);
  if (!slug) {
    return jsonResponse({ error: "Invalid tag name — produces empty slug" }, 400);
  }

  const { data: existing } = await supabase
    .from("tags")
    .select("id, name, slug")
    .eq("slug", slug)
    .maybeSingle();

  if (existing) {
    return jsonResponse({
      error: `Tag '${slug}' already exists`,
      existing,
    }, 409);
  }

  const { data: newTag, error: insertError } = await supabase
    .from("tags")
    .insert({ name: tagName.trim(), slug })
    .select("id, name, slug, created_at")
    .single();

  if (insertError) {
    console.error("Error creating tag:", insertError);
    return jsonResponse({ error: "Failed to create tag" }, 500);
  }

  return jsonResponse({
    tag: newTag,
    message: `Tag '${newTag.name}' created successfully`,
  }, 201);
}

async function handleDeleteTag(params: {
  apiKey: string;
  name?: string;
  slug?: string;
}): Promise<Response> {
  const { apiKey, name: tagName, slug: tagSlug } = params;

  if (!apiKey) {
    return jsonResponse({ error: "API key required" }, 401);
  }

  const person = await validateApiKey(apiKey);
  if (!person) {
    return jsonResponse({ error: "Invalid API key" }, 401);
  }

  const identifier = tagSlug || slugify(tagName || "");
  if (!identifier) {
    return jsonResponse({ error: "name or slug is required" }, 400);
  }

  const { data: tag } = await supabase
    .from("tags")
    .select("id, name, slug")
    .eq("slug", identifier)
    .maybeSingle();

  if (!tag) {
    return jsonResponse({ error: `Tag '${identifier}' not found` }, 404);
  }

  const { error: deleteError } = await supabase
    .from("tags")
    .delete()
    .eq("id", tag.id);

  if (deleteError) {
    console.error("Error deleting tag:", deleteError);
    return jsonResponse({ error: "Failed to delete tag" }, 500);
  }

  return jsonResponse({
    message: `Tag '${tag.name}' deleted successfully`,
    deleted: { id: tag.id, name: tag.name, slug: tag.slug },
  });
}

async function handleTagArticle(params: {
  apiKey: string;
  article: string;
  tagName?: string;
  tagSlug?: string;
}): Promise<Response> {
  const { apiKey, article: articleSlug, tagName, tagSlug } = params;

  if (!apiKey) {
    return jsonResponse({ error: "API key required" }, 401);
  }

  const person = await validateApiKey(apiKey);
  if (!person) {
    return jsonResponse({ error: "Invalid API key" }, 401);
  }

  if (!articleSlug) {
    return jsonResponse({ error: "article (slug) is required" }, 400);
  }

  const identifier = tagSlug || slugify(tagName || "");
  if (!identifier) {
    return jsonResponse({ error: "name or slug of tag is required" }, 400);
  }

  const { data: link } = await supabase
    .from("links")
    .select("id, slug, title")
    .eq("slug", articleSlug)
    .maybeSingle();

  if (!link) {
    return jsonResponse({ error: `Article '${articleSlug}' not found` }, 404);
  }

  const { data: tag } = await supabase
    .from("tags")
    .select("id, name, slug")
    .eq("slug", identifier)
    .maybeSingle();

  if (!tag) {
    return jsonResponse({ error: `Tag '${identifier}' not found` }, 404);
  }

  const { data: existing } = await supabase
    .from("article_tags")
    .select("id")
    .eq("link_id", link.id)
    .eq("tag_id", tag.id)
    .maybeSingle();

  if (existing) {
    return jsonResponse({
      message: `Article '${link.slug}' is already tagged with '${tag.name}'`,
      article: { slug: link.slug, title: link.title },
      tag: { name: tag.name, slug: tag.slug },
    });
  }

  const { error: insertError } = await supabase
    .from("article_tags")
    .insert({ link_id: link.id, tag_id: tag.id });

  if (insertError) {
    console.error("Error tagging article:", insertError);
    return jsonResponse({ error: "Failed to tag article" }, 500);
  }

  return jsonResponse({
    message: `Article '${link.slug}' tagged with '${tag.name}'`,
    article: { slug: link.slug, title: link.title },
    tag: { name: tag.name, slug: tag.slug },
  }, 201);
}

async function handleUntagArticle(params: {
  apiKey: string;
  article: string;
  tagName?: string;
  tagSlug?: string;
}): Promise<Response> {
  const { apiKey, article: articleSlug, tagName, tagSlug } = params;

  if (!apiKey) {
    return jsonResponse({ error: "API key required" }, 401);
  }

  const person = await validateApiKey(apiKey);
  if (!person) {
    return jsonResponse({ error: "Invalid API key" }, 401);
  }

  if (!articleSlug) {
    return jsonResponse({ error: "article (slug) is required" }, 400);
  }

  const identifier = tagSlug || slugify(tagName || "");
  if (!identifier) {
    return jsonResponse({ error: "name or slug of tag is required" }, 400);
  }

  const { data: link } = await supabase
    .from("links")
    .select("id, slug, title")
    .eq("slug", articleSlug)
    .maybeSingle();

  if (!link) {
    return jsonResponse({ error: `Article '${articleSlug}' not found` }, 404);
  }

  const { data: tag } = await supabase
    .from("tags")
    .select("id, name, slug")
    .eq("slug", identifier)
    .maybeSingle();

  if (!tag) {
    return jsonResponse({ error: `Tag '${identifier}' not found` }, 404);
  }

  const { error: deleteError } = await supabase
    .from("article_tags")
    .delete()
    .eq("link_id", link.id)
    .eq("tag_id", tag.id);

  if (deleteError) {
    console.error("Error untagging article:", deleteError);
    return jsonResponse({ error: "Failed to untag article" }, 500);
  }

  return jsonResponse({
    message: `Tag '${tag.name}' removed from article '${link.slug}'`,
    article: { slug: link.slug, title: link.title },
    tag: { name: tag.name, slug: tag.slug },
  });
}

async function handleUpdateTranscript(params: {
  apiKey: string;
  url: string;
  transcript: string;
}): Promise<Response> {
  const { apiKey, url, transcript } = params;

  if (!apiKey) {
    return jsonResponse(
      { error: "API key required. Pass via x-api-key header or api_key parameter." },
      401,
    );
  }

  const person = await validateApiKey(apiKey);
  if (!person) {
    return jsonResponse({ error: "Invalid API key" }, 401);
  }

  if (!url) {
    return jsonResponse({ error: "url parameter is required" }, 400);
  }

  if (!transcript) {
    return jsonResponse({ error: "transcript parameter is required" }, 400);
  }

  const { data: link, error: lookupError } = await supabase
    .from("links")
    .select("id, slug, destination_url, title, transcript")
    .eq("destination_url", url)
    .maybeSingle();

  if (lookupError) {
    console.error("Error looking up link:", lookupError);
    return jsonResponse({ error: "Database error looking up link" }, 500);
  }

  let foundLink = link;
  if (!foundLink) {
    const urlVariant = url.endsWith("/")
      ? url.slice(0, -1)
      : url + "/";
    const { data: variantLink } = await supabase
      .from("links")
      .select("id, slug, destination_url, title, transcript")
      .eq("destination_url", urlVariant)
      .maybeSingle();
    foundLink = variantLink;
  }

  if (!foundLink) {
    return jsonResponse({ error: `No link found for URL: ${url}` }, 404);
  }

  const hadTranscript = !!foundLink.transcript;

  const { error: updateError } = await supabase
    .from("links")
    .update({ transcript })
    .eq("id", foundLink.id);

  if (updateError) {
    console.error("Error updating transcript:", updateError);
    return jsonResponse({ error: "Database error updating transcript" }, 500);
  }

  return jsonResponse({
    message: hadTranscript
      ? `Transcript updated for "${foundLink.title}"`
      : `Transcript added for "${foundLink.title}"`,
    slug: foundLink.slug,
    title: foundLink.title,
    replaced_existing: hadTranscript,
    transcript_length: transcript.length,
  });
}

async function handleListAuthors(): Promise<Response> {
  const { data, error } = await supabase
    .from("links")
    .select("author")
    .not("author", "is", null)
    .not("author", "eq", "");

  if (error) throw error;

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

  return jsonResponse({
    authors,
    count: authors.length,
  });
}

async function handleDbStats(): Promise<Response> {
  const { data: linksData, error: linksError } = await supabase
    .from("links")
    .select("id, author");

  if (linksError) throw linksError;

  const articleCount = (linksData || []).length;
  const distinctAuthors = new Set(
    (linksData || [])
      .map((r) => (r.author as string | null)?.trim())
      .filter((a): a is string => !!a),
  );
  const authorCount = distinctAuthors.size;

  const { count: totalClicks, error: clickError } = await supabase
    .from("click_log")
    .select("id", { count: "exact", head: true });

  if (clickError) throw clickError;

  const { count: personCount, error: personError } = await supabase
    .from("people")
    .select("id", { count: "exact", head: true });

  if (personError) throw personError;

  const { count: variantCount, error: variantError } = await supabase
    .from("tracking_variants")
    .select("id", { count: "exact", head: true });

  if (variantError) throw variantError;

  return jsonResponse({
    articles: articleCount,
    authors: authorCount,
    clicks: totalClicks ?? 0,
    people: personCount ?? 0,
    tracking_variants: variantCount ?? 0,
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  try {
    let action = "list-tags";
    let apiKey = req.headers.get("x-api-key") || "";
    let article = "";
    let tagName = "";
    let tagSlug = "";
    let url = "";
    let transcript = "";

    if (req.method === "POST") {
      const body = await req.json();
      action = body.action || "list-tags";
      apiKey = apiKey || body.api_key || "";
      article = body.article || body.article_slug || "";
      tagName = body.name || body.tag || "";
      tagSlug = body.slug || "";
      url = body.url || "";
      transcript = body.transcript || "";
    } else if (req.method === "GET") {
      const urlObj = new URL(req.url);
      action = urlObj.searchParams.get("action") || "list-tags";
      apiKey = apiKey || urlObj.searchParams.get("api_key") || "";
      article = urlObj.searchParams.get("article") || "";
    } else {
      return jsonResponse({ error: "Method not allowed" }, 405);
    }

    switch (action) {
      case "list-tags":
        return await handleListTags({ apiKey, article });
      case "create-tag":
        return await handleCreateTag({ apiKey, name: tagName, slug: tagSlug });
      case "delete-tag":
        return await handleDeleteTag({ apiKey, name: tagName, slug: tagSlug });
      case "tag-article":
        return await handleTagArticle({ apiKey, article, tagName, tagSlug });
      case "untag-article":
        return await handleUntagArticle({ apiKey, article, tagName, tagSlug });
      case "update-transcript":
        return await handleUpdateTranscript({ apiKey, url, transcript });
      case "list-authors":
        return await handleListAuthors();
      case "stats":
        return await handleDbStats();
      default:
        return jsonResponse(
          { error: `Unknown action '${action}'. Valid actions: list-tags, create-tag, delete-tag, tag-article, untag-article, update-transcript, list-authors, stats` },
          400,
        );
    }
  } catch (error) {
    console.error("Manage-content error:", error);
    const errorMessage =
      error instanceof Error
        ? error.message
        : typeof error === "string"
          ? error
          : JSON.stringify(error);
    return jsonResponse({ error: errorMessage }, 500);
  }
});