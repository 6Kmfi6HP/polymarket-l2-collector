"""
Unit tests for extract_asset_id — pretty-print asset IDs from API responses.
"""

from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import patch

from polymarket_l2_collector.extract_asset_id import extract_asset_ids


class TestExtractAssetIds:
    def test_prints_question_and_slug(self, capsys: Any) -> None:
        extract_asset_ids({
            "question": "BTC > $100k?", "slug": "btc-updown-5m-1000",
            "outcomes": [], "clobTokenIds": [],
        })
        out = capsys.readouterr().out
        assert "BTC > $100k?" in out
        assert "btc-updown-5m-1000" in out

    def test_prints_asset_ids(self, capsys: Any) -> None:
        extract_asset_ids({
            "question": "Q",
            "slug": "s",
            "outcomes": ["Up", "Down"],
            "clobTokenIds": ["1111111111111111abcdefgh", "2222222222222222abcdefgh"],
        })
        out = capsys.readouterr().out
        assert "1111111111111111" in out
        assert "2222222222222222" in out

    def test_wraps_long_tokens(self, capsys: Any) -> None:
        """Token IDs longer than 16 chars are truncated with …."""
        extract_asset_ids({
            "question": "Q",
            "slug": "s",
            "outcomes": ["Up"],
            "clobTokenIds": ["1234567890123456extra"],
        })
        out = capsys.readouterr().out
        assert "1234567890123456" in out
        assert "…" in out

    def test_list_input_uses_first_item(self, capsys: Any) -> None:
        extract_asset_ids([
            {"question": "First", "slug": "first", "outcomes": ["Up"], "clobTokenIds": ["abc"]},
            {"question": "Second", "slug": "second", "outcomes": ["Down"], "clobTokenIds": ["def"]},
        ])
        out = capsys.readouterr().out
        assert "First" in out
        assert "Second" not in out

    def test_empty_list(self, capsys: Any) -> None:
        extract_asset_ids([])
        assert "Empty data" in capsys.readouterr().out

    def test_json_string_fields(self, capsys: Any) -> None:
        """outcomes and clobTokenIds as JSON strings are parsed."""
        extract_asset_ids({
            "question": "Q",
            "slug": "s",
            "outcomes": '["Yes","No"]',
            "clobTokenIds": '["abc","def"]',
        })
        out = capsys.readouterr().out
        assert "Yes" in out
        assert "abc" in out

    def test_missing_fields_use_defaults(self, capsys: Any) -> None:
        extract_asset_ids({})
        out = capsys.readouterr().out
        assert "N/A" in out  # question and slug default to N/A

    def test_config_snippet(self, capsys: Any) -> None:
        extract_asset_ids({
            "question": "Q", "slug": "s",
            "outcomes": ["Up"], "clobTokenIds": ["token1"],
        })
        out = capsys.readouterr().out
        assert "ASSET_IDS" in out
        assert '"token1"' in out

    def test_config_snippet_multiple(self, capsys: Any) -> None:
        extract_asset_ids({
            "question": "Q", "slug": "s",
            "outcomes": ["Up", "Down"],
            "clobTokenIds": ["111", "222"],
        })
        out = capsys.readouterr().out
        assert '"111"' in out
        assert '"222"' in out


class TestMain:
    def test_reads_file(self, tmp_path: Any) -> None:
        data = {"question": "Q", "slug": "s", "outcomes": [], "clobTokenIds": []}
        fp = tmp_path / "response.json"
        fp.write_text(json.dumps(data))

        from polymarket_l2_collector.extract_asset_id import main

        with patch.object(sys, "argv", ["extract_asset_id", str(fp)]):
            main()

    def test_reads_stdin(self, capsys: Any) -> None:
        from polymarket_l2_collector.extract_asset_id import main

        data = {"question": "Q", "slug": "s", "outcomes": [], "clobTokenIds": []}
        with (
            patch.object(sys, "argv", ["extract_asset_id"]),
            patch("sys.stdin", new=type("StdinMock", (), {"read": lambda self: json.dumps(data)})()),
        ):
            main()
