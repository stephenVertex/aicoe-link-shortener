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

Deno.serve(async (req) => {
  const corsHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers":
      "authorization, x-client-info, apikey, content-type, x-api-key",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
  };

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  if (req.method !== "POST") {
    return new Response(
      JSON.stringify({ error: "Method not allowed" }),
      {
        status: 405,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  // Parse request body
  let apiKey = req.headers.get("x-api-key") || "";
  let url = "";
  let transcript = "";

  try {
    const body = await req.json();
    apiKey = apiKey || body.api_key || "";
    url = body.url || "";
    transcript = body.transcript || "";
  } catch {
    return new Response(
      JSON.stringify({ error: "Invalid JSON body" }),
      {
        status: 400,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  // Validate API key
  if (!apiKey) {
    return new Response(
      JSON.stringify({
        error:
          "API key required. Pass via x-api-key header or api_key parameter.",
      }),
      {
        status: 401,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  const person = await validateApiKey(apiKey);
  if (!person) {
    return new Response(
      JSON.stringify({ error: "Invalid API key" }),
      {
        status: 401,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  // Validate required fields
  if (!url) {
    return new Response(
      JSON.stringify({ error: "url parameter is required" }),
      {
        status: 400,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  if (!transcript) {
    return new Response(
      JSON.stringify({ error: "transcript parameter is required" }),
      {
        status: 400,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  }

  try {
    // Look up the link by destination_url
    const { data: link, error: lookupError } = await supabase
      .from("links")
      .select("id, slug, destination_url, title, transcript")
      .eq("destination_url", url)
      .maybeSingle();

    if (lookupError) {
      console.error("Error looking up link:", lookupError);
      return new Response(
        JSON.stringify({ error: "Database error looking up link" }),
        {
          status: 500,
          headers: { "Content-Type": "application/json", ...corsHeaders },
        },
      );
    }

    // Try URL variant (with/without trailing slash) if no exact match
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
      return new Response(
        JSON.stringify({ error: `No link found for URL: ${url}` }),
        {
          status: 404,
          headers: { "Content-Type": "application/json", ...corsHeaders },
        },
      );
    }

    const hadTranscript = !!foundLink.transcript;

    // Update the transcript
    const { error: updateError } = await supabase
      .from("links")
      .update({ transcript })
      .eq("id", foundLink.id);

    if (updateError) {
      console.error("Error updating transcript:", updateError);
      return new Response(
        JSON.stringify({ error: "Database error updating transcript" }),
        {
          status: 500,
          headers: { "Content-Type": "application/json", ...corsHeaders },
        },
      );
    }

    return new Response(
      JSON.stringify({
        message: hadTranscript
          ? `Transcript updated for "${foundLink.title}"`
          : `Transcript added for "${foundLink.title}"`,
        slug: foundLink.slug,
        title: foundLink.title,
        replaced_existing: hadTranscript,
        transcript_length: transcript.length,
      }),
      {
        headers: { "Content-Type": "application/json", ...corsHeaders },
      },
    );
  } catch (error) {
    console.error("update-transcript error:", error);
    return new Response(JSON.stringify({ error: String(error) }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
});
