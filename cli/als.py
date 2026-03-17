#!/usr/bin/env python3
"""User CLI for aicoe.fit link shortener."""

import configparser
import os
from pathlib import Path

import click
import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dumhbtxskncofwwzrmfx.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

CREDENTIALS_PATH = Path.home() / ".als.credentials"


def _save_credentials(api_key: str):
    """Save API key to ~/.als.credentials (INI format, chmod 0600)."""
    config = configparser.ConfigParser()
    config["default"] = {"api_key": api_key}
    with open(CREDENTIALS_PATH, "w") as f:
        config.write(f)
    CREDENTIALS_PATH.chmod(0o600)


def _load_api_key() -> str:
    """Load API key from credentials file."""
    if not CREDENTIALS_PATH.exists():
        raise click.ClickException(
            "Not logged in. Run: als login --api-key YOUR_KEY"
        )
    config = configparser.ConfigParser()
    config.read(CREDENTIALS_PATH)
    api_key = config.get("default", "api_key", fallback=None)
    if not api_key:
        raise click.ClickException(
            "No api_key found in credentials. Run: als login --api-key YOUR_KEY"
        )
    return api_key


def _edge_function(function_name: str, payload: dict) -> dict:
    """POST to a Supabase edge function."""
    url = f"{SUPABASE_URL}/functions/v1/{function_name}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


@click.group()
def cli():
    """aicoe.fit link shortener user CLI."""
    pass


@cli.command()
@click.option("--api-key", required=True, help="Your API key (als_...)")
def login(api_key: str):
    """Save your API key to ~/.als.credentials."""
    _save_credentials(api_key)
    click.echo(f"Saved API key to {CREDENTIALS_PATH}")


@cli.command()
def whoami():
    """Show your identity based on stored API key."""
    api_key = _load_api_key()
    # Query Supabase REST API directly to find person by api_key
    url = f"{SUPABASE_URL}/rest/v1/people"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }
    params = {"api_key": f"eq.{api_key}", "select": "name,slug"}
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        click.echo("No person found for this API key.")
        return
    person = data[0]
    click.echo(f"Name: {person['name']}")
    click.echo(f"Slug: {person['slug']}")


@cli.command()
@click.argument("url")
def shorten(url: str):
    """Get your personalized short link for a URL."""
    api_key = _load_api_key()
    try:
        result = _edge_function("get-link", {"api_key": api_key, "url": url})
    except requests.HTTPError as e:
        if e.response is not None:
            try:
                detail = e.response.json().get("error", e.response.text)
            except Exception:
                detail = e.response.text
            raise click.ClickException(detail)
        raise
    click.echo(result["short_url"])
    if result.get("title"):
        click.echo(f"  Title: {result['title']}")
    if result.get("author"):
        click.echo(f"  Author: {result['author']}")


@cli.command()
@click.argument("query")
def search(query: str):
    """Search articles by semantic similarity. Prints top 3 results."""
    api_key = _load_api_key()
    try:
        result = _edge_function(
            "search-articles",
            {"query": query, "match_count": 3, "api_key": api_key},
        )
    except requests.HTTPError as e:
        if e.response is not None:
            try:
                detail = e.response.json().get("error", e.response.text)
            except Exception:
                detail = e.response.text
            raise click.ClickException(detail)
        raise

    results = result.get("results", [])
    if not results:
        click.echo("No results found.")
        return

    for i, article in enumerate(results, 1):
        title = article.get("title", article.get("slug", "?"))
        slug = article.get("slug", "")
        similarity = article.get("similarity", 0)
        click.echo(f"{i}. {title}")
        click.echo(f"   slug: {slug}  (similarity: {similarity:.3f})")


if __name__ == "__main__":
    cli()
