"""
Unit tests for hbt_converter — event conversion, timestamp handling, correct ordering.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from polymarket_l2_collector.hbt_converter import (
    BUY_EVENT,
    DEPTH_CLEAR_EVENT,
    DEPTH_SNAPSHOT_EVENT,
    EXCH_EVENT,
    LOCAL_EVENT,
    POLY_MAX_PRICE,
    POLY_MIN_PRICE,
    SELL_EVENT,
    TRADE_EVENT,
    _extract_book_side,
    _iterable_items,
    _local_ts_ns,
    _make_book_events,
    _make_trade_events,
    _ts_str_to_ns,
    correct_event_order,
    event_dtype,
    load_event_array,
    rows_to_hbt,
    save_event_array,
)

# ── Event dtype structure ────────────────────────────────────────────────


class TestEventDtype:
    def test_dtype_field_names(self):
        assert event_dtype.names == ("ev", "exch_ts", "local_ts", "px", "qty", "order_id", "ival", "fval")

    def test_dtype_field_types(self):
        assert event_dtype["ev"].kind == "u"  # unsigned
        assert event_dtype["exch_ts"].kind == "i"  # signed
        assert event_dtype["px"].kind == "f"  # float


# ── Timestamp helpers ────────────────────────────────────────────────────


class TestTsStrToNs:
    def test_basic_conversion(self):
        assert _ts_str_to_ns("1000") == 1_000_000_000

    def test_zero(self):
        assert _ts_str_to_ns("0") == 0

    def test_large_timestamp(self):
        # 2026-01-01 in ms
        assert _ts_str_to_ns("1767225600000") == 1767225600000 * 1_000_000


class TestLocalTsNs:
    def test_uses_constant_latency(self):
        row = {"timestamp": "1000", "local_timestamp": "2000"}
        exch_ns = _ts_str_to_ns("1000")
        result = _local_ts_ns(row, exch_ns, constant_latency=5_000_000)
        assert result == exch_ns + 5_000_000

    def test_falls_back_to_local_timestamp(self):
        row = {"timestamp": "1000", "local_timestamp": "2000"}
        exch_ns = _ts_str_to_ns("1000")
        result = _local_ts_ns(row, exch_ns, constant_latency=None)
        assert result == _ts_str_to_ns("2000")

    def test_falls_back_to_default_latency(self):
        row = {"timestamp": "1000"}  # no local_timestamp
        exch_ns = _ts_str_to_ns("1000")
        result = _local_ts_ns(row, exch_ns, constant_latency=None)
        assert result == exch_ns + 20_000_000

    def test_empty_local_timestamp(self):
        row = {"timestamp": "1000", "local_timestamp": ""}
        exch_ns = _ts_str_to_ns("1000")
        result = _local_ts_ns(row, exch_ns, constant_latency=None)
        assert result == exch_ns + 20_000_000


# ── Extract book side ────────────────────────────────────────────────────


class TestExtractBookSide:
    def test_dict_with_price_size(self):
        levels = [{"price": 0.5, "size": 100}, {"price": 0.6, "size": 200}]
        prices, sizes = _extract_book_side(levels)
        assert prices == [0.5, 0.6]
        assert sizes == [100.0, 200.0]

    def test_dict_with_p_s(self):
        """Handle compact format from optimized Parquet storage."""
        levels = [{"p": 48, "s": 3000}, {"p": 47, "s": 1500}]
        prices, sizes = _extract_book_side(levels)
        assert prices == [48.0, 47.0]
        assert sizes == [3000.0, 1500.0]

    def test_list_of_lists(self):
        levels = [[0.5, 100], [0.6, 200]]
        prices, sizes = _extract_book_side(levels)
        assert prices == [0.5, 0.6]
        assert sizes == [100.0, 200.0]

    def test_empty_levels(self):
        assert _extract_book_side([]) == ([], [])

    def test_none_levels(self):
        assert _extract_book_side(None) == ([], [])

    def test_mixed_with_none(self):
        levels = [{"price": 0.5, "size": None}]
        prices, sizes = _extract_book_side(levels)
        assert prices == []  # level with None size is skipped entirely
        assert sizes == []

    def test_missing_price_skipped(self):
        levels = [{"size": 100}]  # no price
        prices, sizes = _extract_book_side(levels)
        assert prices == []
        assert sizes == []


# ── Iterable items ───────────────────────────────────────────────────────


class TestIterableItems:
    def test_list_passthrough(self):
        assert _iterable_items([1, 2, 3]) == [1, 2, 3]

    def test_none_returns_empty(self):
        assert _iterable_items(None) == []

    def test_string_returns_empty(self):
        assert _iterable_items("hello") == []

    def test_numpy_array(self):
        arr = np.array([1, 2, 3])
        assert _iterable_items(arr) == [1, 2, 3]


# ── Book events ──────────────────────────────────────────────────────────


class TestMakeBookEvents:
    def test_empty_returns_empty(self):
        result = _make_book_events([])
        assert len(result) == 0

    def test_single_book_row_two_levels(self):
        """A single book row with 2 bid levels and 2 ask levels produces
        6 events: 1 clear-bid + 2 bid snaps + 1 clear-ask + 2 ask snaps."""
        rows = [
            {
                "timestamp": "1000",
                "local_timestamp": "1100",
                "bids": [{"price": 0.50, "size": 100}, {"price": 0.49, "size": 200}],
                "asks": [{"price": 0.51, "size": 150}, {"price": 0.52, "size": 50}],
            }
        ]
        events = _make_book_events(rows)
        assert len(events) == 6

        # First event: clear bid
        assert events[0]["ev"] == DEPTH_CLEAR_EVENT | BUY_EVENT
        assert events[0]["exch_ts"] == _ts_str_to_ns("1000")
        assert events[0]["qty"] == 0.0

        # Second event: bid level 1
        assert events[1]["ev"] == DEPTH_SNAPSHOT_EVENT | BUY_EVENT
        assert events[1]["px"] == 0.50
        assert events[1]["qty"] == 100.0

        # Third event: bid level 2
        assert events[2]["ev"] == DEPTH_SNAPSHOT_EVENT | BUY_EVENT
        assert events[2]["px"] == 0.49
        assert events[2]["qty"] == 200.0

        # Fourth event: clear ask
        assert events[3]["ev"] == DEPTH_CLEAR_EVENT | SELL_EVENT

        # Fifth event: ask level 1
        assert events[4]["ev"] == DEPTH_SNAPSHOT_EVENT | SELL_EVENT
        assert events[4]["px"] == 0.51

        # Sixth event: ask level 2
        assert events[5]["ev"] == DEPTH_SNAPSHOT_EVENT | SELL_EVENT
        assert events[5]["px"] == 0.52

    def test_sorts_by_timestamp(self):
        """Events are sorted by timestamp."""
        rows = [
            {"timestamp": "2000", "bids": [{"price": 0.50, "size": 100}], "asks": []},
            {"timestamp": "1000", "bids": [{"price": 0.49, "size": 200}], "asks": []},
        ]
        events = _make_book_events(rows)
        # Should be sorted: ts 1000 first, then ts 2000
        assert events[0]["exch_ts"] == _ts_str_to_ns("1000")
        assert events[3]["exch_ts"] == _ts_str_to_ns("2000")

    def test_empty_bids_uses_min_price(self):
        """Empty bids should use POLY_MIN_PRICE as the clear price."""
        rows = [
            {"timestamp": "1000", "bids": [], "asks": [{"price": 0.51, "size": 100}]}
        ]
        events = _make_book_events(rows)
        assert events[0]["ev"] == DEPTH_CLEAR_EVENT | BUY_EVENT
        assert events[0]["px"] == POLY_MIN_PRICE

    def test_empty_asks_uses_max_price(self):
        """Empty asks should use POLY_MAX_PRICE as the clear price."""
        rows = [
            {"timestamp": "1000", "bids": [{"price": 0.49, "size": 100}], "asks": []}
        ]
        events = _make_book_events(rows)
        # clear-ask is the 3rd event (clear-bid, snap-bid, clear-ask)
        assert events[2]["ev"] == DEPTH_CLEAR_EVENT | SELL_EVENT
        assert events[2]["px"] == POLY_MAX_PRICE

    def test_compact_format(self):
        """Handle bids/asks stored in compact 'p'/'s' format."""
        rows = [
            {
                "timestamp": "1000",
                "bids": [{"p": 48, "s": 3000}],
                "asks": [{"p": 52, "s": 2500}],
            }
        ]
        events = _make_book_events(rows)
        assert len(events) == 4
        # Bid level price restored from compact
        assert events[1]["px"] == 48.0
        assert events[1]["qty"] == 3000.0
        assert events[3]["px"] == 52.0


# ── Trade events ─────────────────────────────────────────────────────────


class TestMakeTradeEvents:
    def test_empty_returns_empty(self):
        assert len(_make_trade_events([])) == 0

    def test_buy_trade(self):
        rows = [
            {"timestamp": "1000", "local_timestamp": "1100", "price": "0.50", "size": "100", "side": "buy"}
        ]
        events = _make_trade_events(rows)
        assert len(events) == 1
        assert events[0]["ev"] == TRADE_EVENT | BUY_EVENT
        assert events[0]["exch_ts"] == _ts_str_to_ns("1000")
        assert events[0]["local_ts"] == _ts_str_to_ns("1100")
        assert events[0]["px"] == 0.50
        assert events[0]["qty"] == 100.0

    def test_sell_trade(self):
        rows = [
            {"timestamp": "2000", "price": "0.55", "size": "200", "side": "sell"}
        ]
        events = _make_trade_events(rows)
        assert len(events) == 1
        assert events[0]["ev"] == TRADE_EVENT | SELL_EVENT

    def test_bid_side_is_buy(self):
        rows = [
            {"timestamp": "1000", "price": "0.50", "size": "100", "side": "bid"}
        ]
        events = _make_trade_events(rows)
        assert events[0]["ev"] == TRADE_EVENT | BUY_EVENT

    def test_side_case_insensitive(self):
        rows = [
            {"timestamp": "1000", "price": "0.50", "size": "100", "side": "BUY"}
        ]
        events = _make_trade_events(rows)
        assert events[0]["ev"] == TRADE_EVENT | BUY_EVENT

    def test_default_side_buy(self):
        rows = [
            {"timestamp": "1000", "price": "0.50", "size": "100"}  # no side
        ]
        events = _make_trade_events(rows)
        assert events[0]["ev"] == TRADE_EVENT | BUY_EVENT

    def test_sorts_by_timestamp(self):
        rows = [
            {"timestamp": "3000", "price": "0.60", "size": "100", "side": "sell"},
            {"timestamp": "1000", "price": "0.50", "size": "100", "side": "buy"},
        ]
        events = _make_trade_events(rows)
        assert events[0]["exch_ts"] == _ts_str_to_ns("1000")
        assert events[1]["exch_ts"] == _ts_str_to_ns("3000")

    def test_multiple_trades(self):
        rows = [
            {"timestamp": "1000", "price": "0.50", "size": "100", "side": "buy"},
            {"timestamp": "1100", "price": "0.51", "size": "200", "side": "sell"},
            {"timestamp": "1200", "price": "0.52", "size": "150", "side": "buy"},
        ]
        events = _make_trade_events(rows)
        assert len(events) == 3
        assert float(events[0]["px"]) == 0.50
        assert float(events[1]["px"]) == 0.51
        assert float(events[2]["px"]) == 0.52


# ── Correct event order ──────────────────────────────────────────────────


class TestCorrectEventOrder:
    def test_empty_array(self):
        assert len(correct_event_order(np.zeros(0, dtype=event_dtype))) == 0

    def test_same_order(self):
        """When exch_ts and local_ts share the same ordering, no duplication."""
        data = np.zeros(2, dtype=event_dtype)
        data["exch_ts"] = [100, 200]
        data["local_ts"] = [110, 210]
        data["ev"] = [DEPTH_SNAPSHOT_EVENT | BUY_EVENT, DEPTH_SNAPSHOT_EVENT | BUY_EVENT]

        result = correct_event_order(data)
        assert len(result) == 2
        # Both events should have both flags set
        assert result[0]["ev"] & EXCH_EVENT
        assert result[0]["ev"] & LOCAL_EVENT
        assert result[1]["ev"] & EXCH_EVENT
        assert result[1]["ev"] & LOCAL_EVENT

    def test_reversed_local_timestamps(self):
        """When local_ts order differs from exch_ts, events are duplicated."""
        data = np.zeros(2, dtype=event_dtype)
        data["exch_ts"] = [100, 200]  # correctly ordered
        data["local_ts"] = [210, 110]  # reversed
        data["ev"] = [DEPTH_SNAPSHOT_EVENT | BUY_EVENT, DEPTH_SNAPSHOT_EVENT | SELL_EVENT]

        result = correct_event_order(data)
        # Should have 3 events (one duplicated)
        assert len(result) == 3
        # Event at exch_ts=100 (row 0) fires first on exchange clock
        assert result[0]["exch_ts"] == 100
        assert result[0]["ev"] & EXCH_EVENT
        assert not (result[0]["ev"] & LOCAL_EVENT)
        # Event at local_ts=110 (row 1) fires on local clock before row 0's local_ts=210
        assert result[1]["local_ts"] == 110
        assert result[1]["ev"] & EXCH_EVENT  # row 1 also has exch_ts=200 needing EXCH_EVENT
        assert result[1]["ev"] & LOCAL_EVENT  # matched at local_ts=110
        # Row 0's local_ts=210 fires last
        assert result[2]["local_ts"] == 210
        assert result[2]["ev"] & LOCAL_EVENT


# ── Rows to HBT (integration) ────────────────────────────────────────────


class TestRowsToHbt:
    def test_empty_input(self):
        assert len(rows_to_hbt([])) == 0

    def test_book_rows_conversion(self):
        rows = [
            {
                "timestamp": "1000",
                "local_timestamp": "1100",
                "bids": [{"price": 0.50, "size": 100}],
                "asks": [{"price": 0.51, "size": 150}],
            }
        ]
        events = rows_to_hbt(rows, data_type="orderbooks")
        assert len(events) > 0
        # Every event should have EXCH_EVENT (and possibly LOCAL_EVENT) set
        for ev in events:
            assert ev["ev"] & (EXCH_EVENT | LOCAL_EVENT) != 0
        assert events[0]["qty"] == 0.0  # clear event

    def test_trade_rows_conversion(self):
        rows = [
            {"timestamp": "1000", "local_timestamp": "1100", "price": "0.50", "size": "100", "side": "buy"},
            {"timestamp": "1200", "local_timestamp": "1300", "price": "0.51", "size": "200", "side": "sell"},
        ]
        events = rows_to_hbt(rows, data_type="trades")
        assert len(events) >= 2
        assert events[0]["ev"] & TRADE_EVENT != 0

        # Check buy → BUY_EVENT flag
        assert events[0]["ev"] & BUY_EVENT != 0
        assert events[0]["ev"] & SELL_EVENT == 0

        # Check sell → SELL_EVENT flag
        assert events[1]["ev"] & SELL_EVENT != 0

    def test_sorted_output(self):
        """Events should be sorted by exch_ts."""
        rows = [
            {"timestamp": "3000", "bids": [{"price": 0.60, "size": 100}], "asks": []},
            {"timestamp": "1000", "bids": [{"price": 0.50, "size": 200}], "asks": []},
            {"timestamp": "2000", "bids": [{"price": 0.55, "size": 150}], "asks": []},
        ]
        events = rows_to_hbt(rows, data_type="orderbooks")
        timestamps = [ev["exch_ts"] for ev in events if ev["ev"] & EXCH_EVENT]
        assert timestamps == sorted(timestamps)

    def test_invalid_data_type(self):
        with pytest.raises(ValueError, match="Unknown data_type"):
            rows_to_hbt([{"timestamp": "1000"}], data_type="invalid")

    def test_constant_latency(self):
        """When constant_latency is set, local_ts should be exch_ts + constant."""
        rows = [
            {"timestamp": "1000", "bids": [{"price": 0.50, "size": 100}], "asks": []},
        ]
        events = rows_to_hbt(rows, data_type="orderbooks", constant_latency=10_000_000)
        for ev in events:
            if ev["ev"] & LOCAL_EVENT:
                assert ev["local_ts"] == ev["exch_ts"] + 10_000_000

    def test_book_rows_without_bids_asks(self):
        """Rows without bids/asks keys still produce empty-side clear events."""
        rows = [
            {"timestamp": "1000", "price": "0.50", "size": "100", "side": "buy"},
        ]
        events = rows_to_hbt(rows, data_type="orderbooks")
        # 2 events: clear-bid (empty bids → min price) + clear-ask (empty asks → max price)
        assert len(events) == 2
        assert events[0]["ev"] & DEPTH_CLEAR_EVENT
        assert events[1]["ev"] & DEPTH_CLEAR_EVENT


# ── Save / Load ──────────────────────────────────────────────────────────


class TestSaveLoad:
    def test_save_and_load_roundtrip(self, tmp_path):
        data = np.zeros(3, dtype=event_dtype)
        data["ev"] = [TRADE_EVENT | BUY_EVENT, TRADE_EVENT | SELL_EVENT, DEPTH_SNAPSHOT_EVENT | BUY_EVENT]
        data["exch_ts"] = [100, 200, 300]
        data["local_ts"] = [110, 210, 310]
        data["px"] = [0.50, 0.51, 0.52]
        data["qty"] = [100.0, 200.0, 150.0]

        path = os.path.join(tmp_path, "events.npy")
        save_event_array(data, path)
        assert os.path.exists(path)

        loaded = load_event_array(path)
        assert len(loaded) == 3
        assert loaded.dtype == event_dtype
        assert loaded[0]["ev"] == TRADE_EVENT | BUY_EVENT
        assert loaded[2]["px"] == 0.52

    def test_save_creates_directory(self, tmp_path):
        data = np.zeros(1, dtype=event_dtype)
        data["exch_ts"] = [100]
        path = os.path.join(tmp_path, "sub", "deep", "events.npy")
        save_event_array(data, path)
        assert os.path.exists(path)


# ── CLI entry point ──────────────────────────────────────────────────────


class TestCLI:
    def test_main_importable(self):
        """The main() function should be importable (smoke test)."""
        from polymarket_l2_collector.hbt_converter import main as hbt_main
        assert callable(hbt_main)

    def test_cli_help_does_not_crash(self):
        """Running --help should not raise."""
        import sys
        from io import StringIO

        from polymarket_l2_collector.hbt_converter import main as hbt_main

        old_argv = sys.argv
        old_stdout = sys.stdout
        try:
            sys.argv = ["prog", "--help"]
            sys.stdout = StringIO()
            with pytest.raises(SystemExit):
                hbt_main()
        finally:
            sys.argv = old_argv
            sys.stdout = old_stdout


# ── Integration: export → convert pipeline ──────────────────────────────


class TestConvertFromDataDir:
    def test_no_data(self, tmp_path):
        """Empty data_dir returns 0 events."""
        from polymarket_l2_collector.hbt_converter import convert_from_data_dir

        out = os.path.join(tmp_path, "out.npy")
        count = convert_from_data_dir(str(tmp_path), output=out, data_type="trades")
        assert count == 0
        assert not os.path.exists(out)

    def test_with_trade_files(self, tmp_path):
        """Write some trade Parquet, convert, verify event count."""
        import pandas as pd

        from polymarket_l2_collector.file_cache import _build_file_path, optimize_for_parquet

        # Create a trade Parquet file
        fp = _build_file_path(str(tmp_path), "5m", "btc", "trades", 1000, "up")
        Path(fp).parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"price": "0.50", "size": "100", "side": "buy", "timestamp": "1000123", "local_timestamp": "1000200"},
        ]
        opt = optimize_for_parquet(rows)
        df = pd.DataFrame(opt)
        df.to_parquet(fp, engine="pyarrow")

        from polymarket_l2_collector.hbt_converter import convert_from_data_dir

        out = os.path.join(tmp_path, "trades.npy")
        count = convert_from_data_dir(str(tmp_path), output=out, data_type="trades")
        assert count > 0
        assert os.path.exists(out)

        loaded = np.load(out)
        assert len(loaded) > 0
        assert loaded.dtype == event_dtype
        # The trade event must have TRADE_EVENT in its flags
        assert loaded[0]["ev"] & TRADE_EVENT != 0

    def test_with_book_files(self, tmp_path):
        """Write some orderbook Parquet, convert, verify events."""
        import pandas as pd

        from polymarket_l2_collector.file_cache import _build_file_path

        fp = _build_file_path(str(tmp_path), "5m", "btc", "orderbooks", 1000, "up")
        Path(fp).parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {
                "bids": [{"price": 0.48, "size": 3000}, {"price": 0.47, "size": 1500}],
                "asks": [{"price": 0.52, "size": 2500}],
                "timestamp": "1000123",
                "local_timestamp": "1000200",
            },
        ]
        df = pd.DataFrame(rows)
        df.to_parquet(fp, engine="pyarrow")

        from polymarket_l2_collector.hbt_converter import convert_from_data_dir

        out = os.path.join(tmp_path, "books.npy")
        count = convert_from_data_dir(str(tmp_path), output=out, data_type="orderbooks")
        assert count > 0
        assert os.path.exists(out)

        loaded = np.load(out)
        assert len(loaded) > 0
        assert loaded["ev"][0] & DEPTH_CLEAR_EVENT != 0
