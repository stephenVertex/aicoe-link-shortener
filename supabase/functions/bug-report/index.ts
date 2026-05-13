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
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
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

  let apiKey = req.headers.get("x-api-key") || "";
  let action = "create";
  let title = "";
  let description = "";
  let yesodNoteId = "";
  let commitHash = "";

  if (req.method === "POST") {
    try {
      const body = await req.json();
      apiKey = apiKey || body.api_key || "";
      action = body.action || "create";
      title = body.title || "";
      description = body.description || "";
      yesodNoteId = body.yesod_note_id || "";
      commitHash = body.commit_hash || "";
    } catch {
      return jsonResponse({ error: "Invalid JSON body" }, 400);
    }
  } else {
    const reqUrl = new URL(req.url);
    apiKey = apiKey || reqUrl.searchParams.get("api_key") || "";
    action = reqUrl.searchParams.get("action") || "list";
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

  if (action === "create") {
    if (!title || !description) {
      return jsonResponse(
        { error: "title and description are required" },
        400,
      );
    }

    const { data, error } = await supabase
      .from("bug_reports")
      .insert({
        title: title.trim(),
        description: description.trim(),
        source: "cli",
        created_by: person.slug,
        yesod_note_id: yesodNoteId || null,
        commit_hash: commitHash || null,
      })
      .select("id, title, status, created_at")
      .single();

    if (error) {
      console.error("Error creating bug report:", error);
      return jsonResponse({ error: "Failed to create bug report" }, 500);
    }

    return jsonResponse({
      message: "Bug report filed successfully",
      bug_report: data,
    });
  }

  if (action === "list") {
    const { data, error } = await supabase
      .from("bug_reports")
      .select("id, title, description, status, created_at, created_by, yesod_note_id, commit_hash")
      .order("created_at", { ascending: false });

    if (error) {
      console.error("Error listing bug reports:", error);
      return jsonResponse({ error: "Failed to list bug reports" }, 500);
    }

    return jsonResponse({
      bug_reports: data || [],
      total: (data || []).length,
    });
  }

  return jsonResponse(
    { error: `Unknown action '${action}'. Valid actions: create, list` },
    400,
  );
});
