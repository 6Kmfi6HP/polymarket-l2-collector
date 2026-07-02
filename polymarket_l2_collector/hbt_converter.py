"""
HftBacktest format converter for polymarket-l2-collector.

Converts collected orderbook/trade Parquet data (export_pipeline output)
into the hftbacktest event numpy array format (``event_dtype``), enabling
direct backtesting without depending on the ``pm-hftbacktest`` package.

Usage::

    # CLI: convert orderbook data to hftbacktest .npy
    polymarket-hbt-convert --data-dir data --output exports/btc_5m.npy \\
        --data-type orderbooks

    # CLI: convert trade data
    polymarket-hbt-convert --data-dir data --output exports/btc_trades.npy \\
        --data-type trades
"""

from __future__ import annotations

import argparse
import os
from typing import Any

import numpy as np
from numpy.typing import NDArray

# ── Event types (replicated from hftbacktest.types) ──────────────────────

DEPTH_EVENT = 1
"""Market depth changed."""
TRADE_EVENT = 2
"""Trade occurred."""
DEPTH_CLEAR_EVENT = 3
"""Market depth cleared (full snapshot refresh)."""
DEPTH_SNAPSHOT_EVENT = 4
"""Market depth snapshot level received."""

EXCH_EVENT = 1 << 31
"""Valid event at exchange timestamp."""
LOCAL_EVENT = 1 << 30
"""Valid event at local timestamp."""

BUY_EVENT = 1 << 29
"""Buy-side / bid-side flag."""
SELL_EVENT = 1 << 28
"""Sell-side / ask-side flag."""

#: NumPy dtype matching hftbacktest's ``event_dtype`` exactly.
event_dtype = np.dtype(
    [
        ("ev", "u8"),
        ("exch_ts", "i8"),
        ("local_ts", "i8"),
        ("px", "f8"),
        ("qty", "f8"),
        ("order_id", "u8"),
        ("ival", "i8"),
        ("fval", "f8"),
    ],
    align=True,
)

#: Column names for the hftbacktest event structured array.
HBT_COLS = ["ev", "exch_ts", "local_ts", "px", "qty", "order_id", "ival", "fval"]

POLY_MIN_PRICE = 0.0
POLY_MAX_PRICE = 1.0
DEFAULT_LATENCY_NS = 20_000_000  # 20 ms


# ── Timestamp helpers ────────────────────────────────────────────────────


def _ts_str_to_ns(ts_str: str) -> int:
    """Convert a millisecond timestamp *string* to nanoseconds (int64)."""
    return int(ts_str) * 1_000_000


def _local_ts_ns(
    row: dict[str, Any],
    exch_ts_ns: int,
    constant_latency: int | None,
) -> int:
    """Compute local timestamp in nanoseconds.

    If *constant_latency* is provided it is added to the exchange timestamp;
    otherwise the row's ``local_timestamp`` is used (falling back to
    *exch_ts_ns* + 20 ms).
    """
    if constant_latency is not None:
        return exch_ts_ns + constant_latency
    local = row.get("local_timestamp")
    if local is not None and local != "":
        return _ts_str_to_ns(str(local))
    return exch_ts_ns + DEFAULT_LATENCY_NS


# ── Orderbook conversion ─────────────────────────────────────────────────


def _extract_book_side(levels: Any) -> tuple[list[float], list[float]]:
    """Extract (prices, sizes) from a list of ``{price: ..., size: ...}`` dicts.

    Handles both the raw collector format (``{"p": ..., "s": ...}`` or
    ``{"price": ..., "size": ...}``) and list-of-lists.
    """
    prices: list[float] = []
    sizes: list[float] = []
    if not levels:
        return prices, sizes
    for item in levels:
        if isinstance(item, dict):
            px = item.get("price") or item.get("p")
            sz = item.get("size") or item.get("s")
            if px is not None and sz is not None:
                prices.append(float(px))
                sizes.append(float(sz))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            prices.append(float(item[0]))
            sizes.append(float(item[1]))
    return prices, sizes


def _make_book_events(
    book_rows: list[dict[str, Any]],
    constant_latency: int | None = None,
) -> NDArray:
    """Convert orderbook snapshot rows into hftbacktest depth events.

    Each row produces:
    1. A ``DEPTH_CLEAR_EVENT | BUY_EVENT`` / ``DEPTH_CLEAR_EVENT | SELL_EVENT``
       to clear the existing book side.
    2. One ``DEPTH_SNAPSHOT_EVENT | BUY_EVENT`` / ``DEPTH_SNAPSHOT_EVENT | SELL_EVENT``
       per price level in that row.

    Rows are sorted by timestamp before processing.
    """
    if not book_rows:
        return np.zeros(0, dtype=event_dtype)

    # Sort by exchange timestamp
    book_rows.sort(key=lambda r: str(r.get("timestamp", "0")))

    # Pre-compute total output size
    total_rows = 0
    for row in book_rows:
        bids = _iterable_items(row.get("bids", []))
        asks = _iterable_items(row.get("asks", []))
        # 1 clear per side + N levels per side
        total_rows += 2 + len(bids) + len(asks)

    out = np.zeros(total_rows, dtype=event_dtype)
    pos = 0

    for row in book_rows:
        exch_ts = _ts_str_to_ns(str(row.get("timestamp", "0")))
        local_ts = _local_ts_ns(row, exch_ts, constant_latency)

        bid_prices, bid_sizes = _extract_book_side(_iterable_items(row.get("bids", [])))
        ask_prices, ask_sizes = _extract_book_side(_iterable_items(row.get("asks", [])))

        # ── Bid side ──────────────────────────────────────────────
        clear_px = max(bid_prices) if bid_prices else POLY_MIN_PRICE
        out[pos]["ev"] = DEPTH_CLEAR_EVENT | BUY_EVENT
        out[pos]["exch_ts"] = exch_ts
        out[pos]["local_ts"] = local_ts
        out[pos]["px"] = float(clear_px)
        out[pos]["qty"] = 0.0
        pos += 1

        for i in range(len(bid_prices)):
            out[pos]["ev"] = DEPTH_SNAPSHOT_EVENT | BUY_EVENT
            out[pos]["exch_ts"] = exch_ts
            out[pos]["local_ts"] = local_ts
            out[pos]["px"] = float(bid_prices[i])
            out[pos]["qty"] = float(bid_sizes[i])
            pos += 1

        # ── Ask side ──────────────────────────────────────────────
        clear_px = min(ask_prices) if ask_prices else POLY_MAX_PRICE
        out[pos]["ev"] = DEPTH_CLEAR_EVENT | SELL_EVENT
        out[pos]["exch_ts"] = exch_ts
        out[pos]["local_ts"] = local_ts
        out[pos]["px"] = float(clear_px)
        out[pos]["qty"] = 0.0
        pos += 1

        for i in range(len(ask_prices)):
            out[pos]["ev"] = DEPTH_SNAPSHOT_EVENT | SELL_EVENT
            out[pos]["exch_ts"] = exch_ts
            out[pos]["local_ts"] = local_ts
            out[pos]["px"] = float(ask_prices[i])
            out[pos]["qty"] = float(ask_sizes[i])
            pos += 1

    return out


# ── Trade conversion ─────────────────────────────────────────────────────


def _make_trade_events(
    trade_rows: list[dict[str, Any]],
    constant_latency: int | None = None,
) -> NDArray:
    """Convert trade rows into hftbacktest trade events.

    Each trade row produces one ``TRADE_EVENT | BUY_EVENT`` or
    ``TRADE_EVENT | SELL_EVENT`` entry.

    Rows are sorted by timestamp before processing.
    """
    if not trade_rows:
        return np.zeros(0, dtype=event_dtype)

    trade_rows.sort(key=lambda r: str(r.get("timestamp", "0")))
    out = np.zeros(len(trade_rows), dtype=event_dtype)

    for i, row in enumerate(trade_rows):
        exch_ts = _ts_str_to_ns(str(row.get("timestamp", "0")))
        local_ts = _local_ts_ns(row, exch_ts, constant_latency)
        side = str(row.get("side", "buy")).upper()
        is_buy = side in ("BUY", "BID", "TRUE")

        out[i]["ev"] = TRADE_EVENT | (BUY_EVENT if is_buy else SELL_EVENT)
        out[i]["exch_ts"] = exch_ts
        out[i]["local_ts"] = local_ts
        out[i]["px"] = float(row.get("price", 0))
        out[i]["qty"] = float(row.get("size", 0))

    return out


# ── Correct event order ──────────────────────────────────────────────────


def correct_event_order(data: NDArray) -> NDArray:
    """Correct exchange/local timestamp ordering in an event array.

    Splits each row into separate EXCH_EVENT and LOCAL_EVENT entries
    where necessary, ensuring proper ordering for the hftbacktest engine.

    This is a pure-Python implementation of the logic in
    pm-hftbacktest's ``correct_event_order`` (no Numba dependency).

    Reference:
        ``hftbacktest.data.validation.correct_event_order``
    """
    n = len(data)
    if n == 0:
        return data

    sorted_exch = np.argsort(data["exch_ts"], kind="mergesort")
    sorted_local = np.argsort(data["local_ts"], kind="mergesort")

    # In the simple case where exch_ts and local_ts have the same order,
    # just flag each row with both flags.
    exch_order = np.argsort(sorted_exch)  # rank by exch_ts
    local_order = np.argsort(sorted_local)  # rank by local_ts

    if np.array_equal(exch_order, local_order):
        out = np.zeros(n, dtype=event_dtype)
        out[:] = data[:]
        out["ev"] = out["ev"] | EXCH_EVENT | LOCAL_EVENT
        return out

    # Complex case: need to duplicate rows where order differs
    sorted_final = np.zeros(n * 2, dtype=event_dtype)
    out_rn = 0
    exch_rn = 0
    local_rn = 0

    while exch_rn < n or local_rn < n:
        if exch_rn < n and local_rn < n:
            exch_idx = sorted_exch[exch_rn]
            local_idx = sorted_local[local_rn]
            se = data[exch_idx]
            sl = data[local_idx]

            if (
                se["exch_ts"] == sl["exch_ts"]
                and se["local_ts"] == sl["local_ts"]
            ):
                sorted_final[out_rn] = se
                sorted_final[out_rn]["ev"] = sorted_final[out_rn]["ev"] | EXCH_EVENT | LOCAL_EVENT
                out_rn += 1
                exch_rn += 1
                local_rn += 1
            elif (
                se["exch_ts"] < sl["exch_ts"]
                or (
                    se["exch_ts"] == sl["exch_ts"]
                    and se["local_ts"] < sl["local_ts"]
                )
            ):
                sorted_final[out_rn] = se
                sorted_final[out_rn]["ev"] = sorted_final[out_rn]["ev"] | EXCH_EVENT
                out_rn += 1
                exch_rn += 1
            else:
                sorted_final[out_rn] = sl
                sorted_final[out_rn]["ev"] = sorted_final[out_rn]["ev"] | LOCAL_EVENT
                out_rn += 1
                local_rn += 1
        elif exch_rn < n:
            se = data[sorted_exch[exch_rn]]
            sorted_final[out_rn] = se
            sorted_final[out_rn]["ev"] = sorted_final[out_rn]["ev"] | EXCH_EVENT
            out_rn += 1
            exch_rn += 1
        else:
            sl = data[sorted_local[local_rn]]
            sorted_final[out_rn] = sl
            sorted_final[out_rn]["ev"] = sorted_final[out_rn]["ev"] | LOCAL_EVENT
            out_rn += 1
            local_rn += 1

    return sorted_final[:out_rn]


# ── Main conversion entry point ──────────────────────────────────────────


def _iterable_items(value: Any) -> list:
    """Coerce a value to a list of items for iteration.

    Handles plain lists, numpy arrays, and other iterables.
    Strings, scalars, and None are returned as empty list.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict)):
        return list(value)
    return []


def rows_to_hbt(
    rows: list[dict[str, Any]],
    *,
    data_type: str = "orderbooks",
    constant_latency: int | None = None,
) -> NDArray:
    """Convert collected data rows to an hftbacktest event array.

    Args:
        rows: List of data dicts as returned by ``export_pipeline``
            (``collect_orderbooks`` or ``collect_trades``).
        data_type: ``"orderbooks"`` (default) or ``"trades"``.
        constant_latency: Optional fixed latency in nanoseconds.
            When provided it takes priority over ``local_timestamp``;
            otherwise ``local_timestamp`` is used if available, falling
            back to 20ms.

    Returns:
        A numpy structured array with ``event_dtype``, sorted by exchange
        timestamp, with correct EXCH_EVENT/LOCAL_EVENT flags applied.
    """
    if not rows:
        return np.zeros(0, dtype=event_dtype)

    data_type = data_type.lower()

    if data_type == "orderbooks":
        events = _make_book_events(rows, constant_latency)
    elif data_type == "trades":
        events = _make_trade_events(rows, constant_latency)
    else:
        raise ValueError(f"Unknown data_type: {data_type!r} (expected 'orderbooks' or 'trades')")

    if len(events) == 0:
        return events

    # Sort by exchange timestamp (stable sort)
    events = events[np.argsort(events["exch_ts"], kind="mergesort")]

    # Correct event ordering
    return correct_event_order(events)


# ── File I/O ─────────────────────────────────────────────────────────────


def save_event_array(events: NDArray, output_path: str) -> str:
    """Save an event array to a ``.npy`` file.

    Args:
        events: Numpy structured array with ``event_dtype``.
        output_path: Destination file path (``.npy`` extension).

    Returns:
        The path that was written to.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    np.save(output_path, events)
    return output_path


def load_event_array(path: str) -> NDArray:
    """Load an event array from a ``.npy`` file.

    Args:
        path: Path to a ``.npy`` file produced by :func:`save_event_array`.

    Returns:
        The event array with ``event_dtype``.
    """
    return np.load(path)


# ── Pipeline integration ─────────────────────────────────────────────────


def convert_from_data_dir(
    data_dir: str,
    output: str,
    *,
    data_type: str = "orderbooks",
    constant_latency: int | None = None,
) -> int:
    """Collect data from *data_dir*, convert to hftbacktest events, and save.

    This is the main entry point that bridges the export pipeline with the
    hftbacktest format converter.

    Args:
        data_dir: Root data directory (same as export_pipeline's ``data_dir``).
        output: Output ``.npy`` file path.
        data_type: ``"orderbooks"`` or ``"trades"``.
        constant_latency: Optional fixed latency in nanoseconds.

    Returns:
        Number of events written (0 if nothing to convert).
    """
    from .export_pipeline import collect_orderbooks, collect_trades

    if data_type == "orderbooks":
        rows = collect_orderbooks(data_dir)
    elif data_type == "trades":
        rows = collect_trades(data_dir)
    else:
        raise ValueError(f"Unknown data_type: {data_type!r}")

    if not rows:
        return 0

    events = rows_to_hbt(rows, data_type=data_type, constant_latency=constant_latency)
    save_event_array(events, output)
    return len(events)


# ── CLI ──────────────────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point (``polymarket-hbt-convert`` command)."""
    parser = argparse.ArgumentParser(
        description="Convert collected Polymarket L2 data to hftbacktest event format (.npy)"
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Root data directory (default: data)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output .npy file path",
    )
    parser.add_argument(
        "--data-type",
        default="orderbooks",
        choices=["orderbooks", "trades"],
        help="Data type to convert (default: orderbooks)",
    )
    parser.add_argument(
        "--constant-latency",
        type=int,
        default=None,
        help="Fixed latency in nanoseconds (default: use local_timestamp, fallback 20ms)",
    )
    args = parser.parse_args()

    count = convert_from_data_dir(
        data_dir=args.data_dir,
        output=args.output,
        data_type=args.data_type,
        constant_latency=args.constant_latency,
    )
    if count > 0:
        print(f"✅ Converted {count} events → {args.output}")
    else:
        print("⚠️  Nothing to convert (no data files found)")


if __name__ == "__main__":
    main()
