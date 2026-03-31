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

async function generateShortId(url: string): Promise<string> {
  const data = new TextEncoder().encode(url);
  const hash = await crypto.subtle.digest("SHA-256", data);
  const hex = Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return "aifs-" + parseInt(hex.slice(0, 6), 16).toString(36).slice(0, 3);
}

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
  let ids: string[] = [];
  let note = "";
  let beforeDate = "";
  let filter = "active";

  if (req.method === "POST") {
    try {
      const body = await req.json();
      apiKey = apiKey || body.api_key || "";
      action = body.action || "submit";
      url = body.url || "";
      comment = body.comment || "";
      ids = body.ids || [];
      note = body.note || "";
      beforeDate = body.before_date || "";
      filter = body.filter || "active";
    } catch {
      return jsonResponse({ error: "Invalid JSON body" }, 400);
    }
  } else {
    const reqUrl = new URL(req.url);
    apiKey = apiKey || reqUrl.searchParams.get("api_key") || "";
    action = reqUrl.searchParams.get("action") || "list";
    filter = reqUrl.searchParams.get("filter") || "active";
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
    // Accept either a URL or a short_id (for voting on existing items)
    let existingSubmission: { id: string; url: string; short_id: string | null } | null = null;

    if (url && url.startsWith("aifs-")) {
      // Voting by short_id
      const { data } = await supabase
        .from("aifs_submissions")
        .select("id, url, short_id")
        .eq("short_id", url)
        .maybeSingle();
      existingSubmission = data;
      if (!existingSubmission) {
        return jsonResponse({ error: `No submission found for ${url}` }, 404);
      }
    } else if (url) {
      try {
        new URL(url);
      } catch {
        return jsonResponse({ error: `Invalid URL: ${url}` }, 400);
      }
      const normUrl = url.replace(/\/+$/, "");
      const { data } = await supabase
        .from("aifs_submissions")
        .select("id, url, short_id")
        .eq("url", normUrl)
        .maybeSingle();
      existingSubmission = data;

      // Create new submission if URL not found
      if (!existingSubmission) {
        const shortId = await generateShortId(normUrl);

        const { data: newSubmission, error: insertError } = await supabase
          .from("aifs_submissions")
          .insert({
            url: normUrl,
            submitted_by: person.slug,
            short_id: shortId,
          })
          .select("id, url, short_id")
          .single();

        if (insertError || !newSubmission) {
          console.error("Error creating submission:", insertError);
          return jsonResponse({ error: "Failed to create submission" }, 500);
        }

        // Add the submitter's vote
        await supabase.from("aifs_votes").insert({
          submission_id: newSubmission.id,
          person_ref: person.slug,
          comment: comment || null,
        });

        return jsonResponse({
          status: "submitted",
          submission_id: newSubmission.id,
          short_id: newSubmission.short_id,
          message: "URL submitted successfully",
        });
      }
    } else {
      return jsonResponse({ error: "url is required" }, 400);
    }

    // Check if already voted
    const { data: existingVote } = await supabase
      .from("aifs_votes")
      .select("id")
      .eq("submission_id", existingSubmission.id)
      .eq("person_ref", person.slug)
      .eq("type", "vote")
      .maybeSingle();

    if (existingVote) {
      // Already voted — if comment provided, add it as a comment-type entry
      if (comment) {
        await supabase.from("aifs_votes").insert({
          submission_id: existingSubmission.id,
          person_ref: person.slug,
          comment,
          type: "comment",
        });

        return jsonResponse({
          status: "comment_added",
          submission_id: existingSubmission.id,
          short_id: existingSubmission.short_id,
          message: "Comment added (you already voted)",
        });
      }

      return jsonResponse({
        status: "already_voted",
        submission_id: existingSubmission.id,
        short_id: existingSubmission.short_id,
        message: "You have already voted for this URL",
      });
    }

    await supabase.from("aifs_votes").insert({
      submission_id: existingSubmission.id,
      person_ref: person.slug,
      comment: comment || null,
      type: "vote",
    });

    return jsonResponse({
      status: "voted",
      submission_id: existingSubmission.id,
      short_id: existingSubmission.short_id,
      message: "Vote added successfully",
    });
  }

  if (action === "list") {
    let query = supabase
      .from("aifs_submissions")
      .select("id, url, title, submitted_by, submitted_at, short_id, archived_at, archive_note");

    if (filter === "active") {
      query = query.is("archived_at", null);
    } else if (filter === "archived") {
      query = query.not("archived_at", "is", null);
    }

    const { data: submissions, error: subError } = await query.order("submitted_at", { ascending: false });

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
      .select("submission_id, person_ref, comment, voted_at, type")
      .in("submission_id", submissionIds)
      .order("voted_at", { ascending: true });

    if (votesError) {
      console.error("Error fetching votes:", votesError);
      return jsonResponse({ error: "Failed to fetch votes" }, 500);
    }

    const entriesBySubmission: Record<string, Array<{ person_ref: string; comment: string | null; voted_at: string; type: string }>> = {};
    for (const v of votes || []) {
      const sid = v.submission_id;
      if (!entriesBySubmission[sid]) {
        entriesBySubmission[sid] = [];
      }
      entriesBySubmission[sid].push({
        person_ref: v.person_ref,
        comment: v.comment,
        voted_at: v.voted_at,
        type: v.type || "vote",
      });
    }

    const result = submissions.map((s: { id: string; url: string; title: string | null; submitted_by: string; submitted_at: string; short_id: string | null; archived_at: string | null; archive_note: string | null }) => {
      const entries = entriesBySubmission[s.id] || [];
      const voteCount = entries.filter((e) => e.type === "vote").length;
      const firstVote = entries.find((v) => v.person_ref === s.submitted_by && v.type === "vote");
      const otherEntries = entries.filter((v) => !(v.person_ref === s.submitted_by && v.type === "vote"));

      return {
        id: s.id,
        short_id: s.short_id,
        url: s.url,
        title: s.title,
        submitted_by: s.submitted_by,
        submitted_at: s.submitted_at,
        archived_at: s.archived_at,
        archive_note: s.archive_note,
        vote_count: voteCount,
        voters: [
          { person_ref: s.submitted_by, comment: firstVote?.comment || null, type: "vote" },
          ...otherEntries.map((v) => ({
            person_ref: v.person_ref,
            comment: v.comment,
            type: v.type,
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

  if (action === "archive") {
    if (!note) {
      return jsonResponse({ error: "note is required for archive action" }, 400);
    }

    let updateQuery = supabase
      .from("aifs_submissions")
      .update({ archived_at: new Date().toISOString(), archive_note: note });

    if (beforeDate) {
      updateQuery = updateQuery.lt("submitted_at", beforeDate).is("archived_at", null);
    } else if (ids.length > 0) {
      const uuids: string[] = [];
      const shortIds: string[] = [];
      for (const id of ids) {
        if (id.match(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i)) {
          uuids.push(id);
        } else {
          shortIds.push(id);
        }
      }
      if (uuids.length > 0 && shortIds.length > 0) {
        updateQuery = updateQuery.or(`id.in.(${uuids.join(",")}),short_id.in.(${shortIds.join(",")})`);
      } else if (uuids.length > 0) {
        updateQuery = updateQuery.in("id", uuids);
      } else if (shortIds.length > 0) {
        updateQuery = updateQuery.in("short_id", shortIds);
      }
    } else {
      return jsonResponse({ error: "ids or before_date is required for archive action" }, 400);
    }

    const { data, error: updateError } = await updateQuery.select("id, short_id");

    if (updateError) {
      console.error("Error archiving submissions:", updateError);
      return jsonResponse({ error: "Failed to archive submissions" }, 500);
    }

    return jsonResponse({
      status: "archived",
      count: data?.length || 0,
      submissions: data,
    });
  }

  if (action === "unarchive") {
    if (ids.length === 0) {
      return jsonResponse({ error: "ids is required for unarchive action" }, 400);
    }

    const uuids: string[] = [];
    const shortIds: string[] = [];
    for (const id of ids) {
      if (id.match(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i)) {
        uuids.push(id);
      } else {
        shortIds.push(id);
      }
    }

    let updateQuery = supabase
      .from("aifs_submissions")
      .update({ archived_at: null, archive_note: null });

    if (uuids.length > 0 && shortIds.length > 0) {
      updateQuery = updateQuery.or(`id.in.(${uuids.join(",")}),short_id.in.(${shortIds.join(",")})`);
    } else if (uuids.length > 0) {
      updateQuery = updateQuery.in("id", uuids);
    } else {
      updateQuery = updateQuery.in("short_id", shortIds);
    }

    const { data, error: updateError } = await updateQuery.select("id, short_id");

    if (updateError) {
      console.error("Error unarchiving submissions:", updateError);
      return jsonResponse({ error: "Failed to unarchive submissions" }, 500);
    }

    return jsonResponse({
      status: "unarchived",
      count: data?.length || 0,
      submissions: data,
    });
  }

  return jsonResponse(
    { error: `Unknown action '${action}'. Valid actions: submit, list, archive, unarchive` },
    400,
  );
});
