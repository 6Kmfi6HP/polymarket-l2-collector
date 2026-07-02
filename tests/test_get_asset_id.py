"""
Unit tests for get_asset_id — Gamma API HTTP client (async + sync).

Tests cover:
  - get_market_info_by_slug (sync): success, not-found, network error
  - get_market_info_by_slug_async (async): success, non-200, empty, error
  - get_asset_id_async alias
  - JSON string field decoding (outcomes, outcomePrices, clobTokenIds)
  - URL/invalid-slug handling (strips http prefix)
  - search_markets: found, not-found, API failure
  - CLI entry point
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Sample market data ─────────────────────────────────────────────────

_SAMPLE_MARKETS = [
    {
        "question": "BTC > $100k?",
        "outcomes": ["Up", "Down"],
        "outcomePrices": ["0.5", "0.5"],
        "clobTokenIds": ["111", "222"],
        "closed": False,
    }
]

_SAMPLE_EVENTS = [
    {
        "title": "Bitcoin above $100k?",
        "slug": "btc-updown-5m-1765359900",
        "markets": _SAMPLE_MARKETS,
    }
]

# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def _mock_requests_get() -> Any:
    """Patch requests.get for sync tests."""
    with patch("polymarket_l2_collector.get_asset_id.requests.get") as mock:
        yield mock


@pytest.fixture
def _mock_aiohttp_session() -> Any:
    """Create a mock aiohttp session with a configured get response."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=_SAMPLE_EVENTS)

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = mock_resp
    return mock_session


# ── Sync: get_market_info_by_slug ──────────────────────────────────────


class TestGetMarketInfoBySlug:
    def test_returns_markets_on_success(self, _mock_requests_get: Any) -> None:
        _mock_requests_get.return_value.status_code = 200
        _mock_requests_get.return_value.json.return_value = _SAMPLE_EVENTS

        from polymarket_l2_collector.get_asset_id import get_market_info_by_slug

        result = get_market_info_by_slug("btc-updown-5m-1000")
        assert result is not None
        assert len(result) == 1
        assert result[0]["question"] == "BTC > $100k?"

    def test_returns_none_on_not_found(self, _mock_requests_get: Any) -> None:
        _mock_requests_get.return_value.status_code = 200
        _mock_requests_get.return_value.json.return_value = []

        from polymarket_l2_collector.get_asset_id import get_market_info_by_slug

        result = get_market_info_by_slug("nonexistent-slug")
        assert result is None

    def test_returns_none_on_http_error(self, _mock_requests_get: Any) -> None:
        import requests

        _mock_requests_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        from polymarket_l2_collector.get_asset_id import get_market_info_by_slug

        result = get_market_info_by_slug("fail-slug")
        assert result is None

    def test_strips_http_prefix(self, _mock_requests_get: Any) -> None:
        """Full URL as input should extract slug from path."""
        _mock_requests_get.return_value.status_code = 200
        _mock_requests_get.return_value.json.return_value = _SAMPLE_EVENTS

        from polymarket_l2_collector.get_asset_id import get_market_info_by_slug

        url = "https://polymarket.com/event/btc-updown-5m-1000"
        get_market_info_by_slug(url)
        # The URL should be constructed with just the slug part
        call_url = _mock_requests_get.call_args[0][0]
        assert "slug=btc-updown-5m-1000" in call_url

    def test_decodes_json_string_fields(self, _mock_requests_get: Any) -> None:
        """outcomes / clobTokenIds as JSON strings should be parsed to lists."""
        events = [
            {
                "title": "Test",
                "slug": "test-slug",
                "markets": [
                    {
                        "question": "Test?",
                        "outcomes": '["Yes","No"]',
                        "outcomePrices": '["0.5","0.5"]',
                        "clobTokenIds": '["111","222"]',
                    }
                ],
            }
        ]
        _mock_requests_get.return_value.status_code = 200
        _mock_requests_get.return_value.json.return_value = events

        from polymarket_l2_collector.get_asset_id import get_market_info_by_slug

        result = get_market_info_by_slug("test-slug")
        assert result is not None
        m = result[0]
        assert m["outcomes"] == ["Yes", "No"]
        assert m["clobTokenIds"] == ["111", "222"]
        assert m["outcomePrices"] == ["0.5", "0.5"]

    def test_handles_bad_json_strings_gracefully(self, _mock_requests_get: Any) -> None:
        """Malformed JSON string fields should be left as-is."""
        events = [
            {
                "title": "Test",
                "slug": "test-slug",
                "markets": [
                    {
                        "question": "Bad JSON?",
                        "outcomes": "{not-json",
                        "clobTokenIds": '["111","222"]',
                    }
                ],
            }
        ]
        _mock_requests_get.return_value.status_code = 200
        _mock_requests_get.return_value.json.return_value = events

        from polymarket_l2_collector.get_asset_id import get_market_info_by_slug

        result = get_market_info_by_slug("test-slug")
        assert result is not None
        # Bad JSON should remain as the original string, not crash
        assert isinstance(result[0]["outcomes"], str)


# ── Async: get_market_info_by_slug_async ───────────────────────────────


class TestGetMarketInfoBySlugAsync:
    @pytest.mark.asyncio
    async def test_returns_markets_on_success(self, _mock_aiohttp_session: Any) -> None:
        from polymarket_l2_collector.get_asset_id import get_market_info_by_slug_async

        result = await get_market_info_by_slug_async("btc-updown-5m-1000", session=_mock_aiohttp_session)
        assert result is not None
        assert len(result) == 1
        assert result[0]["question"] == "BTC > $100k?"

    @pytest.mark.asyncio
    async def test_returns_none_on_non_200(self, _mock_aiohttp_session: Any) -> None:
        _mock_aiohttp_session.get.return_value.__aenter__.return_value.status = 404

        from polymarket_l2_collector.get_asset_id import get_market_info_by_slug_async

        result = await get_market_info_by_slug_async("not-found", session=_mock_aiohttp_session)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_data(self, _mock_aiohttp_session: Any) -> None:
        _mock_aiohttp_session.get.return_value.__aenter__.return_value.json = AsyncMock(return_value=[])

        from polymarket_l2_collector.get_asset_id import get_market_info_by_slug_async

        result = await get_market_info_by_slug_async("empty", session=_mock_aiohttp_session)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, _mock_aiohttp_session: Any) -> None:
        _mock_aiohttp_session.get.side_effect = Exception("Network error")

        from polymarket_l2_collector.get_asset_id import get_market_info_by_slug_async

        result = await get_market_info_by_slug_async("fail", session=_mock_aiohttp_session)
        assert result is None

    @pytest.mark.asyncio
    async def test_strips_http_prefix(self, _mock_aiohttp_session: Any) -> None:
        from polymarket_l2_collector.get_asset_id import get_market_info_by_slug_async

        url = "https://polymarket.com/event/btc-updown-5m-1000"
        await get_market_info_by_slug_async(url, session=_mock_aiohttp_session)
        call_url = _mock_aiohttp_session.get.call_args[0][0]
        assert "slug=btc-updown-5m-1000" in call_url

    @pytest.mark.asyncio
    async def test_creates_session_when_none(self) -> None:
        """When session is None, a new session is created and closed."""
        with patch("polymarket_l2_collector.get_asset_id.aiohttp.ClientSession") as mock_cls:
            mock_resp = AsyncMock(spec=["status", "json", "__aenter__", "__aexit__"])
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=_SAMPLE_EVENTS)
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=None)

            mock_close = AsyncMock()
            mock_instance = MagicMock(spec=["get", "close"])
            mock_instance.get.return_value = mock_resp
            mock_instance.close = mock_close
            mock_cls.return_value = mock_instance

            from polymarket_l2_collector.get_asset_id import get_market_info_by_slug_async

            result = await get_market_info_by_slug_async("btc-updown-5m-1000")
            assert result is not None
            mock_cls.assert_called_once()
            mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_close_when_session_provided(self, _mock_aiohttp_session: Any) -> None:
        """When session is provided, it should NOT be closed by the function."""
        from polymarket_l2_collector.get_asset_id import get_market_info_by_slug_async

        await get_market_info_by_slug_async("btc-updown-5m-1000", session=_mock_aiohttp_session)
        assert _mock_aiohttp_session.close.call_count == 0


# ── get_asset_id_async alias ────────────────────────────────────────────


class TestGetAssetIdAsync:
    @pytest.mark.asyncio
    async def test_alias_returns_same_result(self, _mock_aiohttp_session: Any) -> None:
        from polymarket_l2_collector.get_asset_id import get_asset_id_async

        result = await get_asset_id_async("btc-updown-5m-1000", session=_mock_aiohttp_session)
        assert result is not None
        assert result[0]["question"] == "BTC > $100k?"


# ── search_markets ─────────────────────────────────────────────────────


class TestSearchMarkets:
    def test_prints_matching_results(self, _mock_requests_get: Any, capsys: Any) -> None:
        _mock_requests_get.return_value.status_code = 200
        _mock_requests_get.return_value.json.return_value = _SAMPLE_EVENTS

        from polymarket_l2_collector.get_asset_id import search_markets

        search_markets("Bitcoin")
        captured = capsys.readouterr()
        assert "Bitcoin above $100k?" in captured.out
        assert "btc-updown" in captured.out

    def test_prints_not_found(self, _mock_requests_get: Any, capsys: Any) -> None:
        _mock_requests_get.return_value.status_code = 200
        _mock_requests_get.return_value.json.return_value = _SAMPLE_EVENTS

        from polymarket_l2_collector.get_asset_id import search_markets

        search_markets("NonExistentKeyword")
        captured = capsys.readouterr()
        assert "No events matching" in captured.out

    def test_handles_api_failure(self, _mock_requests_get: Any, capsys: Any) -> None:
        import requests

        _mock_requests_get.side_effect = requests.exceptions.Timeout("timed out")

        from polymarket_l2_collector.get_asset_id import search_markets

        search_markets("anything")
        captured = capsys.readouterr()
        assert "API request failed" in captured.out

    def test_prints_token_ids(self, _mock_requests_get: Any, capsys: Any) -> None:
        _mock_requests_get.return_value.status_code = 200
        _mock_requests_get.return_value.json.return_value = _SAMPLE_EVENTS

        from polymarket_l2_collector.get_asset_id import search_markets

        search_markets("Bitcoin")
        captured = capsys.readouterr()
        assert "Token ID: 111" in captured.out


# ── CLI entry point ────────────────────────────────────────────────────


class TestMain:
    def test_usage_without_args(self, capsys: Any) -> None:
        from polymarket_l2_collector.get_asset_id import main

        with patch.object(sys, "argv", ["get_asset_id"]):
            with pytest.raises(SystemExit):
                main()
        captured = capsys.readouterr()
        assert "Usage" in captured.out

    def test_calls_get_market_info(self, _mock_requests_get: Any, capsys: Any) -> None:
        _mock_requests_get.return_value.status_code = 200
        _mock_requests_get.return_value.json.return_value = _SAMPLE_EVENTS

        from polymarket_l2_collector.get_asset_id import main

        with patch.object(sys, "argv", ["get_asset_id", "btc-updown-5m-1000"]):
            main()
        _mock_requests_get.assert_called_once()

    def test_search_flag(self, _mock_requests_get: Any, capsys: Any) -> None:
        _mock_requests_get.return_value.status_code = 200
        _mock_requests_get.return_value.json.return_value = _SAMPLE_EVENTS

        from polymarket_l2_collector.get_asset_id import main

        with patch.object(sys, "argv", ["get_asset_id", "--search", "Bitcoin"]):
            main()
        captured = capsys.readouterr()
        assert "Bitcoin above $100k?" in captured.out

    def test_search_requires_keyword(self, capsys: Any) -> None:
        from polymarket_l2_collector.get_asset_id import main

        with patch.object(sys, "argv", ["get_asset_id", "--search"]):
            with pytest.raises(SystemExit):
                main()
        captured = capsys.readouterr()
        assert "Please provide a search keyword" in captured.out
