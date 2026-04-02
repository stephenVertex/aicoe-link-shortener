"""FastMCP server exposing aicoe.fit link shortener tools.

Authenticates via ALS_API_KEY env var (single-user / ECS default) or via a
per-connection ?api_key=als_... query parameter (multi-user shared server).

Usage:
    ALS_API_KEY=als_... uv run als-mcp          # stdio transport
    ALS_API_KEY=als_... uv run als-mcp --sse     # SSE, single-user
    uv run als-mcp --sse                          # SSE, multi-user (key in URL)

Multi-user connect:
    http://host:8000/sse?api_key=als_yourkey
"""

from __future__ import annotations

import os
import sys
from contextvars import ContextVar

import httpx
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

API_BASE = "https://dumhbtxskncofwwzrmfx.supabase.co/functions/v1"

mcp = FastMCP(
    "als-mcp",
    instructions="aicoe.fit link shortener – search articles, get tracking links, shorten URLs",
)


# ---------------------------------------------------------------------------
# Per-connection API key resolution
# ---------------------------------------------------------------------------

# Maps SSE session_id → api_key for multi-user support
_session_keys: dict[str, str] = {}

# ContextVar set for the duration of each /messages/ POST request
_current_api_key: ContextVar[str] = ContextVar("current_api_key", default="")


class _APIKeyMiddleware:
    """ASGI middleware that wires per-connection API keys to tool calls.

    SSE flow:
      1. Client GETs /sse?api_key=als_xxx
      2. Server responds with: event: endpoint\\ndata: /messages/?session_id=YYY
      3. We intercept that first SSE chunk → store session_id → api_key
      4. Subsequent POSTs to /messages/?session_id=YYY → look up key → set ContextVar

    Falls back to ALS_API_KEY env var if no query param is present.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        params = _parse_qs(scope.get("query_string", b""))

        if path == "/sse":
            api_key = params.get("api_key") or os.environ.get("ALS_API_KEY", "")
            captured = False

            async def capturing_send(message):
                nonlocal captured
                if not captured and message.get("type") == "http.response.body":
                    chunk = message.get("body", b"").decode(errors="replace")
                    for line in chunk.splitlines():
                        if line.startswith("data: /messages/") and "session_id=" in line:
                            sid = line.split("session_id=")[-1].strip()
                            if sid:
                                _session_keys[sid] = api_key
                                captured = True
                                break
                await send(message)

            await self.app(scope, receive, capturing_send)

        elif path.startswith("/messages/"):
            session_id = params.get("session_id", "")
            api_key = _session_keys.get(session_id) or os.environ.get("ALS_API_KEY", "")
            token = _current_api_key.set(api_key)
            try:
                await self.app(scope, receive, send)
            finally:
                _current_api_key.reset(token)

        else:
            await self.app(scope, receive, send)


def _parse_qs(query_string: bytes) -> dict[str, str]:
    """Parse a URL query string into a dict (last value wins)."""
    result: dict[str, str] = {}
    for part in query_string.decode(errors="replace").split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Health check (for ALB / ECS health probes)
# ---------------------------------------------------------------------------


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health endpoint for ALB target group and ECS container health checks."""
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


def _get_api_key() -> str:
    """Return the API key for the current request.

    Checks (in order):
      1. ContextVar set by _APIKeyMiddleware for this SSE session
      2. ALS_API_KEY environment variable (single-user / ECS default)
    """
    key = _current_api_key.get() or os.environ.get("ALS_API_KEY", "")
    if not key:
        raise RuntimeError(
            "No API key for this session. "
            "Connect via /sse?api_key=als_... or set ALS_API_KEY env var."
        )
    return key


async def _http() -> httpx.AsyncClient:
    """Lazy-initialised async HTTP client."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def _post(
    function: str,
    *,
    json_body: dict | None = None,
    auth: bool = False,
) -> dict:
    """POST to a Supabase edge function and return the parsed JSON."""
    client = await _http()
    headers: dict[str, str] = {}
    if auth:
        headers["x-api-key"] = _get_api_key()
    resp = await client.post(
        f"{API_BASE}/{function}",
        json=json_body or {},
        headers=headers,
    )
    resp.raise_for_status()
    return resp.json()


async def _get(function: str, *, auth: bool = False) -> dict:
    """GET a Supabase edge function and return the parsed JSON."""
    client = await _http()
    headers: dict[str, str] = {}
    if auth:
        headers["x-api-key"] = _get_api_key()
    resp = await client.get(f"{API_BASE}/{function}", headers=headers)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def search(query: str, count: int = 3) -> dict:
    """Search articles by semantic similarity and return personalised tracking links.

    Args:
        query: Free-text search query (e.g. "GLM-5", "generative AI").
        count: Number of results to return (default 3, max ~20).

    Returns a dict with ``results`` – each containing title, author,
    similarity score, and personalised tracking links per channel.
    """
    search_data = await _post(
        "search-articles",
        json_body={"query": query, "match_count": count},
    )
    results = search_data.get("results", [])

    enriched = []
    for r in results:
        slug = r.get("slug", "")
        entry: dict = {
            "title": r.get("title", slug),
            "author": r.get("author", ""),
            "similarity": r.get("similarity", 0),
            "published_at": r.get("published_at") or r.get("created_at", ""),
        }
        if slug:
            try:
                link_data = await _post(
                    "get-link",
                    json_body={"article_url": slug},
                    auth=True,
                )
                entry["links"] = link_data.get("links", [])
            except httpx.HTTPStatusError:
                entry["links"] = []
        enriched.append(entry)

    return {"query": query, "count": len(enriched), "results": enriched}


@mcp.tool()
async def last(n: int = 10, author: str | None = None) -> dict:
    """List the most recently published articles with personalised tracking links.

    Args:
        n: Number of articles to return (default 10, max 100).
        author: Optional author name filter (case-insensitive substring match).

    Returns a dict with ``results`` – each containing title, author, date,
    and personalised tracking links.
    """
    body: dict = {"count": n}
    if author:
        body["author"] = author

    last_data = await _post("last-articles", json_body=body)
    results = last_data.get("results", [])

    enriched = []
    for r in results:
        slug = r.get("slug", "")
        entry: dict = {
            "title": r.get("title", slug),
            "author": r.get("author", ""),
            "published_at": r.get("published_at") or r.get("created_at", ""),
        }
        if slug:
            try:
                link_data = await _post(
                    "get-link",
                    json_body={"article_url": slug},
                    auth=True,
                )
                entry["links"] = link_data.get("links", [])
            except httpx.HTTPStatusError:
                entry["links"] = []
        enriched.append(entry)

    return {"count": len(enriched), "results": enriched}


@mcp.tool()
async def authors() -> dict:
    """List all authors and their article counts.

    Returns a dict with ``authors`` – each containing name and article_count.
    """
    return await _get("list-authors")


@mcp.tool()
async def stats() -> dict:
    """Show database statistics (articles, authors, people, tracking variants, clicks).

    Returns a dict with counts for each category.
    """
    return await _get("db-stats")


@mcp.tool()
async def whoami() -> dict:
    """Show the authenticated user's identity.

    Validates the API key and returns the person's name and slug.
    """
    client = await _http()
    api_key = _get_api_key()
    headers = {"x-api-key": api_key}

    resp = await client.post(f"{API_BASE}/validate-key", json={}, headers=headers)
    if resp.status_code == 401:
        return {"error": "Invalid API key", "authenticated": False}

    person = resp.json()
    return {"authenticated": True, "person": person}


@mcp.tool()
async def shorten(url: str, source: str | None = None) -> dict:
    """Create personalised tracking short links for any URL.

    Args:
        url: The URL to shorten (article, blog, any website).
        source: Optional channel filter (e.g. "linkedin").

    Returns a dict with the short slug, tracking links per channel,
    and person info.
    """
    body: dict = {"url": url}
    if source:
        body["source"] = source
    return await _post("shorten-url", json_body=body, auth=True)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main():
    """Run the MCP server.

    SSE mode wraps FastMCP's ASGI app with _APIKeyMiddleware so each
    connecting user can supply their own API key via ?api_key=als_...
    """
    transport = "stdio"
    if "--sse" in sys.argv:
        transport = "sse"

    if transport == "sse":
        import uvicorn

        host = os.environ.get("ALS_MCP_HOST", "0.0.0.0")
        port = int(os.environ.get("ALS_MCP_PORT", "8000"))
        asgi_app = mcp.http_app(transport="sse")
        wrapped = _APIKeyMiddleware(asgi_app)
        uvicorn.run(wrapped, host=host, port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
