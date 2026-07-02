"""
Data retention — purge old collected data windows.

Removes Parquet files and their companion ``.meta.json`` files whose
window timestamp falls outside the configured retention window.  A
grace period of 24h is always enforced so the most recent data is
never deleted, even when ``data_retention_days=0``.

CLI::

    python -m polymarket_l2_collector.data_retention \\
        --data-dir data --retention-days 30 --dry-run

    python -m polymarket_l2_collector.data_retention \\
        --data-dir data --retention-days 0 --force
"""

from __future__ import annotations

import argparse
import os
import time

from .export_pipeline import scan_files
from .logger_config import get_logger

logger = get_logger("data_retention")

# Always keep the most recent 24 hours, regardless of retention_days.
_GRACE_SECONDS = 86_400  # 24 hours


def purge_old_data(
    data_dir: str,
    retention_days: int,
    dry_run: bool = True,
    force: bool = False,
) -> int:
    """Delete collected data windows older than *retention_days*.

    Args:
        data_dir: Root data directory to scan.
        retention_days: Delete windows older than this many days.
            ``0`` means "delete everything older than 24h" (with
            the grace-period safeguard).
        dry_run: If ``True`` (default), only log what would be deleted
            without actually removing any files.
        force: If ``True``, skip the grace-period safeguard.  Only
            meaningful when used together with ``retention_days=0``
            (otherwise the grace period is already weaker than the
            retention window).

    Returns:
        Number of files (parquet + meta) that were (or would be) deleted.
    """
    retention_seconds = retention_days * 86_400
    now = int(time.time())
    cutoff = now - max(retention_seconds, _GRACE_SECONDS) if not force else now - retention_seconds
    # When retention_days=0 and not force, cutoff = now - 86400 (keep last 24h).

    files = scan_files(data_dir)
    if not files:
        logger.info("No data files found under %s", data_dir)
        return 0

    deleted = 0
    for info in files:
        ts = info["window_ts"]
        if ts >= cutoff:
            continue  # within retention window

        # Build the full path to the parquet file
        fp = info["path"]
        meta_fp = fp.replace(".parquet", ".meta.json")

        if not dry_run:
            try:
                os.remove(fp)
                deleted += 1
            except OSError as exc:
                logger.warning("Failed to delete %s: %s", fp, exc)
            try:
                if os.path.exists(meta_fp):
                    os.remove(meta_fp)
                    deleted += 1
            except OSError as exc:
                logger.warning("Failed to delete %s: %s", meta_fp, exc)
            logger.info("Deleted window %s (ts=%d, cutoff=%d)", info.get("coin", "?"), ts, cutoff)
        else:
            deleted += 1  # count the parquet
            if os.path.exists(meta_fp):
                deleted += 1
            info_coin = info.get("coin", "?")
            logger.info(
                "[DRY RUN] Would delete window coin=%s interval=%s ts=%d",
                info_coin, info.get("interval"), ts,
            )

    if dry_run:
        logger.info("[DRY RUN] Would delete %d files (%d windows older than %dd)", deleted, len(files), retention_days)
    else:
        logger.info("Deleted %d files (windows older than %dd)", deleted, retention_days)

    return deleted


def main() -> None:
    """CLI entry point (``polymarket-data-retention`` command)."""
    parser = argparse.ArgumentParser(
        description="Purge old Polymarket L2 collected data"
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Root data directory (default: data)",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=30,
        help="Delete data older than this many days (default: 30)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Show what would be deleted without deleting (default: true)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip 24h grace period safeguard",
    )
    args = parser.parse_args()

    count = purge_old_data(
        data_dir=args.data_dir,
        retention_days=args.retention_days,
        dry_run=args.dry_run,
        force=args.force,
    )
    if count:
        status = "Would delete" if args.dry_run else "Deleted"
        print(f"\n{status} {count} file(s)")
    else:
        print("\nNothing to delete")


if __name__ == "__main__":
    main()
