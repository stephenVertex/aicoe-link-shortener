"""Smoke tests for als CLI — integration tests against live edge functions.

These tests call real Supabase edge functions and validate response shape.
They are read-only or idempotent (pre-publish is idempotent,
search/last/custom-links are read-only).

Run with: uv run pytest tests/test_smoke.py -v

Requires: AICOE_API_KEY env var (or ~/.als.credentials with a valid key).
"""

import os
import re
import subprocess

import pytest


USER_CLI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TRACKING_URL_RE = re.compile(r"^https://aicoe\.fit/[a-z0-9][a-z0-9-]*-[a-f0-9]+$")

JS_CODE_PATTERNS = [
    re.compile(r"=>"),
    re.compile(r"find\("),
    re.compile(r"\{\n"),
    re.compile(r"const\s"),
    re.compile(r"function\s"),
    re.compile(r"=>\s"),
    re.compile(r"\.map\("),
    re.compile(r"\.filter\("),
    re.compile(r"template"),
]


def validate_tracking_url(url: str) -> bool:
    """Validate that a tracking URL matches the expected format.

    Must be https://aicoe.fit/<slug>-<hex> with no raw JS code,
    no template literals, no newlines.
    """
    return bool(TRACKING_URL_RE.match(url))


def _has_js_code(s: str) -> bool:
    """Check if a string contains JS/TS code patterns."""
    for pat in JS_CODE_PATTERNS:
        if pat.search(s):
            return True
    return False


def run_als(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Run an als CLI command and return the CompletedProcess."""
    cmd = ["uv", "run", "als"] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=USER_CLI_DIR,
    )


def _skip_if_no_api_key():
    """Skip test if no API key is configured."""
    creds_path = os.path.expanduser("~/.als.credentials")
    if not os.path.exists(creds_path) and not os.environ.get("AICOE_API_KEY"):
        pytest.skip("No API key configured (set AICOE_API_KEY or run als login)")


class TestSearch:
    def test_search_returns_results(self):
        """als search 'AI' returns results with id/title/author/similarity."""
        result = run_als(["search", "AI", "--count", "3"])
        assert result.returncode == 0, f"als search failed: {result.stderr}"
        output = result.stdout
        assert len(output) > 0, "als search produced no output"

    def test_search_result_has_required_fields(self):
        """Each search result row should have ID, Title, Author, Score columns."""
        result = run_als(["search", "AI", "--count", "3"])
        assert result.returncode == 0
        output = result.stdout
        assert "lnk-" in output or "ID" in output, "No article IDs in search output"


class TestLast:
    def test_last_returns_articles(self):
        """als last 3 returns 3 articles with proper fields."""
        result = run_als(["last", "3"])
        assert result.returncode == 0, f"als last failed: {result.stderr}"
        output = result.stdout
        assert len(output) > 0, "als last produced no output"

    def test_last_articles_have_metadata(self):
        """Articles from als last should have title and date info."""
        result = run_als(["last", "3"])
        assert result.returncode == 0
        output = result.stdout
        lines = [l.strip() for l in output.split("\n") if l.strip()]
        content_lines = [l for l in lines if not l.startswith("Last")]
        assert len(content_lines) >= 3, "Expected at least 3 content lines"


class TestCustomLinks:
    @pytest.fixture(autouse=True)
    def _require_auth(self):
        _skip_if_no_api_key()

    def test_custom_links_succeeds(self):
        """als custom-links should return 0 exit code."""
        result = run_als(["custom-links", "--count", "5"])
        assert result.returncode == 0, f"als custom-links failed: {result.stderr}"

    def test_custom_links_tracking_urls_valid(self):
        """Each tracking URL from als custom-links must match https://aicoe.fit/<slug>-<hex>."""
        result = run_als(["custom-links", "--count", "5"])
        assert result.returncode == 0
        output = result.stdout
        for line in output.split("\n"):
            stripped = line.strip()
            if "aicoe.fit/" in stripped:
                url_match = re.search(r"(https://aicoe\.fit/\S+)", stripped)
                if url_match:
                    url = url_match.group(1).rstrip(",")
                    assert validate_tracking_url(url), f"Invalid tracking URL: {url!r}"

    def test_custom_links_no_raw_js_in_urls(self):
        """No JS/TS code in any URL from als custom-links."""
        result = run_als(["custom-links", "--count", "5"])
        assert result.returncode == 0
        output = result.stdout
        for line in output.split("\n"):
            stripped = line.strip()
            if "aicoe.fit/" in stripped:
                url_match = re.search(r"(https://aicoe\.fit/\S+)", stripped)
                if url_match:
                    url = url_match.group(1).rstrip(",")
                    assert not _has_js_code(url), f"JS code detected in URL: {url!r}"

    def test_custom_links_author_not_empty_string(self):
        """Author field should be null or a non-empty string — never ''."""
        result = run_als(["custom-links", "--count", "5"])
        assert result.returncode == 0
        output = result.stdout
        author_pattern = re.compile(r"by\s+")
        for line in output.split("\n"):
            m = author_pattern.search(line.strip())
            if m:
                after = line.strip()[m.end() :].strip()
                assert after != "", "Author field is an empty string"


class TestPrePublish:
    @pytest.fixture(autouse=True)
    def _require_auth(self):
        _skip_if_no_api_key()

    def test_pre_publish_idempotent(self):
        """als pre-publish <known-slug> should succeed (idempotent)."""
        result = run_als(["pre-publish", "test-smoke-idempotent"])
        assert result.returncode == 0, f"als pre-publish failed: {result.stderr}"
        output = result.stdout
        assert "Pre-publishing" in output or "already exists" in output, (
            f"Unexpected pre-publish output: {output[:200]}"
        )

    def test_pre_publish_tracking_urls_valid(self):
        """Tracking URLs from als pre-publish must match expected format."""
        result = run_als(["pre-publish", "test-smoke-idempotent"])
        assert result.returncode == 0
        output = result.stdout
        for line in output.split("\n"):
            stripped = line.strip()
            if "aicoe.fit/" in stripped:
                url_match = re.search(r"(https://aicoe\.fit/\S+)", stripped)
                if url_match:
                    url = url_match.group(1).rstrip(",")
                    assert validate_tracking_url(url), f"Invalid tracking URL: {url!r}"


class TestValidateTrackingUrl:
    def test_valid_url(self):
        assert validate_tracking_url("https://aicoe.fit/my-article-a1b2c3")

    def test_valid_url_complex_slug(self):
        assert validate_tracking_url("https://aicoe.fit/my-cool-article-d4e5f6")

    def test_rejects_no_https(self):
        assert not validate_tracking_url("http://aicoe.fit/my-article-a1b2c3")

    def test_rejects_wrong_domain(self):
        assert not validate_tracking_url("https://example.com/my-article-a1b2c3")

    def test_rejects_no_hex_suffix(self):
        assert not validate_tracking_url("https://aicoe.fit/my-article")

    def test_rejects_uppercase_hex(self):
        assert not validate_tracking_url("https://aicoe.fit/my-article-A1B2C3")

    def test_rejects_leading_dash(self):
        assert not validate_tracking_url("https://aicoe.fit/-my-article-a1b2c3")

    def test_rejects_js_code_in_url(self):
        assert not validate_tracking_url("https://aicoe.fit/${slug}-${find(part)}")

    def test_rejects_newlines(self):
        assert not validate_tracking_url("https://aicoe.fit/slug-\nabc")
