"""
Unit tests for data retention — purge_old_data function.

Tests cover:
  - dry-run mode
  - actual deletion
  - retention days threshold
  - 24h grace period safeguard
  - force flag bypass
  - empty directory
  - meta.json companion deletion
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from polymarket_l2_collector.data_retention import purge_old_data


def _make_window(base: Path, interval: str, coin: str, data_type: str, ts: int, direction: str = "up") -> Path:
    """Create a parquet file + meta.json for a window at *ts*."""
    import pandas as pd

    pdir = base / interval / coin / data_type
    pdir.mkdir(parents=True, exist_ok=True)
    fp = pdir / f"{ts}{direction}.parquet"
    pd.DataFrame({"col": [1]}).to_parquet(str(fp))
    meta = {
        "interval": interval, "coin": coin, "data_type": data_type,
        "direction": direction, "window_ts": ts, "message_count": 1, "status": "complete",
    }
    mp = pdir / f"{ts}{direction}.meta.json"
    mp.write_text(json.dumps(meta))
    return fp


class TestPurgeOldData:
    def test_dry_run_counts_files(self) -> None:
        """Dry-run should report files that would be deleted."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            _make_window(td_path, "5m", "btc", "orderbooks", 1000)
            _make_window(td_path, "5m", "btc", "orderbooks", 9999999999)  # recent

            # Mock time so 1000 is old
            with patch("polymarket_l2_collector.data_retention.time.time", return_value=9999999999 + 86400):
                n = purge_old_data(td, retention_days=0, dry_run=True)
            assert n > 0  # at least one file counted
            # Check files still exist
            assert (td_path / "5m" / "btc" / "orderbooks" / "1000up.parquet").exists()

    def test_deletes_old_files(self) -> None:
        """Files older than retention_days should be deleted."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            fp = _make_window(td_path, "5m", "btc", "orderbooks", 1000)
            _make_window(td_path, "5m", "btc", "orderbooks", 9999999999)

            with patch("polymarket_l2_collector.data_retention.time.time", return_value=9999999999 + 86400):
                n = purge_old_data(td, retention_days=0, dry_run=False)

            assert n >= 1
            assert not fp.exists()  # old file deleted

    def test_keeps_recent_files(self) -> None:
        """Files within retention window should be kept."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            now = 1_000_000_000
            _make_window(td_path, "5m", "btc", "orderbooks", now - 3600)  # 1h ago
            _make_window(td_path, "5m", "btc", "orderbooks", now)  # now

            with patch("polymarket_l2_collector.data_retention.time.time", return_value=now):
                n = purge_old_data(td, retention_days=30, dry_run=False)

            assert n == 0  # within 30 days, nothing deleted

    def test_deletes_companion_meta(self) -> None:
        """meta.json should be deleted alongside the parquet."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            fp = _make_window(td_path, "5m", "btc", "orderbooks", 1000)
            mp = fp.with_suffix(".meta.json")
            assert mp.exists()

            with patch("polymarket_l2_collector.data_retention.time.time", return_value=9999999999 + 86400):
                n = purge_old_data(td, retention_days=0, dry_run=False)

            assert n >= 1
            assert not mp.exists()

    def test_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            n = purge_old_data(td, retention_days=30)
        assert n == 0

    def test_grace_period_protects_recent_data(self) -> None:
        """With retention_days=0 and recent data, grace period keeps last 24h."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            now = 1_000_000_000
            _make_window(td_path, "5m", "btc", "orderbooks", now - 43_200)  # 12h ago

            with patch("polymarket_l2_collector.data_retention.time.time", return_value=now):
                n = purge_old_data(td, retention_days=0, dry_run=False)

            # 12h is within 24h grace period → should NOT be deleted
            assert n == 0

    def test_force_bypasses_grace_period(self) -> None:
        """force=True skips the 24h grace period safeguard."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            now = 1_000_000_000
            fp = _make_window(td_path, "5m", "btc", "orderbooks", now - 43_200)  # 12h ago

            with patch("polymarket_l2_collector.data_retention.time.time", return_value=now):
                n = purge_old_data(td, retention_days=0, dry_run=False, force=True)

            assert n >= 1
            assert not fp.exists()

    def test_meta_json_does_not_exist_skips(self) -> None:
        """Missing meta.json should not cause errors."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            fp = _make_window(td_path, "5m", "btc", "orderbooks", 1000)
            mp = fp.with_suffix(".meta.json")
            mp.unlink()  # remove meta

            with patch("polymarket_l2_collector.data_retention.time.time", return_value=9999999999 + 86400):
                n = purge_old_data(td, retention_days=0, dry_run=False)

            assert n == 1  # only the parquet counted
