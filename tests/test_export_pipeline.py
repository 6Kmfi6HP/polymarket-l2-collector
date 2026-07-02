"""
Unit tests for the export pipeline — scan, collect, dedup, and output.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd

from polymarket_l2_collector.export_pipeline import (
    _parse_tail,
    collect_orderbooks,
    collect_trades,
    dedup_rows,
    export_pipeline,
    scan_files,
    summary_report,
    write_csv,
    write_parquet,
)
from polymarket_l2_collector.file_cache import _build_file_path, optimize_for_parquet

# ── Path parsing ──────────────────────────────────────────────────────


class TestParseTail:
    def test_valid_path(self):
        info = _parse_tail("data/5m/btc/trades/1765359900up.parquet")
        assert info is not None
        assert info["interval"] == "5m"
        assert info["coin"] == "btc"
        assert info["data_type"] == "trades"
        assert info["direction"] == "up"
        assert info["window_ts"] == 1765359900

    def test_valid_path_down(self):
        info = _parse_tail("data/5m/eth/orderbooks/1765360800down.parquet")
        assert info is not None
        assert info["direction"] == "down"
        assert info["coin"] == "eth"
        assert info["data_type"] == "orderbooks"

    def test_absolute_path(self):
        info = _parse_tail("/tmp/xxx/15m/btc/trades/1765359900up.parquet")
        assert info is not None
        assert info["interval"] == "15m"
        assert info["coin"] == "btc"

    def test_too_short(self):
        assert _parse_tail("short/path.parquet") is None

    def test_non_parquet(self):
        assert _parse_tail("data/5m/btc/trades/foo.csv") is None

    def test_missing_ts(self):
        assert _parse_tail("data/5m/btc/trades/nodigitsup.parquet") is None


# ── File scanning ─────────────────────────────────────────────────────


class TestScanFiles:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def _make_file(self, interval, coin, data_type, ts, direction="up"):
        fp = _build_file_path(self.tmpdir, interval, coin, data_type, ts, direction)
        Path(fp).parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame({"timestamp": [str(ts * 1000)]})
        df.to_parquet(fp, engine="pyarrow")
        return fp

    def test_scan_finds_all_files(self):
        self._make_file("5m", "btc", "trades", 1000)
        self._make_file("5m", "btc", "trades", 1300)
        self._make_file("15m", "eth", "orderbooks", 2000)
        files = scan_files(self.tmpdir)
        assert len(files) == 3

    def test_scan_filter_by_type(self):
        self._make_file("5m", "btc", "trades", 1000)
        self._make_file("5m", "btc", "orderbooks", 1000)
        files = scan_files(self.tmpdir, data_type="trades")
        assert len(files) == 1
        assert files[0]["data_type"] == "trades"

    def test_scan_sorted_by_ts(self):
        self._make_file("5m", "btc", "trades", 1300)
        self._make_file("5m", "btc", "trades", 1000)
        self._make_file("5m", "btc", "trades", 1150)
        files = scan_files(self.tmpdir)
        timestamps = [f["window_ts"] for f in files]
        assert timestamps == sorted(timestamps)

    def test_empty_directory(self):
        assert scan_files(self.tmpdir) == []


# ── Trade collection ──────────────────────────────────────────────────


class TestCollectTrades:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def _make_trade_file(self, interval, coin, direction, ts, price="0.50", size="100.0"):
        fp = _build_file_path(self.tmpdir, interval, coin, "trades", ts, direction)
        Path(fp).parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {
                "price": price,
                "size": size,
                "side": "buy",
                "local_timestamp": str(ts * 1000),
                "timestamp": str(ts * 1000),
                "asset_price": "67000",
                "window_open_ts": ts,
            }
        ]
        opt = optimize_for_parquet(rows)
        df = pd.DataFrame(opt)
        df.to_parquet(fp, engine="pyarrow")
        return fp

    def test_collect_single_file(self):
        self._make_trade_file("5m", "btc", "up", 1000)
        rows = collect_trades(self.tmpdir)
        assert len(rows) == 1
        assert rows[0]["coin"] == "btc"
        assert rows[0]["direction"] == "up"
        assert rows[0]["window_ts"] == 1000
        # Price restored from compressed format
        assert float(rows[0]["price"]) == 0.50

    def test_collect_multiple_files(self):
        self._make_trade_file("5m", "btc", "up", 1000)
        self._make_trade_file("5m", "btc", "up", 1300)
        self._make_trade_file("5m", "eth", "down", 1000, price="0.55")
        rows = collect_trades(self.tmpdir)
        assert len(rows) == 3

    def test_collect_empty_dir(self):
        assert collect_trades(self.tmpdir) == []


# ── Orderbook collection ──────────────────────────────────────────────


class TestCollectOrderbooks:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def _make_book_file(self, interval, coin, direction, ts):
        fp = _build_file_path(self.tmpdir, interval, coin, "orderbooks", ts, direction)
        Path(fp).parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {
                "bids": [{"p": 48, "s": 3000}],
                "asks": [{"p": 52, "s": 2500}],
                "local_timestamp": str(ts * 1000),
                "timestamp": str(ts * 1000),
                "asset_price": "67000",
                "window_open_ts": ts,
            }
        ]
        df = pd.DataFrame(rows)
        df.to_parquet(fp, engine="pyarrow")
        return fp

    def test_collect_single(self):
        self._make_book_file("5m", "btc", "up", 1000)
        rows = collect_orderbooks(self.tmpdir)
        assert len(rows) == 1
        assert rows[0]["coin"] == "btc"

    def test_collect_multiple(self):
        self._make_book_file("5m", "btc", "up", 1000)
        self._make_book_file("5m", "btc", "down", 1000)
        self._make_book_file("15m", "eth", "up", 2000)
        rows = collect_orderbooks(self.tmpdir)
        assert len(rows) == 3


# ── Dedup ─────────────────────────────────────────────────────────────


class TestDedup:
    def test_removes_exact_duplicate(self):
        rows = [
            {
                "window_ts": 1000, "coin": "btc", "direction": "up",
                "timestamp": "1000123", "price": "0.50", "size": "100",
            },
            {
                "window_ts": 1000, "coin": "btc", "direction": "up",
                "timestamp": "1000123", "price": "0.50", "size": "100",
            },
        ]
        result = dedup_rows(rows)
        assert len(result) == 1

    def test_preserves_unique(self):
        rows = [
            {
                "window_ts": 1000, "coin": "btc", "direction": "up",
                "timestamp": "1000123",
            },
            {
                "window_ts": 1000, "coin": "btc", "direction": "down",
                "timestamp": "1000123",
            },
        ]
        result = dedup_rows(rows)
        assert len(result) == 2

    def test_empty(self):
        assert dedup_rows([]) == []

    def test_first_occurrence_wins(self):
        """First occurrence of a duplicate key should be kept."""
        rows = [
            {"window_ts": 1000, "coin": "btc", "direction": "up", "timestamp": "1", "price": "0.50", "size": "100"},
            {"window_ts": 1000, "coin": "btc", "direction": "up", "timestamp": "1", "price": "0.50", "size": "100"},
        ]
        result = dedup_rows(rows)
        assert len(result) == 1
        assert result[0]["price"] == "0.50"


# ── File writing ──────────────────────────────────────────────────────


class TestWrite:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_write_parquet(self):
        rows = [{"col": "a", "window_ts": 1000}]
        out = os.path.join(self.tmpdir, "out.parquet")
        n = write_parquet(rows, out)
        assert n == 1
        df = pd.read_parquet(out)
        assert len(df) == 1
        assert df["col"].iloc[0] == "a"

    def test_write_csv(self):
        rows = [{"col": "a", "window_ts": 1000}]
        out = os.path.join(self.tmpdir, "out.csv")
        n = write_csv(rows, out)
        assert n == 1
        df = pd.read_csv(out)
        assert len(df) == 1

    def test_write_empty(self):
        assert write_csv([], "/tmp/nope.csv") == 0
        assert write_parquet([], "/tmp/nope.parquet") == 0


# ── Full pipeline ─────────────────────────────────────────────────────


class TestExportPipeline:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def _make_files(self):
        """Create a handful of trade and book files."""
        for interval, coin, direction in [("5m", "btc", "up"), ("5m", "btc", "down"), ("15m", "eth", "up")]:
            for data_type in ("trades", "orderbooks"):
                fp = _build_file_path(self.tmpdir, interval, coin, data_type, 1000, direction)
                Path(fp).parent.mkdir(parents=True, exist_ok=True)
                rows = [{"timestamp": str(1000 * 1000), "price": "0.50", "size": "100", "side": "buy"}]
                df = pd.DataFrame(rows)
                df.to_parquet(fp, engine="pyarrow")

    def test_trade_export_to_parquet(self):
        self._make_files()
        out = os.path.join(self.tmpdir, "exports.parquet")
        n = export_pipeline(data_dir=self.tmpdir, output=out, data_type="trades", dedup=True)
        assert n > 0
        df = pd.read_parquet(out)
        assert len(df) == n
        assert "coin" in df.columns
        assert "direction" in df.columns

    def test_trade_export_to_csv(self):
        self._make_files()
        out = os.path.join(self.tmpdir, "exports.csv")
        n = export_pipeline(data_dir=self.tmpdir, output=out, data_type="trades", dedup=True)
        assert n > 0
        df = pd.read_csv(out)
        assert len(df) == n

    def test_pipeline_no_data(self):
        out = os.path.join(self.tmpdir, "nope.parquet")
        n = export_pipeline(data_dir=self.tmpdir, output=out, data_type="trades")
        assert n == 0


# ── Summary report ────────────────────────────────────────────────────


class TestSummaryReport:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def _make_file(self, interval, coin, data_type, ts, direction="up"):
        fp = _build_file_path(self.tmpdir, interval, coin, data_type, ts, direction)
        Path(fp).parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame({"timestamp": [str(ts * 1000)]})
        df.to_parquet(fp, engine="pyarrow")

    def test_summary(self):
        self._make_file("5m", "btc", "trades", 1000)
        self._make_file("5m", "btc", "trades", 1300)
        self._make_file("5m", "btc", "orderbooks", 1000)
        self._make_file("15m", "eth", "trades", 2000)
        report = summary_report(self.tmpdir)
        assert report["total_files"] == 4
        assert report["by_type"]["trades"] == 3
        assert report["by_type"]["orderbooks"] == 1
        assert report["by_coin"]["btc"] == 3
        assert report["window_count"] == 3  # 3 distinct (interval, coin, direction, ts) combos
