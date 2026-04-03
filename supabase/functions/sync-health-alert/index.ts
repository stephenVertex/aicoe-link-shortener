import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? ""
);

const ALERT_THRESHOLD_HOURS = 8;
const ALERT_WEBHOOK_URL = Deno.env.get("ALERT_WEBHOOK_URL");

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }

  const threshold = new Date(Date.now() - ALERT_THRESHOLD_HOURS * 60 * 60 * 1000);

  const { data: staleLinks, error } = await supabase
    .from("links")
    .select("slug, last_synced_at")
    .lt("last_synced_at", threshold.toISOString())
    .not("last_synced_at", "is", null);

  if (error) {
    console.error("Error checking sync status:", error);
    return new Response(JSON.stringify({ error: "Database query failed" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!staleLinks || staleLinks.length === 0) {
    return new Response(JSON.stringify({ 
      status: "healthy", 
      message: "All links synced within threshold" 
    }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  const alertMessage = `⚠️ Sync Health Alert: ${staleLinks.length} link(s) not synced in >${ALERT_THRESHOLD_HOURS}h\n\n` +
    staleLinks.map(link => 
      `- ${link.slug}: last synced ${link.last_synced_at}`
    ).join("\n");

  if (ALERT_WEBHOOK_URL) {
    try {
      const response = await fetch(ALERT_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: alertMessage,
        }),
      });

      if (!response.ok) {
        console.error("Failed to send alert:", await response.text());
      }
    } catch (err) {
      console.error("Error sending alert:", err);
    }
  } else {
    console.log("No ALERT_WEBHOOK_URL configured, logging alert:");
    console.log(alertMessage);
  }

  return new Response(JSON.stringify({ 
    status: "alert_sent",
    stale_count: staleLinks.length,
    stale_links: staleLinks,
  }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});