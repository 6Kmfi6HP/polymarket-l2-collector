"""
Unit tests for data_formatter — format_orderbook, format_trade, _get_asset_price.

Tests cover:
  - Normal formatting for both orderbook and trade messages
  - Asset-to-coin mapping (valid, unknown, missing asset_id)
  - Window timestamp propagation
  - Binance price lookup (available / missing coin)
  - Edge cases: empty messages, missing fields, None values
"""

from __future__ import annotations

from unittest.mock import patch

from polymarket_l2_collector.data_formatter import (
    _get_asset_price,
    format_orderbook,
    format_trade,
)

_ASSET_MAP = {
    "token1": "btc_up",
    "token2": "btc_down",
    "token3": "eth_up",
}


# ── _get_asset_price ────────────────────────────────────────────────────


class TestGetAssetPrice:
    def test_known_coin_returns_mid(self) -> None:
        with patch(
            "polymarket_l2_collector.data_formatter.current_prices",
            {"BTCUSDT": {"mid": 67000.5, "bid": 66900, "ask": 67100}},
        ):
            assert _get_asset_price("btc") == 67000.5

    def test_unknown_coin_returns_zero(self) -> None:
        with patch(
            "polymarket_l2_collector.data_formatter.current_prices",
            {},
        ):
            assert _get_asset_price("sol") == 0.0

    def test_missing_mid_returns_zero(self) -> None:
        with patch(
            "polymarket_l2_collector.data_formatter.current_prices",
            {"ETHUSDT": {"bid": 3000}},
        ):
            assert _get_asset_price("eth") == 0.0

    def test_uses_uppercase_symbol(self) -> None:
        with patch(
            "polymarket_l2_collector.data_formatter.current_prices",
            {"SOLUSDT": {"mid": 150.0}},
        ):
            assert _get_asset_price("sol") == 150.0

    def test_empty_prices_dict(self) -> None:
        with patch(
            "polymarket_l2_collector.data_formatter.current_prices",
            {},
        ):
            assert _get_asset_price("btc") == 0.0

    def test_none_info(self) -> None:
        with patch(
            "polymarket_l2_collector.data_formatter.current_prices",
            {"BTCUSDT": None},
        ):
            assert _get_asset_price("btc") == 0.0


# ── format_orderbook ────────────────────────────────────────────────────


class TestFormatOrderbook:
    def test_single_message(self) -> None:
        msgs = [
            {
                "asset_id": "token1",
                "bids": [["1", "10"]],
                "asks": [["2", "5"]],
                "timestamp": "1000",
            }
        ]
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=100.0):
            rows = format_orderbook(msgs, _ASSET_MAP, window_open_ts=1765359900)

        assert len(rows) == 1
        row = rows[0]
        assert row["bids"] == [["1", "10"]]
        assert row["asks"] == [["2", "5"]]
        assert row["local_timestamp"] == "100000"
        assert row["timestamp"] == "1000"
        assert row["window_open_ts"] == 1765359900
        # asset_price is a float; don't assert exact value with mock

    def test_multiple_messages(self) -> None:
        msgs = [
            {"asset_id": "token1", "bids": [], "asks": [], "timestamp": "1"},
            {"asset_id": "token2", "bids": [], "asks": [], "timestamp": "2"},
        ]
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=200.0):
            rows = format_orderbook(msgs, _ASSET_MAP)

        assert len(rows) == 2
        assert rows[0]["timestamp"] == "1"
        assert rows[1]["timestamp"] == "2"

    def test_skips_unknown_asset_id(self) -> None:
        """Messages with asset_id not in asset_to_coin are skipped."""
        msgs = [
            {"asset_id": "token1", "bids": [], "asks": [], "timestamp": "1"},
            {"asset_id": "unknown_token", "bids": [], "asks": [], "timestamp": "2"},
            {"asset_id": "token2", "bids": [], "asks": [], "timestamp": "3"},
        ]
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=0.0):
            rows = format_orderbook(msgs, _ASSET_MAP)

        assert len(rows) == 2
        assert rows[0]["timestamp"] == "1"
        assert rows[1]["timestamp"] == "3"

    def test_skips_missing_asset_id(self) -> None:
        msgs = [{"bids": [], "asks": [], "timestamp": "1"}]  # no asset_id key
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=0.0):
            rows = format_orderbook(msgs, _ASSET_MAP)
        assert len(rows) == 0

    def test_handles_empty_input(self) -> None:
        rows = format_orderbook([], _ASSET_MAP)
        assert rows == []

    def test_missing_bids_asks_default_to_empty(self) -> None:
        msgs = [{"asset_id": "token1", "timestamp": "1"}]
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=0.0):
            rows = format_orderbook(msgs, _ASSET_MAP)

        assert len(rows) == 1
        assert rows[0]["bids"] == []
        assert rows[0]["asks"] == []

    def test_coin_name_from_tag(self) -> None:
        """coin is derived from tag before underscore."""
        msgs = [{"asset_id": "token1", "bids": [], "asks": [], "timestamp": "1"}]
        with (
            patch("polymarket_l2_collector.data_formatter.time.time", return_value=0.0),
            patch(
                "polymarket_l2_collector.data_formatter.current_prices",
                {"BTCUSDT": {"mid": 50000.0}},
            ),
        ):
            rows = format_orderbook(msgs, _ASSET_MAP)
        assert rows[0]["asset_price"] == 50000.0

    def test_none_window_open_ts(self) -> None:
        msgs = [{"asset_id": "token1", "bids": [], "asks": [], "timestamp": "1"}]
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=0.0):
            rows = format_orderbook(msgs, _ASSET_MAP, window_open_ts=None)
        assert rows[0]["window_open_ts"] is None

    def test_timestamp_falls_back_to_now(self) -> None:
        """If message has no timestamp, use local_timestamp."""
        msgs = [{"asset_id": "token1", "bids": [], "asks": []}]
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=123456.0):
            rows = format_orderbook(msgs, _ASSET_MAP)
        assert rows[0]["timestamp"] == "123456000"


# ── format_trade ────────────────────────────────────────────────────────


class TestFormatTrade:
    def test_single_trade(self) -> None:
        msgs = [
            {
                "asset_id": "token1",
                "price": "0.50",
                "size": "100.0",
                "side": "BUY",
                "timestamp": "1000",
            }
        ]
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=100.0):
            rows = format_trade(msgs, _ASSET_MAP, window_open_ts=1765359900)

        assert len(rows) == 1
        row = rows[0]
        assert row["price"] == "0.50"
        assert row["size"] == "100.0"
        assert row["side"] == "buy"
        assert row["local_timestamp"] == "100000"
        assert row["timestamp"] == "1000"
        assert row["window_open_ts"] == 1765359900

    def test_side_is_lowered(self) -> None:
        """Side should always be lowercase."""
        for raw_side in ("BUY", "buy", "Buy", "SELL"):
            msgs = [{"asset_id": "token1", "price": "1", "size": "1", "side": raw_side, "timestamp": "1"}]
            with patch("polymarket_l2_collector.data_formatter.time.time", return_value=0.0):
                rows = format_trade(msgs, _ASSET_MAP)
            assert rows[0]["side"] == raw_side.lower()

    def test_multiple_trades(self) -> None:
        msgs = [
            {"asset_id": "token1", "price": "1", "size": "10", "side": "BUY", "timestamp": "1"},
            {"asset_id": "token2", "price": "2", "size": "20", "side": "SELL", "timestamp": "2"},
        ]
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=0.0):
            rows = format_trade(msgs, _ASSET_MAP)

        assert len(rows) == 2
        assert rows[0]["price"] == "1"
        assert rows[1]["price"] == "2"

    def test_skips_unknown_asset(self) -> None:
        msgs = [
            {"asset_id": "token1", "price": "1", "size": "10", "side": "BUY", "timestamp": "1"},
            {"asset_id": "no_such_token", "price": "2", "size": "20", "side": "SELL", "timestamp": "2"},
        ]
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=0.0):
            rows = format_trade(msgs, _ASSET_MAP)
        assert len(rows) == 1

    def test_handles_empty_input(self) -> None:
        assert format_trade([], _ASSET_MAP) == []

    def test_missing_price_size_default(self) -> None:
        msgs = [{"asset_id": "token1", "side": "BUY", "timestamp": "1"}]
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=0.0):
            rows = format_trade(msgs, _ASSET_MAP)
        assert rows[0]["price"] == "0"
        assert rows[0]["size"] == "0"

    def test_missing_side_default(self) -> None:
        msgs = [{"asset_id": "token1", "price": "1", "size": "1", "timestamp": "1"}]
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=0.0):
            rows = format_trade(msgs, _ASSET_MAP)
        assert rows[0]["side"] == ""

    def test_timestamp_falls_back_to_now(self) -> None:
        msgs = [{"asset_id": "token1", "price": "1", "size": "1", "side": "BUY"}]
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=500.0):
            rows = format_trade(msgs, _ASSET_MAP)
        assert rows[0]["timestamp"] == "500000"

    def test_none_window_open_ts(self) -> None:
        msgs = [{"asset_id": "token1", "price": "1", "size": "1", "side": "BUY", "timestamp": "1"}]
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=0.0):
            rows = format_trade(msgs, _ASSET_MAP, window_open_ts=None)
        assert rows[0]["window_open_ts"] is None

    def test_ignores_missing_asset_id_key(self) -> None:
        """A message dict without asset_id should be skipped."""
        msgs = [{"price": "1", "size": "1", "side": "BUY", "timestamp": "1"}]
        with patch("polymarket_l2_collector.data_formatter.time.time", return_value=0.0):
            rows = format_trade(msgs, _ASSET_MAP)
        assert len(rows) == 0
