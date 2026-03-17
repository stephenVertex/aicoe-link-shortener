#!/usr/bin/env python3
"""User CLI for aicoe.fit link shortener.

Authenticate with a personal API key to get personalised tracking links
for articles, and search the article catalogue.
"""

import configparser
import os
import sys
from pathlib import Path

import click
import requests

CREDENTIALS_FILE = Path.home() / ".als.credentials"
API_BASE = "https://dumhbtxskncofwwzrmfx.supabase.co/functions/v1"


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------


def _read_credentials() -> dict[str, str]:
    """Read credentials from ~/.als.credentials (INI format)."""
    if not CREDENTIALS_FILE.exists():
        return {}
    config = configparser.ConfigParser()
    config.read(CREDENTIALS_FILE)
    if "default" not in config:
        return {}
    return dict(config["default"])


def _write_credentials(api_key: str) -> None:
    """Write credentials to ~/.als.credentials with mode 0600."""
    config = configparser.ConfigParser()
    config["default"] = {"api_key": api_key}
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CREDENTIALS_FILE, "w") as f:
        config.write(f)
    os.chmod(CREDENTIALS_FILE, 0o600)


def _get_api_key() -> str:
    """Get the API key from credentials file, or exit with an error."""
    creds = _read_credentials()
    api_key = creds.get("api_key", "")
    if not api_key:
        click.echo("Not logged in. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    return api_key


def _api_request(
    function: str,
    *,
    method: str = "POST",
    api_key: str | None = None,
    json_body: dict | None = None,
    params: dict | None = None,
) -> requests.Response:
    """Make a request to a Supabase edge function."""
    if api_key is None:
        api_key = _get_api_key()
    url = f"{API_BASE}/{function}"
    headers = {"x-api-key": api_key}
    if method == "POST":
        resp = requests.post(url, json=json_body or {}, headers=headers, timeout=30)
    else:
        resp = requests.get(url, params=params or {}, headers=headers, timeout=30)
    return resp


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def cli():
    """aicoe.fit link shortener - get your personalised tracking links."""
    pass


@cli.command()
@click.option("--api-key", required=True, help="Your personal API key (als_...)")
def login(api_key: str):
    """Save your API key for future use."""
    if not api_key.startswith("als_"):
        click.echo(
            "Warning: API key doesn't start with 'als_'. Are you sure?", err=True
        )

    # Validate the key by calling get-link with no URL (expect 400, not 401)
    resp = _api_request("get-link", api_key=api_key, json_body={})
    if resp.status_code == 401:
        click.echo("Invalid API key.", err=True)
        sys.exit(1)

    _write_credentials(api_key)
    click.echo(f"Logged in. Credentials saved to {CREDENTIALS_FILE}")


@cli.command()
def whoami():
    """Show the current authenticated user."""
    api_key = _get_api_key()

    # First, validate the key is still good (400 = valid key, no article provided)
    probe = _api_request("get-link", api_key=api_key, json_body={})
    if probe.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)

    # Search for any article to get one we can use to extract person info
    search_resp = requests.post(
        f"{API_BASE}/search-articles",
        json={"query": "article", "match_count": 1},
        timeout=30,
    )
    if search_resp.status_code == 200:
        results = search_resp.json().get("results", [])
        if results:
            slug = results[0].get("slug", "")
            link_resp = _api_request(
                "get-link", api_key=api_key, json_body={"article_url": slug}
            )
            if link_resp.status_code == 200:
                person = link_resp.json().get("person", {})
                click.echo(
                    f"Logged in as: {person.get('name', '?')} ({person.get('slug', '?')})"
                )
                click.echo(f"Credentials: {CREDENTIALS_FILE}")
                return

    # Fallback: key is valid but couldn't resolve identity
    click.echo(f"API key is valid. Credentials: {CREDENTIALS_FILE}")


@cli.command()
@click.argument("url")
@click.option(
    "--source", default=None, help="Filter to a specific source (e.g. linkedin)"
)
def shorten(url: str, source: str | None):
    """Get your personalised tracking link for an article.

    URL can be a full article URL or a slug (e.g. 'cursor-mar26').
    """
    body: dict = {"article_url": url}
    if source:
        body["source"] = source

    resp = _api_request("get-link", json_body=body)

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code == 404:
        data = resp.json()
        click.echo(f"Article not found: {data.get('error', url)}", err=True)
        click.echo("Try: als search <query> to find the article.", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    article = data.get("article", {})
    links = data.get("links", [])
    person = data.get("person", {})

    click.echo(f"\n{click.style(article.get('title', ''), bold=True)}")
    if article.get("author"):
        click.echo(f"  by {article['author']}")
    click.echo(f"  Original: {article.get('url', '')}")
    click.echo()

    if links:
        click.echo(f"  Your tracking links ({person.get('name', '')}):")
        for link in links:
            label = link.get("label") or link.get("source", "")
            click.echo(f"    {label:12s}  {link['short_url']}")
    else:
        click.echo("  No tracking links generated.")

    click.echo()


@cli.command()
@click.argument("query")
@click.option("--count", default=3, help="Number of results to return")
def search(query: str, count: int):
    """Search articles and get your personalised tracking links.

    Uses semantic search to find matching articles, then returns
    your personalised tracking link for each result.
    """
    api_key = _get_api_key()

    # Step 1: Search for articles
    search_resp = requests.post(
        f"{API_BASE}/search-articles",
        json={"query": query, "match_count": count},
        timeout=30,
    )
    if search_resp.status_code != 200:
        click.echo(
            f"Search error ({search_resp.status_code}): {search_resp.text}", err=True
        )
        sys.exit(1)

    search_data = search_resp.json()
    results = search_data.get("results", [])

    if not results:
        click.echo("No matching articles found.")
        return

    click.echo(f"\nSearch results for: {click.style(query, bold=True)}\n")

    # Step 2: For each result, get personalised tracking link
    for i, result in enumerate(results, 1):
        title = result.get("title", result.get("slug", ""))
        author = result.get("author", "")
        slug = result.get("slug", "")
        similarity = result.get("similarity", 0)

        click.echo(f"  {i}. {click.style(title, bold=True)}")
        if author:
            click.echo(f"     by {author}")
        click.echo(f"     Score: {similarity:.2f}")

        # Get tracking link for this article
        link_resp = _api_request(
            "get-link",
            api_key=api_key,
            json_body={"article_url": slug},
        )
        if link_resp.status_code == 200:
            link_data = link_resp.json()
            links = link_data.get("links", [])
            for link in links:
                label = link.get("label") or link.get("source", "")
                click.echo(f"     {label:12s}  {link['short_url']}")
        else:
            click.echo(f"     (could not generate tracking link)")

        click.echo()


if __name__ == "__main__":
    cli()
