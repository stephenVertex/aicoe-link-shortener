import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";
import Anthropic from "npm:@anthropic-ai/sdk@0.39.0";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-api-key",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

function jsonResponse(body: Record<string, unknown>, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

async function validateApiKey(
  apiKey: string,
): Promise<{ id: string; name: string; slug: string } | null> {
  const { data, error } = await supabase.rpc("validate_api_key", {
    p_api_key: apiKey,
  });
  if (error || !data) return null;
  return data as { id: string; name: string; slug: string };
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, "")
    .replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

async function inferUtmFromNote(
  note: string,
): Promise<{ utm_source: string; utm_medium: string }> {
  const fallback = { utm_source: "direct", utm_medium: "referral" };
  if (!note.trim()) return fallback;

  try {
    const anthropicKey = Deno.env.get("ANTHROPIC_API_KEY");
    if (!anthropicKey) return fallback;

    const client = new Anthropic({ apiKey: anthropicKey });
    const resp = await client.messages.create({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 100,
      messages: [
        {
          role: "user",
          content:
            "Given this description of where a link will be shared, " +
            "return a JSON object with utm_source and utm_medium.\n\n" +
            "Common mappings:\n" +
            '- twitter/x → {"utm_source": "twitter", "utm_medium": "social"}\n' +
            '- linkedin → {"utm_source": "linkedin", "utm_medium": "social"}\n' +
            '- youtube → {"utm_source": "youtube", "utm_medium": "video"}\n' +
            '- email/newsletter → {"utm_source": "email", "utm_medium": "newsletter"}\n' +
            '- discord/slack → {"utm_source": "discord"/"slack", "utm_medium": "social"}\n' +
            '- blog/website → {"utm_source": "<site>", "utm_medium": "referral"}\n' +
            "\nReturn ONLY valid JSON, no explanation.\n\n" +
            `Description: ${note}`,
        },
      ],
    });
    const text =
      resp.content[0].type === "text" ? resp.content[0].text.trim() : "";
    const result = JSON.parse(text);
    return {
      utm_source: String(result.utm_source || "direct").toLowerCase(),
      utm_medium: String(result.utm_medium || "referral").toLowerCase(),
    };
  } catch {
    return fallback;
  }
}

/**
 * Resolve a context by ID or ID prefix. Returns the context row or an error response.
 */
async function resolveContext(
  ctxId: string,
  selectFields = "*",
): Promise<
  | { ctx: Record<string, unknown>; error?: never }
  | { ctx?: never; error: Response }
> {
  const { data, error } = await supabase
    .from("link_contexts")
    .select(selectFields)
    .like("id", `${ctxId}%`);

  if (error) return { error: jsonResponse({ error: error.message }, 500) };
  if (!data || data.length === 0) {
    return { error: jsonResponse({ error: `Context not found: ${ctxId}` }, 404) };
  }
  if (data.length > 1) {
    return {
      error: jsonResponse(
        {
          error: `Ambiguous context ID '${ctxId}'`,
          matches: data.slice(0, 5).map((c) => ({ id: c.id, label: c.label })),
        },
        400,
      ),
    };
  }
  return { ctx: data[0] };
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  // Extract API key
  let apiKey = req.headers.get("x-api-key") || "";

  // Parse request
  let params: Record<string, string> = {};
  let body: Record<string, unknown> = {};

  if (req.method === "POST") {
    try {
      body = await req.json();
      apiKey = apiKey || (body.api_key as string) || "";
    } catch {
      return jsonResponse({ error: "Invalid JSON body" }, 400);
    }
  } else {
    const url = new URL(req.url);
    for (const [k, v] of url.searchParams) {
      params[k] = v;
    }
    apiKey = apiKey || params.api_key || "";
  }

  // Auth
  if (!apiKey) {
    return jsonResponse(
      { error: "API key required. Pass via x-api-key header." },
      401,
    );
  }
  const person = await validateApiKey(apiKey);
  if (!person) {
    return jsonResponse({ error: "Invalid API key" }, 401);
  }

  // ─── GET routes ───────────────────────────────────────────────────────
  if (req.method === "GET") {
    // Show single context
    if (params.id) {
      const resolved = await resolveContext(params.id);
      if (resolved.error) return resolved.error;
      const ctx = resolved.ctx;

      // Get variants for this context
      const { data: variants } = await supabase
        .from("tracking_variants")
        .select("id, suffix, link_id, utm_source, utm_medium, note, ref")
        .eq("context_id", ctx.id);

      const variantList = variants || [];

      // Resolve link slugs
      const linkIds = [...new Set(variantList.map((v) => v.link_id))];
      let linkMap: Record<string, string> = {};
      if (linkIds.length > 0) {
        const { data: links } = await supabase
          .from("links")
          .select("id, slug")
          .in("id", linkIds);
        linkMap = Object.fromEntries(
          (links || []).map((l) => [l.id, l.slug]),
        );
      }

      // Get click counts
      const clickMap: Record<string, number> = {};
      const variantIds = variantList.map((v) => v.id);
      if (variantIds.length > 0) {
        for (const vid of variantIds) {
          const { count } = await supabase
            .from("click_log")
            .select("id", { count: "exact", head: true })
            .eq("variant_id", vid);
          clickMap[vid] = count || 0;
        }
      }

      return jsonResponse({
        context: ctx,
        variants: variantList.map((v) => ({
          ...v,
          link_slug: linkMap[v.link_id] || v.link_id,
          short_url: `https://aicoe.fit/${linkMap[v.link_id] || v.link_id}-${v.suffix}`,
          clicks: clickMap[v.id] || 0,
        })),
      });
    }

    // List contexts
    if (params.list === "true") {
      const archived = params.archived === "true";
      let query = supabase
        .from("link_contexts")
        .select("*")
        .order("created_at", { ascending: false });

      if (archived) {
        query = query.not("archived_at", "is", null);
      } else {
        query = query.is("archived_at", null);
      }

      const { data, error } = await query;
      if (error) {
        return jsonResponse({ error: error.message }, 500);
      }
      return jsonResponse({ contexts: data || [] });
    }

    return jsonResponse({ error: "Provide ?id=<ctx_id> or ?list=true" }, 400);
  }

  // ─── POST actions ─────────────────────────────────────────────────────
  const action = body.action as string;

  if (action === "create") {
    const label = body.label as string;
    if (!label) {
      return jsonResponse({ error: "label is required" }, 400);
    }

    const slug = slugify(label);
    const row: Record<string, unknown> = { label, slug };

    if (body.expires) {
      const match = String(body.expires).match(/^(\d+)d$/);
      if (!match) {
        return jsonResponse(
          { error: "expires must be in format Nd (e.g. 30d, 90d)" },
          400,
        );
      }
      const days = parseInt(match[1], 10);
      const expiresAt = new Date(Date.now() + days * 86400000).toISOString();
      row.expires_at = expiresAt;
    }

    const { data, error } = await supabase
      .from("link_contexts")
      .insert(row)
      .select()
      .single();

    if (error) {
      return jsonResponse({ error: error.message }, 500);
    }
    return jsonResponse({ context: data });
  }

  if (action === "generate") {
    const ctxId = body.ctx_id as string;
    if (!ctxId) {
      return jsonResponse({ error: "ctx_id is required" }, 400);
    }

    const resolved = await resolveContext(ctxId, "id, label, slug");
    if (resolved.error) return resolved.error;
    const ctx = resolved.ctx;

    const pinned = body.pinned as boolean;
    if (!pinned) {
      return jsonResponse(
        { error: "--pinned is required (specify which links to generate for)" },
        400,
      );
    }

    // Get pinned links
    const { data: links, error: linksError } = await supabase
      .from("links")
      .select("id, slug")
      .eq("is_pinned", true);

    if (linksError) {
      return jsonResponse({ error: linksError.message }, 500);
    }
    if (!links || links.length === 0) {
      return jsonResponse({
        error: "No pinned links found. Pin some with 'als links pin <slug>'.",
      }, 400);
    }

    const note = (body.note as string) || "";

    // Infer UTM from note (server-side AI)
    const utm = await inferUtmFromNote(note);

    // Generate variants for each pinned link
    const generated = [];
    for (const link of links) {
      const { data: variant, error: rpcError } = await supabase.rpc(
        "ensure_tracking_variant",
        {
          p_link_id: link.id,
          p_ref: person.slug,
          p_source: utm.utm_source,
          p_medium: utm.utm_medium,
          p_content: ctx.slug,
        },
      );

      if (rpcError) {
        console.error(
          `Error generating variant for ${link.slug}:`,
          rpcError,
        );
        continue;
      }

      const variantData =
        typeof variant === "string" ? JSON.parse(variant) : variant;
      const variantId = variantData?.id || "";
      const suffix = variantData?.suffix || "";

      // Update variant with context_id and note
      if (variantId) {
        await supabase
          .from("tracking_variants")
          .update({ context_id: ctx.id, note })
          .eq("id", variantId);
      }

      generated.push({
        slug: link.slug,
        short_url: `https://aicoe.fit/${link.slug}-${suffix}`,
      });
    }

    return jsonResponse({
      context: ctx,
      utm,
      generated,
    });
  }

  if (action === "archive") {
    const ctxId = body.ctx_id as string;
    if (!ctxId) {
      return jsonResponse({ error: "ctx_id is required" }, 400);
    }

    const resolved = await resolveContext(ctxId, "id, label");
    if (resolved.error) return resolved.error;
    const ctx = resolved.ctx;

    const { error: updateError } = await supabase
      .from("link_contexts")
      .update({ archived_at: new Date().toISOString() })
      .eq("id", ctx.id);

    if (updateError) {
      return jsonResponse({ error: updateError.message }, 500);
    }

    return jsonResponse({ archived: true, context: ctx });
  }

  return jsonResponse({ error: `Unknown action: ${action}` }, 400);
});
