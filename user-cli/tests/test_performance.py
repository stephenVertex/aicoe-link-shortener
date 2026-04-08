"""Performance tests for als CLI response times.

These tests measure wall-clock time for key CLI commands and fail if they
exceed thresholds. They make real API calls against the live API.

Run with: uv run pytest user-cli/tests/test_performance.py -v

Skip slow tests: uv run pytest user-cli/tests/test_performance.py -v -m "not slow"
"""

from pathlib import Path
import subprocess
import time

import pytest


USER_CLI_DIR = Path(__file__).resolve().parents[1]


def run_als_command(args: list[str], timeout: int = 30) -> tuple[float, str]:
    """Run an als command and return (elapsed_seconds, stdout).

    Args:
        args: List of arguments to pass to als (e.g., ["search", "Claude"])
        timeout: Maximum time to wait for the command

    Returns:
        Tuple of (elapsed_seconds, stdout)

    Raises:
        subprocess.TimeoutExpired: If command exceeds timeout
        subprocess.CalledProcessError: If command returns non-zero exit code
    """
    cmd = ["uv", "run", "als"] + args
    start = time.perf_counter()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
        cwd=USER_CLI_DIR,
    )
    elapsed = time.perf_counter() - start
    return elapsed, result.stdout


@pytest.mark.slow
def test_search_response_time():
    """als search 'Claude' should complete in < 3s."""
    elapsed, stdout = run_als_command(["search", "Claude", "--count", "5"])
    print(f"\n  als search 'Claude': {elapsed:.2f}s")
    assert elapsed < 3.0, f"als search took {elapsed:.2f}s (threshold: 3s)"


@pytest.mark.slow
def test_last_response_time():
    """als last 5 should complete in < 3s."""
    elapsed, stdout = run_als_command(["last", "5"])
    print(f"\n  als last 5: {elapsed:.2f}s")
    assert elapsed < 3.0, f"als last took {elapsed:.2f}s (threshold: 3s)"


@pytest.mark.slow
def test_get_response_time():
    """als get <slug> should complete in < 2s.

    Uses a known article slug from the database.
    """
    elapsed, stdout = run_als_command(["get", "your-agent-my-agent"])
    print(f"\n  als get your-agent-my-agent: {elapsed:.2f}s")
    assert elapsed < 2.0, f"als get took {elapsed:.2f}s (threshold: 2s)"


@pytest.mark.slow
def test_custom_links_response_time():
    """als custom-links should complete in < 2s."""
    elapsed, stdout = run_als_command(["custom-links"])
    print(f"\n  als custom-links: {elapsed:.2f}s")
    assert elapsed < 2.0, f"als custom-links took {elapsed:.2f}s (threshold: 2s)"


@pytest.mark.slow
def test_stats_response_time():
    """als stats <slug> should complete in < 3s.

    Uses a known article slug from the database.
    """
    elapsed, stdout = run_als_command(["stats", "your-agent-my-agent"])
    print(f"\n  als stats your-agent-my-agent: {elapsed:.2f}s")
    assert elapsed < 3.0, f"als stats took {elapsed:.2f}s (threshold: 3s)"


@pytest.mark.slow
def test_context_list_response_time():
    """als context list should complete in < 2s."""
    elapsed, stdout = run_als_command(["context", "list"])
    print(f"\n  als context list: {elapsed:.2f}s")
    assert elapsed < 2.0, f"als context list took {elapsed:.2f}s (threshold: 2s)"


@pytest.mark.slow
def test_links_list_pinned_response_time():
    """als links list --pinned should complete in < 2s."""
    elapsed, stdout = run_als_command(["links", "list", "--pinned"])
    print(f"\n  als links list --pinned: {elapsed:.2f}s")
    assert elapsed < 2.0, f"als links list --pinned took {elapsed:.2f}s (threshold: 2s)"
