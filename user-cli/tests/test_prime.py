"""Tests for the agent-facing ``als prime`` guide."""

from click.testing import CliRunner

import als


def test_prime_documents_agent_workflows_without_auth_or_network():
    result = CliRunner().invoke(als.cli, ["prime"])

    assert result.exit_code == 0
    assert "aicoe.fit link discovery, shortening, tracking, and analytics" in result.output
    assert "aifs submit" in result.output
    assert "aifs vote" in result.output
    assert "aifs list" in result.output
    assert "aifs archive" in result.output
    assert "aifs episodes" in result.output
    assert "Covered in episode YYYYMMDD" in result.output
    assert "auto-archives after 60 days" in result.output
    assert "redirect and click logging continue" in result.output
    assert "yesod tool als distill" in result.output
    assert "yesod ask" in result.output
