export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Skip favicon and other non-link requests
    if (path === "/" || path === "/favicon.ico" || path === "/robots.txt") {
      return new Response("aicoe.fit link shortener", { status: 200 });
    }

    // Strip leading slash to get the slug
    const slug = path.slice(1);

    // Proxy to Supabase Edge Function
    const targetUrl = `${env.SUPABASE_FUNCTION_URL}/${slug}`;

    const response = await fetch(targetUrl, {
      method: request.method,
      headers: {
        "user-agent": request.headers.get("user-agent") || "",
        "referer": request.headers.get("referer") || "",
        "x-forwarded-for": request.headers.get("cf-connecting-ip") || "",
        "x-real-ip": request.headers.get("cf-connecting-ip") || "",
      },
      redirect: "manual", // Don't follow redirects — pass them through
    });

    // Pass through the redirect response (or 404) directly
    return new Response(response.body, {
      status: response.status,
      headers: response.headers,
    });
  },
};
