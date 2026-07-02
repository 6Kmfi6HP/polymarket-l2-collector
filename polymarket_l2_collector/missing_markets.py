"""
Market backfill — fetch metadata for unknown asset IDs from Gamma API.

Mirrors poly_data's ``update_missing_tokens()`` functionality, adapted for
polymarket-l2-collector's project structure and conventions.

CLI::

    echo "123…abc" | python -m polymarket_l2_collector.missing_markets

    python -m polymarket_l2_collector.missing_markets --scan
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import polars as pl
import requests

from .logger_config import get_logger

logger = get_logger("missing_markets")

GAMMA_MARKETS = "https://gamma-api.polymarket.com/markets"

# Token IDs per Gamma request. The URL holds ~50 of these 77-char ids before the
# server returns 414 (URI too large), so 40 leaves headroom.
_MISSING_BATCH = 40
_MISSING_WORKERS = 12

# Columns written to missing_markets.csv. `id` = conditionId so the join key and
# market_id stay consistent with the CLOB-built markets.csv; clobTokenIds carries
# the token pair through for get_lean_markets.
_MISSING_COLUMNS = ["id", "clobTokenIds", "conditionId", "question", "slug", "closed"]

_local = threading.local()


def _gamma_session() -> requests.Session:
    """Get a thread-local requests session."""
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        _local.s = s
    return s


def _flatten_value(v: Any) -> str:
    """Serialize a value for CSV storage.

    - ``None`` → ``""``
    - ``dict`` / ``list`` → JSON string
    - Everything else → ``str(v)``
    """
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _market_cond_id(m: dict) -> str:
    """Stable id for a Gamma market — conditionId (to match the CLOB-built
    ``markets.csv`` whose ``id`` column is the on-chain condition_id)."""
    return str(m.get("conditionId") or m.get("id") or "")


# ── Gamma API helpers ──────────────────────────────────────────────────────


def fetch_market_info(token_ids: list[str]) -> list[dict]:
    """Fetch markets for a batch of token IDs from Gamma API.

    Tries ``closed=true`` first, then ``closed=false`` (Gamma defaults to
    closed=false but most missed tokens are recently-closed short-duration
    markets).  Results are deduped by ``conditionId`` within the batch.

    Args:
        token_ids: List of CLOB token IDs to look up (typically ~40).

    Returns:
        List of market dicts (empty if nothing found).
    """
    s = _gamma_session()
    found: dict[str, dict] = {}
    for closed_flag in ("true", "false"):
        params = [("clob_token_ids", t) for t in token_ids]
        params += [("closed", closed_flag), ("limit", len(token_ids))]
        try:
            resp = s.get(GAMMA_MARKETS, params=params, timeout=20)
            if resp.status_code != 200:
                continue
            payload = resp.json()
            markets = (
                payload
                if isinstance(payload, list)
                else payload.get("markets") or payload.get("data") or []
            )
            for m in markets:
                cid = _market_cond_id(m)
                if cid:
                    found[cid] = m
        except Exception as exc:
            logger.warning("Batch fetch failed (%d tokens): %s", len(token_ids), exc)
    return list(found.values())


# ── Core operations ────────────────────────────────────────────────────────


def update_missing_markets(missing_ids: list[str], output_dir: str = "data") -> int:
    """Fetch market info for missing token IDs and append to
    ``{output_dir}/missing_markets.csv``.

    Batches token IDs (``_MISSING_BATCH`` per request) and parallel-fetches
    them with ``_MISSING_WORKERS`` threads.  Skips IDs already recorded in
    the CSV to avoid duplicates.

    Args:
        missing_ids: Asset (clob token) IDs to look up.
        output_dir: Directory holding (or to hold) ``missing_markets.csv``.

    Returns:
        Number of new markets appended (0 if none found).
    """
    missing_ids = [m for m in missing_ids if m and m != "0"]
    if not missing_ids:
        return 0

    out = os.path.join(output_dir, "missing_markets.csv")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    # Load existing IDs to avoid duplicates
    existing_ids: set[str] = set()
    if os.path.exists(out):
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header and "id" in header:
                idx = header.index("id")
                for row in reader:
                    if row and len(row) > idx:
                        existing_ids.add(row[idx])

    batches = [
        missing_ids[i : i + _MISSING_BATCH]
        for i in range(0, len(missing_ids), _MISSING_BATCH)
    ]

    fetched: list[dict] = []
    with ThreadPoolExecutor(max_workers=_MISSING_WORKERS) as ex:
        for markets in ex.map(fetch_market_info, batches):
            for m in markets:
                cid = _market_cond_id(m)
                if cid and cid not in existing_ids:
                    existing_ids.add(cid)
                    fetched.append(m)

    if not fetched:
        return 0

    write_header = not os.path.exists(out)
    with open(out, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(_MISSING_COLUMNS)
        for m in fetched:
            cid = _market_cond_id(m)
            writer.writerow(
                [
                    cid,
                    _flatten_value(m.get("clobTokenIds")),
                    cid,
                    _flatten_value(m.get("question")),
                    _flatten_value(m.get("slug")),
                    _flatten_value(m.get("closed")),
                ]
            )

    logger.info("Appended %d missing markets -> %s", len(fetched), out)
    return len(fetched)


def load_all_markets(data_dir: str = "data") -> pl.DataFrame:
    """Load and merge ``markets.csv`` + ``missing_markets.csv``, dedup by ``id``.

    Returns an empty DataFrame with the expected columns when neither file
    exists, rather than raising.

    Args:
        data_dir: Directory holding the CSV files.

    Returns:
        A Polars DataFrame with at minimum ``id`` and ``clobTokenIds`` columns.
    """
    frames: list[pl.DataFrame] = []
    for fname in ("markets.csv", "missing_markets.csv"):
        path = os.path.join(data_dir, fname)
        if os.path.exists(path):
            df = pl.read_csv(
                path,
                schema_overrides={"id": pl.Utf8, "clobTokenIds": pl.Utf8},
                ignore_errors=True,
            )
            frames.append(df)

    if not frames:
        return pl.DataFrame(schema={"id": pl.Utf8, "clobTokenIds": pl.Utf8})

    return pl.concat(frames, how="diagonal_relaxed").unique(subset=["id"], keep="first")


def discover_missing_asset_ids(data_dir: str, known_df: pl.DataFrame) -> list[str]:
    """Scan collected Parquet data for asset IDs not present in the known
    markets DataFrame.

    Works by:
    1. Walking all Parquet files under *data_dir*.
    2. Reconstructing the event slug from each file's path.
    3. Resolving the slug to CLOB token IDs via the Gamma events API.
    4. Returning token IDs that are **not** found in the ``clobTokenIds``
       column of *known_df*.

    Args:
        data_dir: Root data directory to scan (recursive).
        known_df: DataFrame of known markets (from :func:`load_all_markets`).

    Returns:
        List of CLOB token IDs that should be backfilled.
    """
    # Build set of known token IDs from known_df
    known_token_ids: set[str] = set()
    if not known_df.is_empty() and "clobTokenIds" in known_df.columns:
        for raw in known_df["clobTokenIds"].to_list():
            if raw is None:
                continue
            try:
                ids = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(ids, list):
                    known_token_ids.update(str(i) for i in ids)
            except (json.JSONDecodeError, TypeError):
                pass

    # Scan parquet files for unique windows
    import glob

    windows: set[tuple[str, str, int]] = set()
    for fp in sorted(glob.glob(os.path.join(data_dir, "**", "*.parquet"), recursive=True)):
        parts = fp.replace("\\", "/").rstrip("/").split("/")
        if len(parts) < 5:
            continue
        fname = parts[-1]
        if not fname.endswith(".parquet"):
            continue
        stem = fname[: -len(".parquet")]
        ts_str = stem.replace("up", "").replace("down", "")
        if not ts_str.isdigit():
            continue
        windows.add((parts[-3], parts[-4], int(ts_str)))  # (coin, interval, window_ts)

    if not windows:
        return []

    # Resolve each unique window's slug to token IDs via Gamma API
    from .get_asset_id import get_market_info_by_slug
    from .market_discovery import _build_event_slug

    missing: set[str] = set()
    for coin, interval, window_ts in windows:
        slug = _build_event_slug(coin, interval, window_ts)
        try:
            markets = get_market_info_by_slug(slug)
            if not markets:
                continue
            for m in markets:
                token_ids = m.get("clobTokenIds", [])
                if isinstance(token_ids, str):
                    try:
                        token_ids = json.loads(token_ids)
                    except (json.JSONDecodeError, TypeError):
                        token_ids = []
                for tid in (token_ids or []):
                    tid_s = str(tid)
                    if tid_s not in known_token_ids:
                        missing.add(tid_s)
        except Exception as exc:
            logger.debug("Could not resolve slug %s: %s", slug, exc)

    logger.info(
        "Discovered %d missing asset IDs across %d windows",
        len(missing),
        len(windows),
    )
    return list(missing)


# ── CLI ────────────────────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point (``python -m polymarket_l2_collector.missing_markets``).

    Without ``--scan``, reads token IDs from stdin (one per line).
    With ``--scan``, scans collected data for missing tokens.
    """
    parser = argparse.ArgumentParser(description="Backfill missing market metadata from Gamma API")
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Root data directory (default: data)",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Scan collected Parquet data for missing token IDs",
    )
    args = parser.parse_args()

    if args.scan:
        known = load_all_markets(args.data_dir)
        missing = discover_missing_asset_ids(args.data_dir, known)
        if missing:
            print(f"Found {len(missing)} missing asset IDs")
            for tid in sorted(missing):
                print(tid)
            count = update_missing_markets(missing, output_dir=args.data_dir)
            print(f"Fetched metadata for {count} markets")
        else:
            print("No missing asset IDs found")
        return

    # Read token IDs from stdin
    ids = [line.strip() for line in sys.stdin if line.strip()]
    if not ids:
        print("No token IDs provided (pipe some IDs via stdin)")
        sys.exit(1)

    count = update_missing_markets(ids, output_dir=args.data_dir)
    print(f"Fetched metadata for {count} markets")


if __name__ == "__main__":
    main()
