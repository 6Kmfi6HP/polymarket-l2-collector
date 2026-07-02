"""
Unit tests for ``missing_markets`` module.
"""

from __future__ import annotations

import json
import os
import tempfile

import polars as pl

from polymarket_l2_collector.missing_markets import (
    _flatten_value,
    _market_cond_id,
    discover_missing_asset_ids,
    load_all_markets,
    update_missing_markets,
)


class TestFlattenValue:
    """Value serialization for CSV output."""

    def test_none(self):
        assert _flatten_value(None) == ""

    def test_string(self):
        assert _flatten_value("hello") == "hello"

    def test_number(self):
        assert _flatten_value(42) == "42"

    def test_list(self):
        result = _flatten_value(["a", "b"])
        assert json.loads(result) == ["a", "b"]

    def test_dict(self):
        result = _flatten_value({"key": "val"})
        assert json.loads(result) == {"key": "val"}

    def test_bool(self):
        assert _flatten_value(True) == "True"


class TestMarketCondId:
    """Market ID resolution."""

    def test_condition_id_preferred(self):
        m = {"conditionId": "cond-123", "id": "id-456"}
        assert _market_cond_id(m) == "cond-123"

    def test_id_fallback(self):
        m = {"id": "id-456"}
        assert _market_cond_id(m) == "id-456"

    def test_empty(self):
        assert _market_cond_id({}) == ""


class TestUpdateMissingMarkets:
    """``update_missing_markets`` entry point."""

    def test_empty_input(self):
        """Empty input returns 0 without creating any files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            count = update_missing_markets([], output_dir=tmpdir)
            assert count == 0
            assert not os.path.exists(os.path.join(tmpdir, "missing_markets.csv"))


class TestDiscoverMissingAssetIds:
    """``discover_missing_asset_ids`` — file scanning for unknown tokens."""

    def test_empty_dir(self):
        """Empty data directory returns an empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            known = pl.DataFrame(schema={"id": pl.Utf8, "clobTokenIds": pl.Utf8})
            result = discover_missing_asset_ids(tmpdir, known)
            assert result == []


class TestLoadAllMarkets:
    """``load_all_markets`` — CSV loading and merging."""

    def test_no_files_returns_empty(self):
        """No CSV files present returns an empty DataFrame with expected columns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            df = load_all_markets(tmpdir)
            assert isinstance(df, pl.DataFrame)
            assert "id" in df.columns
            assert "clobTokenIds" in df.columns
            assert df.is_empty()

    def test_load_missing_only(self):
        """Load just a missing_markets.csv."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import csv as csv_mod

            csv_path = os.path.join(tmpdir, "missing_markets.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv_mod.writer(f)
                writer.writerow(["id", "clobTokenIds", "conditionId", "question", "slug", "closed"])
                writer.writerow(['c1', '["t1","t2"]', 'c1', 'Test?', 'test-slug', 'false'])
            df = load_all_markets(tmpdir)
            assert len(df) == 1
            assert df["id"][0] == "c1"

    def test_dedup_by_id(self):
        """When both files contain the same id, only one row survives."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # markets.csv
            with open(os.path.join(tmpdir, "markets.csv"), "w", newline="", encoding="utf-8") as f:
                f.write("id,clobTokenIds\n")
                f.write('dup,["old"]\n')
            # missing_markets.csv (same id)
            with open(os.path.join(tmpdir, "missing_markets.csv"), "w", newline="", encoding="utf-8") as f:
                f.write("id,clobTokenIds,question\n")
                f.write('dup,["new"],Q?\n')
            df = load_all_markets(tmpdir)
            assert len(df) == 1
            # First occurrence ("old") wins (keep="first")
            assert '"old"' in df["clobTokenIds"][0]
