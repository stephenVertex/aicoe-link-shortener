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
            '- twitter/x \u2192 {"utm_source": "twitter", "utm_medium": "social"}\n' +
            '- linkedin \u2192 {"utm_source": "linkedin", "utm_medium": "social"}\n' +
            '- youtube \u2192 {"utm_source": "youtube", "utm_medium": "video"}\n' +
            '- email/newsletter \u2192 {"utm_source": "email", "utm_medium": "newsletter"}\n' +
            '- discord/slack \u2192 {"utm_source": "discord"/"slack", "utm_medium": "social"}\n' +
            '- blog/website \u2192 {"utm_source": "<site>", "utm_medium": "referral"}\n' +
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

  // Route: GET = list links, POST = action dispatch
  if (req.method === "GET") {
    // List links
    const pinned = params.pinned === "true";
    let query = supabase
      .from("links")
      .select("id, slug, destination_url, title, is_pinned, created_at");
    if (pinned) {
      query = query.eq("is_pinned", true);
    }
    query = query.order("created_at", { ascending: false }).limit(50);

    const { data, error } = await query;
    if (error) {
      return jsonResponse({ error: error.message }, 500);
    }
    return jsonResponse({ links: data || [] });
  }

  // POST actions
  const action = body.action as string;

  if (action === "pin") {
    const slugOrId = body.slug_or_id as string;
    if (!slugOrId) {
      return jsonResponse({ error: "slug_or_id is required" }, 400);
    }

    // Find the link
    let query;
    if (slugOrId.startsWith("lnk-")) {
      query = supabase
        .from("links")
        .select("id, slug")
        .like("id", `${slugOrId}%`);
    } else {
      query = supabase
        .from("links")
        .select("id, slug")
        .eq("slug", slugOrId);
    }

    const { data: matches, error: findError } = await query;
    if (findError) {
      return jsonResponse({ error: findError.message }, 500);
    }
    if (!matches || matches.length === 0) {
      return jsonResponse({ error: `Link not found: ${slugOrId}` }, 404);
    }
    if (matches.length > 1) {
      return jsonResponse(
        {
          error: `Ambiguous match for '${slugOrId}'`,
          matches: matches.slice(0, 5),
        },
        400,
      );
    }

    const link = matches[0];
    const { error: updateError } = await supabase
      .from("links")
      .update({ is_pinned: true })
      .eq("id", link.id);
    if (updateError) {
      return jsonResponse({ error: updateError.message }, 500);
    }

    return jsonResponse({ pinned: true, link });
  }

  if (action === "shorten_with_note") {
    const linkIdOrUrl = body.link as string;
    const note = (body.note as string) || "";
    const expires = body.expires as string | undefined;
    const noExpires = body.no_expires as boolean | undefined;

    if (!linkIdOrUrl) {
      return jsonResponse({ error: "link (ID, slug, or URL) is required" }, 400);
    }
    if (!note) {
      return jsonResponse({ error: "note is required" }, 400);
    }

    // Resolve link
    let link: { id: string; slug: string } | null = null;

    if (linkIdOrUrl.startsWith("lnk-")) {
      // Try exact then prefix
      const { data: exact } = await supabase
        .from("links")
        .select("id, slug")
        .eq("id", linkIdOrUrl)
        .maybeSingle();
      if (exact) {
        link = exact;
      } else {
        const { data: prefix } = await supabase
          .from("links")
          .select("id, slug")
          .like("id", `${linkIdOrUrl}%`);
        if (!prefix || prefix.length === 0) {
          return jsonResponse({ error: `Link not found: ${linkIdOrUrl}` }, 404);
        }
        if (prefix.length > 1) {
          return jsonResponse(
            { error: `Ambiguous ID '${linkIdOrUrl}'`, matches: prefix.slice(0, 5) },
            400,
          );
        }
        link = prefix[0];
      }
    } else {
      // Try by URL then slug
      const { data: byUrl } = await supabase
        .from("links")
        .select("id, slug")
        .eq("destination_url", linkIdOrUrl)
        .maybeSingle();
      if (byUrl) {
        link = byUrl;
      } else {
        const { data: bySlug } = await supabase
          .from("links")
          .select("id, slug")
          .eq("slug", linkIdOrUrl)
          .maybeSingle();
        if (bySlug) {
          link = bySlug;
        }
      }
    }

    if (!link) {
      return jsonResponse({ error: `Link not found: ${linkIdOrUrl}` }, 404);
    }

    // Infer UTM from note
    const utm = await inferUtmFromNote(note);

    // Create tracking variant
    const { data: variant, error: rpcError } = await supabase.rpc(
      "ensure_tracking_variant",
      {
        p_link_id: link.id,
        p_ref: person.slug,
        p_source: utm.utm_source,
        p_medium: utm.utm_medium,
      },
    );

    if (rpcError) {
      return jsonResponse({ error: rpcError.message }, 500);
    }

    const variantData = typeof variant === "string" ? JSON.parse(variant) : variant;
    const variantId = variantData?.id || "";
    const suffix = variantData?.suffix || "";

    // Compute expires_at
    let expiresAt: string | null = null;
    if (!noExpires) {
      if (expires) {
        const match = expires.match(/^(\d+)d$/);
        if (!match) {
          return jsonResponse({ error: "expires must be in format Nd (e.g. 30d, 90d)" }, 400);
        }
        expiresAt = new Date(Date.now() + parseInt(match[1], 10) * 86400000).toISOString();
      } else {
        // Default 60 days
        expiresAt = new Date(Date.now() + 60 * 86400000).toISOString();
      }
    }

    // Update variant with note and expires_at
    const updateFields: Record<string, unknown> = { note };
    if (expiresAt !== null) {
      updateFields.expires_at = expiresAt;
    }
    if (variantId) {
      await supabase
        .from("tracking_variants")
        .update(updateFields)
        .eq("id", variantId);
    }

    return jsonResponse({
      link,
      utm,
      variant: {
        id: variantId,
        suffix,
        short_url: `https://aicoe.fit/${link.slug}-${suffix}`,
        note,
        expires_at: expiresAt,
      },
    });
  }

  return jsonResponse({ error: `Unknown action: ${action}` }, 400);
});
