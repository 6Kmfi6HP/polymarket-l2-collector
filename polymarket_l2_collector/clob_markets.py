"""
Fetch the complete Polymarket market list from the CLOB API into data/markets.csv.

CLOB's /markets endpoint paginates 1000 rows/page with an offset-based cursor,
allowing the full market history to be pulled with concurrent requests.

Each market is written with:

    id            -> CLOB condition_id (stable on-chain market identifier)
    clobTokenIds  -> JSON array of the market's CLOB token_ids (token1, token2)

plus every other field the CLOB market object carries, preserved as-is (nested
values JSON-encoded).

Resumable: the next offset and discovered column order are saved to
{output_dir}/markets_state.json so an interrupted run picks up where it left off.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from .logger_config import get_logger

logger = get_logger("clob_markets")

CLOB_MARKETS = "https://clob.polymarket.com/markets"
PAGE = 1000            # CLOB's fixed page size
WAVE = 20              # concurrent pages per wave
END_CURSOR = "LTE="    # base64("-1"): CLOB's end-of-data marker
MAX_RETRIES = 8

_local = threading.local()


def _session() -> requests.Session:
    """Return a thread-local requests Session."""
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        _local.s = s
    return s


def _cursor(offset: int) -> str:
    """Encode an integer offset as base64 cursor."""
    return base64.b64encode(str(offset).encode()).decode()


def _token_ids(market: dict) -> list[str]:
    """Extract CLOB token IDs from a market dict's 'tokens' field."""
    toks = market.get("tokens") or []
    return [str(t["token_id"]) for t in toks if "token_id" in t]


def _flatten(v: Any) -> Any:
    """Flatten a value for CSV output: None->'', dict/list->JSON, else passthrough."""
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def _row(market: dict, columns: list[str]) -> list:
    """Map a market dict to a CSV row according to *columns*."""
    ids = _token_ids(market)
    out: list = []
    for c in columns:
        if c == "id":
            out.append(market.get("condition_id", ""))
        elif c == "clobTokenIds":
            out.append(json.dumps(ids) if ids else "")
        else:
            out.append(_flatten(market.get(c)))
    return out


def _fetch_page(offset: int) -> tuple[int, list[dict]]:
    """Return (offset, markets).  Empty list means at/past end of data."""
    s = _session()
    for attempt in range(MAX_RETRIES):
        try:
            r = s.get(CLOB_MARKETS, params={"next_cursor": _cursor(offset)}, timeout=30)
            if r.status_code == 200:
                return offset, r.json().get("data", [])
            if r.status_code in (429, 500, 502, 503):
                time.sleep(min(2 ** attempt, 10))
                continue
            r.raise_for_status()
        except requests.exceptions.RequestException:
            time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(
        f"CLOB /markets failed at offset {offset} after {MAX_RETRIES} retries"
    )


def _load_state(output_dir: str) -> dict:
    """Load resumption state from {output_dir}/markets_state.json."""
    path = os.path.join(output_dir, "markets_state.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return dict(json.load(f))
        except Exception:
            pass
    return {}


def _save_state(
    output_dir: str,
    offset: int,
    fetched: int,
    columns: list[str] | None,
    completed: bool = False,
) -> None:
    """Atomically save resumption state to {output_dir}/markets_state.json."""
    path = os.path.join(output_dir, "markets_state.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(
            {
                "offset": offset,
                "fetched": fetched,
                "columns": columns,
                "completed": completed,
            },
            f,
        )
    os.replace(tmp, path)


def _read_tail_ids(csv_file: str, n: int) -> set:
    """Return the ``id`` (first column) of up to the last *n* rows, reading
    only a bounded chunk from the end of the file -- avoids scanning a multi-GB
    CSV just to seed the resume dedup set."""
    if not os.path.exists(csv_file):
        return set()
    with open(csv_file, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        chunk = min(size, 16 * 1024 * 1024)
        if chunk == 0:
            return set()
        f.seek(size - chunk)
        data = f.read(chunk)
    lines = [ln for ln in data.split(b"\n") if ln.strip()]
    if chunk < size:
        lines = lines[1:]  # drop the (likely partial) first line
    ids = {ln.split(b",", 1)[0].decode("utf-8", "replace") for ln in lines[-n:]}
    ids.discard("id")  # header, if it landed in the window
    return ids


def fetch_markets(output_dir: str = "data", max_workers: int = WAVE) -> int:
    """Fetch all markets from CLOB into ``{output_dir}/markets.csv``.

    Resumable: saves progress to ``{output_dir}/markets_state.json`` so an
    interrupted run picks up near where it left off.

    Returns the total number of markets written.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)  # live progress when piped
    os.makedirs(output_dir, exist_ok=True)

    csv_file = os.path.join(output_dir, "markets.csv")
    state = _load_state(output_dir)
    columns = state.get("columns")
    resuming = state.get("offset", 0) > 0 and os.path.exists(csv_file)

    if resuming:
        fetched = state.get("fetched", 0)
        # Resume from the start of the last (partial) page so markets added to
        # that page since are picked up -- independent of any overshoot in the
        # saved offset.  Dedup that page against its existing rows, read from
        # the file tail rather than scanning the whole CSV.
        offset = (fetched // PAGE) * PAGE
        seen = _read_tail_ids(csv_file, PAGE + 500)
        logger.info(
            "Resuming near offset %s (%s markets already saved)",
            f"{offset:,}",
            f"{fetched:,}",
        )
        f = open(csv_file, "a", newline="", encoding="utf-8")
    else:
        seen: set = set()
        offset = 0
        fetched = 0
        columns = None
        f = open(csv_file, "w", newline="", encoding="utf-8")

    writer = csv.writer(f)
    done = False
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            while not done:
                offsets = [offset + i * PAGE for i in range(max_workers)]
                for off, markets in ex.map(_fetch_page, offsets):
                    if not markets:
                        done = True
                        continue
                    for m in markets:
                        cid = str(m.get("condition_id", ""))
                        if not cid or cid in seen:
                            continue
                        seen.add(cid)
                        if columns is None:
                            columns = ["id", "clobTokenIds"] + list(m.keys())
                            writer.writerow(columns)
                        writer.writerow(_row(m, columns))
                        fetched += 1
                offset += max_workers * PAGE
                f.flush()
                _save_state(output_dir, offset, fetched, columns)
                logger.info(
                    "Fetched %s markets (scanned through offset %s)",
                    f"{fetched:,}",
                    f"{offset:,}",
                )
    finally:
        f.close()

    _save_state(output_dir, offset, fetched, columns, completed=True)
    logger.info("Total markets: %s  ->  %s", f"{fetched:,}", csv_file)
    return fetched


def download_markets_file(output_dir: str = "data") -> int:
    """Convenience wrapper -- skip if already complete, otherwise fetch all.

    Returns 0 if the file was already complete, otherwise the number of
    markets written.
    """
    state = _load_state(output_dir)
    csv_file = os.path.join(output_dir, "markets.csv")
    if state.get("completed") and os.path.exists(csv_file):
        logger.info("markets.csv already complete -- skipping")
        return 0
    return fetch_markets(output_dir=output_dir)


def main() -> None:
    """CLI entry point for ``clob-markets``."""
    parser = argparse.ArgumentParser(
        description="Fetch Polymarket market list from CLOB API"
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Output directory (default: data)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if already complete",
    )
    args = parser.parse_args()

    if args.force:
        fetch_markets(output_dir=args.data_dir)
    else:
        download_markets_file(output_dir=args.data_dir)


if __name__ == "__main__":
    main()
