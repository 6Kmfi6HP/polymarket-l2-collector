"""
Unit tests for clob_markets -- CLOB market list fetcher.

Tests cover cursor encoding, token ID extraction, value flattening, CSV row
mapping, end-of-data marker, and empty-fetch behaviour.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from polymarket_l2_collector.clob_markets import (
    END_CURSOR,
    _cursor,
    _flatten,
    _read_tail_ids,
    _row,
    _token_ids,
    fetch_markets,
)


class TestCursorEncoding:
    """Base64 cursor encoding for CLOB pagination."""

    def test_offset_0(self) -> None:
        assert _cursor(0) == "MA=="

    def test_offset_1000(self) -> None:
        assert _cursor(1000) == "MTAwMA=="


class TestTokenIds:
    """Extracting CLOB token IDs from a market dict."""

    def test_extract(self) -> None:
        market = {
            "tokens": [
                {"token_id": "111"},
                {"token_id": "222"},
            ],
        }
        assert _token_ids(market) == ["111", "222"]

    def test_empty(self) -> None:
        assert _token_ids({}) == []
        assert _token_ids({"tokens": None}) == []
        assert _token_ids({"tokens": []}) == []

    def test_missing_token_id(self) -> None:
        """A token dict without token_id should be skipped."""
        market = {
            "tokens": [
                {"token_id": "111"},
                {"not_token_id": "xyz"},
                {"token_id": "333"},
            ],
        }
        assert _token_ids(market) == ["111", "333"]

    def test_numeric_token_id(self) -> None:
        """token_id may be numeric; it should be stringified."""
        market = {
            "tokens": [
                {"token_id": 111},
                {"token_id": 222},
            ],
        }
        assert _token_ids(market) == ["111", "222"]


class TestFlatten:
    """Value flattening for CSV output."""

    def test_none_becomes_empty(self) -> None:
        assert _flatten(None) == ""

    def test_scalar_passthrough(self) -> None:
        assert _flatten("hello") == "hello"
        assert _flatten(123) == 123
        assert _flatten(45.6) == 45.6
        assert _flatten(True) is True

    def test_dict_becomes_json(self) -> None:
        assert json.loads(_flatten({"a": 1})) == {"a": 1}

    def test_list_becomes_json(self) -> None:
        assert json.loads(_flatten([1, 2, 3])) == [1, 2, 3]

    def test_nested_dict_becomes_json(self) -> None:
        val = {"a": [1, {"b": "c"}]}
        assert json.loads(_flatten(val)) == val


class TestRowMapping:
    """Mapping from market dict to CSV columns."""

    def test_full_row(self) -> None:
        market = {
            "condition_id": "abc123",
            "tokens": [
                {"token_id": "111"},
                {"token_id": "222"},
            ],
            "question": "BTC > $50k?",
            "outcomes": ["Up", "Down"],
        }
        columns = ["id", "clobTokenIds", "question", "outcomes"]
        row = _row(market, columns)
        assert row[0] == "abc123"
        assert json.loads(row[1]) == ["111", "222"]
        assert row[2] == "BTC > $50k?"
        assert json.loads(row[3]) == ["Up", "Down"]

    def test_empty_token_ids(self) -> None:
        market = {
            "condition_id": "abc123",
            "tokens": [],
            "question": "BTC > $50k?",
        }
        columns = ["id", "clobTokenIds", "question"]
        row = _row(market, columns)
        assert row[0] == "abc123"
        assert row[1] == ""  # empty token list -> empty string
        assert row[2] == "BTC > $50k?"

    def test_missing_condition_id(self) -> None:
        market = {"question": "No condition_id"}
        columns = ["id", "clobTokenIds", "question"]
        row = _row(market, columns)
        assert row[0] == ""  # missing condition_id -> empty string
        assert row[1] == ""
        assert row[2] == "No condition_id"

    def test_nested_field_json_encoded(self) -> None:
        market = {
            "condition_id": "abc",
            "tokens": [],
            "reward": {"amount": 100, "type": "flat"},
        }
        columns = ["id", "clobTokenIds", "reward"]
        row = _row(market, columns)
        assert row[0] == "abc"
        assert row[1] == ""
        assert json.loads(row[2]) == {"amount": 100, "type": "flat"}


class TestEndCursor:
    """End-of-data marker constant."""

    def test_end_cursor_value(self) -> None:
        """LTE= is base64('-1'), the CLOB end marker."""
        assert END_CURSOR == "LTE="


class TestReadTailIds:
    """Reading the last N rows of a CSV for resume dedup."""

    def test_missing_file(self) -> None:
        assert _read_tail_ids("/nonexistent/path.csv", 10) == set()

    def test_empty_file(self, tmp_path) -> None:
        p = tmp_path / "markets.csv"
        p.write_text("")
        assert _read_tail_ids(str(p), 10) == set()

    def test_small_file(self, tmp_path) -> None:
        p = tmp_path / "markets.csv"
        p.write_text("id,col\nabc,val1\ndef,val2\n")
        ids = _read_tail_ids(str(p), 10)
        assert ids == {"abc", "def"}

    def test_reads_last_n(self, tmp_path) -> None:
        p = tmp_path / "markets.csv"
        lines = ["id,col"] + [f"id{i},val{i}" for i in range(100)]
        p.write_text("\n".join(lines))
        ids = _read_tail_ids(str(p), 3)
        assert ids == {"id97", "id98", "id99"}

    def test_discards_header(self, tmp_path) -> None:
        """If the header line happens to land in the tail window, skip it."""
        p = tmp_path / "markets.csv"
        p.write_text("id,col\nabc,val1")
        ids = _read_tail_ids(str(p), 5)
        assert "id" not in ids
        assert ids == {"abc"}

    def test_file_smaller_than_chunk(self, tmp_path) -> None:
        """File under 16MB reads the entire file correctly."""
        p = tmp_path / "markets.csv"
        p.write_text("id,col\n" + "\n".join(f"id{i},v{i}" for i in range(10)))
        ids = _read_tail_ids(str(p), 5)
        assert len(ids) == 5


class TestSaveLoadState:
    """State persistence for resumable fetches."""

    def test_load_missing_state(self, tmp_path) -> None:
        from polymarket_l2_collector.clob_markets import _load_state

        state = _load_state(str(tmp_path))
        assert state == {}

    def test_save_and_load(self, tmp_path) -> None:
        from polymarket_l2_collector.clob_markets import _load_state, _save_state

        _save_state(str(tmp_path), 5000, 42, ["id", "col"], completed=False)
        state = _load_state(str(tmp_path))
        assert state["offset"] == 5000
        assert state["fetched"] == 42
        assert state["columns"] == ["id", "col"]
        assert state["completed"] is False

    def test_save_and_load_completed(self, tmp_path) -> None:
        from polymarket_l2_collector.clob_markets import _load_state, _save_state

        _save_state(str(tmp_path), 10000, 999, ["a"], completed=True)
        state = _load_state(str(tmp_path))
        assert state["completed"] is True
        assert state["fetched"] == 999

    def test_corrupted_state_returns_empty(self, tmp_path) -> None:
        from polymarket_l2_collector.clob_markets import _load_state

        p = tmp_path / "markets_state.json"
        p.write_text("not valid json")
        state = _load_state(str(tmp_path))
        assert state == {}


class TestEmptyFetch:
    """Edge-case: no data available from the API."""

    def test_empty_fetch_returns_zero(self, tmp_path) -> None:
        """When every page returns empty, the total should be 0."""
        with patch("polymarket_l2_collector.clob_markets._fetch_page") as mock_fetch:
            mock_fetch.side_effect = lambda offset: (offset, [])
            result = fetch_markets(output_dir=str(tmp_path), max_workers=1)
            assert result == 0


class TestMainCli:
    """CLI entry-point tests."""

    def test_download_markets_file_skips_when_complete(self, tmp_path) -> None:
        """download_markets_file returns 0 when state says completed."""
        from polymarket_l2_collector.clob_markets import download_markets_file

        state = {"offset": 0, "fetched": 0, "columns": ["a"], "completed": True}
        state_path = tmp_path / "markets_state.json"
        state_path.write_text(json.dumps(state))
        csv_path = tmp_path / "markets.csv"
        csv_path.write_text("a\n")
        result = download_markets_file(output_dir=str(tmp_path))
        assert result == 0

    def test_download_markets_file_fetches_when_incomplete(self, tmp_path) -> None:
        """download_markets_file calls fetch_markets when not completed."""
        from polymarket_l2_collector.clob_markets import download_markets_file

        with patch(
            "polymarket_l2_collector.clob_markets.fetch_markets",
            return_value=42,
        ) as mock_fetch:
            result = download_markets_file(output_dir=str(tmp_path))
            assert result == 42
            mock_fetch.assert_called_once_with(output_dir=str(tmp_path))
