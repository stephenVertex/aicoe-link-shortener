// admin-rpc: authenticated bridge for the admin dashboard's database RPCs.
//
// The admin pages used to call these functions directly via PostgREST with
// the anon key + the user's Supabase Auth session. That required granting
// EXECUTE on SECURITY DEFINER functions to anon/authenticated (security
// advisor lints 0028/0029). Instead, this function verifies the caller's
// Supabase Auth JWT, derives their identity server-side, and invokes
// service_role-only RPC variants that take the verified email explicitly.
import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

Deno.serve(async (req) => {
  const corsHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers":
      "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
  };

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }
  if (req.method !== "POST") {
    return json({ error: "Method not allowed" }, 405);
  }

  // Verify the caller's Supabase Auth session token. The anon key itself is
  // a valid JWT but has no user, so it fails getUser() and gets a 401 here.
  const authHeader = req.headers.get("Authorization") ?? "";
  const token = authHeader.replace(/^Bearer\s+/i, "").trim();
  if (!token) {
    return json({ error: "Missing Authorization header" }, 401);
  }
  const { data: userData, error: userError } = await supabase.auth.getUser(
    token,
  );
  const user = userData?.user;
  if (userError || !user?.email) {
    return json({ error: "Not authenticated" }, 401);
  }

  let action = "";
  let params: Record<string, unknown> = {};
  try {
    const body = await req.json();
    action = typeof body.action === "string" ? body.action : "";
    if (body.params && typeof body.params === "object") {
      params = body.params as Record<string, unknown>;
    }
  } catch {
    return json({ error: "Invalid JSON body" }, 400);
  }

  const displayName = (user.user_metadata?.full_name as string | undefined) ??
    (user.user_metadata?.name as string | undefined) ?? null;

  const str = (key: string): string | null => {
    const value = params[key];
    return typeof value === "string" && value !== "" ? value : null;
  };

  let rpcName: string;
  let rpcParams: Record<string, unknown>;

  switch (action) {
    case "get_or_create_person":
      rpcName = "get_or_create_person";
      rpcParams = { p_email: user.email, p_name: displayName };
      break;
    case "create_person_source":
      rpcName = "create_person_source";
      rpcParams = {
        p_email: user.email,
        p_label: str("p_label"),
        p_source: str("p_source"),
        p_medium: str("p_medium"),
        p_content: str("p_content"),
        p_term: str("p_term"),
        p_icon: str("p_icon"),
      };
      break;
    case "delete_person_source":
      rpcName = "delete_person_source";
      rpcParams = { p_email: user.email, p_source_id: str("p_source_id") };
      break;
    case "get_click_analytics":
      rpcName = "get_click_analytics";
      rpcParams = {
        p_interval: str("p_interval") ?? "day",
        p_link_id: str("p_link_id"),
        p_variant_id: str("p_variant_id"),
        p_start_date: str("p_start_date"),
        p_end_date: str("p_end_date"),
        p_ref: str("p_ref"),
      };
      break;
    default:
      return json({ error: `Unknown action: ${action}` }, 400);
  }

  const { data, error } = await supabase.rpc(rpcName, rpcParams);
  if (error) {
    console.error(`admin-rpc ${action} failed for ${user.email}:`, error);
    return json({ error: error.message }, 400);
  }
  return json({ data });
});
