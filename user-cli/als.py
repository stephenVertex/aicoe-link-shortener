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


def _update_credentials(**fields: str) -> None:
    """Update specific fields in ~/.als.credentials, preserving existing values."""
    creds = _read_credentials()
    creds.update(fields)
    config = configparser.ConfigParser()
    config["default"] = creds
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


def _resolve_my_author_name(api_key: str) -> str | None:
    """Resolve the logged-in user's author name.

    Checks ~/.als.credentials for a cached author_name first.  If not
    cached, falls back to probing the get-link endpoint via the API.

    Returns the person's name (as stored in the people table, e.g. "Simon Thornton")
    or None if it cannot be determined.
    """
    # Check credentials cache first — avoids API call overhead
    creds = _read_credentials()
    cached = creds.get("author_name", "").strip()
    if cached:
        return cached

    # Fall back to auto-resolve via API
    search_resp = requests.post(
        f"{API_BASE}/search-articles",
        json={"query": "article", "match_count": 1},
        timeout=30,
    )
    if search_resp.status_code != 200:
        return None
    results = search_resp.json().get("results", [])
    if not results:
        return None
    slug = results[0].get("slug", "")
    if not slug:
        return None
    # Call get-link with the slug to retrieve person info
    link_resp = requests.post(
        f"{API_BASE}/get-link",
        json={"article_url": slug},
        headers={"x-api-key": api_key},
        timeout=30,
    )
    if link_resp.status_code != 200:
        return None
    return link_resp.json().get("person", {}).get("name") or None


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
    """aicoe.fit link shortener - get your personalised tracking links.

    \b
    Usage:
      First time:  als login --api-key <key>
                   als authors              # find your name
                   als set-author-name "Your Name"
      Search:      als search "GLM-5"
      My articles: als last --me 5
      Shorten URL: als shorten <url>
      Upgrade:     als upgrade
    """
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
_RELEASES_API = (
    "https://api.github.com/repos/stephenVertex/aicoe-link-shortener/releases"
)


def _fetch_latest_release() -> dict | None:
    """Fetch the latest release info from GitHub API.

    Returns dict with 'tag_name' (e.g. 'v0.5.1') and 'body' (release notes),
    or None if the request fails.
    """
    try:
        resp = requests.get(
            f"{_RELEASES_API}/latest",
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return None


def _parse_version_from_tag(tag: str) -> str:
    """Strip leading 'v' from a git tag to get the version number."""
    return tag.lstrip("v")


@cli.command()
@click.option("--force", is_flag=True, help="Force reinstall even if up to date.")
def upgrade(force: bool):
    """Upgrade als to the latest version from GitHub Releases.

    Downloads the latest wheel from the GitHub Releases page and
    reinstalls the CLI tool via uv.
    """
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

    release_info = _fetch_latest_release()
    latest_tag = release_info.get("tag_name", "") if release_info else ""
    latest_version = _parse_version_from_tag(latest_tag) if latest_tag else ""

    if latest_version and latest_version == old_version and not force:
        click.echo(f"Already up to date (v{old_version}).")
        click.echo("Use --force to reinstall.")
        return

    click.echo("Upgrading als...")
    if latest_version:
        click.echo(f"Latest release: {latest_tag}")

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

    if result.stderr.strip():
        click.echo(result.stderr.strip())

    new_version = latest_version or "(unknown)"
    click.echo(f"\nUpgraded als: {old_version} → {new_version}")

    if release_info and release_info.get("body"):
        click.echo(f"\nWhat's new in {latest_tag}:")
        changelog = release_info["body"].strip()
        for line in changelog.split("\n"):
            if line.strip():
                click.echo(f"  {line}")


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


@cli.command("set-author-name")
@click.argument("name")
def set_author_name(name: str):
    """Cache your author name in credentials for use with --me.

    Stores NAME in ~/.als.credentials so that 'als last --me' can look up
    your articles without making an extra API call.  This is especially useful
    in bot/automation contexts or when working offline.

    To find your exact author name as it appears in the database, run:

        als authors

    Then cache it with:

        als set-author-name "Your Name"

    To clear the cached name (revert to API auto-resolve), pass an empty string:

        als set-author-name ""
    """
    if not CREDENTIALS_FILE.exists():
        click.echo("Not logged in. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)

    name = name.strip()
    _update_credentials(author_name=name)

    if name:
        click.echo(f"Author name cached: {name!r}")
        click.echo(f"Credentials updated: {CREDENTIALS_FILE}")
    else:
        click.echo("Author name cleared. 'als last --me' will auto-resolve via API.")


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
@click.option(
    "--source",
    type=click.Choice(["aifs", "blog", "both"], case_sensitive=False),
    default="both",
    help="Filter by content source: aifs (AI-First Show videos), blog (AI COE blog posts), or both (default).",
)
def search(query: str, count: int, source: str):
    """Search articles and get your personalised tracking links.

    Uses semantic search to find matching articles, then returns
    your personalised tracking link for each result.

    Use --source to filter by content type:
    - aifs: AI-First Show YouTube videos only
    - blog: AI COE blog posts only
    - both: All content (default)
    """
    api_key = _get_api_key()

    search_body: dict = {"query": query, "match_count": count}
    if source != "both":
        content_type = "video" if source == "aifs" else "article"
        search_body["content_type"] = content_type
        # Videos are long multi-topic documents; lower threshold needed for single-topic queries
        if content_type == "video":
            search_body["match_threshold"] = 0.2

    search_resp = requests.post(
        f"{API_BASE}/search-articles",
        json=search_body,
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
        content_type = result.get("content_type", "article")

        type_label = "📺" if content_type == "video" else "📝"
        duration_seconds = result.get("duration_seconds")
        duration_str = ""
        if duration_seconds:
            mins, secs = divmod(duration_seconds, 60)
            hours, mins = divmod(mins, 60)
            if hours:
                duration_str = f"  ⏱ {hours}h {mins}m"
            else:
                duration_str = f"  ⏱ {mins}m {secs:02d}s"

        click.echo(f"  {i}. {type_label} {click.style(title, bold=True)}")
        click.echo(f"     type: {content_type}")
        if author:
            click.echo(f"     by {author}")
        meta_line = "     " + "  ".join(
            filter(None, [date_str, duration_str.strip() if duration_str else ""])
        )
        if meta_line.strip():
            click.echo(meta_line)
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
@click.option(
    "--me",
    "filter_me",
    is_flag=True,
    default=False,
    help=(
        "Filter to articles written by the logged-in user. "
        "Uses cached author name if set (see 'als set-author-name'), "
        "otherwise auto-resolves via API. "
        "Run 'als authors' to find your name."
    ),
)
def last(n: int, author: str | None, filter_me: bool):
    """Show the last N articles with your personalised tracking links.

    N defaults to 10. Shows the most recently published articles in the
    database, with your personalised tracking link for each one.

    Use --author to filter to a specific author, e.g.:

        als last 5 --author "Simon"

    Use --me to filter to your own articles automatically:

        als last 5 --me
    """
    api_key = _get_api_key()

    # Resolve --me to the logged-in user's author name
    if filter_me:
        if author:
            click.echo("Error: --me and --author cannot be used together.", err=True)
            sys.exit(1)
        my_name = _resolve_my_author_name(api_key)
        if not my_name:
            click.echo(
                "Could not determine your author name. "
                "Make sure you are logged in and have articles in the database.",
                err=True,
            )
            sys.exit(1)
        author = my_name

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
        if filter_me:
            click.echo(f"No articles found for you ({author}).")
        elif author:
            click.echo(f"No articles found for author: {author}")
        else:
            click.echo("No articles found.")
        return

    if filter_me:
        click.echo(
            f"\nLast {len(results)} article(s) by you ({click.style(author, bold=True)}):\n"
        )
    elif author:
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
        destination_url = result.get("destination_url", "")
        date_str = published_at[:10] if published_at else ""

        click.echo(f"  {i}. {click.style(title, bold=True)}")
        if article_author:
            click.echo(f"     by {article_author}")
        if date_str:
            click.echo(f"     {date_str}")
        if destination_url:
            click.echo(f"     URL:  {destination_url}")

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
@click.argument("article", default="")
@click.option(
    "--days",
    default=30,
    show_default=True,
    help="Number of days to look back for click history.",
)
@click.option(
    "--everybody",
    is_flag=True,
    default=False,
    help="Show per-person click breakdown (all team members).",
)
def stats(article: str, days: int, everybody: bool):
    """Show statistics for a specific article, or overall database stats.

    \b
    Without an argument, shows database-level statistics (article counts,
    authors, people, tracking variants, total clicks).

    With an ARTICLE argument (slug or URL), shows per-article statistics:
    total clicks, daily click history, and per-variant breakdown.

    \b
    Examples:
      als stats                        # database overview
      als stats cursor-mar26           # article stats by slug
      als stats cursor-mar26 --days 7  # last 7 days only
      als stats cursor-mar26 --everybody  # show per-person breakdown
      als stats https://aicoe.link/abc  # article stats by short URL
    """
    if not article:
        # Database-level stats (original behaviour)
        resp = requests.get(f"{API_BASE}/db-stats", timeout=30)
        if resp.status_code != 200:
            click.echo(
                f"Error fetching stats ({resp.status_code}): {resp.text}", err=True
            )
            sys.exit(1)

        data = resp.json()

        click.echo("\nDatabase statistics:\n")
        click.echo(f"  Articles:          {data.get('articles', 0)}")
        click.echo(f"  Authors:           {data.get('authors', 0)}")
        click.echo(f"  People:            {data.get('people', 0)}")
        click.echo(f"  Tracking variants: {data.get('tracking_variants', 0)}")
        click.echo(f"  Total clicks:      {data.get('clicks', 0)}")
        click.echo()
        return

    # Article-level stats
    # Detect if article is a URL and pass it as such to the edge function
    payload: dict = {"days": days}
    if article.startswith("http://") or article.startswith("https://"):
        payload["url"] = article
    else:
        payload["slug"] = article

    if everybody:
        payload["everybody"] = True

    resp = requests.post(
        f"{API_BASE}/article-stats",
        json=payload,
        timeout=30,
    )

    if resp.status_code == 404:
        click.echo(f"Article not found: {article}", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    art = data.get("article", {})
    total = data.get("total_clicks", 0)
    variants = data.get("tracking_variants", 0)
    daily = data.get("daily_clicks", [])
    by_variant = data.get("by_variant", [])
    by_source = data.get("by_source", [])
    by_person = data.get("by_person", [])

    # Header
    click.echo(
        f"\n{click.style(art.get('title') or art.get('slug', article), bold=True)}"
    )
    if art.get("author"):
        click.echo(f"  by {art['author']}")
    click.echo(f"  URL:  {art.get('url', '')}")
    click.echo(f"  Slug: {art.get('slug', '')}")
    click.echo(f"  Short: {art.get('short_url', '')}")
    if art.get("published_at"):
        click.echo(f"  Published: {art['published_at'][:10]}")

    # Summary
    click.echo(f"\n  Total clicks:      {total}")
    click.echo(f"  Tracking variants: {variants}")

    # Daily click history
    if daily:
        click.echo(f"\n  Daily clicks (last {days} days):")
        max_clicks = max(row["clicks"] for row in daily)
        bar_width = 20
        for row in daily:
            date_str = row["date"]
            count = row["clicks"]
            bar_len = int((count / max_clicks) * bar_width) if max_clicks > 0 else 0
            bar = "#" * bar_len
            click.echo(f"    {date_str}  {bar:<{bar_width}s}  {count}")
    else:
        click.echo(f"\n  No clicks in the last {days} days.")

    # Per-variant breakdown
    if by_variant:
        click.echo(f"\n  Clicks by variant:")
        max_variant_clicks = max(v["clicks"] for v in by_variant) if by_variant else 0
        bar_width = 20
        for v in by_variant:
            count = v["clicks"]
            bar_len = (
                int((count / max_variant_clicks) * bar_width)
                if max_variant_clicks > 0
                else 0
            )
            bar = "#" * bar_len
            click.echo(f"    {v.get('label', '?'):30s}  {bar:<{bar_width}s}  {count}")

    # Per-source breakdown (aggregated by variant utm_source)
    if by_source:
        click.echo(f"\n  Clicks by source:")
        max_src_clicks = max(s["clicks"] for s in by_source) if by_source else 0
        bar_width = 20
        for s in by_source:
            source = s.get("source", "?")
            count = s["clicks"]
            bar_len = (
                int((count / max_src_clicks) * bar_width) if max_src_clicks > 0 else 0
            )
            bar = "#" * bar_len
            click.echo(f"    {source:20s}  {bar:<{bar_width}s}  {count}")

    # Per-person breakdown (when --everybody flag is used)
    if by_person:
        click.echo(f"\n  Clicks by person:")
        max_person_clicks = max(p["clicks"] for p in by_person) if by_person else 0
        bar_width = 20
        for p in by_person:
            name = p.get("name", p.get("ref", "?"))
            count = p["clicks"]
            bar_len = (
                int((count / max_person_clicks) * bar_width)
                if max_person_clicks > 0
                else 0
            )
            bar = "#" * bar_len
            click.echo(f"    {name:20s}  {bar:<{bar_width}s}  {count}")

    click.echo()


@cli.command("custom-links")
@click.option(
    "--count", default=10, show_default=True, help="Number of results to return."
)
@click.option(
    "--all", "show_all", is_flag=True, help="Show all custom links (ignores --count)."
)
def custom_links(count: int, show_all: bool):
    """List your custom short links created via 'als shorten'.

    Shows only manually-created links (not auto-imported Substack articles),
    with the original URL, short slug, creation date, and your tracking links
    per channel.

    Examples:

        als custom-links           # last 10 custom links
        als custom-links --count 5 # last 5 custom links
        als custom-links --all     # all custom links
    """
    body: dict = {"count": count}
    if show_all:
        body["all"] = True

    resp = _api_request("list-custom-links", json_body=body)

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    results = data.get("results", [])
    person = data.get("person", {})

    if not results:
        click.echo("No custom links found. Use 'als shorten <url>' to create one.")
        return

    label = "all" if show_all else str(len(results))
    click.echo(
        f"\nCustom links for {click.style(person.get('name', ''), bold=True)}"
        f" ({label}):\n"
    )

    for result in results:
        url = result.get("url", "")
        slug = result.get("slug", "")
        created_at = result.get("created_at", "")
        date_str = created_at[:10] if created_at else ""
        links = result.get("links", [])

        click.echo(f"  {click.style(url, bold=True)}")
        click.echo(f"    Slug:    {slug}")
        if date_str:
            click.echo(f"    Created: {date_str}")

        if links:
            click.echo(f"    Tracking links:")
            for link in links:
                label_str = link.get("label") or link.get("utm_source", "")
                click.echo(f"      {label_str:12s}  {link['short_url']}")
        else:
            click.echo(f"    (no tracking links)")

        click.echo()


@cli.command("sync-substack")
@click.option(
    "--force",
    is_flag=True,
    help="Force re-sync of existing articles (updates metadata even if already imported).",
)
def sync_substack(force: bool):
    """Trigger a sync of the latest articles from the Trilogy Substack.

    Calls the sync-substack edge function to fetch the Substack RSS/sitemap
    feed and import any new articles into the database.  Shows how many
    articles were checked and how many new ones were imported.

    Examples:

        als sync-substack          # import any new articles
        als sync-substack --force  # re-sync and update existing article metadata
    """
    api_key = _get_api_key()

    click.echo("Syncing Trilogy Substack articles...")

    # The sync-substack function accepts `force=true` as a query param.
    # We always POST (the function accepts GET and POST equally).
    url = f"{API_BASE}/sync-substack"
    if force:
        url += "?force=true"

    headers = {"x-api-key": api_key}
    try:
        resp = requests.post(url, headers=headers, timeout=120)
    except requests.exceptions.Timeout:
        click.echo("Error: request timed out (sync may still be running).", err=True)
        sys.exit(1)

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()

    message = data.get("message", "")
    checked = data.get("checked", 0)
    created = data.get("created", [])
    updated = data.get("updated", [])

    click.echo(f"\nResult: {message}")
    click.echo(f"  Checked:  {checked} article(s) in feed")
    click.echo(f"  Imported: {len(created)} new article(s)")
    if updated:
        click.echo(f"  Updated:  {len(updated)} existing article(s)")

    if created:
        click.echo("\nNewly imported articles:")
        for slug in created:
            click.echo(f"  - {slug}")

    if updated:
        click.echo("\nUpdated articles:")
        for slug in updated:
            click.echo(f"  - {slug}")

    click.echo()


@cli.command("sync-youtube")
@click.option(
    "--force",
    is_flag=True,
    help="Force re-sync of existing videos (updates metadata and re-fetches transcripts).",
)
@click.option(
    "--limit",
    type=int,
    default=0,
    help="Limit the number of new videos to import (0 = no limit).",
)
def sync_youtube(force: bool, limit: int):
    """Trigger a sync of videos from the AI-First Show YouTube channel.

    Calls the sync-youtube edge function to fetch the channel's video list,
    descriptions, and transcripts, then imports them into the database.

    Examples:

        als sync-youtube              # import any new videos
        als sync-youtube --limit 3    # import up to 3 new videos
        als sync-youtube --force      # re-sync and update existing video metadata
    """
    api_key = _get_api_key()

    click.echo("Syncing AI-First Show YouTube videos...")

    params = []
    if force:
        params.append("force=true")
    if limit > 0:
        params.append(f"limit={limit}")
    url = f"{API_BASE}/sync-youtube"
    if params:
        url += "?" + "&".join(params)

    headers = {"x-api-key": api_key}
    try:
        resp = requests.post(url, headers=headers, timeout=300)
    except requests.exceptions.Timeout:
        click.echo("Error: request timed out (sync may still be running).", err=True)
        sys.exit(1)

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()

    message = data.get("message", "")
    checked = data.get("checked", 0)
    created = data.get("created", [])
    updated = data.get("updated", [])
    transcripts = data.get("transcripts_fetched", 0)

    click.echo(f"\nResult: {message}")
    click.echo(f"  Checked:      {checked} video(s) on channel")
    click.echo(f"  Imported:     {len(created)} new video(s)")
    if updated:
        click.echo(f"  Updated:      {len(updated)} existing video(s)")
    click.echo(f"  Transcripts:  {transcripts} fetched")

    if created:
        click.echo("\nNewly imported videos:")
        for slug in created:
            click.echo(f"  - {slug}")

    if updated:
        click.echo("\nUpdated videos:")
        for slug in updated:
            click.echo(f"  - {slug}")

    click.echo()


@cli.command("update-transcript")
@click.option(
    "--url",
    required=True,
    help="YouTube video URL (destination_url to match in the database).",
)
@click.option(
    "--transcript-file",
    type=click.Path(exists=True),
    help="Path to a file containing the transcript text.",
)
@click.option(
    "--transcript",
    "transcript_text",
    help="Transcript text to set (alternative to --transcript-file).",
)
def update_transcript(
    url: str, transcript_file: str | None, transcript_text: str | None
):
    """Update or add a transcript for an existing video.

    Looks up the link by its destination URL and sets the transcript column.
    Use this to backfill transcripts for videos that were imported without one
    (e.g. from aysp/Clip Together exports).

    Provide the transcript via --transcript-file (reads from a file) or
    --transcript (inline text). Exactly one must be specified.

    Examples:

        als update-transcript --url "https://www.youtube.com/watch?v=abc123" \\
            --transcript-file transcript.txt

        als update-transcript --url "https://www.youtube.com/watch?v=abc123" \\
            --transcript "Hello and welcome to the show..."
    """
    if transcript_file and transcript_text:
        click.echo(
            "Error: specify either --transcript-file or --transcript, not both.",
            err=True,
        )
        sys.exit(1)

    if not transcript_file and not transcript_text:
        click.echo(
            "Error: one of --transcript-file or --transcript is required.", err=True
        )
        sys.exit(1)

    if transcript_file:
        with open(transcript_file, "r", encoding="utf-8") as f:
            transcript_content = f.read().strip()
    else:
        transcript_content = (transcript_text or "").strip()

    if not transcript_content:
        click.echo("Error: transcript is empty.", err=True)
        sys.exit(1)

    api_key = _get_api_key()

    click.echo(f"Updating transcript for: {url}")
    click.echo(f"  Transcript length: {len(transcript_content)} characters")

    resp = _api_request(
        "update-transcript",
        json_body={"url": url, "transcript": transcript_content},
    )

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code == 404:
        click.echo(f"Error: no link found for URL: {url}", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()

    click.echo(f"\nResult: {data.get('message', 'OK')}")
    click.echo(f"  Slug:     {data.get('slug', '?')}")
    click.echo(f"  Title:    {data.get('title', '?')}")
    click.echo(f"  Length:   {data.get('transcript_length', 0)} chars")
    if data.get("replaced_existing"):
        click.echo("  (Replaced existing transcript)")
    click.echo()


@cli.group("tags")
def tags():
    """Manage article tags for categorization and filtering.

    Tags are reusable labels that can be assigned to articles. Use them
    to categorize your article collection by topic, project, or any
    other grouping.

    Examples:

        als tags list
        als tags create "Machine Learning"
        als tags assign --article my-article-slug --tag machine-learning
        als tags remove --article my-article-slug --tag machine-learning
        als tags delete "Machine Learning"
    """
    pass


@tags.command("list")
@click.option(
    "--article",
    default="",
    help="Filter to tags on a specific article (by slug).",
)
def tags_list(article: str):
    """List all tags, or list tags on a specific article.

    Without --article, shows all tags with article counts.
    With --article, shows only the tags assigned to that article.

    Examples:

        als tags list
        als tags list --article my-article-slug
    """
    body: dict = {"action": "list"}
    if article:
        body["article"] = article

    resp = _api_request("manage-tags", json_body=body)

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code == 404:
        data = resp.json()
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()

    if article:
        art = data.get("article", {})
        tag_list = data.get("tags", [])
        title = art.get("title") or art.get("slug", article)
        click.echo(f"\nTags on {click.style(title, bold=True)}:\n")
        if not tag_list:
            click.echo("  (no tags)")
        else:
            for t in tag_list:
                click.echo(f"  {t.get('name', '')}  ({t.get('slug', '')})")
    else:
        tag_list = data.get("tags", [])
        click.echo(f"\nAll tags ({len(tag_list)} total):\n")
        if not tag_list:
            click.echo('  (no tags yet — create one with: als tags create "Name")')
        else:
            for t in tag_list:
                count = t.get("article_count", 0)
                click.echo(
                    f"  {click.style(t.get('name', ''), bold=True)}  "
                    f"({t.get('slug', '')})  "
                    f"{count} article{'s' if count != 1 else ''}"
                )
    click.echo()


@tags.command("create")
@click.argument("name")
@click.option(
    "--slug", default="", help="Custom slug (auto-generated from name if omitted)."
)
def tags_create(name: str, slug: str):
    """Create a new tag.

    NAME is the human-readable tag name. A URL-friendly slug is
    auto-generated from the name unless --slug is provided.

    Examples:

        als tags create "Machine Learning"
        als tags create "GenAI" --slug gen-ai
    """
    body: dict = {"action": "create", "name": name}
    if slug:
        body["slug"] = slug

    resp = _api_request("manage-tags", json_body=body)

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code == 409:
        data = resp.json()
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)
    if resp.status_code == 400:
        data = resp.json()
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)
    if resp.status_code not in (200, 201):
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    tag = data.get("tag", {})
    click.echo(f"\n{data.get('message', 'Created.')}")
    if tag:
        click.echo(f"  Name: {tag.get('name', '')}")
        click.echo(f"  Slug: {tag.get('slug', '')}")
    click.echo()


@tags.command("delete")
@click.argument("name")
def tags_delete(name: str):
    """Delete a tag and remove it from all articles.

    Identifies the tag by name (converted to slug). All article
    associations are removed automatically.

    Example:

        als tags delete "Machine Learning"
    """
    body: dict = {"action": "delete", "name": name}

    resp = _api_request("manage-tags", json_body=body)

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code == 404:
        data = resp.json()
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    click.echo(f"\n{data.get('message', 'Deleted.')}\n")


@tags.command("assign")
@click.option("--article", required=True, help="Article slug to tag.")
@click.option("--tag", required=True, help="Tag name or slug to assign.")
def tags_assign(article: str, tag: str):
    """Assign a tag to an article.

    Both --article and --tag are required. The tag is identified by
    name (converted to slug) or directly by slug.

    Example:

        als tags assign --article my-article-slug --tag machine-learning
    """
    body: dict = {"action": "tag", "article": article, "tag": tag}

    resp = _api_request("manage-tags", json_body=body)

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code == 404:
        data = resp.json()
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)
    if resp.status_code not in (200, 201):
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    click.echo(f"\n{data.get('message', 'Tagged.')}\n")


@tags.command("remove")
@click.option("--article", required=True, help="Article slug to untag.")
@click.option("--tag", required=True, help="Tag name or slug to remove.")
def tags_remove(article: str, tag: str):
    """Remove a tag from an article.

    Both --article and --tag are required. The tag is identified by
    name (converted to slug) or directly by slug.

    Example:

        als tags remove --article my-article-slug --tag machine-learning
    """
    body: dict = {"action": "untag", "article": article, "tag": tag}

    resp = _api_request("manage-tags", json_body=body)

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code == 404:
        data = resp.json()
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    click.echo(f"\n{data.get('message', 'Removed.')}\n")


@cli.group("tracking-variants")
def tracking_variants():
    """Manage your tracking variant channels (Discord, LinkedIn, X, etc.).

    Tracking variants are the per-channel configurations used to generate
    personalised tracking links.  Each variant maps to a source (e.g.
    'linkedin') with optional UTM parameters.

    Default/system variants (Discord, LinkedIn, X, YouTube) cannot be
    deleted.  Only custom variants you create can be removed.

    Examples:

        als tracking-variants list
        als tracking-variants add --source whatsapp --label "WhatsApp Group"
        als tracking-variants delete --label "WhatsApp Group"
    """
    pass


@tracking_variants.command("list")
def tracking_variants_list():
    """List all your tracking variant channels.

    Shows each channel with its label, UTM source, and whether it is a
    default system variant or a custom one you created.

    Example:

        als tracking-variants list
    """
    resp = _api_request("manage-tracking-variants", json_body={"action": "list"})

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    variants = data.get("variants", [])
    person = data.get("person", {})

    if not variants:
        click.echo("No tracking variants found.")
        return

    click.echo(
        f"\nTracking variants for {click.style(person.get('name', ''), bold=True)}"
        f" ({len(variants)} total):\n"
    )

    for v in variants:
        label = v.get("label", "")
        source = v.get("utm_source", "")
        medium = v.get("utm_medium", "social")
        content = v.get("utm_content") or ""
        term = v.get("utm_term") or ""
        icon = v.get("icon") or ""
        is_default = v.get("is_default", False)

        default_marker = " [default]" if is_default else " [custom]"
        prefix = f"{icon} " if icon else ""
        click.echo(f"  {prefix}{click.style(label, bold=True)}{default_marker}")
        click.echo(f"    source={source}  medium={medium}", nl=False)
        if content:
            click.echo(f"  content={content}", nl=False)
        if term:
            click.echo(f"  term={term}", nl=False)
        click.echo()

    click.echo()


@tracking_variants.command("add")
@click.option(
    "--source",
    required=True,
    help="UTM source value (e.g. linkedin, discord, whatsapp).",
)
@click.option(
    "--label",
    default="",
    help="Human-readable label (defaults to capitalised source name).",
)
@click.option(
    "--medium",
    default="social",
    show_default=True,
    help="UTM medium (e.g. social, email).",
)
@click.option(
    "--content",
    default="",
    help="UTM content for sub-channel targeting (e.g. ai-coe-general).",
)
@click.option(
    "--term",
    default="",
    help="UTM term for keyword targeting.",
)
@click.option(
    "--icon",
    default="",
    help="Icon emoji for the variant (auto-assigned if omitted).",
)
def tracking_variants_add(
    source: str,
    label: str,
    medium: str,
    content: str,
    term: str,
    icon: str,
):
    """Add a new custom tracking variant channel.

    Creates a new per-channel tracking configuration.  The SOURCE is the
    UTM source value used in tracking links (e.g. 'whatsapp', 'slack').

    Examples:

        als tracking-variants add --source whatsapp --label "WhatsApp Group"
        als tracking-variants add --source slack --content eng-team
    """
    body: dict = {"action": "add", "source": source}
    if label:
        body["label"] = label
    if medium:
        body["medium"] = medium
    if content:
        body["content"] = content
    if term:
        body["term"] = term
    if icon:
        body["icon"] = icon

    resp = _api_request("manage-tracking-variants", json_body=body)

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code == 409:
        data = resp.json()
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)
    if resp.status_code == 400:
        data = resp.json()
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)
    if resp.status_code not in (200, 201):
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    variant = data.get("variant", {})
    click.echo(f"\n{data.get('message', 'Created.')}")
    if variant:
        lbl = variant.get("label", "")
        src = variant.get("utm_source", "")
        med = variant.get("utm_medium", "social")
        cnt = variant.get("utm_content") or ""
        trm = variant.get("utm_term") or ""
        click.echo(f"  Label:  {lbl}")
        click.echo(f"  Source: {src}  Medium: {med}", nl=False)
        if cnt:
            click.echo(f"  Content: {cnt}", nl=False)
        if trm:
            click.echo(f"  Term: {trm}", nl=False)
        click.echo()
    click.echo()


@tracking_variants.command("delete")
@click.option(
    "--label",
    default="",
    help="Label of the variant to delete (case-insensitive).",
)
@click.option(
    "--source",
    default="",
    help="UTM source of the variant to delete (if label not provided).",
)
def tracking_variants_delete(label: str, source: str):
    """Delete a custom tracking variant channel.

    Default/system variants (Discord, LinkedIn, X, YouTube) are protected
    and cannot be deleted.  Only custom variants you have created can be
    removed.

    Examples:

        als tracking-variants delete --label "WhatsApp Group"
        als tracking-variants delete --source slack
    """
    if not label and not source:
        click.echo(
            "Error: provide --label or --source to identify the variant.", err=True
        )
        sys.exit(1)

    body: dict = {"action": "delete"}
    if label:
        body["label"] = label
    if source:
        body["source"] = source

    resp = _api_request("manage-tracking-variants", json_body=body)

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code == 403:
        data = resp.json()
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)
    if resp.status_code == 404:
        data = resp.json()
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)
    if resp.status_code == 409:
        data = resp.json()
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        matches = data.get("matches", [])
        if matches:
            click.echo("Matching variants:", err=True)
            for m in matches:
                click.echo(f"  {m.get('label')} (source={m.get('source')})", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    click.echo(f"\n{data.get('message', 'Deleted.')}\n")


@cli.command("aifs")
@click.argument("url_or_action", required=False)
@click.option(
    "--comment",
    default="",
    help="Optional comment with your vote (when submitting a URL).",
)
def aifs(url_or_action: str | None, comment: str):
    """AI First Show episode candidate submission and voting.

    Submit URLs as candidates for the next AI First Show episode,
    vote on existing submissions, and view current rankings.

    \b
    Examples:
      als aifs https://example.com/article            # submit/vote
      als aifs https://example.com --comment '...'    # with comment
      als aifs list                                   # show candidates
    """
    if not url_or_action:
        click.echo(click.get_current_context().get_help())
        raise SystemExit(1)

    if url_or_action == "list":
        _aifs_list()
        return

    # Treat as a URL submission
    _aifs_submit(url_or_action, comment)


def _aifs_submit(url: str, comment: str):
    """Submit a URL as a candidate for the next AI First Show episode."""
    body: dict = {"action": "submit", "url": url}
    if comment:
        body["comment"] = comment

    resp = _api_request("aifs", json_body=body)

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
    status = data.get("status", "")

    if status == "submitted":
        click.echo(f"\n{click.style('Submitted!', fg='green', bold=True)}")
        click.echo(f"  URL: {url}")
        click.echo(f"  This is the first vote for this URL.")
    elif status == "voted":
        click.echo(f"\n{click.style('Voted!', fg='green', bold=True)}")
        click.echo(f"  URL: {url}")
        click.echo(f"  Your vote has been added to an existing submission.")
    elif status == "already_voted":
        click.echo(f"\n{click.style('Already voted', fg='yellow')}")
        click.echo(f"  URL: {url}")
        click.echo(f"  You have already voted for this URL.")

    click.echo()


def _aifs_list():
    """Show current AI First Show candidates sorted by vote count.

    Displays all submitted URLs with their vote counts, the submitter,
    and any comments from voters.

    \b
    Example:
      als aifs list
    """
    resp = _api_request("aifs", json_body={"action": "list"})

    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    submissions = data.get("submissions", [])

    if not submissions:
        click.echo("\nNo submissions yet.")
        click.echo("Submit one with: als aifs <url>")
        click.echo()
        return

    total = data.get("total", len(submissions))
    click.echo(
        f"\n{click.style('AI First Show', bold=True)} — next episode candidates "
        f"({total} submission{'s' if total != 1 else ''})\n"
    )

    for sub in submissions:
        vote_count = sub.get("vote_count", 0)
        url = sub.get("url", "")
        voters = sub.get("voters", [])

        vote_str = f"{vote_count} vote{'s' if vote_count != 1 else ''}"
        click.echo(f"  {click.style(vote_str, fg='cyan', bold=True)}  {url}")

        if voters:
            first_voter = voters[0] if voters else None
            if first_voter:
                comment_str = (
                    f' → {first_voter["person_ref"]}: "{first_voter["comment"]}"'
                    if first_voter.get("comment")
                    else f" → {first_voter['person_ref']}"
                )
                click.echo(f"           {comment_str}")

            other_voters = voters[1:] if len(voters) > 1 else []
            if other_voters:
                refs = [v.get("person_ref", "?") for v in other_voters]
                click.echo(f"           → {', '.join(refs)}")

        click.echo()


if __name__ == "__main__":
    cli()
