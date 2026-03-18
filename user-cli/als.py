#!/usr/bin/env python3
"""User CLI for aicoe.fit link shortener.

Authenticate with a personal API key to get personalised tracking links
for articles, and search the article catalogue.
"""

import configparser
import os
import shutil
import subprocess
import sys
from importlib.metadata import version as _pkg_version
from pathlib import Path

import click
import requests

__version__ = _pkg_version("als")

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
@click.version_option(version=__version__, prog_name="als")
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


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

# Canonical install source — wheel hosted on GitHub Releases.
# This URL is stable: always points to the latest release asset.
_WHEEL_URL = (
    "https://github.com/stephenVertex/aicoe-link-shortener/"
    "releases/latest/download/als-0-py3-none-any.whl"
)


@cli.command()
@click.option("--force", is_flag=True, help="Force reinstall even if up to date.")
def upgrade(force: bool):
    """Upgrade als to the latest version from GitHub Releases.

    Downloads the latest wheel from the GitHub Releases page and
    reinstalls the CLI tool via uv.
    """
    # Ensure uv is available
    uv_path = shutil.which("uv")
    if uv_path is None:
        click.echo(
            "Error: 'uv' is not installed. Install it first: "
            "https://docs.astral.sh/uv/getting-started/installation/",
            err=True,
        )
        sys.exit(1)

    old_version = __version__
    click.echo(f"Current version: {old_version}")
    click.echo("Upgrading als...")

    env = {**os.environ, "UV_SKIP_WHEEL_FILENAME_CHECK": "1"}
    cmd = [
        uv_path,
        "tool",
        "install",
        _WHEEL_URL,
        "--force",
        "--reinstall",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except subprocess.TimeoutExpired:
        click.echo("Error: upgrade timed out after 120 seconds.", err=True)
        sys.exit(1)

    if result.returncode != 0:
        click.echo("Upgrade failed:", err=True)
        if result.stderr:
            click.echo(result.stderr.strip(), err=True)
        if result.stdout:
            click.echo(result.stdout.strip(), err=True)
        sys.exit(1)

    # Show uv output (contains version info)
    if result.stdout.strip():
        click.echo(result.stdout.strip())
    if result.stderr.strip():
        # uv prints progress to stderr
        click.echo(result.stderr.strip())

    click.echo(f"\nUpgrade complete. (was: {old_version})")
    click.echo("Run 'als --version' to check the new version.")


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
    """Get your personalised tracking link(s) for any URL.

    Accepts any URL — article, blog post, website, etc. — and returns
    your personalised aicoe.fit short tracking links. Calling with the
    same URL always returns the same set of links (idempotent).
    """
    body: dict = {"url": url}
    if source:
        body["source"] = source

    resp = _api_request("shorten-url", json_body=body)

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code == 400:
        data = resp.json()
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    links = data.get("links", [])
    person = data.get("person", {})
    slug = data.get("slug", "")
    destination = data.get("url", url)

    click.echo(f"\n{click.style(destination, bold=True)}")
    click.echo(f"  Slug: {slug}")
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
        published_at = result.get("published_at") or result.get("created_at", "")
        date_str = published_at[:10] if published_at else ""

        click.echo(f"  {i}. {click.style(title, bold=True)}")
        if author:
            click.echo(f"     by {author}")
        if date_str:
            click.echo(f"     {date_str}")
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


@cli.command()
@click.argument("n", default=10, type=int)
@click.option(
    "--author",
    default=None,
    help="Filter articles by author name (case-insensitive substring match).",
)
def last(n: int, author: str | None):
    """Show the last N articles with your personalised tracking links.

    N defaults to 10. Shows the most recently published articles in the
    database, with your personalised tracking link for each one.

    Use --author to filter to a specific author, e.g.:

        als last 5 --author "Simon"
    """
    api_key = _get_api_key()

    # Step 1: Fetch last N articles (optionally filtered by author)
    body: dict = {"count": n}
    if author:
        body["author"] = author

    last_resp = requests.post(
        f"{API_BASE}/last-articles",
        json=body,
        timeout=30,
    )
    if last_resp.status_code != 200:
        click.echo(
            f"Error fetching articles ({last_resp.status_code}): {last_resp.text}",
            err=True,
        )
        sys.exit(1)

    last_data = last_resp.json()
    results = last_data.get("results", [])

    if not results:
        if author:
            click.echo(f"No articles found for author: {author}")
        else:
            click.echo("No articles found.")
        return

    if author:
        click.echo(
            f"\nLast {len(results)} article(s) by {click.style(author, bold=True)}:\n"
        )
    else:
        click.echo(f"\nLast {len(results)} article(s):\n")

    # Step 2: For each article, get personalised tracking link
    for i, result in enumerate(results, 1):
        title = result.get("title") or result.get("slug", "")
        article_author = result.get("author", "")
        slug = result.get("slug", "")
        published_at = result.get("published_at") or result.get("created_at", "")
        # Trim to date portion if present
        date_str = published_at[:10] if published_at else ""

        click.echo(f"  {i}. {click.style(title, bold=True)}")
        if article_author:
            click.echo(f"     by {article_author}")
        if date_str:
            click.echo(f"     {date_str}")

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


@cli.command()
def authors():
    """List all authors in the database.

    Shows each distinct author and how many articles they have.
    """
    resp = requests.get(f"{API_BASE}/list-authors", timeout=30)
    if resp.status_code != 200:
        click.echo(
            f"Error fetching authors ({resp.status_code}): {resp.text}", err=True
        )
        sys.exit(1)

    data = resp.json()
    author_list = data.get("authors", [])

    if not author_list:
        click.echo("No authors found.")
        return

    click.echo(f"\nAuthors ({len(author_list)} total):\n")
    for entry in author_list:
        name = entry.get("name", "")
        count = entry.get("article_count", 0)
        click.echo(f"  {name}  ({count} article{'s' if count != 1 else ''})")
    click.echo()


@cli.command()
def stats():
    """Show statistics about the link shortener database.

    Displays counts of articles, authors, people, tracking variants,
    and total clicks recorded.
    """
    resp = requests.get(f"{API_BASE}/db-stats", timeout=30)
    if resp.status_code != 200:
        click.echo(f"Error fetching stats ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()

    click.echo("\nDatabase statistics:\n")
    click.echo(f"  Articles:          {data.get('articles', 0)}")
    click.echo(f"  Authors:           {data.get('authors', 0)}")
    click.echo(f"  People:            {data.get('people', 0)}")
    click.echo(f"  Tracking variants: {data.get('tracking_variants', 0)}")
    click.echo(f"  Total clicks:      {data.get('clicks', 0)}")
    click.echo()


if __name__ == "__main__":
    cli()
