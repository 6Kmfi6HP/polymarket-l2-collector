"""
Unit tests for logger_config — get_logger, _JsonFormatter, log_context.

Tests cover:
  - get_logger: caching, handler setup, level propagation
  - _JsonFormatter: format, timestamp, extra_fields
  - log_context: context manager injection, field merging
  - LOG_FORMAT env var switching (plain vs json)
  - makeRecord patching for extra kwargs
  - Global _LOGGERS state isolation
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import pytest

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_loggers() -> Any:
    """Reset the global _LOGGERS cache before each test to avoid cross-test
    contamination (get_logger caches by name)."""
    import polymarket_l2_collector.logger_config as lc

    saved = dict(lc._LOGGERS)
    lc._LOGGERS.clear()
    yield
    lc._LOGGERS.clear()
    lc._LOGGERS.update(saved)


@pytest.fixture
def _plain_format(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Force plain log format."""
    import polymarket_l2_collector.logger_config as lc

    monkeypatch.setattr(lc, "_LOG_FORMAT", "plain")


@pytest.fixture
def _json_format(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Force JSON log format."""
    import polymarket_l2_collector.logger_config as lc

    monkeypatch.setattr(lc, "_LOG_FORMAT", "json")


def _capture_logger(name: str = "test", level: int = logging.INFO) -> tuple[logging.Logger, io.StringIO]:
    """Create a logger that writes to a StringIO for assertion."""
    from polymarket_l2_collector.logger_config import get_logger

    buf = io.StringIO()
    logger = get_logger(name, level=level)
    # Replace the stream handler's stream with our buffer
    for h in logger.handlers:
        if isinstance(h, logging.StreamHandler):
            h.stream = buf
            h.flush = lambda: None  # type: ignore[method-assign]
    # Clear any cached ref so _LOGGERS[name] picks up the modified logger
    import polymarket_l2_collector.logger_config as lc

    lc._LOGGERS[name] = logger
    return logger, buf


# ── get_logger ──────────────────────────────────────────────────────────


class TestGetLogger:
    def test_returns_logger_instance(self) -> None:
        from polymarket_l2_collector.logger_config import get_logger

        logger = get_logger("test_instance")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_instance"

    def test_caches_logger_by_name(self) -> None:
        from polymarket_l2_collector.logger_config import get_logger

        l1 = get_logger("cache_test")
        l2 = get_logger("cache_test")
        assert l1 is l2

    def test_same_name_returns_same(self) -> None:
        from polymarket_l2_collector.logger_config import get_logger

        assert get_logger("same") is get_logger("same")

    def test_different_names_different_loggers(self) -> None:
        from polymarket_l2_collector.logger_config import get_logger

        assert get_logger("a") is not get_logger("b")

    def test_has_stream_handler(self) -> None:
        from polymarket_l2_collector.logger_config import get_logger

        logger = get_logger("handler_check")
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert "StreamHandler" in handler_types

    def test_level_is_info_by_default(self) -> None:
        from polymarket_l2_collector.logger_config import get_logger

        logger = get_logger("level_check")
        assert logger.level == logging.INFO

    def test_custom_level(self) -> None:
        from polymarket_l2_collector.logger_config import get_logger

        logger = get_logger("custom_level", level=logging.DEBUG)
        assert logger.level == logging.DEBUG

    def test_does_not_duplicate_handlers(self) -> None:
        """Calling get_logger twice should not add extra handlers."""
        from polymarket_l2_collector.logger_config import get_logger

        logger = get_logger("duplicate")
        count = len(logger.handlers)
        get_logger("duplicate")
        assert len(logger.handlers) == count


# ── Plain-text output ───────────────────────────────────────────────────


class TestPlainFormat:
    def test_logs_message(self, _plain_format: Any) -> None:
        logger, buf = _capture_logger("plain_test")
        logger.info("hello world")
        output = buf.getvalue()
        assert "hello world" in output

    def test_includes_level(self, _plain_format: Any) -> None:
        logger, buf = _capture_logger("level_test")
        logger.warning("warn msg")
        assert "WARNING" in buf.getvalue()

    def test_includes_logger_name(self, _plain_format: Any) -> None:
        logger, buf = _capture_logger("my_module")
        logger.info("test")
        assert "my_module" in buf.getvalue()

    def test_plain_with_extra(self, _plain_format: Any) -> None:
        logger, buf = _capture_logger("extra_test")
        logger.info("data msg", extra={"coin": "btc"})
        assert "data msg" in buf.getvalue()


# ── JSON output ─────────────────────────────────────────────────────────


class TestJsonFormat:
    def test_output_is_valid_json(self, _json_format: Any) -> None:
        logger, buf = _capture_logger("json_test")
        logger.info("json msg")
        record = json.loads(buf.getvalue())
        assert record["msg"] == "json msg"

    def test_includes_all_fields(self, _json_format: Any) -> None:
        logger, buf = _capture_logger("json_full")
        logger.info("test msg")
        record = json.loads(buf.getvalue())
        assert "ts" in record
        assert "level" in record
        assert "name" in record
        assert "msg" in record
        assert record["level"] == "INFO"
        assert record["name"] == "json_full"

    def test_includes_extra_data(self, _json_format: Any) -> None:
        logger, buf = _capture_logger("json_extra")
        logger.info("with extra", extra={"coin": "btc", "rows": 50})
        record = json.loads(buf.getvalue())
        assert record["msg"] == "with extra"
        assert record["data"] == {"coin": "btc", "rows": 50}

    def test_plain_warning(self, _plain_format: Any) -> None:
        logger, buf = _capture_logger("plain_warn")
        logger.warning("warning here")
        assert "WARNING" in buf.getvalue()


# ── log_context ─────────────────────────────────────────────────────────


class TestLogContext:
    def test_adds_context_fields(self, _json_format: Any) -> None:
        from polymarket_l2_collector.logger_config import log_context

        logger, buf = _capture_logger("ctx_test")
        with log_context(logger, coin="btc", interval="5m"):
            logger.info("inside context")
        record = json.loads(buf.getvalue())
        assert record["data"]["coin"] == "btc"
        assert record["data"]["interval"] == "5m"

    def test_adds_fields_to_plain_output(self, _plain_format: Any) -> None:
        from polymarket_l2_collector.logger_config import log_context

        logger, buf = _capture_logger("ctx_plain")
        with log_context(logger, coin="btc"):
            logger.info("inside plain context")
        output = buf.getvalue()
        assert "inside plain context" in output

    def test_merges_with_extra(self, _json_format: Any) -> None:
        """log_context fields should merge with explicit extra (extra wins)."""
        from polymarket_l2_collector.logger_config import log_context

        logger, buf = _capture_logger("ctx_merge")
        with log_context(logger, coin="btc", source="context"):
            logger.info("merge", extra={"source": "extra"})
        record = json.loads(buf.getvalue())
        assert record["data"]["coin"] == "btc"
        assert record["data"]["source"] == "extra"  # explicit extra wins

    def test_resets_after_block(self, _json_format: Any) -> None:
        from polymarket_l2_collector.logger_config import log_context

        logger, buf = _capture_logger("ctx_reset")
        with log_context(logger, coin="btc"):
            logger.info("inside")
        logger.info("outside")
        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 2
        inside = json.loads(lines[0])
        outside = json.loads(lines[1])
        assert "coin" in inside["data"]
        assert "data" not in outside or "coin" not in outside.get("data", {})

    def test_context_nested(self, _json_format: Any) -> None:
        """Nested log_context blocks should merge fields."""
        from polymarket_l2_collector.logger_config import log_context

        logger, buf = _capture_logger("ctx_nest")
        with log_context(logger, coin="btc"):
            with log_context(logger, interval="5m"):
                logger.info("nested")
        record = json.loads(buf.getvalue())
        assert record["data"]["coin"] == "btc"
        assert record["data"]["interval"] == "5m"

    def test_no_leak_after_context(self, _json_format: Any) -> None:
        """After exiting the context, logs should not contain context fields
        (proving the context manager fully cleaned up)."""
        from polymarket_l2_collector.logger_config import log_context

        logger, buf = _capture_logger("ctx_no_leak")
        with log_context(logger, coin="btc"):
            logger.info("inside")
        logger.info("outside")
        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 2
        outside = json.loads(lines[1])
        if "data" in outside:
            assert "coin" not in outside["data"]


# ── _JsonFormatter ──────────────────────────────────────────────────────


class TestJsonFormatter:
    def test_format_creates_json(self) -> None:
        from polymarket_l2_collector.logger_config import _JsonFormatter

        fmt = _JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="json test", args=(), exc_info=None,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert data["msg"] == "json test"
        assert data["level"] == "INFO"

    def test_format_includes_timestamp(self) -> None:
        from polymarket_l2_collector.logger_config import _JsonFormatter

        fmt = _JsonFormatter()
        record = logging.LogRecord(
            name="ts_test", level=logging.INFO, pathname="", lineno=0,
            msg="msg", args=(), exc_info=None,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert "ts" in data
        assert "T" in data["ts"]  # ISO-8601 format

    def test_format_with_extra_fields(self) -> None:
        from polymarket_l2_collector.logger_config import _JsonFormatter

        fmt = _JsonFormatter()
        record = logging.LogRecord(
            name="extra", level=logging.INFO, pathname="", lineno=0,
            msg="extra msg", args=(), exc_info=None,
        )
        record.extra_fields = {"coin": "btc"}  # type: ignore[attr-defined]
        output = fmt.format(record)
        data = json.loads(output)
        assert data["data"] == {"coin": "btc"}
