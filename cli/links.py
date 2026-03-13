#!/usr/bin/env python3
"""CLI admin tool for aicoe.fit link shortener."""

import hashlib
import os

import click
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
DOMAIN = "aicoe.fit"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def make_suffix(*parts: str | None) -> str:
    """Deterministic short base36 hash of UTM param values."""
    combined = "|".join(p or "" for p in parts)
    h = hashlib.sha256(combined.encode()).hexdigest()
    # Convert first 6 hex chars to base36 for a short suffix
    num = int(h[:8], 16)
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    result = ""
    while num:
        result = chars[num % 36] + result
        num //= 36
    return result[:4] or "0"


@click.group()
def cli():
    """aicoe.fit link shortener admin CLI."""
    pass


@cli.command()
@click.option("--slug", required=True, help="Short slug, e.g. cursor-mar26")
@click.option("--url", required=True, help="Destination URL")
def create_link(slug: str, url: str):
    """Create a new short link."""
    result = (
        supabase.table("links").insert({"slug": slug, "destination_url": url}).execute()
    )
    link = result.data[0]
    click.echo(f"Created: https://{DOMAIN}/{link['slug']}")
    click.echo(f"  -> {link['destination_url']}")
    click.echo(f"  ID: {link['id']}")


@cli.command()
@click.option("--slug", required=True, help="Slug of existing link")
@click.option("--utm-source", default=None, help="utm_source value")
@click.option("--utm-medium", default=None, help="utm_medium value")
@click.option("--utm-campaign", default=None, help="utm_campaign value")
@click.option("--utm-content", default=None, help="utm_content value")
@click.option("--utm-term", default=None, help="utm_term value")
@click.option("--ref", default=None, help="ref value")
def create_variant(
    slug: str,
    utm_source: str | None,
    utm_medium: str | None,
    utm_campaign: str | None,
    utm_content: str | None,
    utm_term: str | None,
    ref: str | None,
):
    """Add a tracking variant to an existing link."""
    # Look up the link
    link_result = (
        supabase.table("links").select("id").eq("slug", slug).single().execute()
    )
    link_id = link_result.data["id"]

    # Generate deterministic suffix
    suffix = make_suffix(
        utm_source, utm_medium, utm_campaign, utm_content, utm_term, ref
    )

    # Check for collision
    existing = (
        supabase.table("tracking_variants").select("id").eq("suffix", suffix).execute()
    )
    if existing.data:
        click.echo(f"Variant with suffix '{suffix}' already exists.")
        return

    row = {
        "link_id": link_id,
        "suffix": suffix,
        "utm_source": utm_source,
        "utm_medium": utm_medium,
        "utm_campaign": utm_campaign,
        "utm_content": utm_content,
        "utm_term": utm_term,
        "ref": ref,
    }
    # Remove None values
    row = {k: v for k, v in row.items() if v is not None}
    row["link_id"] = link_id
    row["suffix"] = suffix

    result = supabase.table("tracking_variants").insert(row).execute()
    variant = result.data[0]
    click.echo(f"Created variant: https://{DOMAIN}/{slug}-{suffix}")
    click.echo(f"  suffix: {suffix}")
    click.echo(f"  utm_source: {utm_source}")
    click.echo(f"  utm_medium: {utm_medium}")
    click.echo(f"  utm_campaign: {utm_campaign}")
    if utm_content:
        click.echo(f"  utm_content: {utm_content}")
    if utm_term:
        click.echo(f"  utm_term: {utm_term}")
    if ref:
        click.echo(f"  ref: {ref}")


@cli.command()
def list_links():
    """Show all links and their variants."""
    links = supabase.table("links").select("*").order("created_at", desc=True).execute()

    if not links.data:
        click.echo("No links found.")
        return

    for link in links.data:
        click.echo(f"\n{click.style(link['slug'], bold=True)}")
        click.echo(f"  URL: {link['destination_url']}")
        click.echo(f"  Short: https://{DOMAIN}/{link['slug']}")
        click.echo(f"  Created: {link['created_at']}")

        variants = (
            supabase.table("tracking_variants")
            .select("*")
            .eq("link_id", link["id"])
            .order("created_at")
            .execute()
        )

        if variants.data:
            click.echo(f"  Variants ({len(variants.data)}):")
            for v in variants.data:
                parts = []
                if v.get("utm_source"):
                    parts.append(f"source={v['utm_source']}")
                if v.get("utm_medium"):
                    parts.append(f"medium={v['utm_medium']}")
                if v.get("utm_campaign"):
                    parts.append(f"campaign={v['utm_campaign']}")
                if v.get("ref"):
                    parts.append(f"ref={v['ref']}")
                params = ", ".join(parts)
                click.echo(f"    -{v['suffix']}  ({params})")
                click.echo(f"      https://{DOMAIN}/{link['slug']}-{v['suffix']}")
        else:
            click.echo("  No variants.")


@cli.command()
@click.option("--slug", required=True, help="Slug of existing link")
@click.option("--utm-source", required=True, help="utm_source value")
@click.option("--utm-medium", required=True, help="utm_medium value")
@click.option(
    "--utm-campaign", default=None, help="utm_campaign value (defaults to slug)"
)
def generate_all(slug: str, utm_source: str, utm_medium: str, utm_campaign: str | None):
    """Generate tracking variants for all people on a link."""
    # Look up the link
    link_result = (
        supabase.table("links").select("id").eq("slug", slug).single().execute()
    )
    link_id = link_result.data["id"]
    campaign = utm_campaign or slug

    # Get all people
    people = supabase.table("people").select("*").order("name").execute()
    if not people.data:
        click.echo("No people configured.")
        return

    click.echo(f"Generating variants for {click.style(slug, bold=True)}:\n")

    for person in people.data:
        ref = person["slug"]
        suffix = make_suffix(utm_source, utm_medium, campaign, None, None, ref)

        # Check if already exists
        existing = (
            supabase.table("tracking_variants")
            .select("id")
            .eq("suffix", suffix)
            .execute()
        )
        if existing.data:
            click.echo(
                f"  {person['name']:10s}  (already exists) https://{DOMAIN}/{slug}-{suffix}"
            )
            continue

        row = {
            "link_id": link_id,
            "suffix": suffix,
            "utm_source": utm_source,
            "utm_medium": utm_medium,
            "utm_campaign": campaign,
            "ref": ref,
        }
        supabase.table("tracking_variants").insert(row).execute()
        click.echo(f"  {person['name']:10s}  https://{DOMAIN}/{slug}-{suffix}")

    click.echo(f"\nDone.")


@cli.command()
def list_people():
    """Show all configured people."""
    people = supabase.table("people").select("*").order("name").execute()
    if not people.data:
        click.echo("No people configured.")
        return

    click.echo("Configured people:")
    for p in people.data:
        click.echo(f"  {p['name']} ({p['slug']})")


@cli.command()
@click.option("--name", required=True, help="Display name")
@click.option("--person-slug", required=True, help="Lowercase slug for ref param")
def add_person(name: str, person_slug: str):
    """Add a new person to the config."""
    supabase.table("people").insert({"name": name, "slug": person_slug}).execute()
    click.echo(f"Added: {name} ({person_slug})")


@cli.command()
@click.option("--slug", default=None, help="Filter by link slug")
@click.option("--days", default=7, help="Number of days to look back")
def click_stats(slug: str | None, days: int):
    """Show click statistics."""
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    if slug:
        # Get link ID
        link_result = (
            supabase.table("links")
            .select("id, slug, destination_url")
            .eq("slug", slug)
            .single()
            .execute()
        )
        link = link_result.data
        link_ids = [link["id"]]
        click.echo(f"\nStats for {click.style(slug, bold=True)} (last {days} days)")
        click.echo(f"  URL: {link['destination_url']}")
    else:
        links_result = (
            supabase.table("links").select("id, slug, destination_url").execute()
        )
        link_ids = [l["id"] for l in links_result.data]
        click.echo(f"\nAll link stats (last {days} days)")

    # Get clicks
    query = (
        supabase.table("click_log")
        .select("id, link_id, variant_id, clicked_at")
        .gte("clicked_at", since)
    )
    if slug:
        query = query.eq("link_id", link_ids[0])

    clicks = query.order("clicked_at", desc=True).execute()

    if not clicks.data:
        click.echo("  No clicks in this period.")
        return

    click.echo(f"  Total clicks: {len(clicks.data)}")

    # Group by link
    by_link: dict[str, list] = {}
    for c in clicks.data:
        by_link.setdefault(c["link_id"], []).append(c)

    # Get all links and variants for display
    all_links = supabase.table("links").select("id, slug").execute()
    link_map = {l["id"]: l["slug"] for l in all_links.data}

    all_variants = (
        supabase.table("tracking_variants")
        .select("id, suffix, utm_source, ref")
        .execute()
    )
    variant_map = {v["id"]: v for v in all_variants.data}

    for lid, link_clicks in by_link.items():
        slug_name = link_map.get(lid, lid)
        click.echo(
            f"\n  {click.style(slug_name, bold=True)}: {len(link_clicks)} clicks"
        )

        # Group by variant
        by_variant: dict[str | None, int] = {}
        for c in link_clicks:
            vid = c.get("variant_id")
            by_variant[vid] = by_variant.get(vid, 0) + 1

        for vid, count in sorted(by_variant.items(), key=lambda x: -x[1]):
            if vid is None:
                click.echo(f"    direct (no variant): {count}")
            else:
                v = variant_map.get(vid, {})
                label = v.get("suffix", vid)
                source = v.get("utm_source", "")
                ref = v.get("ref", "")
                extra = f" ({source}, ref={ref})" if source or ref else ""
                click.echo(f"    -{label}{extra}: {count}")


@cli.command()
@click.option(
    "--substack-url",
    default="https://trilogyai.substack.com",
    help="Substack publication URL",
)
@click.option("--utm-source", default="linkedin", help="Default utm_source")
@click.option("--utm-medium", default="social", help="Default utm_medium")
@click.option(
    "--generate-variants/--no-generate-variants",
    default=True,
    help="Auto-generate variants for all people",
)
@click.option("--dry-run/--no-dry-run", default=False, help="Preview without creating")
def import_substack(
    substack_url: str,
    utm_source: str,
    utm_medium: str,
    generate_variants: bool,
    dry_run: bool,
):
    """Import all articles from a Substack publication."""
    import xml.etree.ElementTree as ET

    import requests

    # Fetch sitemap for complete article list
    sitemap_url = f"{substack_url}/sitemap.xml"
    click.echo(f"Fetching sitemap from {sitemap_url}...")
    resp = requests.get(sitemap_url, timeout=30)
    resp.raise_for_status()

    tree = ET.fromstring(resp.content)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = tree.findall(".//s:url/s:loc", ns)
    post_urls = [u.text for u in urls if u.text and "/p/" in u.text]

    click.echo(f"Found {len(post_urls)} articles in sitemap.")

    # Fetch RSS feed for titles of recent articles
    feed_url = f"{substack_url}/feed"
    click.echo(f"Fetching RSS feed for article titles...")
    import feedparser

    feed = feedparser.parse(feed_url)
    title_map: dict[str, str] = {}
    for entry in feed.entries:
        # Extract slug from link
        link = entry.get("link", "")
        if "/p/" in link:
            slug = link.split("/p/")[-1].rstrip("/")
            title_map[slug] = entry.get("title", slug)

    # Get existing links to avoid duplicates
    existing = supabase.table("links").select("slug").execute()
    existing_slugs = {l["slug"] for l in existing.data}

    # Get people for variant generation
    people = []
    if generate_variants:
        people_result = supabase.table("people").select("*").order("name").execute()
        people = people_result.data or []

    created = 0
    skipped = 0

    for post_url in post_urls:
        # Derive slug from URL: https://trilogyai.substack.com/p/some-article -> some-article
        substack_slug = post_url.split("/p/")[-1].rstrip("/")

        # Use title from RSS if available, otherwise use slug
        title = title_map.get(substack_slug, substack_slug)

        if substack_slug in existing_slugs:
            skipped += 1
            continue

        if dry_run:
            click.echo(f"  [DRY RUN] Would create: {substack_slug} -> {post_url}")
            click.echo(f"    Title: {title}")
            created += 1
            continue

        # Create the link
        try:
            result = (
                supabase.table("links")
                .insert({"slug": substack_slug, "destination_url": post_url})
                .execute()
            )
            link_id = result.data[0]["id"]
            existing_slugs.add(substack_slug)
            created += 1

            click.echo(f"  Created: {substack_slug}")
            click.echo(f"    {title}")
            click.echo(f"    https://{DOMAIN}/{substack_slug}")

            # Generate variants for all people
            if generate_variants and people:
                campaign = substack_slug
                for person in people:
                    ref = person["slug"]
                    suffix = make_suffix(
                        utm_source, utm_medium, campaign, None, None, ref
                    )

                    # Check for suffix collision
                    dup = (
                        supabase.table("tracking_variants")
                        .select("id")
                        .eq("suffix", suffix)
                        .execute()
                    )
                    if dup.data:
                        continue

                    row = {
                        "link_id": link_id,
                        "suffix": suffix,
                        "utm_source": utm_source,
                        "utm_medium": utm_medium,
                        "utm_campaign": campaign,
                        "ref": ref,
                    }
                    supabase.table("tracking_variants").insert(row).execute()

                click.echo(f"    Generated {len(people)} variants")
        except Exception as e:
            click.echo(f"  ERROR creating {substack_slug}: {e}", err=True)

    click.echo(f"\nDone. Created: {created}, Skipped (existing): {skipped}")


@cli.command()
@click.option(
    "--substack-url",
    default="https://trilogyai.substack.com",
    help="Substack publication URL",
)
@click.option("--utm-source", default="linkedin", help="Default utm_source")
@click.option("--utm-medium", default="social", help="Default utm_medium")
def sync_substack(substack_url: str, utm_source: str, utm_medium: str):
    """Check for new Substack articles and create links for them.

    This is the same as import-substack but designed to be run
    repeatedly (e.g. via cron). Only creates links for new articles.
    """
    import xml.etree.ElementTree as ET

    import requests

    # Fetch sitemap
    resp = requests.get(f"{substack_url}/sitemap.xml", timeout=30)
    resp.raise_for_status()

    tree = ET.fromstring(resp.content)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = tree.findall(".//s:url/s:loc", ns)
    post_urls = [u.text for u in urls if u.text and "/p/" in u.text]

    # Get existing links
    existing = supabase.table("links").select("slug").execute()
    existing_slugs = {l["slug"] for l in existing.data}

    # Find new articles
    new_urls = [
        u for u in post_urls if u.split("/p/")[-1].rstrip("/") not in existing_slugs
    ]

    if not new_urls:
        click.echo("No new articles found.")
        return

    click.echo(f"Found {len(new_urls)} new article(s).")

    # Get RSS feed for titles
    import feedparser

    feed = feedparser.parse(f"{substack_url}/feed")
    title_map: dict[str, str] = {}
    for entry in feed.entries:
        link = entry.get("link", "")
        if "/p/" in link:
            slug = link.split("/p/")[-1].rstrip("/")
            title_map[slug] = entry.get("title", slug)

    # Get people
    people_result = supabase.table("people").select("*").order("name").execute()
    people = people_result.data or []

    for post_url in new_urls:
        substack_slug = post_url.split("/p/")[-1].rstrip("/")
        title = title_map.get(substack_slug, substack_slug)

        try:
            result = (
                supabase.table("links")
                .insert({"slug": substack_slug, "destination_url": post_url})
                .execute()
            )
            link_id = result.data[0]["id"]

            click.echo(f"  Created: {substack_slug} - {title}")

            # Generate variants
            campaign = substack_slug
            for person in people:
                ref = person["slug"]
                suffix = make_suffix(utm_source, utm_medium, campaign, None, None, ref)
                dup = (
                    supabase.table("tracking_variants")
                    .select("id")
                    .eq("suffix", suffix)
                    .execute()
                )
                if dup.data:
                    continue
                row = {
                    "link_id": link_id,
                    "suffix": suffix,
                    "utm_source": utm_source,
                    "utm_medium": utm_medium,
                    "utm_campaign": campaign,
                    "ref": ref,
                }
                supabase.table("tracking_variants").insert(row).execute()

            click.echo(f"    + {len(people)} variants")
        except Exception as e:
            click.echo(f"  ERROR: {e}", err=True)

    click.echo("Sync complete.")


if __name__ == "__main__":
    cli()
