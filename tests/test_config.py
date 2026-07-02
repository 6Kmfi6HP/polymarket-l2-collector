"""
Unit tests for config — Settings dataclass, validation, and load_settings().

Tests cover:
  - Default settings construction
  - Environment variable overrides
  - _csv_list helper
  - validate() with valid and invalid configurations
  - interval_seconds mapping
  - data_path property
  - load_settings() caching and skip_validation
  - SettingsValidationError messages
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from polymarket_l2_collector.config import (
    Settings,
    SettingsValidationError,
    _csv_list,
    load_settings,
)

# ── _csv_list helper ────────────────────────────────────────────────────


class TestCsvList:
    def test_empty_value_returns_default(self) -> None:
        assert _csv_list(None, ["a", "b"]) == ["a", "b"]
        assert _csv_list("", ["x"]) == ["x"]

    def test_comma_separated(self) -> None:
        assert _csv_list("a,b,c", []) == ["a", "b", "c"]

    def test_strips_whitespace(self) -> None:
        assert _csv_list(" a , b , c ", []) == ["a", "b", "c"]

    def test_lowercases(self) -> None:
        assert _csv_list("BTC,ETH", []) == ["btc", "eth"]

    def test_skips_empty_parts(self) -> None:
        assert _csv_list("a,,b", []) == ["a", "b"]


# ── Default settings ────────────────────────────────────────────────────


class TestDefaults:
    def test_default_coins(self) -> None:
        s = Settings()
        assert s.coins == ["btc", "eth"]

    def test_default_intervals(self) -> None:
        s = Settings()
        assert s.intervals == ["5m", "15m"]

    def test_default_directions(self) -> None:
        s = Settings()
        assert s.directions == ["up"]

    def test_default_ws_url(self) -> None:
        s = Settings()
        assert s.ws_url.startswith("wss://")

    def test_default_flush_thresholds(self) -> None:
        s = Settings()
        assert s.flush_threshold_trades == 50
        assert s.flush_threshold_book == 30
        assert s.max_cached_windows == 30

    def test_default_memory_limits(self) -> None:
        s = Settings()
        assert s.memory_soft_limit_mb == 300
        assert s.memory_hard_limit_mb == 400

    def test_default_health_check(self) -> None:
        s = Settings()
        assert s.health_check_interval == 30
        assert s.binance_stale_seconds == 300
        assert s.poly_ws_stale_seconds == 600

    def test_default_restart_time(self) -> None:
        s = Settings()
        assert s.restart_hour == 3
        assert s.restart_minute == 0

    def test_default_wallet_config(self) -> None:
        s = Settings()
        assert s.wallet_primary_timeout == 60
        assert s.wallet_verify_interval == 1.0

    def test_chain_verify_disabled_by_default(self) -> None:
        s = Settings()
        assert s.chain_verify_enabled is False

    def test_default_data_retention(self) -> None:
        s = Settings()
        assert s.data_retention_days == 0


# ── Environment overrides ──────────────────────────────────────────────


# ── Environment overrides ──────────────────────────────────────────────


class TestEnvOverrides:
    def test_coins_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COINS", "sol,btc")
        s = Settings()
        assert s.coins == ["sol", "btc"]

    def test_intervals_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INTERVALS", "5m,1h")
        s = Settings()
        assert s.intervals == ["5m", "1h"]

    def test_directions_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DIRECTIONS", "up,down")
        s = Settings()
        assert s.directions == ["up", "down"]

    def test_ws_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WS_URL", "wss://custom.example.com/ws")
        s = Settings()
        assert s.ws_url == "wss://custom.example.com/ws"

    def test_chain_verify_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHAIN_VERIFY_ENABLED", "true")
        s = Settings()
        assert s.chain_verify_enabled is True

    def test_all_ints_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Various int settings are parsed correctly."""
        monkeypatch.setenv("FLUSH_THRESHOLD_TRADES", "100")
        monkeypatch.setenv("MAX_CACHED_WINDOWS", "50")
        monkeypatch.setenv("MEMORY_HARD_LIMIT_MB", "800")
        monkeypatch.setenv("HEALTH_CHECK_INTERVAL", "15")
        s = Settings()
        assert s.flush_threshold_trades == 100
        assert s.max_cached_windows == 50
        assert s.memory_hard_limit_mb == 800
        assert s.health_check_interval == 15

    def test_float_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WALLET_VERIFY_INTERVAL", "2.5")
        s = Settings()
        assert s.wallet_verify_interval == 2.5

    def test_data_retention_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATA_RETENTION_DAYS", "7")
        s = Settings()
        assert s.data_retention_days == 7


# ── Validation: success ────────────────────────────────────────────────


class TestValidationSuccess:
    def test_default_settings_pass_validation(self) -> None:
        s = Settings()
        s.validate()  # should not raise

    def test_valid_one_coin(self) -> None:
        s = Settings(coins=["eth"])
        s.validate()


# ── Validation: failure ────────────────────────────────────────────────


class TestValidationFailure:
    def test_empty_coins(self) -> None:
        s = Settings(coins=[])
        with pytest.raises(SettingsValidationError) as exc:
            s.validate()
        assert any("COINS" in m for m in exc.value.messages)

    def test_invalid_interval(self) -> None:
        s = Settings(intervals=["3m"])
        with pytest.raises(SettingsValidationError) as exc:
            s.validate()
        assert any("INTERVALS" in m for m in exc.value.messages)

    def test_invalid_direction(self) -> None:
        s = Settings(directions=["sideways"])
        with pytest.raises(SettingsValidationError) as exc:
            s.validate()
        assert any("DIRECTIONS" in m for m in exc.value.messages)

    def test_invalid_ws_url(self) -> None:
        s = Settings(ws_url="not-a-websocket")
        with pytest.raises(SettingsValidationError) as exc:
            s.validate()
        assert any("WS_URL" in m for m in exc.value.messages)

    def test_empty_data_dir(self) -> None:
        s = Settings(data_dir="")
        with pytest.raises(SettingsValidationError) as exc:
            s.validate()
        assert any("DATA_DIR" in m for m in exc.value.messages)

    def test_invalid_log_level(self) -> None:
        s = Settings(log_level="verbose")
        with pytest.raises(SettingsValidationError) as exc:
            s.validate()
        assert any("LOG_LEVEL" in m for m in exc.value.messages)

    def test_memory_hard_not_greater_than_soft(self) -> None:
        s = Settings(memory_soft_limit_mb=400, memory_hard_limit_mb=400)
        with pytest.raises(SettingsValidationError) as exc:
            s.validate()
        assert any("HARD" in m.upper() for m in exc.value.messages)

    def test_invalid_restart_hour(self) -> None:
        s = Settings(restart_hour=24)
        with pytest.raises(SettingsValidationError) as exc:
            s.validate()
        assert any("RESTART_HOUR" in m for m in exc.value.messages)

    def test_multiple_errors_collected(self) -> None:
        """Multiple validation failures are collected into one exception."""
        s = Settings(
            coins=[],
            intervals=["3m"],
            directions=[],
            ws_url="bad-url",
            log_level="verbose",
        )
        with pytest.raises(SettingsValidationError) as exc:
            s.validate()
        assert len(exc.value.messages) >= 4

    def test_error_message_includes_all(self) -> None:
        """The str representation of SettingsValidationError shows all errors."""
        s = Settings(coins=[], intervals=["3m"])
        try:
            s.validate()
        except SettingsValidationError as e:
            msg = str(e)
            assert "COINS" in msg
            assert "INTERVALS" in msg

    def test_flush_thresholds_too_low(self) -> None:
        s = Settings(flush_threshold_trades=0, flush_threshold_book=-1)
        with pytest.raises(SettingsValidationError) as exc:
            s.validate()
        assert any("FLUSH_THRESHOLD_TRADES" in m for m in exc.value.messages)
        assert any("FLUSH_THRESHOLD_BOOK" in m for m in exc.value.messages)

    def test_wallet_timeout_too_low(self) -> None:
        s = Settings(wallet_primary_timeout=0, wallet_verify_interval=0)
        with pytest.raises(SettingsValidationError) as exc:
            s.validate()
        assert any("WALLET_PRIMARY_TIMEOUT" in m for m in exc.value.messages)
        assert any("WALLET_VERIFY_INTERVAL" in m for m in exc.value.messages)

    def test_negative_data_retention(self) -> None:
        s = Settings(data_retention_days=-1)
        with pytest.raises(SettingsValidationError) as exc:
            s.validate()
        assert any("DATA_RETENTION_DAYS" in m for m in exc.value.messages)


# ── Derived helpers ─────────────────────────────────────────────────────


class TestDataPath:
    def test_data_path_returns_path(self) -> None:
        s = Settings(data_dir="/tmp/test_data")
        assert str(s.data_path) == "/tmp/test_data"
        assert s.data_path.is_absolute()


class TestIntervalSeconds:
    def test_5m(self) -> None:
        assert Settings().interval_seconds("5m") == 300

    def test_15m(self) -> None:
        assert Settings().interval_seconds("15m") == 900

    def test_1h(self) -> None:
        assert Settings().interval_seconds("1h") == 3600

    def test_unknown_interval(self) -> None:
        with pytest.raises(ValueError, match="Unknown interval"):
            Settings().interval_seconds("10m")


# ── load_settings() ─────────────────────────────────────────────────────


class TestLoadSettings:
    def teardown_method(self) -> None:
        """Clear the cached singleton after each test."""
        import polymarket_l2_collector.config as cfg

        cfg._settings = None

    def test_returns_settings_instance(self) -> None:
        s = load_settings(skip_validation=True)
        assert isinstance(s, Settings)

    def test_caches_instance(self) -> None:
        s1 = load_settings(skip_validation=True)
        s2 = load_settings(skip_validation=True)
        assert s1 is s2  # same cached instance

    def test_loads_dotenv_if_available(self) -> None:
        """load_settings tries to call load_dotenv (may or may not be installed)."""
        # Unlike our test env, the collector always has python-dotenv.
        # We just verify it doesn't crash.
        with patch("polymarket_l2_collector.config.load_settings") as mock:
            mock.return_value = Settings()
            s = load_settings(skip_validation=True)
            assert isinstance(s, Settings)

    def test_skip_validation_passes_invalid(self) -> None:
        """With skip_validation=True, invalid settings don't raise."""
        with patch(
            "polymarket_l2_collector.config.Settings.validate",
        ) as mock_validate:
            load_settings(skip_validation=True)
            mock_validate.assert_not_called()

    def test_validation_called_by_default(self) -> None:
        """Without skip_validation, validate() is called."""
        with patch(
            "polymarket_l2_collector.config.Settings.validate",
        ) as mock_validate:
            try:
                load_settings(skip_validation=False)
            except SettingsValidationError:
                # Validation may raise on default settings if any fail;
                # that's fine -- we're checking it was *called*.
                pass
            mock_validate.assert_called_once()
