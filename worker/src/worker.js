export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Skip favicon and robots
    if (path === "/favicon.ico" || path === "/robots.txt") {
      return new Response("", { status: 404 });
    }

    // Root page — redirect to admin dashboard on Amplify
    if (path === "/" || path === "/admin" || path === "/admin/") {
      return new Response(null, {
        status: 302,
        headers: { Location: env.ADMIN_URL || "https://admin.aicoe.fit" },
      });
    }

    // Everything else — redirect logic via the Supabase edge function
    const slug = path.slice(1);
    const targetUrl = `${env.SUPABASE_BASE_URL}/functions/v1/redirect/${slug}`;

    const response = await fetch(targetUrl, {
      method: request.method,
      headers: {
        "user-agent": request.headers.get("user-agent") || "",
        "referer": request.headers.get("referer") || "",
        "x-forwarded-for": request.headers.get("cf-connecting-ip") || "",
        "x-real-ip": request.headers.get("cf-connecting-ip") || "",
      },
      redirect: "manual",
    });

    return new Response(response.body, {
      status: response.status,
      headers: response.headers,
    });
  },
};
