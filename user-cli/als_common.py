#!/usr/bin/env python3
"""Shared infrastructure for the aicoe.fit CLIs (``als`` and ``aifs``).

Credential storage, API-key resolution, and the Supabase edge-function
HTTP client used by both the ``als`` link shortener CLI and the ``aifs``
AI First Show CLI. Both binaries share ``~/.als.credentials``, so logging
in with either one authenticates both.
"""

import configparser
import os
import sys
from pathlib import Path

import click
import requests

CREDENTIALS_FILE = Path.home() / ".als.credentials"
API_BASE = "https://dumhbtxskncofwwzrmfx.supabase.co/functions/v1"

# Name of the binary the user invoked. Each CLI's entry group sets this so
# error messages suggest the right `<prog> login` command.
PROG = "als"


def login_hint() -> str:
    """Login instruction naming the binary the user actually invoked."""
    return f"Run: {PROG} login --api-key <your-key>"


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
    """Get the API key from env var, credentials file, or exit with an error."""
    api_key = os.environ.get("AICOE_API_KEY", "")
    if not api_key:
        creds = _read_credentials()
        api_key = creds.get("api_key", "")
    if not api_key:
        click.echo(f"Not logged in. {login_hint()}", err=True)
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
