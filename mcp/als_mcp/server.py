"""FastMCP server exposing aicoe.fit link shortener tools.

Authenticates via ALS_API_KEY env var and proxies requests to the same
Supabase edge-function backend used by the ``als`` CLI.

Usage:
    ALS_API_KEY=als_... uv run als-mcp          # stdio transport (default)
    ALS_API_KEY=als_... uv run als-mcp --sse     # SSE transport
"""

from __future__ import annotations

import os
import sys

import httpx
from fastmcp import FastMCP

API_BASE = "https://dumhbtxskncofwwzrmfx.supabase.co/functions/v1"

mcp = FastMCP(
    "als-mcp",
    instructions="aicoe.fit link shortener – search articles, get tracking links, shorten URLs",
)

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


def _get_api_key() -> str:
    key = os.environ.get("ALS_API_KEY", "")
    if not key:
        raise RuntimeError(
            "ALS_API_KEY environment variable is not set. "
            "Set it to your als API key (als_...)."
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
    # Step 1: semantic search (no auth required)
    search_data = await _post(
        "search-articles",
        json_body={"query": query, "match_count": count},
    )
    results = search_data.get("results", [])

    # Step 2: enrich each result with personalised tracking links
    api_key = _get_api_key()
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
    # Probe key validity: get-link with empty body → 400 means valid, 401 means invalid
    client = await _http()
    api_key = _get_api_key()
    headers = {"x-api-key": api_key}

    probe = await client.post(f"{API_BASE}/get-link", json={}, headers=headers)
    if probe.status_code == 401:
        return {"error": "Invalid API key", "authenticated": False}

    # Grab any article slug to extract person info from get-link
    search_data = await _post(
        "search-articles", json_body={"query": "article", "match_count": 1}
    )
    results = search_data.get("results", [])
    if not results:
        return {
            "authenticated": True,
            "person": None,
            "note": "Key valid but no articles to resolve identity",
        }

    slug = results[0].get("slug", "")
    link_resp = await client.post(
        f"{API_BASE}/get-link",
        json={"article_url": slug},
        headers=headers,
    )
    if link_resp.status_code == 200:
        person = link_resp.json().get("person", {})
        return {"authenticated": True, "person": person}

    return {
        "authenticated": True,
        "person": None,
        "note": "Key valid but could not resolve identity",
    }


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
    """Run the MCP server."""
    transport = "stdio"
    if "--sse" in sys.argv:
        transport = "sse"
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
