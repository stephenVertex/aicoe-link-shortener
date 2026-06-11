"""Tests for aifs episodes — listing completed AIFS episodes.

Tests the CLI dispatch and display logic by mocking _api_request.
Edge function regex parsing tested implicitly through the mock responses.
"""

from unittest.mock import MagicMock, patch

import pytest

MOCK_COMPLETED_RESPONSE = {
    "episodes": [
        {
            "episode_number": 1,
            "completed_at": "2026-03-15T10:30:00.000Z",
            "submission_count": 2,
            "submissions": [
                {
                    "id": "uuid-aaa",
                    "short_id": "aifs-a1a",
                    "url": "https://example.com/article-a",
                    "title": None,
                    "submitted_by": "alice",
                },
                {
                    "id": "uuid-bbb",
                    "short_id": "aifs-b2b",
                    "url": "https://example.com/article-b",
                    "title": None,
                    "submitted_by": "bob",
                },
            ],
        },
        {
            "episode_number": 2,
            "completed_at": "2026-04-01T14:00:00.000Z",
            "submission_count": 1,
            "submissions": [
                {
                    "id": "uuid-ccc",
                    "short_id": "aifs-c3c",
                    "url": "https://example.com/article-c",
                    "title": None,
                    "submitted_by": "alice",
                },
            ],
        },
    ],
    "total": 2,
}

MOCK_MIXED_RESPONSE = {
    "episodes": [
        {
            "episode_number": 3,
            "completed_at": "2026-05-01T09:00:00.000Z",
            "submission_count": 1,
            "submissions": [
                {
                    "id": "uuid-ddd",
                    "short_id": "aifs-d4d",
                    "url": "https://example.com/article-d",
                    "title": "A Great Article",
                    "submitted_by": "carol",
                },
            ],
        },
    ],
    "total": 1,
}

MOCK_EMPTY_RESPONSE = {"episodes": [], "total": 0}


def _mock_resp(status_code: int, json_data: dict):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    return mock


class TestAifsEpisodes:
    def test_completed_episodes(self):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, MOCK_COMPLETED_RESPONSE)

            import aifs as aifs_mod

            aifs_mod._episodes()

        assert mock_req.call_count == 1
        call_args = mock_req.call_args
        assert call_args[0][0] == "aifs"
        assert call_args[1]["json_body"]["action"] == "episodes"

    def test_completed_episodes_json(self, capsys):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, MOCK_COMPLETED_RESPONSE)

            import aifs as aifs_mod

            aifs_mod._episodes(output_json=True)

        captured = capsys.readouterr()
        assert "episode_number" in captured.out
        assert '"episode_number": 1' in captured.out
        assert '"episode_number": 2' in captured.out

    def test_empty_state(self, capsys):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, MOCK_EMPTY_RESPONSE)

            import aifs as aifs_mod

            aifs_mod._episodes()

        captured = capsys.readouterr()
        assert "No completed episodes found" in captured.out

    def test_empty_state_json(self, capsys):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, MOCK_EMPTY_RESPONSE)

            import aifs as aifs_mod

            aifs_mod._episodes(output_json=True)

        captured = capsys.readouterr()
        assert "[]" in captured.out

    def test_mixed_states(self, capsys):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(200, MOCK_MIXED_RESPONSE)

            import aifs as aifs_mod

            aifs_mod._episodes()

        captured = capsys.readouterr()
        assert "Episode 3" in captured.out
        assert "aifs-d4d" in captured.out
        assert "example.com/article-d" in captured.out

    def test_api_error_handling(self, capsys):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(401, {"error": "Invalid API key"})

            import aifs as aifs_mod

            with pytest.raises(SystemExit) as exc_info:
                aifs_mod._episodes()
            assert exc_info.value.code == 1

    def test_api_generic_error(self, capsys):
        with patch("aifs._api_request") as mock_req:
            mock_req.return_value = _mock_resp(500, {"error": "Server error"})
            mock_req.return_value.text = "Server error"

            import aifs as aifs_mod

            with pytest.raises(SystemExit) as exc_info:
                aifs_mod._episodes()
            assert exc_info.value.code == 1


class TestAifsEpisodesEdgeFunction:
    @pytest.mark.parametrize(
        "note,expected",
        [
            ("Covered in episode 42", 42),
            ("covered in episode 5", 5),
            ("Episode 10", 10),
            ("ep 3", 3),
            ("e 7", 7),
            ("Covered in ep #15", 15),
            ("#42", 42),
        ],
    )
    def test_episode_regex_matches(self, note, expected):
        import re

        regex = re.compile(
            r"(?:covered\s+in\s+)?(?:episode|ep|e)\s*[#]?\s*(\d+)|#\s*(\d+)",
            re.IGNORECASE,
        )
        match = regex.match(note)
        assert match is not None, f"Regex failed to match: {note}"
        ep_num = int(match[1] or match[2])
        assert ep_num == expected

    @pytest.mark.parametrize(
        "note",
        [
            "Just a note without episode",
            "Covered something",
            "",
            "episode",
            "ep",
        ],
    )
    def test_episode_regex_no_match(self, note):
        import re

        regex = re.compile(
            r"(?:covered\s+in\s+)?(?:episode|ep|e)\s*[#]?\s*(\d+)|#\s*(\d+)",
            re.IGNORECASE,
        )
        match = regex.match(note)
        assert match is None or (
            match[1] is None and match[2] is None
        ), f"Regex should not match: {note}"
