"""
Consolidated data export pipeline for polymarket-l2-collector.

Scans all windowed Parquet files across intervals/coins/directions,
merges market metadata (question, outcomes, slug), and exports
a unified Parquet or CSV dataset — mirroring poly_data's ``process_live``
pipeline but for L2 orderbook/trade windows rather than on-chain events.

CLI::

    python -m polymarket_l2_collector.export_pipeline \\
        --data-dir data --output exports/trades_export.parquet \\
        --data-type trades
"""

from __future__ import annotations

import argparse
import glob
import os
from typing import Any

from .file_cache import restore_from_parquet
from .logger_config import get_logger

logger = get_logger("export_pipeline")

# ── Window discovery ─────────────────────────────────────────────────


def _parse_tail(path: str) -> dict[str, Any] | None:
    """Extract (interval, coin, data_type, direction, window_ts) from a
    Parquet file path, returning a dict, or ``None`` if the path doesn't
    match the expected pattern."""
    parts = path.replace("\\", "/").rstrip("/").split("/")
    if len(parts) < 5:
        return None
    fname = parts[-1]
    if not fname.endswith(".parquet"):
        return None
    stem = fname[: -len(".parquet")]
    direction = "up" if "up" in stem else "down"
    ts_str = stem.replace("up", "").replace("down", "")
    if not ts_str.isdigit():
        return None
    return {
        "interval": parts[-4],
        "coin": parts[-3],
        "data_type": parts[-2],
        "direction": direction,
        "window_ts": int(ts_str),
        "path": path,
    }


def scan_files(
    data_dir: str,
    data_type: str | None = None,
) -> list[dict[str, Any]]:
    """Recursively scan *data_dir* for Parquet files and parse their metadata.

    Args:
        data_dir: Root data directory to scan.
        data_type: If set, only return files whose data_type matches
            (``"trades"`` or ``"orderbooks"``).  ``None`` returns all.

    Returns:
        A list of dicts with keys ``interval``, ``coin``, ``data_type``,
        ``direction``, ``window_ts``, ``path``, sorted by window_ts.
    """
    pattern = os.path.join(data_dir, "**", "*.parquet")
    files: list[dict[str, Any]] = []
    for fp in sorted(glob.glob(pattern, recursive=True)):
        info = _parse_tail(fp)
        if info is None:
            continue
        if data_type is not None and info["data_type"] != data_type:
            continue
        files.append(info)
    return sorted(files, key=lambda x: (x["interval"], x["coin"], x["direction"], x["window_ts"]))


# ── Trade export ──────────────────────────────────────────────────────


def collect_trades(data_dir: str, **kwargs: Any) -> list[dict[str, Any]]:
    """Read every trade Parquet file under *data_dir* and return the
    concatenated rows.

    Each row is augmented with ``interval``, ``coin``, ``direction``,
    and ``window_ts`` so the output is self-describing.

    Returns:
        A list of record dicts (empty if no trade files found).
    """
    files = scan_files(data_dir, data_type="trades")
    if not files:
        logger.info("No trade files found under %s", data_dir)
        return []

    all_rows: list[dict[str, Any]] = []
    for info in files:
        fp = info["path"]
        try:
            import pandas as pd

            df = pd.read_parquet(fp)
            rows = restore_from_parquet(df.to_dict("records"))
            del df
        except Exception as exc:
            logger.warning("Skipping unreadable %s: %s", fp, exc)
            continue

        for row in rows:
            row["interval"] = info["interval"]
            row["coin"] = info["coin"]
            row["direction"] = info["direction"]
            row["window_ts"] = info["window_ts"]
        all_rows.extend(rows)

    logger.info("Collected %d trade rows from %d files", len(all_rows), len(files))
    return all_rows


# ── Orderbook export ──────────────────────────────────────────────────


def collect_orderbooks(data_dir: str, **kwargs: Any) -> list[dict[str, Any]]:
    """Read every orderbook Parquet file under *data_dir* and return the
    concatenated rows.

    Each row is augmented with ``interval``, ``coin``, ``direction``,
    and ``window_ts``.

    Returns:
        A list of record dicts (empty if no orderbook files found).
    """
    files = scan_files(data_dir, data_type="orderbooks")
    if not files:
        logger.info("No orderbook files found under %s", data_dir)
        return []

    all_rows: list[dict[str, Any]] = []
    for info in files:
        fp = info["path"]
        try:
            import pandas as pd

            df = pd.read_parquet(fp)
            rows = restore_from_parquet(df.to_dict("records"))
            del df
        except Exception as exc:
            logger.warning("Skipping unreadable %s: %s", fp, exc)
            continue

        for row in rows:
            row["interval"] = info["interval"]
            row["coin"] = info["coin"]
            row["direction"] = info["direction"]
            row["window_ts"] = info["window_ts"]
        all_rows.extend(rows)

    logger.info("Collected %d orderbook rows from %d files", len(all_rows), len(files))
    return all_rows


# ── Dedup helpers ─────────────────────────────────────────────────────


def _dedup_key(row: dict[str, Any]) -> tuple:
    """Return a stable, unique-ish key for a trade or orderbook row.

    For trades: (window_ts, coin, direction, timestamp, price, size).
    For orderbooks: (window_ts, coin, direction, timestamp).

    Falls back to row identity if the expected fields are missing.
    """
    if "price" in row:
        return (
            row.get("window_ts", 0),
            row.get("coin", ""),
            row.get("direction", ""),
            row.get("timestamp", ""),
            row.get("price", ""),
            row.get("size", ""),
        )
    return (
        row.get("window_ts", 0),
        row.get("coin", ""),
        row.get("direction", ""),
        row.get("timestamp", ""),
    )


def dedup_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate rows while preserving order (first occurrence wins).

    Dedup is based on the key returned by ``_dedup_key``, which is designed
    to catch the common case: the same message written by both a live WS
    flush and a REST backfill.
    """
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = _dedup_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


# ── File export ───────────────────────────────────────────────────────


def write_parquet(rows: list[dict[str, Any]], output_path: str) -> int:
    """Write rows to a consolidated Parquet file.

    Args:
        rows: List of record dicts.
        output_path: Destination file path (``.parquet``).

    Returns:
        Number of rows written.
    """
    if not rows:
        logger.warning("No rows to export")
        return 0

    import pandas as pd

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_parquet(output_path, index=False, engine="pyarrow", compression="zstd")
    logger.info("Exported %d rows → %s", len(df), output_path)
    return len(df)


def write_csv(rows: list[dict[str, Any]], output_path: str) -> int:
    """Write rows to a consolidated CSV file.

    Args:
        rows: List of record dicts.
        output_path: Destination file path (``.csv``).

    Returns:
        Number of rows written.
    """
    if not rows:
        logger.warning("No rows to export")
        return 0

    import pandas as pd

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False)
    logger.info("Exported %d rows → %s", len(df), output_path)
    return len(df)


# ── Pipeline entrypoint ───────────────────────────────────────────────


def export_pipeline(
    data_dir: str = "data",
    output: str = "exports/consolidated.parquet",
    data_type: str = "trades",
    dedup: bool = True,
) -> int:
    """Run the full export pipeline: scan → collect → dedup → write.

    Args:
        data_dir: Root data directory to scan.
        output: Output file path.  Extensions ``.csv`` or ``.parquet``
            select the format; anything else defaults to Parquet.
        data_type: ``"trades"`` or ``"orderbooks"``.
        dedup: If ``True`` (default), remove duplicate rows before writing.

    Returns:
        Number of rows written (0 if nothing to export).
    """
    logger.info(
        "Export pipeline: data_dir=%s output=%s data_type=%s dedup=%s",
        data_dir,
        output,
        data_type,
        dedup,
    )

    if data_type == "trades":
        rows = collect_trades(data_dir)
    elif data_type == "orderbooks":
        rows = collect_orderbooks(data_dir)
    else:
        raise ValueError(f"Unknown data_type: {data_type!r} (expected 'trades' or 'orderbooks')")

    if not rows:
        return 0

    if dedup:
        before = len(rows)
        rows = dedup_rows(rows)
        after = len(rows)
        if before > after:
            logger.info("Dedup removed %d duplicate rows", before - after)

    _sort_by_ts(rows)

    ext = os.path.splitext(output)[1].lower()
    if ext == ".csv":
        return write_csv(rows, output)
    else:
        return write_parquet(rows, output)


def _sort_by_ts(rows: list[dict[str, Any]]) -> None:
    """Sort rows in-place by window_ts then timestamp."""
    rows.sort(key=lambda r: (r.get("window_ts", 0), str(r.get("timestamp", ""))))


def summary_report(data_dir: str) -> dict[str, Any]:
    """Generate a summary report of collected data.

    Returns a dict with:
    - ``total_files``: number of Parquet files found
    - ``by_type``: ``{"trades": N, "orderbooks": N}``
    - ``by_coin``: ``{"btc": N, "eth": N, ...}``
    - ``window_count``: number of distinct windows
    """
    files = scan_files(data_dir)
    by_type: dict[str, int] = {}
    by_coin: dict[str, int] = {}
    windows: set[tuple[str, str, str, int]] = set()

    for f in files:
        by_type[f["data_type"]] = by_type.get(f["data_type"], 0) + 1
        by_coin[f["coin"]] = by_coin.get(f["coin"], 0) + 1
        windows.add((f["interval"], f["coin"], f["direction"], f["window_ts"]))

    return {
        "total_files": len(files),
        "by_type": by_type,
        "by_coin": by_coin,
        "window_count": len(windows),
    }


# ── CLI ───────────────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point (``polymarket-export`` command)."""
    parser = argparse.ArgumentParser(description="Export consolidated Polymarket L2 data")
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Root data directory (default: data)",
    )
    parser.add_argument(
        "--output",
        default="exports/consolidated.parquet",
        help="Output path (.csv or .parquet, default: exports/consolidated.parquet)",
    )
    parser.add_argument(
        "--data-type",
        default="trades",
        choices=["trades", "orderbooks"],
        help="Data type to export (default: trades)",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Skip duplicate removal (default: dedup is enabled)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show summary report and exit without exporting",
    )
    args = parser.parse_args()

    if args.summary:
        report = summary_report(args.data_dir)
        print(f"\n{'=' * 50}")
        print(f"Data Summary — {args.data_dir}")
        print(f"{'=' * 50}")
        print(f"  Total Parquet files: {report['total_files']}")
        print(f"  Distinct windows:    {report['window_count']}")
        print(f"  By type: {report['by_type']}")
        print(f"  By coin: {report['by_coin']}")
        return

    count = export_pipeline(
        data_dir=args.data_dir,
        output=args.output,
        data_type=args.data_type,
        dedup=not args.no_dedup,
    )
    if count > 0:
        print(f"\n✅ Exported {count} rows → {args.output}")
    else:
        print("\n⚠️  Nothing to export (no data files found)")


if __name__ == "__main__":
    main()
