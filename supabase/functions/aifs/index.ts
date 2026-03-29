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
  let action = "submit";
  let url = "";
  let comment = "";

  if (req.method === "POST") {
    try {
      const body = await req.json();
      apiKey = apiKey || body.api_key || "";
      action = body.action || "submit";
      url = body.url || "";
      comment = body.comment || "";
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

  if (action === "submit") {
    if (!url) {
      return jsonResponse({ error: "url is required" }, 400);
    }

    try {
      new URL(url);
    } catch {
      return jsonResponse({ error: `Invalid URL: ${url}` }, 400);
    }

    const normUrl = url.replace(/\/+$/, "");

    const { data: existingSubmission } = await supabase
      .from("aifs_submissions")
      .select("id, url")
      .eq("url", normUrl)
      .maybeSingle();

    let submissionId: string;
    let status: string;

    if (existingSubmission) {
      submissionId = existingSubmission.id;

      const { data: existingVote } = await supabase
        .from("aifs_votes")
        .select("id")
        .eq("submission_id", submissionId)
        .eq("person_ref", person.slug)
        .maybeSingle();

      if (existingVote) {
        return jsonResponse({
          status: "already_voted",
          submission_id: submissionId,
          message: "You have already voted for this URL",
        });
      }

      const { error: voteError } = await supabase
        .from("aifs_votes")
        .insert({
          submission_id: submissionId,
          person_ref: person.slug,
          comment: comment || null,
        });

      if (voteError) {
        console.error("Error adding vote:", voteError);
        return jsonResponse({ error: "Failed to add vote" }, 500);
      }

      status = "voted";
    } else {
      const { data: newSubmission, error: insertError } = await supabase
        .from("aifs_submissions")
        .insert({
          url: normUrl,
          submitted_by: person.slug,
        })
        .select("id")
        .single();

      if (insertError || !newSubmission) {
        console.error("Error creating submission:", insertError);
        return jsonResponse({ error: "Failed to create submission" }, 500);
      }

      submissionId = newSubmission.id;

      const { error: voteError } = await supabase
        .from("aifs_votes")
        .insert({
          submission_id: submissionId,
          person_ref: person.slug,
          comment: comment || null,
        });

      if (voteError) {
        console.error("Error adding vote:", voteError);
        return jsonResponse({ error: "Failed to add vote" }, 500);
      }

      status = "submitted";
    }

    return jsonResponse({
      status,
      submission_id: submissionId,
      message: status === "submitted"
        ? "URL submitted successfully"
        : "Vote added successfully",
    });
  }

  if (action === "list") {
    const { data: submissions, error: subError } = await supabase
      .from("aifs_submissions")
      .select("id, url, title, submitted_by, submitted_at")
      .order("submitted_at", { ascending: false });

    if (subError) {
      console.error("Error fetching submissions:", subError);
      return jsonResponse({ error: "Failed to fetch submissions" }, 500);
    }

    if (!submissions || submissions.length === 0) {
      return jsonResponse({
        submissions: [],
        total: 0,
      });
    }

    const submissionIds = submissions.map((s: { id: string }) => s.id);

    const { data: votes, error: votesError } = await supabase
      .from("aifs_votes")
      .select("submission_id, person_ref, comment, voted_at")
      .in("submission_id", submissionIds)
      .order("voted_at", { ascending: true });

    if (votesError) {
      console.error("Error fetching votes:", votesError);
      return jsonResponse({ error: "Failed to fetch votes" }, 500);
    }

    const votesBySubmission: Record<string, Array<{ person_ref: string; comment: string | null; voted_at: string }>> = {};
    for (const v of votes || []) {
      const sid = v.submission_id;
      if (!votesBySubmission[sid]) {
        votesBySubmission[sid] = [];
      }
      votesBySubmission[sid].push({
        person_ref: v.person_ref,
        comment: v.comment,
        voted_at: v.voted_at,
      });
    }

    const result = submissions.map((s: { id: string; url: string; title: string | null; submitted_by: string; submitted_at: string }) => {
      const svotes = votesBySubmission[s.id] || [];
      const firstVote = svotes.find((v: { person_ref: string }) => v.person_ref === s.submitted_by);
      const otherVotes = svotes.filter((v: { person_ref: string }) => v.person_ref !== s.submitted_by);

      return {
        id: s.id,
        url: s.url,
        title: s.title,
        submitted_by: s.submitted_by,
        submitted_at: s.submitted_at,
        vote_count: svotes.length,
        voters: [
          { person_ref: s.submitted_by, comment: firstVote?.comment || null },
          ...otherVotes.map((v: { person_ref: string; comment: string | null }) => ({
            person_ref: v.person_ref,
            comment: v.comment,
          })),
        ],
      };
    });

    result.sort((a: { vote_count: number }, b: { vote_count: number }) => b.vote_count - a.vote_count);

    return jsonResponse({
      submissions: result,
      total: result.length,
    });
  }

  return jsonResponse(
    { error: `Unknown action '${action}'. Valid actions: submit, list` },
    400,
  );
});
