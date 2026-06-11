"""Tests asserting that CLI output copy clarifies expiration-date semantics.

These tests verify the human-readable wording in `als shorten` help and `als help`
so that users (and agents) do not confuse auto-archive dates with link expiration.
"""

import os
import subprocess
from click.testing import CliRunner

import als

USER_CLI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_als_subprocess(args: list[str]) -> subprocess.CompletedProcess:
    """Run an als CLI command via `uv run als` and return the result."""
    cmd = ["uv", "run", "als"] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=USER_CLI_DIR,
    )


class TestShortenHelpCopy:
    def test_shorten_help_mentions_auto_archive(self):
        """als shorten --help should clarify that the date is for auto-archive,
        not link expiration."""
        runner = CliRunner()
        result = runner.invoke(als.cli, ["shorten", "--help"])
        assert result.exit_code == 0, f"als shorten --help failed: {result.output}"
        output = result.output
        assert "auto-archive" in output.lower(), "Expected 'auto-archive' in shorten --help"
        assert "link does not expire" in output.lower(), "Expected 'link does not expire' in shorten --help"

    def test_shorten_help_no_longer_says_expiry(self):
        """The old confusing phrase '60-day default expiry' should be removed."""
        runner = CliRunner()
        result = runner.invoke(als.cli, ["shorten", "--help"])
        assert result.exit_code == 0
        output = result.output
        assert "60-day default expiry" not in output, "Old confusing 'expiry' wording should be removed"


class TestHelpExampleCopy:
    def test_help_example_uses_auto_archive_wording(self):
        """The built-in `als help` example for sharing should mention auto-archive
        and explicitly state that the link does not expire."""
        runner = CliRunner()
        result = runner.invoke(als.cli, ["help"])
        assert result.exit_code == 0, f"als help failed: {result.output}"
        output = result.output
        assert "auto-archive after" in output.lower(), "Expected 'auto-archive after' in help output"
        assert "link does not expire" in output.lower(), "Expected 'link does not expire' in help output"


class TestSourceCodeCopy:
    """Verify that the source code itself contains the new label.

    These are lightweight static checks that do not require running the CLI.
    """

    def test_shorten_output_label_changed(self):
        """The _shorten_with_note function should print 'Auto-archive' instead of 'Expires'."""
        als_path = os.path.join(USER_CLI_DIR, "als.py")
        with open(als_path) as f:
            source = f.read()
        assert "Auto-archive:" in source, "Expected 'Auto-archive' label in als.py source"
        assert 'click.echo(f"  Expires: {variant' not in source, "Old 'Expires:' label should be removed from source"

    def test_no_expires_help_text_clarified(self):
        """The --no-expires option help should explicitly say the link never expires."""
        als_path = os.path.join(USER_CLI_DIR, "als.py")
        with open(als_path) as f:
            source = f.read()
        assert "Link never expires." in source, "Expected 'Link never expires.' in --no-expires help text"
