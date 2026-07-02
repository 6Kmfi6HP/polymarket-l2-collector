"""
Unit tests for Parquet optimisation helpers.
"""

from polymarket_l2_collector.file_cache import (
    _build_file_path,
    _parse_file_path,
    optimize_for_parquet,
    restore_from_parquet,
)


class TestFileCacheKey:
    """File path parsing and building."""

    def test_build_path_5m_btc_orderbook_up(self):
        path = _build_file_path("data", "5m", "btc", "orderbooks", 1765359900, "up")
        assert path == "data/5m/btc/orderbooks/1765359900up.parquet"

    def test_build_path_15m_eth_trades_up(self):
        path = _build_file_path("data", "15m", "eth", "trades", 1765360800, "up")
        assert path == "data/15m/eth/trades/1765360800up.parquet"

    def test_parse_path(self):
        interval, coin, data_type, direction, ts = _parse_file_path("data/5m/btc/orderbooks/1765359900up.parquet")
        assert interval == "5m"
        assert coin == "btc"
        assert data_type == "orderbooks"
        assert direction == "up"
        assert ts == 1765359900

    def test_build_path_down_direction(self):
        path = _build_file_path("data", "5m", "btc", "orderbooks", 1765359900, "down")
        assert path == "data/5m/btc/orderbooks/1765359900down.parquet"

    def test_parse_path_down_direction(self):
        interval, coin, data_type, direction, ts = _parse_file_path("data/5m/btc/orderbooks/1765359900down.parquet")
        assert interval == "5m"
        assert coin == "btc"
        assert data_type == "orderbooks"
        assert direction == "down"
        assert ts == 1765359900

    def test_parse_path_down(self):
        interval, coin, data_type, direction, ts = _parse_file_path("data/15m/eth/trades/1765360800down.parquet")
        assert direction == "down"
        assert ts == 1765360800


class TestOptimisation:
    """Integer ↔ float optimisation helpers."""

    def test_optimize_book_price_size(self):
        raw = [
            {
                "bids": [{"price": "0.48", "size": "30.0"}],
                "asks": [{"price": "0.52", "size": "25.0"}],
                "timestamp": "1765359900123",
            }
        ]
        opt = optimize_for_parquet(raw)
        assert opt[0]["bids"][0]["p"] == 48
        assert opt[0]["bids"][0]["s"] == 3000
        assert opt[0]["asks"][0]["p"] == 52
        assert opt[0]["asks"][0]["s"] == 2500
        assert opt[0]["timestamp"] == 1765359900123

    def test_restore_book_price_size(self):
        opt = [
            {
                "bids": [{"p": 48, "s": 3000}],
                "asks": [{"p": 52, "s": 2500}],
            }
        ]
        restored = restore_from_parquet(opt)
        assert restored[0]["bids"][0]["price"] == 0.48
        assert restored[0]["bids"][0]["size"] == 30.0
        assert restored[0]["asks"][0]["price"] == 0.52
        assert restored[0]["asks"][0]["size"] == 25.0

    def test_optimize_trade_price_size(self):
        raw = [{"price": "0.50", "size": "100.0", "side": "buy"}]
        opt = optimize_for_parquet(raw)
        assert opt[0]["p"] == 50
        assert opt[0]["s"] == 10000
        assert opt[0]["side"] == "buy"

    def test_restore_trade_price_size(self):
        opt = [{"p": 50, "s": 10000, "side": "buy"}]
        restored = restore_from_parquet(opt)
        assert restored[0]["price"] == 0.50
        assert restored[0]["size"] == 100.0

    def test_roundtrip_preserves_data(self):
        """Optimise → restore should yield the same data."""
        raw = [
            {
                "bids": [{"price": "0.48", "size": "30.0"}],
                "asks": [{"price": "0.52", "size": "25.0"}],
                "timestamp": "1765359900123",
            },
            {"price": "0.50", "size": "100.0", "side": "buy", "timestamp": "1765359901123"},
        ]
        opt = optimize_for_parquet(raw)
        restored = restore_from_parquet(opt)

        # Book entry
        assert restored[0]["bids"][0]["price"] == 0.48
        assert restored[0]["bids"][0]["size"] == 30.0
        assert restored[0]["timestamp"] == 1765359900123

        # Trade entry
        assert restored[1]["price"] == 0.50
        assert restored[1]["size"] == 100.0
        assert restored[1]["side"] == "buy"
        assert restored[1]["timestamp"] == 1765359901123

    def test_empty_data(self):
        assert optimize_for_parquet([]) == []
        assert restore_from_parquet([]) == []

    def test_preserves_unknown_fields(self):
        """Unknown fields should be passed through unchanged."""
        raw = [{"price": "1.50", "unknown_field": "keep_me", "flag": True}]
        opt = optimize_for_parquet(raw)
        assert opt[0]["unknown_field"] == "keep_me"
        assert opt[0]["flag"] is True

    def test_restore_preserves_unknown_fields(self):
        opt = [{"p": 150, "unknown": "data", "flag": False}]
        restored = restore_from_parquet(opt)
        assert restored[0]["unknown"] == "data"
        assert restored[0]["flag"] is False

    def test_none_values_handled(self):
        """None values should not crash."""
        raw = [{"price": None, "size": None, "bids": None}]
        opt = optimize_for_parquet(raw)
        restored = restore_from_parquet(opt)
        assert "p" not in opt[0] or opt[0].get("p") is None
        assert len(restored) == 1


# ── _parse_file_path edge cases ────────────────────────────────────────


class TestParseFilePathEdgeCases:
    def test_absolute_path(self):
        interval, coin, data_type, direction, ts = _parse_file_path(
            "/tmp/xxx/5m/btc/trades/1765359900up.parquet"
        )
        assert interval == "5m"
        assert coin == "btc"

    def test_absolute_path_down(self):
        interval, coin, data_type, direction, ts = _parse_file_path(
            "/abs/path/15m/eth/orderbooks/2000down.parquet"
        )
        assert direction == "down"
        assert ts == 2000


# ── _write_parquet_atomic ───────────────────────────────────────────────


class TestWriteParquetAtomic:
    def test_writes_and_reads(self, tmp_path):
        import pandas as pd

        from polymarket_l2_collector.file_cache import _write_parquet_atomic

        out = tmp_path / "test.parquet"
        data = [{"col": "a", "val": 1}]
        _write_parquet_atomic(data, str(out))
        assert out.exists()
        df = pd.read_parquet(str(out))
        assert len(df) == 1
        assert df["col"].iloc[0] == "a"

    def test_atomic_replaces_existing(self, tmp_path):
        from polymarket_l2_collector.file_cache import _write_parquet_atomic

        out = tmp_path / "test.parquet"
        _write_parquet_atomic([{"x": 1}], str(out))
        _write_parquet_atomic([{"x": 2}], str(out))
        import pandas as pd

        df = pd.read_parquet(str(out))
        assert df["x"].iloc[0] == 2

    def test_creates_dirs(self, tmp_path):
        from polymarket_l2_collector.file_cache import _write_parquet_atomic

        nested = tmp_path / "a" / "b" / "c" / "test.parquet"
        _write_parquet_atomic([{"v": 1}], str(nested))
        assert nested.exists()


# ── Cache flush helpers ─────────────────────────────────────────────────


class TestFlushCacheEntry:
    def test_returns_zero_for_missing_key(self, tmp_path):
        from polymarket_l2_collector.file_cache import _flush_cache_entry

        assert _flush_cache_entry({}, "nonexistent", str(tmp_path / "f.parquet")) == 0

    def test_returns_zero_for_no_data(self, tmp_path):
        from polymarket_l2_collector.file_cache import _flush_cache_entry

        d = {"k": {"data": []}}
        assert _flush_cache_entry(d, "k", str(tmp_path / "f.parquet")) == 0


# ── save_trades / save_book ─────────────────────────────────────────────


class TestSaveTrades:
    def test_buffers_and_flushes_on_threshold(self, tmp_path):
        from polymarket_l2_collector.file_cache import (
            flush_all_caches,
            save_trades,
            trades_cache_dict,
        )

        # Reset cache
        trades_cache_dict.clear()
        fp = str(tmp_path / "5m" / "btc" / "trades" / "1000up.parquet")

        # Save below threshold — no flush yet
        save_trades([{"price": "0.50"}], fp)
        key = "5m/btc/trades/up/1000"
        assert key in trades_cache_dict
        assert len(trades_cache_dict[key]["data"]) == 1

        # Flush all
        n = flush_all_caches()
        assert n >= 1
        assert tmp_path.joinpath("5m/btc/trades/1000up.parquet").exists()

    def test_flush_idempotent(self, tmp_path):
        from polymarket_l2_collector.file_cache import flush_all_caches, trades_cache_dict

        trades_cache_dict.clear()
        n1 = flush_all_caches()
        n2 = flush_all_caches()
        assert n1 == 0
        assert n2 == 0


class TestSaveBook:
    def test_buffers(self, tmp_path):
        from polymarket_l2_collector.file_cache import (
            flush_all_caches,
            orderbook_cache_dict,
            save_book,
        )

        orderbook_cache_dict.clear()
        fp = str(tmp_path / "5m" / "btc" / "orderbooks" / "1000up.parquet")
        save_book([{"bids": [], "asks": []}], fp)
        assert len(orderbook_cache_dict) == 1

        n = flush_all_caches()
        assert n >= 1


# ── drop_empty_cache_windows ────────────────────────────────────────────


class TestDropEmptyCacheWindows:
    def test_removes_empty_entries_over_limit(self):
        from polymarket_l2_collector.file_cache import (
            drop_empty_cache_windows,
            trades_cache_dict,
        )

        trades_cache_dict.clear()
        for i in range(5):
            trades_cache_dict[f"5m/btc/trades/down/{i}"] = {"data": [], "file_path": f"/tmp/{i}.parquet"}
        removed = drop_empty_cache_windows(max_windows=3)
        assert removed >= 2
        assert len(trades_cache_dict) <= 3
