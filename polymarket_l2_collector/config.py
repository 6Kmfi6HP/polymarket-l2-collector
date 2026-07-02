"""
Centralised configuration loaded from environment variables.

Allows every component to be configured via .env or environment without
hard-coded globals scattered across modules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


class SettingsValidationError(ValueError):
    """Raised when loaded settings fail validation.

    Carries a list of human-readable messages describing each issue so
    the caller can report them all at once rather than failing on the
    first one.
    """

    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        super().__init__("; ".join(messages))


_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_VALID_INTERVALS = {"5m", "15m", "1h"}
_VALID_DIRECTIONS = {"up", "down", "both"}


def _csv_list(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [v.strip().lower() for v in value.split(",") if v.strip()]


@dataclass
class Settings:
    # ── Coins & intervals ──────────────────────────────────────────
    coins: list[str] = field(default_factory=lambda: _csv_list(os.getenv("COINS"), ["btc", "eth"]))
    intervals: list[str] = field(default_factory=lambda: _csv_list(os.getenv("INTERVALS"), ["5m", "15m"]))
    directions: list[str] = field(default_factory=lambda: _csv_list(os.getenv("DIRECTIONS"), ["up"]))

    # ── Polymarket WebSocket ───────────────────────────────────────
    ws_url: str = field(default_factory=lambda: os.getenv("WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/market"))  # noqa: E501
    ws_max_size: int = field(default_factory=lambda: int(os.getenv("WS_MAX_SIZE", "524288")))  # 512 KB

    # ── Data paths ─────────────────────────────────────────────────
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", "data"))

    # ── Flush thresholds ───────────────────────────────────────────
    flush_threshold_trades: int = field(default_factory=lambda: int(os.getenv("FLUSH_THRESHOLD_TRADES", "50")))
    flush_threshold_book: int = field(default_factory=lambda: int(os.getenv("FLUSH_THRESHOLD_BOOK", "30")))
    max_cached_windows: int = field(default_factory=lambda: int(os.getenv("MAX_CACHED_WINDOWS", "30")))

    # ── Logging ────────────────────────────────────────────────────
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    # ── Memory protection ──────────────────────────────────────────
    memory_soft_limit_mb: int = field(default_factory=lambda: int(os.getenv("MEMORY_SOFT_LIMIT_MB", "300")))
    memory_hard_limit_mb: int = field(default_factory=lambda: int(os.getenv("MEMORY_HARD_LIMIT_MB", "400")))

    # ── Health check ───────────────────────────────────────────────
    binance_stale_seconds: int = field(default_factory=lambda: int(os.getenv("BINANCE_STALE_SECONDS", "300")))
    poly_ws_stale_seconds: int = field(default_factory=lambda: int(os.getenv("POLY_WS_STALE_SECONDS", "600")))
    health_check_interval: int = field(default_factory=lambda: int(os.getenv("HEALTH_CHECK_INTERVAL", "30")))

    # ── Daily restart ──────────────────────────────────────────────
    restart_hour: int = field(default_factory=lambda: int(os.getenv("RESTART_HOUR", "3")))
    restart_minute: int = field(default_factory=lambda: int(os.getenv("RESTART_MINUTE", "0")))

    # ── Wallet / Dual-WS ──────────────────────────────────────────
    wallet_primary_timeout: int = field(default_factory=lambda: int(os.getenv("WALLET_PRIMARY_TIMEOUT", "60")))
    wallet_secondary_timeout: int = field(default_factory=lambda: int(os.getenv("WALLET_SECONDARY_TIMEOUT", "120")))
    wallet_verify_interval: float = field(default_factory=lambda: float(os.getenv("WALLET_VERIFY_INTERVAL", "1.0")))
    wallet_switch_on_divergence: float = field(default_factory=lambda: float(os.getenv("WALLET_SWITCH_ON_DIVERGENCE", "50.0")))  # noqa: E501

    # ── Chain verify ──────────────────────────────────────────────
    chain_verify_enabled: bool = field(
        default_factory=lambda: os.getenv("CHAIN_VERIFY_ENABLED", "false").lower() in ("1", "true", "yes")
    )

    # ── Data retention ────────────────────────────────────────────
    data_retention_days: int = field(default_factory=lambda: int(os.getenv("DATA_RETENTION_DAYS", "0")))

    # ── Validation ────────────────────────────────────────────────
    def validate(self) -> None:
        """Validate all settings, raising ``SettingsValidationError`` if any
        check fails.  Collects *all* errors before raising so the caller
        sees the full picture, not just the first failure."""
        errors: list[str] = []

        if not self.coins:
            errors.append("COINS must be a non-empty list")
        for c in self.coins:
            if len(c) < 2:
                errors.append(f"COINS entry {c!r} looks invalid (too short)")

        if not self.intervals:
            errors.append("INTERVALS must be a non-empty list")
        for iv in self.intervals:
            if iv not in _VALID_INTERVALS:
                errors.append(f"INTERVALS entry {iv!r} is not supported (choose from {sorted(_VALID_INTERVALS)})")

        if not self.directions:
            errors.append("DIRECTIONS must be a non-empty list")
        for d in self.directions:
            if d not in _VALID_DIRECTIONS:
                errors.append(f"DIRECTIONS entry {d!r} is not supported (choose from {sorted(_VALID_DIRECTIONS)})")

        if not self.ws_url.startswith("ws") or "://" not in self.ws_url:
            errors.append(f"WS_URL {self.ws_url!r} does not look like a valid WebSocket URL")

        if not self.data_dir:
            errors.append("DATA_DIR cannot be empty")

        if self.flush_threshold_trades < 1:
            errors.append(f"FLUSH_THRESHOLD_TRADES must be >= 1 (got {self.flush_threshold_trades})")
        if self.flush_threshold_book < 1:
            errors.append(f"FLUSH_THRESHOLD_BOOK must be >= 1 (got {self.flush_threshold_book})")
        if self.max_cached_windows < 1:
            errors.append(f"MAX_CACHED_WINDOWS must be >= 1 (got {self.max_cached_windows})")

        if self.log_level.upper() not in _LOG_LEVELS:
            errors.append(f"LOG_LEVEL {self.log_level!r} is not valid (choose from {sorted(_LOG_LEVELS)})")

        if self.memory_soft_limit_mb < 50:
            errors.append(f"MEMORY_SOFT_LIMIT_MB should be >= 50 (got {self.memory_soft_limit_mb})")
        if self.memory_hard_limit_mb <= self.memory_soft_limit_mb:
            errors.append(
                f"MEMORY_HARD_LIMIT_MB ({self.memory_hard_limit_mb}) must be > "
                f"MEMORY_SOFT_LIMIT_MB ({self.memory_soft_limit_mb})"
            )

        if self.binance_stale_seconds < 10:
            errors.append(f"BINANCE_STALE_SECONDS should be >= 10 (got {self.binance_stale_seconds})")
        if self.poly_ws_stale_seconds < 10:
            errors.append(f"POLY_WS_STALE_SECONDS should be >= 10 (got {self.poly_ws_stale_seconds})")
        if self.health_check_interval < 5:
            errors.append(f"HEALTH_CHECK_INTERVAL should be >= 5 (got {self.health_check_interval})")

        if not (0 <= self.restart_hour <= 23):
            errors.append(f"RESTART_HOUR must be in 0-23 (got {self.restart_hour})")
        if not (0 <= self.restart_minute <= 59):
            errors.append(f"RESTART_MINUTE must be in 0-59 (got {self.restart_minute})")

        if self.wallet_primary_timeout < 1:
            errors.append(f"WALLET_PRIMARY_TIMEOUT must be >= 1 (got {self.wallet_primary_timeout})")
        if self.wallet_secondary_timeout < 1:
            errors.append(f"WALLET_SECONDARY_TIMEOUT must be >= 1 (got {self.wallet_secondary_timeout}")
        if self.wallet_verify_interval <= 0:
            errors.append(f"WALLET_VERIFY_INTERVAL must be > 0 (got {self.wallet_verify_interval})")

        if self.data_retention_days < 0:
            errors.append(f"DATA_RETENTION_DAYS must be >= 0 (got {self.data_retention_days})")

        if errors:
            raise SettingsValidationError(errors)

    # ── Derived helpers ────────────────────────────────────────────
    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    def interval_seconds(self, interval: str) -> int:
        """Convert interval string ('5m' / '15m' / '1h') to seconds."""
        mapping = {"5m": 5 * 60, "15m": 15 * 60, "1h": 60 * 60}
        if interval not in mapping:
            raise ValueError(f"Unknown interval {interval!r} (expected one of {set(mapping)})")
        return mapping[interval]


_settings: Settings | None = None


def load_settings(skip_validation: bool = False) -> Settings:
    """Load (or return cached) settings.

    Call once at startup.  Subsequent calls return the same instance.

    Args:
        skip_validation: If ``True``, skip the ``validate()`` call.
            Use only in tests that deliberately set invalid values.

    Raises:
        SettingsValidationError: If validation fails.
    """
    global _settings
    if _settings is None:
        # Try loading .env via python-dotenv if available
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        _settings = Settings()
    if not skip_validation:
        _settings.validate()
    return _settings
