#!/usr/bin/env python3
"""AI First Show (AIFS) episode candidate CLI.

Submit URLs as candidates for the next AI First Show episode, vote on
existing submissions, view rankings, and manage the archive. Shares
credentials (~/.als.credentials) and the Supabase backend with the
``als`` link shortener CLI — logging in with either authenticates both.
"""

import json
import re
import sys
from importlib.metadata import version as _pkg_version

import click

import als_common
from als_common import CREDENTIALS_FILE, _api_request, _write_credentials, login_hint

# Distributed in the same package as the als CLI.
__version__ = _pkg_version("als")


def _auth_error() -> None:
    click.echo(f"Invalid API key. {login_hint()}", err=True)
    sys.exit(1)


class AifsGroup(click.Group):
    """Click group that treats a URL first argument as ``submit``.

    Preserves the muscle memory of ``als aifs <url>``: running
    ``aifs https://...`` behaves like ``aifs submit https://...``.
    """

    def resolve_command(self, ctx, args):
        if args and args[0].startswith(("http://", "https://")):
            return "submit", self.get_command(ctx, "submit"), args
        return super().resolve_command(ctx, args)


@click.group(cls=AifsGroup)
@click.version_option(version=__version__, prog_name="aifs")
def cli():
    """AI First Show — episode candidate submission and voting.

    Submit URLs as candidates for the next AI First Show episode,
    vote on existing submissions, and view current rankings.

    \b
    Usage:
      First time:  aifs login --api-key <key>   # shared with the als CLI
      Submit:      aifs submit <url> --comment "Great overview of RAG"
                   aifs <url>                   # shorthand for submit
      Vote:        aifs vote aifs-c6u --comment "Strong reasoning results"
      Rankings:    aifs list
      Tags:        aifs submit <url> --tag model-release
                   aifs list --tag model-release
      Archive:     aifs archive aifs-c6u --note "Covered in episode 42"
      Unarchive:   aifs unarchive aifs-c6u
      Episodes:    aifs episodes

    \b
    Acting for a Discord user (agents/bots):
      aifs submit https://... --as 442587729172234252
      aifs list --as 442587729172234252

    \b
    Machine-readable output:
      aifs list --json
      aifs episodes --json
    """
    als_common.PROG = "aifs"


@cli.command()
@click.option("--api-key", required=True, help="Your personal API key (als_...)")
def login(api_key: str):
    """Save your API key for future use (shared with the als CLI)."""
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
@click.argument("url")
@click.option("--comment", default="", help="Optional comment with your submission.")
@click.option(
    "--as",
    "discord_user",
    default="",
    help="Act as a Discord user (maps to a person via static config).",
)
@click.option(
    "--tag",
    "tags",
    multiple=True,
    help="Categorize this submission with a tag (e.g. model-release). Repeatable.",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    default=False,
    help="Output raw JSON instead of human-readable text.",
)
def submit(url: str, comment: str, discord_user: str, tags: tuple[str, ...], output_json: bool):
    """Submit a URL as a candidate for the next episode.

    The URL gets a short ID (aifs-xxx) and your vote is automatically
    counted. Submitting a URL that already exists adds your vote instead.

    \b
    Examples:
      aifs submit https://arxiv.org/abs/2501.12345
      aifs submit https://example.com --comment "Great overview of RAG"
      aifs submit https://... --tag model-release --tag agent-tooling
      aifs submit https://... --json | jq '.short_id'
    """
    _submit(url, comment, discord_user, output_json, tags=tags)


@cli.command()
@click.argument("item")
@click.option("--comment", default="", help="Optional comment with your vote.")
@click.option(
    "--as",
    "discord_user",
    default="",
    help="Act as a Discord user (maps to a person via static config).",
)
@click.option(
    "--tag",
    "tags",
    multiple=True,
    help="Add a tag to this submission (e.g. model-release). Repeatable.",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    default=False,
    help="Output raw JSON instead of human-readable text.",
)
def vote(item: str, comment: str, discord_user: str, tags: tuple[str, ...], output_json: bool):
    """Vote on an existing submission by its short ID (e.g., aifs-c6u).

    Use the short ID from aifs list.

    \b
    Examples:
      aifs vote aifs-c6u
      aifs vote aifs-c6u --comment "Strong reasoning results"
      aifs vote aifs-c6u --tag model-release
    """
    _submit(item, comment, discord_user, output_json, tags=tags)


@cli.command("list")
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
    "--as",
    "discord_user",
    default="",
    help="Act as a Discord user (maps to a person via static config).",
)
@click.option(
    "--tag",
    "tags",
    multiple=True,
    help="Filter submissions by tag (e.g. model-release). Repeatable (OR).",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    default=False,
    help="Output raw JSON instead of human-readable text.",
)
def list_cmd(archived: bool, show_all: bool, discord_user: str, tags: tuple[str, ...], output_json: bool):
    """Show current candidates sorted by vote count.

    Displays all submitted URLs with their vote counts, the submitter,
    and any comments from voters.

    \b
    Examples:
      aifs list              # active only (default)
      aifs list --archived   # archived only
      aifs list --all        # everything
      aifs list --tag model-release
      aifs list --json
    """
    filter_val = "all" if show_all else ("archived" if archived else "active")
    _list_submissions(filter_val, discord_user, output_json, tags=tags)


@cli.command()
@click.argument("ids", nargs=-1, required=False)
@click.option("--note", default="", help="Archive note (required).")
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
@click.option(
    "--as",
    "discord_user",
    default="",
    help="Act as a Discord user (maps to a person via static config).",
)
def archive(
    ids: tuple[str, ...],
    note: str,
    before_date: str,
    archive_all: bool,
    discord_user: str,
):
    """Archive submissions that were covered or are no longer relevant.

    \b
    Examples:
      aifs archive aifs-c6u --note "Covered in episode 42"
      aifs archive aifs-c6u aifs-j0p --note "Batch archive"
      aifs archive --before 2026-03-31 --note "Stale nominations"
      aifs archive --archive-all --note "Starting fresh"
    """
    _archive(list(ids), note, before_date, archive_all, discord_user)


@cli.command()
@click.argument("ids", nargs=-1, required=True)
@click.option(
    "--as",
    "discord_user",
    default="",
    help="Act as a Discord user (maps to a person via static config).",
)
def unarchive(ids: tuple[str, ...], discord_user: str):
    """Bring archived submissions back into active status.

    \b
    Example:
      aifs unarchive aifs-c6u
    """
    _unarchive(list(ids), discord_user)


@cli.command()
@click.option(
    "--as",
    "discord_user",
    default="",
    help="Act as a Discord user (maps to a person via static config).",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    default=False,
    help="Output raw JSON instead of human-readable text.",
)
def episodes(discord_user: str, output_json: bool):
    """List completed episodes parsed from archive notes.

    Shows which AIFS episodes are complete, parsed from archive notes
    that reference episode numbers (e.g., "Covered in episode 42").

    \b
    Examples:
      aifs episodes
      aifs episodes --json
    """
    _episodes(discord_user, output_json)


# ---------------------------------------------------------------------------
# Implementation (also called by the deprecated `als aifs` shim)
# ---------------------------------------------------------------------------


def _submit(url: str, comment: str, discord_user: str = "", output_json: bool = False, tags: tuple[str, ...] = ()):
    """Submit a URL as a candidate for the next AI First Show episode."""
    body: dict = {"action": "submit", "url": url}
    if comment:
        comment = re.sub(r"\\([?=&#])", r"\1", comment)
        body["comment"] = comment
    if discord_user:
        body["discord_user"] = discord_user
    if tags:
        body["tags"] = list(tags)

    resp = _api_request("aifs", json_body=body)

    if resp.status_code == 401:
        _auth_error()
    if resp.status_code == 400:
        data = resp.json()
        click.echo(f"Error: {data.get('error', resp.text)}", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()

    if output_json:
        click.echo(json.dumps(data, indent=2))
        return

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

    attached = data.get("tags") or []
    if attached:
        tag_str = ", ".join(t.get("slug", t.get("name", "")) for t in attached)
        click.echo(f"  Tags: {click.style(tag_str, fg='blue')}")

    click.echo()


def _list_submissions(
    filter_val: str = "active", discord_user: str = "", output_json: bool = False, tags: tuple[str, ...] = ()
):
    """Show current AI First Show candidates sorted by vote count."""
    body: dict = {"action": "list", "filter": filter_val}
    if discord_user:
        body["discord_user"] = discord_user
    if tags:
        body["tags"] = list(tags)
    resp = _api_request("aifs", json_body=body)

    if resp.status_code == 401:
        _auth_error()
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    submissions = data.get("submissions", [])

    if not submissions:
        if output_json:
            click.echo(json.dumps([]))
            return
        click.echo("\nNo submissions yet.")
        click.echo("Submit one with: aifs submit <url>")
        click.echo()
        return

    if output_json:
        click.echo(json.dumps(submissions, indent=2))
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

        sub_tags = sub.get("tags") or []
        if sub_tags:
            tag_str = " ".join(
                click.style(f"#{t.get('slug', t.get('name', ''))}", fg="blue")
                for t in sub_tags
            )
            click.echo(f"           {tag_str}")

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


def _archive(
    ids: list[str], note: str, before_date: str, archive_all: bool, discord_user: str = ""
) -> None:
    """Archive AI First Show submissions."""
    if not note:
        click.echo("Error: --note is required for archive action.", err=True)
        sys.exit(1)

    if archive_all:
        body: dict = {"action": "list", "filter": "active"}
        if discord_user:
            body["discord_user"] = discord_user
        resp = _api_request("aifs", json_body=body)
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
    if discord_user:
        body["discord_user"] = discord_user

    resp = _api_request("aifs", json_body=body)

    if resp.status_code == 401:
        _auth_error()
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


def _unarchive(ids: list[str], discord_user: str = "") -> None:
    """Unarchive AI First Show submissions."""
    if not ids:
        click.echo("Error: provide IDs for unarchive action.", err=True)
        sys.exit(1)

    body: dict = {"action": "unarchive", "ids": ids}
    if discord_user:
        body["discord_user"] = discord_user

    resp = _api_request("aifs", json_body=body)

    if resp.status_code == 401:
        _auth_error()
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


def _episodes(discord_user: str = "", output_json: bool = False):
    """List completed AIFS episodes with their submission counts and completion dates."""
    body: dict = {"action": "episodes"}
    if discord_user:
        body["discord_user"] = discord_user
    resp = _api_request("aifs", json_body=body)

    if resp.status_code == 401:
        _auth_error()
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    episodes = data.get("episodes", [])

    if not episodes:
        if output_json:
            click.echo(json.dumps([]))
            return
        click.echo("\nNo completed episodes found.")
        click.echo(
            "Archive submissions with episode notes to mark them complete:"
        )
        click.echo('  aifs archive aifs-xxx --note "Covered in episode 1"')
        click.echo()
        return

    if output_json:
        click.echo(json.dumps(episodes, indent=2))
        return

    total = data.get("total", len(episodes))
    click.echo(
        f"\n{click.style('AI First Show', bold=True)} — completed episodes "
        f"({total} episode{'s' if total != 1 else ''})\n"
    )

    for ep in episodes:
        ep_num = ep.get("episode_number")
        completed_at = ep.get("completed_at", "") or ""
        sub_count = ep.get("submission_count", 0)
        submissions = ep.get("submissions", [])

        ts_display = ""
        if completed_at:
            ts = completed_at.replace("T", " ").split(".")[0]
            ts_display = f"  {click.style(ts, fg='black', dim=True)}"

        click.echo(
            f"  {click.style(f'Episode {ep_num}', fg='cyan', bold=True)}"
            f"  {sub_count} submission{'s' if sub_count != 1 else ''}"
            f"{ts_display}"
        )

        for sub in submissions:
            short_id = sub.get("short_id", "")
            url = sub.get("url", "")
            id_str = click.style(short_id, fg="magenta") if short_id else ""
            click.echo(f"           {id_str}  {url}")


if __name__ == "__main__":
    cli()
