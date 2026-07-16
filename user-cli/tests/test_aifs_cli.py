"""Tests for the dedicated aifs CLI and the deprecated `als aifs` shim.

Covers the full aifs command surface (submit, vote, list, archive,
unarchive, episodes) by invoking the click commands with a mocked
_api_request, and verifies that `als aifs` delegates to the same
implementation with a deprecation notice.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

import aifs
import als


def _mock_resp(status_code: int, json_data: dict):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.text = json.dumps(json_data)
    return mock


def _stderr(result) -> str:
    """Result stderr across click versions (mixed into output before 8.2)."""
    try:
        return result.stderr
    except ValueError:
        return result.output


SUBMITTED = {"status": "submitted", "short_id": "aifs-new"}
VOTED = {"status": "voted", "short_id": "aifs-c6u"}
SUBMITTED_WITH_TAGS = {
    "status": "submitted",
    "short_id": "aifs-new",
    "tags": [{"name": "Model Release", "slug": "model-release"}],
}

LIST_RESPONSE = {
    "submissions": [
        {
            "short_id": "aifs-c6u",
            "url": "https://example.com/a",
            "vote_count": 2,
            "voters": [
                {"person_ref": "alice", "comment": "Great"},
                {"person_ref": "bob", "comment": ""},
            ],
            "archived_at": None,
            "archive_note": None,
            "tags": [],
        },
    ],
    "total": 1,
}

LIST_RESPONSE_WITH_TAGS = {
    "submissions": [
        {
            "short_id": "aifs-c6u",
            "url": "https://example.com/a",
            "vote_count": 2,
            "voters": [
                {"person_ref": "alice", "comment": "Great"},
            ],
            "archived_at": None,
            "archive_note": None,
            "tags": [
                {"name": "Model Release", "slug": "model-release"},
                {"name": "Agent Tooling", "slug": "agent-tooling"},
            ],
        },
    ],
    "total": 1,
}

ARCHIVE_RESPONSE = {"count": 1, "submissions": [{"short_id": "aifs-c6u"}]}


class TestAifsHelp:
    def test_help_lists_subcommands(self):
        result = CliRunner().invoke(aifs.cli, ["--help"])
        assert result.exit_code == 0
        for cmd in ("submit", "vote", "list", "archive", "unarchive", "episodes", "login"):
            assert cmd in result.output

    def test_subcommand_help(self):
        for cmd in ("submit", "vote", "list", "archive", "unarchive", "episodes"):
            result = CliRunner().invoke(aifs.cli, [cmd, "--help"])
            assert result.exit_code == 0, f"aifs {cmd} --help failed"


class TestAifsSubmit:
    def test_submit_url(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, SUBMITTED)
            result = CliRunner().invoke(aifs.cli, ["submit", "https://example.com/a"])

        assert result.exit_code == 0
        assert "Submitted!" in result.output
        assert "aifs-new" in result.output
        body = mock_req.call_args[1]["json_body"]
        assert body == {"action": "submit", "url": "https://example.com/a"}

    def test_submit_with_comment_and_as(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, SUBMITTED)
            result = CliRunner().invoke(
                aifs.cli,
                ["submit", "https://example.com/a", "--comment", "Nice", "--as", "42"],
            )

        assert result.exit_code == 0
        body = mock_req.call_args[1]["json_body"]
        assert body["comment"] == "Nice"
        assert body["discord_user"] == "42"

    def test_submit_json_output(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, SUBMITTED)
            result = CliRunner().invoke(
                aifs.cli, ["submit", "https://example.com/a", "--json"]
            )

        assert result.exit_code == 0
        assert json.loads(result.output) == SUBMITTED

    def test_url_shorthand_routes_to_submit(self):
        """`aifs <url>` behaves like `aifs submit <url>`."""
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, SUBMITTED)
            result = CliRunner().invoke(aifs.cli, ["https://example.com/a"])

        assert result.exit_code == 0
        assert "Submitted!" in result.output
        body = mock_req.call_args[1]["json_body"]
        assert body["url"] == "https://example.com/a"

    def test_submit_401_names_aifs_login(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(401, {"error": "Invalid API key"})
            result = CliRunner().invoke(aifs.cli, ["submit", "https://example.com/a"])

        assert result.exit_code == 1
        assert "aifs login" in _stderr(result)


class TestAifsVote:
    def test_vote_by_short_id(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, VOTED)
            result = CliRunner().invoke(
                aifs.cli, ["vote", "aifs-c6u", "--comment", "Strong"]
            )

        assert result.exit_code == 0
        assert "Voted!" in result.output
        body = mock_req.call_args[1]["json_body"]
        assert body["url"] == "aifs-c6u"
        assert body["comment"] == "Strong"


class TestAifsList:
    @pytest.mark.parametrize(
        "args,expected_filter",
        [([], "active"), (["--archived"], "archived"), (["--all"], "all")],
    )
    def test_list_filters(self, args, expected_filter):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, LIST_RESPONSE)
            result = CliRunner().invoke(aifs.cli, ["list"] + args)

        assert result.exit_code == 0
        body = mock_req.call_args[1]["json_body"]
        assert body == {"action": "list", "filter": expected_filter}
        assert "aifs-c6u" in result.output
        assert "2 votes" in result.output

    def test_list_json(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, LIST_RESPONSE)
            result = CliRunner().invoke(aifs.cli, ["list", "--json"])

        assert result.exit_code == 0
        assert json.loads(result.output) == LIST_RESPONSE["submissions"]

    def test_list_empty_hints_new_cli(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, {"submissions": [], "total": 0})
            result = CliRunner().invoke(aifs.cli, ["list"])

        assert result.exit_code == 0
        assert "aifs submit <url>" in result.output


class TestAifsArchive:
    def test_archive_requires_note(self):
        result = CliRunner().invoke(aifs.cli, ["archive", "aifs-c6u"])
        assert result.exit_code == 1
        assert "--note is required" in _stderr(result)

    def test_archive_requires_target(self):
        result = CliRunner().invoke(aifs.cli, ["archive", "--note", "n"])
        assert result.exit_code == 1
        assert "provide IDs, --before, or --archive-all" in _stderr(result)

    def test_archive_by_ids(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, ARCHIVE_RESPONSE)
            result = CliRunner().invoke(
                aifs.cli,
                ["archive", "aifs-c6u", "aifs-j0p", "--note", "Covered in episode 42"],
            )

        assert result.exit_code == 0
        assert "Archived" in result.output
        body = mock_req.call_args[1]["json_body"]
        assert body["action"] == "archive"
        assert body["ids"] == ["aifs-c6u", "aifs-j0p"]
        assert body["note"] == "Covered in episode 42"

    def test_archive_before_date(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, ARCHIVE_RESPONSE)
            result = CliRunner().invoke(
                aifs.cli, ["archive", "--before", "2026-03-31", "--note", "Stale"]
            )

        assert result.exit_code == 0
        body = mock_req.call_args[1]["json_body"]
        assert body["before_date"] == "2026-03-31"

    def test_archive_all_lists_then_archives(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.side_effect = [
                _mock_resp(200, LIST_RESPONSE),
                _mock_resp(200, ARCHIVE_RESPONSE),
            ]
            result = CliRunner().invoke(
                aifs.cli, ["archive", "--archive-all", "--note", "Fresh start"]
            )

        assert result.exit_code == 0
        assert mock_req.call_count == 2
        first_body = mock_req.call_args_list[0][1]["json_body"]
        second_body = mock_req.call_args_list[1][1]["json_body"]
        assert first_body == {"action": "list", "filter": "active"}
        assert second_body["action"] == "archive"
        assert second_body["ids"] == ["aifs-c6u"]


class TestAifsUnarchive:
    def test_unarchive_requires_ids(self):
        result = CliRunner().invoke(aifs.cli, ["unarchive"])
        assert result.exit_code == 2  # click-enforced required argument

    def test_unarchive_by_ids(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, ARCHIVE_RESPONSE)
            result = CliRunner().invoke(aifs.cli, ["unarchive", "aifs-c6u"])

        assert result.exit_code == 0
        assert "Unarchived" in result.output
        body = mock_req.call_args[1]["json_body"]
        assert body == {"action": "unarchive", "ids": ["aifs-c6u"]}


class TestAifsEpisodesCommand:
    def test_episodes_via_cli(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(
                200,
                {
                    "episodes": [
                        {
                            "episode_number": 42,
                            "completed_at": "2026-05-01T09:00:00.000Z",
                            "submission_count": 1,
                            "submissions": [
                                {"short_id": "aifs-d4d", "url": "https://example.com/d"}
                            ],
                        }
                    ],
                    "total": 1,
                },
            )
            result = CliRunner().invoke(aifs.cli, ["episodes"])

        assert result.exit_code == 0
        assert "Episode 42" in result.output
        body = mock_req.call_args[1]["json_body"]
        assert body == {"action": "episodes"}


class TestAlsAifsShim:
    """`als aifs` delegates to the aifs module with a deprecation notice."""

    def test_shim_list_delegates_and_warns(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, LIST_RESPONSE)
            result = CliRunner().invoke(als.cli, ["aifs", "list"])

        assert result.exit_code == 0
        assert "aifs-c6u" in result.output
        assert "deprecated" in _stderr(result)
        body = mock_req.call_args[1]["json_body"]
        assert body == {"action": "list", "filter": "active"}

    def test_shim_url_submission(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, SUBMITTED)
            result = CliRunner().invoke(als.cli, ["aifs", "https://example.com/a"])

        assert result.exit_code == 0
        assert "Submitted!" in result.output
        body = mock_req.call_args[1]["json_body"]
        assert body == {"action": "submit", "url": "https://example.com/a"}

    def test_shim_item_vote(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, VOTED)
            result = CliRunner().invoke(
                als.cli, ["aifs", "--item", "aifs-c6u", "--comment", "Nice"]
            )

        assert result.exit_code == 0
        assert "Voted!" in result.output
        body = mock_req.call_args[1]["json_body"]
        assert body["url"] == "aifs-c6u"

    def test_shim_archive(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, ARCHIVE_RESPONSE)
            result = CliRunner().invoke(
                als.cli, ["aifs", "archive", "aifs-c6u", "--note", "Done"]
            )

        assert result.exit_code == 0
        assert "Archived" in result.output

    def test_shim_episodes(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, {"episodes": [], "total": 0})
            result = CliRunner().invoke(als.cli, ["aifs", "episodes"])

        assert result.exit_code == 0
        assert "No completed episodes found" in result.output

    def test_shim_help_mentions_deprecation(self):
        result = CliRunner().invoke(als.cli, ["aifs", "--help"])
        assert result.exit_code == 0
        assert "DEPRECATED" in result.output


class TestAifsSubmitTags:
    def test_submit_with_single_tag(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, SUBMITTED_WITH_TAGS)
            result = CliRunner().invoke(
                aifs.cli, ["submit", "https://example.com/a", "--tag", "model-release"]
            )

        assert result.exit_code == 0
        body = mock_req.call_args[1]["json_body"]
        assert body["tags"] == ["model-release"]

    def test_submit_with_multiple_tags(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, SUBMITTED_WITH_TAGS)
            result = CliRunner().invoke(
                aifs.cli,
                [
                    "submit", "https://example.com/a",
                    "--tag", "model-release", "--tag", "agent-tooling",
                ],
            )

        assert result.exit_code == 0
        body = mock_req.call_args[1]["json_body"]
        assert body["tags"] == ["model-release", "agent-tooling"]

    def test_submit_without_tag_omits_tags_key(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, SUBMITTED)
            result = CliRunner().invoke(aifs.cli, ["submit", "https://example.com/a"])

        assert result.exit_code == 0
        body = mock_req.call_args[1]["json_body"]
        assert "tags" not in body

    def test_submit_displays_tags(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, SUBMITTED_WITH_TAGS)
            result = CliRunner().invoke(
                aifs.cli, ["submit", "https://example.com/a", "--tag", "model-release"]
            )

        assert result.exit_code == 0
        assert "Tags:" in result.output
        assert "model-release" in result.output


class TestAifsVoteTags:
    def test_vote_with_tag(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, VOTED)
            result = CliRunner().invoke(
                aifs.cli, ["vote", "aifs-c6u", "--tag", "model-release"]
            )

        assert result.exit_code == 0
        body = mock_req.call_args[1]["json_body"]
        assert body["url"] == "aifs-c6u"
        assert body["tags"] == ["model-release"]

    def test_vote_with_multiple_tags(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, VOTED)
            result = CliRunner().invoke(
                aifs.cli,
                ["vote", "aifs-c6u", "--tag", "model-release", "--tag", "open-weights"],
            )

        assert result.exit_code == 0
        body = mock_req.call_args[1]["json_body"]
        assert body["tags"] == ["model-release", "open-weights"]


class TestAifsListTags:
    def test_list_with_tag_filter(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, LIST_RESPONSE)
            result = CliRunner().invoke(
                aifs.cli, ["list", "--tag", "model-release"]
            )

        assert result.exit_code == 0
        body = mock_req.call_args[1]["json_body"]
        assert body["action"] == "list"
        assert body["tags"] == ["model-release"]

    def test_list_without_tag_omits_tags_key(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, LIST_RESPONSE)
            result = CliRunner().invoke(aifs.cli, ["list"])

        assert result.exit_code == 0
        body = mock_req.call_args[1]["json_body"]
        assert "tags" not in body

    def test_list_displays_tags(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, LIST_RESPONSE_WITH_TAGS)
            result = CliRunner().invoke(aifs.cli, ["list"])

        assert result.exit_code == 0
        assert "#model-release" in result.output
        assert "#agent-tooling" in result.output

    def test_list_with_multiple_tag_filters(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, LIST_RESPONSE)
            result = CliRunner().invoke(
                aifs.cli, ["list", "--tag", "model-release", "--tag", "agent-tooling"]
            )

        assert result.exit_code == 0
        body = mock_req.call_args[1]["json_body"]
        assert body["tags"] == ["model-release", "agent-tooling"]


class TestAlsAifsShimTags:
    def test_shim_submit_with_tag(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, SUBMITTED)
            result = CliRunner().invoke(
                als.cli, ["aifs", "https://example.com/a", "--tag", "model-release"]
            )

        assert result.exit_code == 0
        body = mock_req.call_args[1]["json_body"]
        assert body["tags"] == ["model-release"]

    def test_shim_list_with_tag(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, LIST_RESPONSE)
            result = CliRunner().invoke(als.cli, ["aifs", "list", "--tag", "model-release"])

        assert result.exit_code == 0
        body = mock_req.call_args[1]["json_body"]
        assert body["tags"] == ["model-release"]

    def test_shim_vote_with_tag(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, VOTED)
            result = CliRunner().invoke(
                als.cli, ["aifs", "--item", "aifs-c6u", "--tag", "model-release"]
            )

        assert result.exit_code == 0
        body = mock_req.call_args[1]["json_body"]
        assert body["tags"] == ["model-release"]


class TestSharedCredentials:
    def test_both_clis_use_same_credentials_file(self):
        import als_common

        assert als_common.CREDENTIALS_FILE.name == ".als.credentials"

    def test_login_hint_follows_prog(self):
        import als_common

        old = als_common.PROG
        try:
            als_common.PROG = "aifs"
            assert "aifs login" in als_common.login_hint()
            als_common.PROG = "als"
            assert "als login" in als_common.login_hint()
        finally:
            als_common.PROG = old
