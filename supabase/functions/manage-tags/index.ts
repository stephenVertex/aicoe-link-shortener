import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

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

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-api-key",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
};

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-+|-+$)/g, "");
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  let apiKey = req.headers.get("x-api-key") || "";
  let action = "list";
  let tagName = "";
  let tagSlug = "";
  let articleSlug = "";

  if (req.method === "POST") {
    try {
      const body = await req.json();
      apiKey = apiKey || body.api_key || "";
      action = body.action || "list";
      tagName = body.name || body.tag || "";
      tagSlug = body.slug || "";
      articleSlug = body.article || body.article_slug || "";
    } catch {
      return jsonResponse({ error: "Invalid JSON body" }, 400);
    }
  } else if (req.method === "GET") {
    const url = new URL(req.url);
    apiKey = apiKey || url.searchParams.get("api_key") || "";
    action = url.searchParams.get("action") || "list";
    articleSlug = url.searchParams.get("article") || "";
  } else {
    return jsonResponse({ error: "Method not allowed" }, 405);
  }

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

  // --- list: list all tags, optionally filtered to an article ---
  if (action === "list") {
    if (articleSlug) {
      // List tags for a specific article
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

    // List all tags with article counts
    const { data: tags, error: tagError } = await supabase
      .from("tags")
      .select("id, name, slug, created_at")
      .order("name");

    if (tagError) {
      console.error("Error listing tags:", tagError);
      return jsonResponse({ error: "Failed to list tags" }, 500);
    }

    // Get article counts per tag
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

  // --- create: create a new tag ---
  if (action === "create") {
    if (!tagName) {
      return jsonResponse({ error: "name is required" }, 400);
    }

    const slug = tagSlug || slugify(tagName);
    if (!slug) {
      return jsonResponse({ error: "Invalid tag name — produces empty slug" }, 400);
    }

    // Check for duplicate
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

  // --- delete: delete a tag ---
  if (action === "delete") {
    const identifier = tagSlug || slugify(tagName);
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

    // Delete the tag (cascade removes article_tags entries)
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

  // --- tag: assign a tag to an article ---
  if (action === "tag") {
    if (!articleSlug) {
      return jsonResponse({ error: "article (slug) is required" }, 400);
    }

    const identifier = tagSlug || slugify(tagName);
    if (!identifier) {
      return jsonResponse({ error: "name or slug of tag is required" }, 400);
    }

    // Look up the article
    const { data: link } = await supabase
      .from("links")
      .select("id, slug, title")
      .eq("slug", articleSlug)
      .maybeSingle();

    if (!link) {
      return jsonResponse({ error: `Article '${articleSlug}' not found` }, 404);
    }

    // Look up the tag
    const { data: tag } = await supabase
      .from("tags")
      .select("id, name, slug")
      .eq("slug", identifier)
      .maybeSingle();

    if (!tag) {
      return jsonResponse({ error: `Tag '${identifier}' not found` }, 404);
    }

    // Check if already tagged
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

  // --- untag: remove a tag from an article ---
  if (action === "untag") {
    if (!articleSlug) {
      return jsonResponse({ error: "article (slug) is required" }, 400);
    }

    const identifier = tagSlug || slugify(tagName);
    if (!identifier) {
      return jsonResponse({ error: "name or slug of tag is required" }, 400);
    }

    // Look up the article
    const { data: link } = await supabase
      .from("links")
      .select("id, slug, title")
      .eq("slug", articleSlug)
      .maybeSingle();

    if (!link) {
      return jsonResponse({ error: `Article '${articleSlug}' not found` }, 404);
    }

    // Look up the tag
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

  return jsonResponse(
    { error: `Unknown action '${action}'. Valid actions: list, create, delete, tag, untag` },
    400,
  );
});
