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

/**
 * Validate an API key and return the person info.
 */
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

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  // Extract API key and action
  let apiKey = req.headers.get("x-api-key") || "";
  let action = "list";
  let label = "";
  let source = "";
  let medium = "social";
  let content = "";
  let term = "";
  let icon = "";

  if (req.method === "POST") {
    try {
      const body = await req.json();
      apiKey = apiKey || body.api_key || "";
      action = body.action || "list";
      label = body.label || "";
      source = body.source || "";
      medium = body.medium || "social";
      content = body.content || "";
      term = body.term || "";
      icon = body.icon || "";
    } catch {
      return jsonResponse({ error: "Invalid JSON body" }, 400);
    }
  } else if (req.method === "GET") {
    const url = new URL(req.url);
    apiKey = apiKey || url.searchParams.get("api_key") || "";
    action = url.searchParams.get("action") || "list";
  } else {
    return jsonResponse({ error: "Method not allowed" }, 405);
  }

  // Validate API key
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

  // Route by action
  if (action === "list") {
    // List all tracking variants (person_sources) for this person
    const { data: sources, error: srcError } = await supabase
      .from("person_sources")
      .select("id, label, utm_source, utm_medium, utm_content, utm_term, icon, is_default, created_at")
      .eq("person_id", person.id)
      .order("created_at");

    if (srcError) {
      console.error("Error listing sources:", srcError);
      return jsonResponse({ error: "Failed to list tracking variants" }, 500);
    }

    return jsonResponse({
      variants: sources || [],
      person: { name: person.name, slug: person.slug },
      total: (sources || []).length,
    });
  } else if (action === "add") {
    // Validate required fields
    if (!source) {
      return jsonResponse({ error: "source is required (e.g. linkedin, discord)" }, 400);
    }

    // Normalise inputs (same logic as create_person_source RPC)
    const sourceNorm = source.toLowerCase().trim()
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/(^-+|-+$)/g, "");
    if (!sourceNorm) {
      return jsonResponse({ error: "Invalid source value" }, 400);
    }

    const mediumNorm = (medium || "social").toLowerCase().trim() || "social";
    const contentNorm = content
      ? (content.toLowerCase().trim().replace(/[^a-z0-9_-]+/g, "-").replace(/(^-+|-+$)/g, "") || null)
      : null;
    const termNorm = term
      ? (term.toLowerCase().trim().replace(/[^a-z0-9_-]+/g, "-").replace(/(^-+|-+$)/g, "") || null)
      : null;

    // Derive label if not provided
    let labelNorm = label.trim();
    if (!labelNorm) {
      labelNorm = sourceNorm.charAt(0).toUpperCase() + sourceNorm.slice(1);
      if (contentNorm) {
        labelNorm += " - " + contentNorm.replace(/-/g, " ");
      }
    }

    // Derive icon if not provided
    const iconMap: Record<string, string> = {
      linkedin: "💼",
      x: "⚡",
      twitter: "⚡",
      youtube: "▶️",
      discord: "🎮",
      whatsapp: "💬",
      slack: "⚙️",
      email: "✉️",
    };
    const iconNorm = icon.trim() || iconMap[sourceNorm] || "🔗";

    // Check for duplicate with matching UTM params
    const dupQuery = supabase
      .from("person_sources")
      .select("id, label, is_default")
      .eq("person_id", person.id)
      .eq("utm_source", sourceNorm)
      .eq("utm_medium", mediumNorm);

    const { data: dupCheck } = contentNorm !== null
      ? await dupQuery.eq("utm_content", contentNorm).maybeSingle()
      : await dupQuery.is("utm_content", null).maybeSingle();

    if (dupCheck) {
      return jsonResponse({
        error: `A tracking variant for '${sourceNorm}' with these parameters already exists (label: '${dupCheck.label}')`,
        existing: dupCheck,
      }, 409);
    }

    // Insert new person_source (always custom, not default)
    const { data: newSource, error: insertError } = await supabase
      .from("person_sources")
      .insert({
        person_id: person.id,
        label: labelNorm,
        icon: iconNorm,
        utm_source: sourceNorm,
        utm_medium: mediumNorm,
        utm_content: contentNorm,
        utm_term: termNorm,
        is_default: false,
      })
      .select("id, label, utm_source, utm_medium, utm_content, utm_term, icon, is_default, created_at")
      .single();

    if (insertError) {
      console.error("Error creating source:", insertError);
      return jsonResponse({ error: "Failed to create tracking variant" }, 500);
    }

    return jsonResponse({
      variant: newSource,
      message: `Tracking variant '${labelNorm}' created successfully`,
    }, 201);
  } else if (action === "delete") {
    // Delete by label (case-insensitive) or by source
    if (!label && !source) {
      return jsonResponse({ error: "label or source is required" }, 400);
    }

    // Find the variant(s) to delete
    let query = supabase
      .from("person_sources")
      .select("id, label, utm_source, is_default")
      .eq("person_id", person.id);

    if (label) {
      query = query.ilike("label", label);
    } else {
      query = query.eq("utm_source", source.toLowerCase().trim());
    }

    const { data: toDelete, error: findError } = await query;

    if (findError) {
      console.error("Error finding source:", findError);
      return jsonResponse({ error: "Failed to look up tracking variant" }, 500);
    }

    if (!toDelete || toDelete.length === 0) {
      return jsonResponse({
        error: `No tracking variant found matching '${label || source}'`,
      }, 404);
    }

    if (toDelete.length > 1) {
      return jsonResponse({
        error: `Multiple variants match '${label || source}'. Please be more specific.`,
        matches: toDelete.map((s: { id: string; label: string; utm_source: string }) => ({
          id: s.id,
          label: s.label,
          source: s.utm_source,
        })),
      }, 409);
    }

    const target = toDelete[0];

    // Refuse to delete default/system variants
    if (target.is_default) {
      return jsonResponse({
        error: `Cannot delete '${target.label}' — it is a default system tracking variant. Only custom variants can be deleted.`,
        is_default: true,
      }, 403);
    }

    // Delete the source
    const { error: deleteError } = await supabase
      .from("person_sources")
      .delete()
      .eq("id", target.id)
      .eq("person_id", person.id);

    if (deleteError) {
      console.error("Error deleting source:", deleteError);
      return jsonResponse({ error: "Failed to delete tracking variant" }, 500);
    }

    return jsonResponse({
      message: `Tracking variant '${target.label}' deleted successfully`,
      deleted: { id: target.id, label: target.label },
    });
  } else {
    return jsonResponse(
      { error: `Unknown action '${action}'. Valid actions: list, add, delete` },
      400,
    );
  }
});
