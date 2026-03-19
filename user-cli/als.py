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
@click.argument("article", default="")
@click.option("--days", default=30, show_default=True, help="Number of days to look back for click history.")
def stats(article: str, days: int):
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
    """
    if not article:
        # Database-level stats (original behaviour)
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
        return

    # Article-level stats
    resp = requests.post(
        f"{API_BASE}/article-stats",
        json={"slug": article, "days": days},
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

    # Header
    click.echo(f"\n{click.style(art.get('title') or art.get('slug', article), bold=True)}")
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
            click.echo(f"    {date_str}  {bar:>{bar_width}s}  {count}")
    else:
        click.echo(f"\n  No clicks in the last {days} days.")

    # Per-variant breakdown
    if by_variant:
        click.echo(f"\n  Clicks by variant:")
        for v in by_variant:
            click.echo(f"    {v.get('label', '?'):30s}  {v['clicks']}")

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


if __name__ == "__main__":
    cli()
