"""
Unit tests for main module — GracefulKiller, compute_restart_delay, _get_rss_mb.
"""

from __future__ import annotations

import signal

import pytest

from polymarket_l2_collector.main import GracefulKiller, _get_rss_mb, compute_restart_delay

# ── compute_restart_delay ───────────────────────────────────────────────


class TestComputeRestartDelay:
    def test_normal_session_returns_3(self) -> None:
        """quick_restarts=0 → 3s."""
        assert compute_restart_delay(0) == 3

    def test_three_quick_restarts_still_3(self) -> None:
        """3 quick restarts → still 3s (threshold is >3)."""
        assert compute_restart_delay(3) == 3

    def test_four_quick_restarts_backs_off(self) -> None:
        """4 quick restarts → 60s (30 * 2^1)."""
        assert compute_restart_delay(4) == 60

    def test_five_quick_restarts_doubles(self) -> None:
        """5 quick restarts → 120s (30 * 2^2)."""
        assert compute_restart_delay(5) == 120

    def test_six_quick_restarts_capped(self) -> None:
        """6+ quick restarts → 120s (capped)."""
        assert compute_restart_delay(6) == 120
        assert compute_restart_delay(7) == 120
        assert compute_restart_delay(100) == 120


# ── _get_rss_mb ──────────────────────────────────────────────────────────


class TestGetRssMb:
    def test_returns_positive_float(self) -> None:
        """RSS should be a positive number on Linux."""
        rss = _get_rss_mb()
        assert isinstance(rss, (int, float))
        assert rss > 0

    def test_reasonable_value(self) -> None:
        """RSS should be reasonable (< 1TB, > 1MB for any Python process)."""
        rss = _get_rss_mb()
        assert 1 <= rss <= 1_000_000


# ── GracefulKiller ───────────────────────────────────────────────────


class TestGracefulKiller:
    def test_initial_state(self) -> None:
        killer = GracefulKiller()
        assert killer.kill_now is False
        assert killer._count == 0

    def test_first_signal_sets_kill_now(self) -> None:
        killer = GracefulKiller()
        killer._handler(signal.SIGTERM, None)
        assert killer.kill_now is True
        assert killer._count == 1

    def test_second_signal_exits(self) -> None:
        killer = GracefulKiller()
        killer._handler(signal.SIGTERM, None)
        with pytest.raises(SystemExit):
            killer._handler(signal.SIGTERM, None)
