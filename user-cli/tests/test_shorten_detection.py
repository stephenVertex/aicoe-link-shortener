"""Unit tests for the short-link detection in als shorten."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure als module is importable when running from repo tree
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import als as als_module


class TestShortLinkDetection:
    """Tests that als shorten detects already-shortened URLs and warns."""

    @staticmethod
    def _mock_response(status_code=200, json_data=None):
        mock = MagicMock()
        mock.status_code = status_code
        mock.json.return_value = json_data if json_data is not None else {}
        return mock

    @patch("als.requests.post")
    @patch("als._api_request")
    def test_detects_aicoe_fit_url(self, mock_api_request, mock_post):
        """If the URL is already on aicoe.fit, warn and skip creation."""
        mock_post.return_value = self._mock_response(
            200,
            {
                "article": {
                    "slug": "my-article",
                    "title": "My Article",
                    "author": "Alice",
                    "published_at": "2024-01-15T00:00:00Z",
                }
            },
        )
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(
            als_module.cli, ["shorten", "https://aicoe.fit/my-article-abc123"]
        )
        assert result.exit_code == 0, result.output
        assert "already a short link" in result.output
        assert "My Article" in result.output
        assert "by Alice" in result.output
        assert "2024-01-15" in result.output
        assert "Slug:  my-article" in result.output
        assert "Short: https://aicoe.fit/my-article" in result.output
        assert "--force" in result.output
        mock_api_request.assert_not_called()

    @patch("als.requests.post")
    @patch("als._api_request")
    def test_force_flag_bypasses_detection(self, mock_api_request, mock_post):
        """--force allows creation even if the URL is already a short link."""
        mock_post.return_value = self._mock_response(
            200,
            {
                "article": {
                    "slug": "my-article",
                    "title": "My Article",
                }
            },
        )
        mock_api_request.return_value = self._mock_response(
            200,
            {
                "url": "https://aicoe.fit/my-article",
                "slug": "new-slug",
                "existed": False,
                "links": [],
                "person": {"name": "Alice", "slug": "alice"},
            },
        )
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(
            als_module.cli, ["shorten", "https://aicoe.fit/my-article", "--force"]
        )
        assert result.exit_code == 0, result.output
        assert "already a short link" not in result.output
        mock_api_request.assert_called_once()

    @patch("als.requests.post")
    @patch("als._api_request")
    def test_normal_url_proceeds(self, mock_api_request, mock_post):
        """Non-aicoe.fit URLs proceed with normal shortening."""
        mock_post.return_value = self._mock_response(404)
        mock_api_request.return_value = self._mock_response(
            200,
            {
                "url": "https://example.com",
                "slug": "example",
                "existed": False,
                "links": [],
                "person": {"name": "Alice", "slug": "alice"},
            },
        )
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(als_module.cli, ["shorten", "https://example.com"])
        assert result.exit_code == 0, result.output
        assert "already a short link" not in result.output
        mock_api_request.assert_called_once()

    @patch("als.requests.post")
    @patch("als._api_request")
    def test_lnk_id_bypasses_detection(self, mock_api_request, mock_post):
        """lnk-xxx IDs bypass the short-link detection."""
        mock_post.return_value = self._mock_response(404)
        mock_api_request.return_value = self._mock_response(
            200,
            {
                "url": "https://example.com",
                "slug": "example",
                "existed": False,
                "links": [],
                "person": {"name": "Alice", "slug": "alice"},
            },
        )
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(als_module.cli, ["shorten", "lnk-abc123"])
        assert result.exit_code == 0, result.output
        assert "already a short link" not in result.output
        mock_api_request.assert_called_once()

    @patch("als.requests.post")
    @patch("als._api_request")
    def test_json_output_on_detection(self, mock_api_request, mock_post):
        """--json returns JSON warning when a short link is detected."""
        mock_post.return_value = self._mock_response(
            200,
            {
                "article": {
                    "slug": "my-article",
                    "title": "My Article",
                }
            },
        )
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(
            als_module.cli, ["shorten", "https://aicoe.fit/my-article", "--json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["warning"] == "This URL is already a short link."
        assert data["article"]["slug"] == "my-article"
        assert data["article"]["title"] == "My Article"
        mock_api_request.assert_not_called()

    @patch("als.requests.post")
    @patch("als._api_request")
    def test_extracts_base_slug_from_tracking_variant(self, mock_api_request, mock_post):
        """Tracking variant URLs like https://aicoe.fit/slug-hex are detected."""
        # First call with full path returns 404, second with base slug returns article
        mock_post.side_effect = [
            self._mock_response(404),
            self._mock_response(
                200,
                {
                    "article": {
                        "slug": "my-article",
                        "title": "My Article",
                    }
                },
            ),
        ]
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(
            als_module.cli, ["shorten", "https://aicoe.fit/my-article-a1b2c3"]
        )
        assert result.exit_code == 0, result.output
        assert "already a short link" in result.output
        assert "My Article" in result.output
        mock_api_request.assert_not_called()
        # Should have made two get-link requests: full path and base slug
        assert mock_post.call_count == 2

    @patch("als.requests.post")
    @patch("als._api_request")
    def test_www_subdomain_detected(self, mock_api_request, mock_post):
        """www.aicoe.fit is also detected as a short-link domain."""
        mock_post.return_value = self._mock_response(
            200,
            {
                "article": {
                    "slug": "my-article",
                    "title": "My Article",
                }
            },
        )
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(
            als_module.cli, ["shorten", "https://www.aicoe.fit/my-article"]
        )
        assert result.exit_code == 0, result.output
        assert "already a short link" in result.output
        mock_api_request.assert_not_called()

    @patch("als.requests.post")
    @patch("als._api_request")
    def test_non_aicoe_domain_proceeds(self, mock_api_request, mock_post):
        """URLs on other domains are never checked and proceed normally."""
        mock_api_request.return_value = self._mock_response(
            200,
            {
                "url": "https://example.com",
                "slug": "example",
                "existed": False,
                "links": [],
                "person": {"name": "Alice", "slug": "alice"},
            },
        )
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(als_module.cli, ["shorten", "https://example.com"])
        assert result.exit_code == 0, result.output
        assert "already a short link" not in result.output
        # requests.post should never be called for non-aicoe domains
        mock_post.assert_not_called()
        mock_api_request.assert_called_once()
