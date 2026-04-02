#!/usr/bin/env python3
"""User CLI for aicoe.fit link shortener.

Authenticate with a personal API key to get personalised tracking links
for articles, and search the article catalogue.
"""

import configparser
import json
import os
import re
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
# Short ID helpers
# ---------------------------------------------------------------------------


def _compute_short_ids(ids: list[str]) -> dict[str, str]:
    """Compute the shortest unique prefix for each ID.

    IDs are in the format 'lnk-<hash>'. We compute the shortest prefix
    after 'lnk-' that uniquely identifies each ID in the given list.

    Returns a mapping from full ID to short ID (e.g., 'lnk-edktk8ri3c' -> 'lnk-edk').
    """
    if not ids:
        return {}

    result: dict[str, str] = {}

    for length in range(3, 20):
        prefix_to_full: dict[str, str | None] = {}
        collisions: set[str] = set()

        for full_id in ids:
            if not full_id.startswith("lnk-"):
                result[full_id] = full_id
                continue
            if full_id in result:
                continue

            hash_part = full_id[4:]
            if len(hash_part) < length:
                prefix = full_id
            else:
                prefix = "lnk-" + hash_part[:length]

            if prefix in prefix_to_full:
                existing = prefix_to_full[prefix]
                if existing:
                    collisions.add(existing)
                collisions.add(full_id)
                prefix_to_full[prefix] = None
            else:
                prefix_to_full[prefix] = full_id

        for prefix, full_id in prefix_to_full.items():
            if full_id and full_id not in collisions and full_id not in result:
                result[full_id] = prefix

    for full_id in ids:
        if full_id not in result:
            result[full_id] = full_id

    return result


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
    cached, falls back to the validate-key endpoint.

    Returns the person's name (as stored in the people table, e.g. "Simon Thornton")
    or None if it cannot be determined.
    """
    # Check credentials cache first — avoids API call overhead
    creds = _read_credentials()
    cached = creds.get("author_name", "").strip()
    if cached:
        return cached

    # Resolve via validate-key endpoint
    resp = _api_request("validate-key", api_key=api_key, json_body={})
    if resp.status_code != 200:
        return None
    return resp.json().get("name") or None


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
         Get article: als get <slug>
         My articles: als last --me 5
         Shorten URL: als shorten <url>
         Upgrade:     als upgrade

    \b
    Workflow:
      als last 10 --summary          # scan recent articles
      als get lnk-3f7                # get full details + tracking links
      als search 'AI agents'         # find by topic
      als stats lnk-3f7              # check click performance
      als aifs https://... --comment # submit for AI First Show
    """
    pass


@cli.command("help")
def help_cmd():
    """Show use-case-driven guidance for common workflows."""
    _h = click.style  # shorthand

    sections = [
        (
            "1. Share a specific article on social media",
            "You wrote or found an article and want to share it on Twitter/LinkedIn "
            "with a link that tracks this specific share.",
            [
                'als search "your article topic"       # find it by topic',
                "als get lnk-xxx                       # see full details + all your tracking links",
                "# or, create a one-off variant with AI-inferred UTM:",
                'als shorten lnk-xxx --note "replying to @mike on twitter"',
                "# → aicoe.fit/article-slug-a1b2c3   (auto-expires 60d)",
            ],
        ),
        (
            "2. YouTube video description",
            "You posted a video and want tracked links to your Substack, Discord, "
            "etc. in the description. All links are clean (no visible UTM params).",
            [
                'als context create "My Video Title (1 Apr 2026)" --expires 90d',
                'als context generate ctx-xxx --pinned --note "youtube video description"',
                "# → aicoe.fit/substack-e7f8a1",
                "# → aicoe.fit/discord-b2c3d4",
                "# Paste these into your YouTube description.",
            ],
        ),
        (
            "3. Pin your permanent destinations (LinkedIn, Substack, Discord, etc.)",
            "Pinned links are permanent destinations you want to track everywhere — "
            "your LinkedIn profile, your Substack, Discord invite, etc. Pin them "
            "once, then they appear in every context you generate.",
            [
                "# Pin a link (one-time setup per destination)",
                "als shorten https://linkedin.com/in/yourname --slug linkedinSJB",
                "als shorten https://trilogyai.substack.com --slug substack",
                "# Then ask your admin to mark them as pinned, or they can pin via:",
                "#   als links pin linkedinSJB",
                "#   als links pin substack",
                "",
                "# List your pinned links",
                "als links list --pinned",
                "",
                "# Once pinned, any context generate --pinned will include them:",
                'als context generate ctx-xxx --pinned --note "youtube description"',
            ],
        ),
        (
            "4. Check how an article is performing",
            "See total clicks, per-channel breakdown, or per-person breakdown.",
            [
                'als stats "article-slug"              # your clicks',
                'als stats "article-slug" --everybody  # whole team breakdown',
                "als stats lnk-xxx --days 7            # last 7 days only",
            ],
        ),
        (
            "5. See the latest articles",
            "Quick scan of what has been published recently and get your tracking links.",
            [
                "als last 5                            # last 5 articles, all tracking links",
                "als last 10 --me                      # filter to articles you authored",
                "als last 10 --summary                 # compact table view",
            ],
        ),
        (
            "6. Submit a link for the AI First Show",
            "You found something interesting and want to nominate it for the next episode.",
            [
                'als aifs "https://arxiv.org/abs/..." --comment "Strong reasoning paper"',
                "als aifs list                         # see all current nominations",
            ],
        ),
        (
            "7. Create a permanent personal short link",
            "You want a clean short URL for your LinkedIn profile, GitHub, etc.",
            [
                'als shorten "https://linkedin.com/in/yourname" --slug linkedinSJB',
                "# → aicoe.fit/linkedinSJB",
            ],
        ),
        (
            "8. Find content by topic (semantic search)",
            "You remember a video or article covered a topic but can't recall the title.",
            [
                'als search "late interaction retrieval"',
                'als search "multi-agent deep research"',
            ],
        ),
        (
            "9. Manage your tracking channels",
            "See or customise what channels (Discord, LinkedIn, X, etc.) get variants "
            "when you run als get.",
            [
                "als tracking-variants list",
                'als tracking-variants add --label "Newsletter" --source newsletter --medium email',
            ],
        ),
    ]

    click.echo()
    click.echo(_h("als — Use-Case Guide", bold=True, fg="cyan"))
    click.echo()

    for title, desc, commands in sections:
        click.echo(_h(title, bold=True))
        click.echo(f"  {desc}")
        click.echo()
        for cmd in commands:
            click.echo(f"    {cmd}")
        click.echo()

    click.echo(
        f"Run {_h('als <command> --help', bold=True)} for full options on any command."
    )
    click.echo()


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
        click.echo("\nWhat's new:")
        changelog = release_info["body"].strip()
        for line in changelog.split("\n"):
            if line.strip():
                click.echo(f"  {line}")
        click.echo("\nRun 'als --help' to see all commands.")


@cli.command()
def whoami():
    """Show the current authenticated user."""
    api_key = _get_api_key()

    resp = _api_request("validate-key", api_key=api_key, json_body={})
    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)

    person = resp.json()
    click.echo(f"Logged in as: {person.get('name', '?')} ({person.get('slug', '?')})")
    click.echo(f"Credentials: {CREDENTIALS_FILE}")


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
@click.argument("link_id_or_url")
@click.option(
    "--source", default=None, help="Filter to a specific source (e.g. linkedin)"
)
@click.option(
    "--slug", default=None, help="Custom slug for the short link (e.g. 'my-link')"
)
@click.option(
    "--note",
    default=None,
    help="Describe where you're sharing this link. AI infers UTM source/medium.",
)
@click.option(
    "--expires",
    default=None,
    help="Expiry in days (e.g. 30d, 90d). Default: 60d when --note is used.",
)
@click.option(
    "--no-expires",
    is_flag=True,
    default=False,
    help="Keep variant in active list indefinitely (no auto-archive).",
)
def shorten(
    link_id_or_url: str,
    source: str | None,
    slug: str | None,
    note: str | None,
    expires: str | None,
    no_expires: bool,
):
    """Get your personalised tracking link(s) for any URL or link ID.

    Accepts a URL or lnk-xxx ID. Without --note, behaves as before.
    With --note, uses AI to infer UTM source/medium from the description
    and creates a tracking variant with a 60-day default expiry.

    \b
    Examples:
      als shorten https://example.com
      als shorten https://example.com --slug my-link
      als shorten lnk-abc --note "replying to @mike on twitter"
      als shorten https://example.com --note "linkedin post" --expires 90d
      als shorten lnk-abc --note "pinned in discord" --no-expires
    """
    if note is not None:
        _shorten_with_note(link_id_or_url, note, expires, no_expires)
        return

    # Original behaviour — call shorten-url edge function
    url = link_id_or_url
    body: dict = {"url": url}
    if source:
        body["source"] = source
    if slug:
        body["slug"] = slug

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
    existed = data.get("existed", False)
    article = data.get("article", {})

    if existed:
        title = article.get("title") or slug
        author = article.get("author", "")
        published_at = article.get("published_at", "")
        date_str = published_at[:10] if published_at else ""

        click.echo(f"\n{click.style('This URL already exists:', bold=True)}\n")
        click.echo(f"  {click.style(title, bold=True)}")
        if author:
            click.echo(f"  by {author}")
        if date_str:
            click.echo(f"  {date_str}")
        click.echo(f"  Slug:  {slug}")
        click.echo(f"  Short: https://aicoe.fit/{slug}")
        click.echo()

        if links:
            click.echo(f"  Your tracking links ({person.get('name', '')}):")
            for link in links:
                label = link.get("label") or link.get("source", "")
                click.echo(f"    {label:12s}  {link['short_url']}")
        else:
            click.echo("  No tracking links generated.")
    else:
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


def _shorten_with_note(
    link_id_or_url: str, note: str, expires: str | None, no_expires: bool
):
    """Create a tracking variant using server-side AI-inferred UTM from --note."""
    if expires and not re.match(r"^\d+d$", expires):
        click.echo(
            "Error: --expires must be in the format Nd (e.g. 30d, 90d).", err=True
        )
        sys.exit(1)

    click.echo("Creating variant with server-side UTM inference...")

    body: dict = {
        "action": "shorten_with_note",
        "link": link_id_or_url,
        "note": note,
    }
    if expires:
        body["expires"] = expires
    if no_expires:
        body["no_expires"] = True

    resp = _api_request("manage-links", json_body=body)
    data = resp.json()
    if resp.status_code != 200:
        if "matches" in data:
            click.echo(f"Ambiguous ID '{link_id_or_url}', matches:", err=True)
            for r in data["matches"][:5]:
                click.echo(f"  {r['id']}", err=True)
        else:
            click.echo(f"{data.get('error', resp.text)}", err=True)
        sys.exit(1)

    link = data.get("link", {})
    utm = data.get("utm", {})
    variant = data.get("variant", {})

    click.echo(f"\n{click.style('Variant created:', fg='green', bold=True)}")
    click.echo(f"  Link:    {link.get('slug', '')} ({link.get('id', '')})")
    click.echo(f"  Note:    {note}")
    click.echo(
        f"  UTM:     source={utm.get('utm_source', '?')}, medium={utm.get('utm_medium', '?')}"
    )
    if variant.get("expires_at"):
        click.echo(f"  Expires: {variant['expires_at'][:10]}")
    else:
        click.echo(f"  Expires: never")
    click.echo(f"  Short:   {variant.get('short_url', '')}")
    click.echo()


@cli.group("links")
def links_group():
    """Manage pinned links (permanent destinations reused across contexts).

    Pinned links are permanent destinations like your Substack, Discord,
    or Twitter profile that participate in bulk context generation.

    \b
    Examples:
      als links list --pinned
      als links pin substack
      als links pin lnk-abc123
    """
    pass


@links_group.command("list")
@click.option(
    "--pinned",
    is_flag=True,
    default=False,
    help="Show only pinned links.",
)
def links_list(pinned: bool):
    """List links, optionally filtered to pinned only.

    \b
    Examples:
      als links list --pinned
    """
    params = {}
    if pinned:
        params["pinned"] = "true"
    resp = _api_request("manage-links", method="GET", params=params)
    if resp.status_code != 200:
        click.echo(f"Error: {resp.json().get('error', resp.text)}", err=True)
        sys.exit(1)

    links = resp.json().get("links", [])
    if not links:
        if pinned:
            click.echo("No pinned links. Use 'als links pin <slug>' to pin one.")
        else:
            click.echo("No links found.")
        return

    label = "Pinned links" if pinned else "Links"
    click.echo(f"\n{label} ({len(links)}):\n")

    for link in links:
        pin_marker = " [pinned]" if link.get("is_pinned") else ""
        title = link.get("title") or link.get("slug", "")
        click.echo(
            f"  {click.style(link['id'][:12], fg='magenta')}  "
            f"{click.style(title, bold=True)}{pin_marker}"
        )
        click.echo(f"    Slug:  {link['slug']}")
        click.echo(f"    URL:   {link.get('destination_url', '')}")
        click.echo()


@links_group.command("pin")
@click.argument("slug_or_id")
def links_pin(slug_or_id: str):
    """Pin a link so it participates in context generation.

    Accepts a link slug or lnk-xxx ID.

    \b
    Examples:
      als links pin substack
      als links pin lnk-abc123
    """
    resp = _api_request(
        "manage-links",
        json_body={"action": "pin", "slug_or_id": slug_or_id},
    )
    data = resp.json()
    if resp.status_code != 200:
        if "matches" in data:
            click.echo(f"Ambiguous match for '{slug_or_id}':", err=True)
            for r in data["matches"]:
                click.echo(f"  {r['id']}  {r['slug']}", err=True)
        else:
            click.echo(f"{data.get('error', resp.text)}", err=True)
        sys.exit(1)

    link = data.get("link", {})
    click.echo(
        f"\nPinned: {click.style(link.get('slug', slug_or_id), bold=True)} ({link.get('id', '')})"
    )
    click.echo()


@cli.group("context")
def context_group():
    """Manage link contexts for grouped tracking variants.

    A context is a named, time-bounded reason for generating tracking
    links — e.g. a YouTube video description, a conference talk, or a
    newsletter issue.

    \b
    Examples:
      als context create "AI First Show Apr 1 2026" --expires 90d
      als context generate ctx-abc --pinned --note "youtube video"
      als context show ctx-abc
      als context list
      als context archive ctx-abc
    """
    pass


@context_group.command("create")
@click.argument("label")
@click.option(
    "--expires",
    default=None,
    help="Expiry in days (e.g. 30d, 90d). Default: never.",
)
def context_create(label: str, expires: str | None):
    """Create a new link context.

    LABEL is a human-readable name (e.g. "AI First Show Apr 1 2026").
    A URL-friendly slug is auto-generated from the label.

    \b
    Examples:
      als context create "AI First Show Apr 1 2026"
      als context create "Newsletter Issue 42" --expires 30d
    """
    body: dict = {"action": "create", "label": label}
    if expires:
        if not re.match(r"^\d+d$", expires):
            click.echo(
                "Error: --expires must be in the format Nd (e.g. 30d, 90d).", err=True
            )
            sys.exit(1)
        body["expires"] = expires

    resp = _api_request("manage-contexts", json_body=body)
    if resp.status_code != 200:
        click.echo(f"Error: {resp.json().get('error', resp.text)}", err=True)
        sys.exit(1)

    ctx = resp.json().get("context", {})

    click.echo(f"\n{click.style('Context created:', fg='green', bold=True)}")
    click.echo(f"  ID:      {ctx.get('id', '')}")
    click.echo(f"  Label:   {ctx.get('label', '')}")
    click.echo(f"  Slug:    {ctx.get('slug', '')}")
    if ctx.get("expires_at"):
        click.echo(f"  Expires: {ctx['expires_at'][:10]}")
    else:
        click.echo(f"  Expires: never")
    click.echo()


@context_group.command("generate")
@click.argument("ctx_id")
@click.option(
    "--pinned", is_flag=True, default=False, help="Generate for all pinned links."
)
@click.option("--note", required=True, help="Description for AI UTM inference.")
def context_generate(ctx_id: str, pinned: bool, note: str):
    """Generate tracking variants for a context.

    Creates tracking variants for all pinned links (with --pinned) scoped
    to the given context. The context slug becomes utm_content, and UTM
    source/medium are inferred from --note via server-side AI.

    \b
    Examples:
      als context generate ctx-abc --pinned --note "youtube video description"
    """
    if not pinned:
        click.echo(
            "Error: --pinned is required (specify which links to generate for).",
            err=True,
        )
        sys.exit(1)

    click.echo("Generating tracking variants (server-side UTM inference)...")

    resp = _api_request(
        "manage-contexts",
        json_body={
            "action": "generate",
            "ctx_id": ctx_id,
            "pinned": True,
            "note": note,
        },
    )
    data = resp.json()
    if resp.status_code != 200:
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)

    utm = data.get("utm", {})
    click.echo(
        f"  source={utm.get('utm_source', '?')}  medium={utm.get('utm_medium', '?')}"
    )
    click.echo()

    ctx = data.get("context", {})
    generated = data.get("generated", [])

    click.echo(
        f"{click.style('Generated', fg='green', bold=True)} {len(generated)} variant(s) "
        f"for context {click.style(ctx.get('label', ctx_id), bold=True)}:\n"
    )
    for g in generated:
        click.echo(f"  {g['slug']:30s}  {g['short_url']}")
    click.echo()


@context_group.command("show")
@click.argument("ctx_id")
def context_show(ctx_id: str):
    """Show details of a context including its variants and click counts.

    \b
    Examples:
      als context show ctx-abc
    """
    resp = _api_request("manage-contexts", method="GET", params={"id": ctx_id})
    data = resp.json()
    if resp.status_code != 200:
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)

    ctx = data.get("context", {})
    variants = data.get("variants", [])

    click.echo(f"\n{click.style(ctx.get('label', ''), bold=True)}")
    click.echo(f"  ID:       {ctx.get('id', '')}")
    click.echo(f"  Slug:     {ctx.get('slug', '')}")
    click.echo(f"  Created:  {ctx.get('created_at', '')[:10]}")
    if ctx.get("expires_at"):
        click.echo(f"  Expires:  {ctx['expires_at'][:10]}")
    if ctx.get("archived_at"):
        click.echo(f"  Archived: {ctx['archived_at'][:10]}")

    if not variants:
        click.echo("\n  No variants generated for this context yet.")
        click.echo()
        return

    click.echo(f"\n  Variants ({len(variants)}):\n")
    for v in variants:
        link_slug = v.get("link_slug", v.get("link_id", "")[:12])
        short_url = v.get("short_url", "")
        clicks = v.get("clicks", 0)
        click.echo(f"    {link_slug:25s}  {short_url}  ({clicks} clicks)")

    click.echo()


@context_group.command("list")
@click.option(
    "--expired",
    is_flag=True,
    default=False,
    help="Show expired/archived contexts.",
)
def context_list(expired: bool):
    """List link contexts.

    By default shows active contexts (not archived). Use --expired to
    see archived/expired contexts instead.

    \b
    Examples:
      als context list
      als context list --expired
    """
    params: dict[str, str] = {"list": "true"}
    if expired:
        params["archived"] = "true"

    resp = _api_request("manage-contexts", method="GET", params=params)
    if resp.status_code != 200:
        click.echo(f"Error: {resp.json().get('error', resp.text)}", err=True)
        sys.exit(1)

    contexts = resp.json().get("contexts", [])

    if not contexts:
        label = "expired/archived" if expired else "active"
        click.echo(f"No {label} contexts found.")
        return

    label = "Expired/archived" if expired else "Active"
    click.echo(f"\n{label} contexts ({len(contexts)}):\n")

    for ctx in contexts:
        expires_str = ""
        if ctx.get("expires_at"):
            expires_str = f"  expires {ctx['expires_at'][:10]}"
        archived_str = ""
        if ctx.get("archived_at"):
            archived_str = f"  [archived {ctx['archived_at'][:10]}]"

        click.echo(
            f"  {click.style(ctx['id'], fg='magenta')}  "
            f"{click.style(ctx['label'], bold=True)}"
            f"{expires_str}{archived_str}"
        )
        click.echo(f"    slug: {ctx['slug']}  created: {ctx['created_at'][:10]}")

    click.echo()


@context_group.command("archive")
@click.argument("ctx_id")
def context_archive(ctx_id: str):
    """Archive a link context.

    Sets archived_at to now. Variants continue to redirect and log clicks.

    \b
    Examples:
      als context archive ctx-abc
    """
    resp = _api_request(
        "manage-contexts",
        json_body={"action": "archive", "ctx_id": ctx_id},
    )
    data = resp.json()
    if resp.status_code != 200:
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)

    ctx = data.get("context", {})
    click.echo(
        f"\nArchived: {click.style(ctx.get('label', ctx_id), bold=True)} ({ctx.get('id', '')})"
    )
    click.echo()


@cli.command()
@click.argument("slug_or_url")
def get(slug_or_url: str):
    """Get full details and tracking links for a single article.

    Fetches the article by slug, URL, or short ID and displays its details
    with your personalised tracking links for each channel.

    \b
    Examples:
      als get your-agent-my-agent
      als get https://trilogyai.substack.com/p/your-agent-my-agent
      als get lnk-edk
    """
    api_key = _get_api_key()

    if slug_or_url.startswith("lnk-"):
        resolved = _resolve_short_id(api_key, slug_or_url)
        if resolved is None:
            return
        slug_or_url = resolved

    payload: dict = {"article_url": slug_or_url}
    resp = _api_request("get-link", api_key=api_key, json_body=payload)

    if resp.status_code == 404:
        click.echo(f"Article not found: {slug_or_url}", err=True)
        sys.exit(1)
    if resp.status_code == 401:
        click.echo("Invalid API key. Run: als login --api-key <your-key>", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    article = data.get("article", {})
    links = data.get("links", [])

    title = article.get("title") or ""
    author = article.get("author", "")
    slug = article.get("slug", "")
    destination = article.get("url", "")
    published_at = article.get("published_at") or ""
    date_str = published_at[:10] if published_at else ""

    click.echo(f"\n{click.style(title or slug, bold=True)}")
    if author:
        click.echo(f"  by {author}")
    if date_str:
        click.echo(f"  Published: {date_str}")
    if destination:
        click.echo(f"  URL: {destination}")
    click.echo(f"  Short: https://aicoe.fit/{slug}")

    if links:
        click.echo(f"\n  Your tracking links:")
        for link in links:
            label = link.get("label") or link.get("source", "")
            click.echo(f"    {label:12s}  {link['short_url']}")
    else:
        click.echo(f"\n  No tracking links found.")

    click.echo()


def _resolve_short_id(api_key: str, short_id: str) -> str | None:
    """Resolve a short ID prefix to a slug.

    Uses server-side lookup via get-link?id_prefix=... endpoint.
    Returns the slug if unique match, None if ambiguous or not found.
    """
    resp = _api_request("get-link", api_key=api_key, json_body={"id_prefix": short_id})

    if resp.status_code == 404:
        data = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        click.echo(
            f"{data.get('error', f'No article found with ID starting with {short_id}')}",
            err=True,
        )
        return None

    if resp.status_code == 400:
        data = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        matches = data.get("matches", [])
        total = data.get("total", len(matches))
        click.echo(f"Ambiguous ID '{short_id}' matches {total} articles:", err=True)
        click.echo(err=True)
        ids = [m.get("id", "") for m in matches]
        short_id_map = _compute_short_ids(ids)
        for m in matches:
            full_id = m.get("id", "")
            display_id = short_id_map.get(full_id, full_id[:10])
            title = m.get("title") or m.get("slug", "")
            click.echo(f"  {display_id}  {title[:50]}", err=True)
        if total > len(matches):
            click.echo(f"  ... ({total - len(matches)} more)", err=True)
        click.echo(err=True)
        click.echo("Use more characters to disambiguate.", err=True)
        return None

    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        return None

    data = resp.json()
    article = data.get("article", {})
    return article.get("slug", "")


@cli.command()
@click.argument("query")
@click.option("--count", default=3, help="Number of results to return")
@click.option(
    "--source",
    type=click.Choice(["aifs", "blog", "both"], case_sensitive=False),
    default="both",
    help="Filter by content source: aifs (AI-First Show videos), blog (AI COE blog posts), or both (default).",
)
@click.option(
    "--me",
    "filter_me",
    is_flag=True,
    default=False,
    help=(
        "Filter results to articles written by you. "
        "Uses cached author name (see als set-author-name) or auto-resolves via API."
    ),
)
@click.option(
    "--tracking",
    is_flag=True,
    default=False,
    help="Include tracking links for each result (makes one batch API call).",
)
def search(query: str, count: int, source: str, filter_me: bool, tracking: bool):
    """Search articles by semantic similarity.

    Returns a compact table of matching articles ranked by relevance.
    Use `als get <lnk-xxx>` to see full details and tracking links for a result.

    Use --source to filter by content type:
    - aifs: AI-First Show YouTube videos only
    - blog: AI COE blog posts only
    - both: All content (default)

    Use --me to filter to your own articles:

        als search "Claude 4" --me

    Use --tracking to include your tracking links (one batch call, no N+1):

        als search "AI agents" --tracking
    """
    api_key = _get_api_key() if tracking or filter_me else ""

    author_filter: str | None = None
    if filter_me:
        author_filter = _resolve_my_author_name(api_key)
        if not author_filter:
            click.echo(
                "Could not determine your author name. "
                "Make sure you are logged in and have articles in the database.",
                err=True,
            )
            sys.exit(1)

    search_body: dict = {"query": query, "match_count": count}
    if author_filter:
        search_body["author"] = author_filter
    if source != "both":
        content_type = "video" if source == "aifs" else "article"
        search_body["content_type"] = content_type
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
        if filter_me:
            click.echo(f"No matching articles found for you ({author_filter}).")
        else:
            click.echo("No matching articles found.")
        return

    ids = [r.get("id", "") for r in results if r.get("id")]
    short_id_map = _compute_short_ids(ids)

    tracking_data: dict[str, dict] = {}
    if tracking:
        slugs = [r.get("slug", "") for r in results if r.get("slug")]
        if slugs:
            batch_resp = _api_request(
                "batch-get-links",
                api_key=api_key,
                json_body={"slugs": slugs},
            )
            if batch_resp.status_code == 200:
                tracking_data = batch_resp.json().get("results", {})

    click.echo(f"\nSearch results for: {click.style(query, bold=True)}\n")

    click.echo(
        f"  {'ID':<12s} {'Title':<42s} {'Author':<17s} {'Score':>5s}  {'Date':<10s}"
    )
    click.echo(f"  {'─' * 12} {'─' * 42} {'─' * 17} {'─' * 5}  {'─' * 10}")

    for result in results:
        full_id = result.get("id", "")
        short_id = short_id_map.get(full_id, full_id[:10]) if full_id else ""
        title = result.get("title", result.get("slug", ""))
        author = result.get("author", "")
        similarity = result.get("similarity", 0)
        published_at = result.get("published_at") or result.get("created_at", "")
        date_str = published_at[:10] if published_at else ""
        slug = result.get("slug", "")

        if len(title) > 40:
            title = title[:39] + "…"
        if len(author) > 15:
            author = author[:14] + "…"

        id_display = (
            click.style(f"{short_id:<12s}", fg="magenta") if short_id else f"{'':<12s}"
        )
        click.echo(
            f"  {id_display} {title:<42s} {author:<17s} {similarity:5.2f}  {date_str:<10s}"
        )

        if tracking and slug in tracking_data:
            links = tracking_data[slug].get("links", [])
            for link in links:
                label = link.get("label") or link.get("source", "")
                click.echo(f"    {label:12s}  {link['short_url']}")

    click.echo()
    if not tracking:
        click.echo("  Use `als get <lnk-xxx>` to see full details and tracking links.")
        click.echo("  Or use --tracking to include tracking links in results.")


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
@click.option(
    "--summary",
    is_flag=True,
    default=False,
    help="Show compact table instead of full details with tracking links.",
)
def last(n: int, author: str | None, filter_me: bool, summary: bool):
    """Show the last N articles with your personalised tracking links.

    N defaults to 10. Shows the most recently published articles in the
    database, with your personalised tracking link for each one.

    Uses a batch API call for tracking links (no N+1 queries).

    Use --author to filter to a specific author, e.g.:

        als last 5 --author "Simon"

    Use --me to filter to your own articles automatically:

        als last 5 --me
    """
    api_key = _get_api_key()

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

    if summary:
        _print_summary_table(results, filter_me, author)
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

    slugs = [r.get("slug", "") for r in results if r.get("slug")]
    tracking_data: dict[str, dict] = {}

    if slugs:
        batch_resp = _api_request(
            "batch-get-links",
            api_key=api_key,
            json_body={"slugs": slugs},
        )
        if batch_resp.status_code == 200:
            tracking_data = batch_resp.json().get("results", {})

    for i, result in enumerate(results, 1):
        title = result.get("title") or result.get("slug", "")
        article_author = result.get("author", "")
        slug = result.get("slug", "")
        published_at = result.get("published_at") or result.get("created_at", "")
        destination_url = result.get("url", "")
        date_str = published_at[:10] if published_at else ""

        click.echo(f"  {i}. {click.style(title, bold=True)}")
        if article_author:
            click.echo(f"     by {article_author}")
        if date_str:
            click.echo(f"     {date_str}")
        if destination_url:
            click.echo(f"     URL:  {destination_url}")

        if slug in tracking_data:
            links = tracking_data[slug].get("links", [])
            for link in links:
                label = link.get("label") or link.get("source", "")
                click.echo(f"     {label:12s}  {link['short_url']}")
        else:
            click.echo(f"     (could not generate tracking link)")

    click.echo()


def _print_summary_table(results: list, filter_me: bool, author: str | None):
    """Print a compact summary table of articles with short IDs."""
    term_width = shutil.get_terminal_size(fallback=(100, 24)).columns

    ids = [r.get("id", "") for r in results if r.get("id")]
    short_id_map = _compute_short_ids(ids)

    col_widths = {
        "id": 10,
        "title": max(10, min(36, term_width // 5)),
        "author": max(8, min(18, term_width // 10)),
        "date": 10,
        "url": max(10, min(45, term_width // 5)),
    }

    header = (
        f"{'ID':<{col_widths['id']}}  "
        f"{'Title':<{col_widths['title']}}  "
        f"{'Author':<{col_widths['author']}}  "
        f"{'Date':<{col_widths['date']}}  "
        f"{'URL':<{col_widths['url']}}"
    )
    click.echo()
    click.echo(click.style(header, bold=True))
    click.echo("─" * min(len(header), term_width))

    def truncate(s: str, max_len: int) -> str:
        if len(s) > max_len:
            return s[: max_len - 1] + "…"
        return s

    for result in results:
        full_id = result.get("id", "")
        short_id = short_id_map.get(full_id, full_id[:10]) if full_id else ""
        title = result.get("title") or result.get("slug", "")
        article_author = result.get("author", "")
        published_at = result.get("published_at") or result.get("created_at", "")
        destination_url = result.get("url", "")
        date_str = published_at[:10] if published_at else ""

        row = (
            f"{short_id:<{col_widths['id']}}  "
            f"{truncate(title, col_widths['title']):<{col_widths['title']}}  "
            f"{truncate(article_author, col_widths['author']):<{col_widths['author']}}  "
            f"{date_str:<{col_widths['date']}}  "
            f"{truncate(destination_url, col_widths['url']):<{col_widths['url']}}"
        )
        click.echo(row)

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

    ids = [r.get("id", "") for r in results if r.get("id")]
    short_id_map = _compute_short_ids(ids)

    label = "all" if show_all else str(len(results))
    click.echo(
        f"\nCustom links for {click.style(person.get('name', ''), bold=True)}"
        f" ({label}):\n"
    )

    for result in results:
        full_id = result.get("id", "")
        short_id = short_id_map.get(full_id, full_id[:10]) if full_id else ""
        url = result.get("url", "")
        slug = result.get("slug", "")
        created_at = result.get("created_at", "")
        date_str = created_at[:10] if created_at else ""
        links = result.get("links", [])

        id_display = click.style(short_id, fg="magenta") if short_id else ""
        click.echo(f"  {id_display}  {click.style(url, bold=True)}")
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
@click.argument("ids", nargs=-1, required=False)
@click.option(
    "--comment",
    default="",
    help="Optional comment with your vote.",
)
@click.option(
    "--item",
    default="",
    help="Vote on an existing submission by its short ID (e.g., aifs-c6u).",
)
@click.option(
    "--archived",
    is_flag=True,
    default=False,
    help="Show archived submissions only.",
)
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    default=False,
    help="Show all submissions (active and archived).",
)
@click.option(
    "--note",
    default="",
    help="Archive note (required for archive action).",
)
@click.option(
    "--before",
    "before_date",
    default="",
    help="Archive all submissions before this date (YYYY-MM-DD).",
)
@click.option(
    "--archive-all",
    is_flag=True,
    default=False,
    help="Archive all active submissions.",
)
def aifs(
    url_or_action: str | None,
    ids: tuple[str, ...],
    comment: str,
    item: str,
    archived: bool,
    show_all: bool,
    note: str,
    before_date: str,
    archive_all: bool,
):
    """AI First Show episode candidate submission and voting.

    Submit URLs as candidates for the next AI First Show episode,
    vote on existing submissions, and view current rankings.

    \b
    Examples:
      als aifs https://example.com/article            # submit/vote
      als aifs https://example.com --comment '...'    # with comment
      als aifs --item aifs-c6u --comment '...'        # vote by short ID
      als aifs list                                   # show active candidates
      als aifs list --archived                        # show archived only
      als aifs list --all                             # show all
      als aifs archive aifs-c6u aifs-j0p --note '...' # archive specific
      als aifs archive --before 2026-03-31 --note '...' # archive by date
      als aifs archive --archive-all --note '...'     # archive all active
      als aifs unarchive aifs-c6u                     # unarchive
    """
    if item:
        _aifs_submit(item, comment)
        return

    if not url_or_action:
        click.echo(click.get_current_context().get_help())
        raise SystemExit(1)

    if url_or_action == "list":
        filter_val = "all" if show_all else ("archived" if archived else "active")
        _aifs_list(filter_val)
        return

    if url_or_action == "archive":
        _aifs_archive(list(ids), note, before_date, archive_all)
        return

    if url_or_action == "unarchive":
        _aifs_unarchive(list(ids))
        return

    # Treat as a URL submission
    _aifs_submit(url_or_action, comment)


def _aifs_submit(url: str, comment: str):
    """Submit a URL as a candidate for the next AI First Show episode."""
    body: dict = {"action": "submit", "url": url}
    if comment:
        comment = re.sub(r"\\([?=&#])", r"\1", comment)
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
    short_id = data.get("short_id", "")

    if status == "submitted":
        click.echo(f"\n{click.style('Submitted!', fg='green', bold=True)}")
        click.echo(f"  URL: {url}")
        if short_id:
            click.echo(f"  ID:  {click.style(short_id, bold=True)}")
        click.echo(f"  This is the first vote for this URL.")
    elif status == "voted":
        click.echo(f"\n{click.style('Voted!', fg='green', bold=True)}")
        click.echo(f"  URL: {url}")
        if short_id:
            click.echo(f"  ID:  {click.style(short_id, bold=True)}")
        click.echo(f"  Your vote has been added to an existing submission.")
    elif status == "comment_added":
        click.echo(f"\n{click.style('Comment added!', fg='green', bold=True)}")
        click.echo(f"  URL: {url}")
        if short_id:
            click.echo(f"  ID:  {click.style(short_id, bold=True)}")
        click.echo(f"  You already voted — comment added separately.")
    elif status == "already_voted":
        click.echo(f"\n{click.style('Already voted', fg='yellow')}")
        click.echo(f"  URL: {url}")
        if short_id:
            click.echo(f"  ID:  {click.style(short_id, bold=True)}")
        click.echo(f"  You have already voted for this URL.")
        click.echo(f"  Tip: add --comment to attach a comment.")

    click.echo()


def _aifs_list(filter_val: str = "active"):
    """Show current AI First Show candidates sorted by vote count.

    Displays all submitted URLs with their vote counts, the submitter,
    and any comments from voters.

    \b
    Example:
      als aifs list              # active only (default)
      als aifs list --archived   # archived only
      als aifs list --all        # everything
    """
    resp = _api_request("aifs", json_body={"action": "list", "filter": filter_val})

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
    filter_label = {"active": "active", "archived": "archived", "all": "all"}
    label = filter_label.get(filter_val, "active")
    click.echo(
        f"\n{click.style('AI First Show', bold=True)} — {label} submissions "
        f"({total} submission{'s' if total != 1 else ''})\n"
    )

    for sub in submissions:
        vote_count = sub.get("vote_count", 0)
        url = sub.get("url", "")
        short_id = sub.get("short_id", "")
        voters = sub.get("voters", [])
        archived_at = sub.get("archived_at")
        archive_note = sub.get("archive_note")

        vote_str = f"{vote_count} vote{'s' if vote_count != 1 else ''}"
        id_str = click.style(short_id, fg="magenta") if short_id else ""

        if archived_at:
            archive_badge = click.style(
                f"[archived: {archive_note}]" if archive_note else "[archived]",
                fg="black",
                bold=True,
            )
            click.echo(
                f"  {id_str}  {click.style(vote_str, fg='cyan', bold=True)}  {url}  {archive_badge}"
            )
        else:
            click.echo(
                f"  {id_str}  {click.style(vote_str, fg='cyan', bold=True)}  {url}"
            )

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
            for v in other_voters:
                if v.get("comment"):
                    click.echo(
                        f'           → {v.get("person_ref", "?")}: "{v["comment"]}"'
                    )
                else:
                    click.echo(f"           → {v.get('person_ref', '?')}")

        click.echo()


def _aifs_archive(
    ids: list[str], note: str, before_date: str, archive_all: bool
) -> None:
    """Archive AI First Show submissions."""
    if not note:
        click.echo("Error: --note is required for archive action.", err=True)
        sys.exit(1)

    if archive_all:
        resp = _api_request("aifs", json_body={"action": "list", "filter": "active"})
        if resp.status_code != 200:
            click.echo(f"Error fetching submissions: {resp.text}", err=True)
            sys.exit(1)
        data = resp.json()
        submissions = data.get("submissions", [])
        ids = [s.get("short_id", "") for s in submissions if s.get("short_id")]
        if not ids:
            click.echo("No active submissions to archive.")
            return

    if not ids and not before_date:
        click.echo(
            "Error: provide IDs, --before, or --archive-all for archive action.",
            err=True,
        )
        sys.exit(1)

    body: dict = {"action": "archive", "note": note}
    if ids:
        body["ids"] = ids
    if before_date:
        body["before_date"] = before_date

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
    count = data.get("count", 0)
    archived_subs = data.get("submissions", [])

    click.echo(
        f"\n{click.style('Archived', fg='green', bold=True)} {count} submission(s):"
    )
    for sub in archived_subs:
        short_id = sub.get("short_id", "")
        if short_id:
            click.echo(f"  {click.style(short_id, fg='magenta')}")
    click.echo(f"  Note: {note}")
    click.echo()


def _aifs_unarchive(ids: list[str]) -> None:
    """Unarchive AI First Show submissions."""
    if not ids:
        click.echo("Error: provide IDs for unarchive action.", err=True)
        sys.exit(1)

    body: dict = {"action": "unarchive", "ids": ids}

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
    count = data.get("count", 0)
    unarchived_subs = data.get("submissions", [])

    click.echo(
        f"\n{click.style('Unarchived', fg='green', bold=True)} {count} submission(s):"
    )
    for sub in unarchived_subs:
        short_id = sub.get("short_id", "")
        if short_id:
            click.echo(f"  {click.style(short_id, fg='magenta')}")
    click.echo()


if __name__ == "__main__":
    cli()
