"""
Backtest performance metrics and statistics for Polymarket strategies.

Analyzes backtest record arrays (as produced by hftbacktest's ``Recorder``)
and computes standard financial metrics — Sharpe, Sortino, Max Drawdown,
Return, and Polymarket-specific settlement handling.

Usage::

    import numpy as np
    from polymarket_l2_collector.backtest_stats import PolyAssetRecord

    record = np.load("backtest_result.npy")  # record_dtype array
    stats = PolyAssetRecord(record).resample("10s").stats(book_size=100_000)
    print(stats.summary())
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# ── Record dtype (matches hftbacktest.types.record_dtype) ─────────────────

record_dtype = np.dtype(
    [
        ("timestamp", "i8"),
        ("price", "f8"),
        ("position", "f8"),
        ("balance", "f8"),
        ("fee", "f8"),
        ("num_trades", "i8"),
        ("trading_volume", "f8"),
        ("trading_value", "f8"),
    ],
    align=True,
)

SECONDS_PER_DAY = 86400
TRADING_DAYS_PER_YEAR = 365  # crypto runs 24/7


# ── Price settlement (Polymarket-specific) ───────────────────────────────


def fix_record_prices(record_arr: np.ndarray, settlement: bool = True) -> np.ndarray:
    """Fix settlement prices in a Polymarket backtest record array.

    If the last valid price is < 0.5, sets it to 0.0 (and any trailing NaNs).
    If > 0.5, sets it to 1.0 (and any trailing NaNs).

    Args:
        record_arr: Record array with ``record_dtype`` (modified in-place).
        settlement: If ``True`` (default), apply settlement price logic.

    Returns:
        The same array with fixed prices.
    """
    prices = record_arr["price"]
    valid_idx = np.flatnonzero(np.isfinite(prices))
    if len(valid_idx) == 0:
        return record_arr

    last_idx = int(valid_idx[-1])
    raw_last = float(prices[last_idx])

    if settlement:
        if raw_last < 0.5:
            settle_price = 0.0
        elif raw_last > 0.5:
            settle_price = 1.0
        else:
            settle_price = raw_last

        prices[last_idx] = settle_price
        if last_idx + 1 < len(prices):
            tail = prices[last_idx + 1 :]
            tail[np.isnan(tail)] = settle_price

    return record_arr


# ── Individual metric functions ──────────────────────────────────────────


def _get_equity(df: pd.DataFrame) -> pd.Series:
    """Compute equity series (balance + position value - fees)."""
    if df.empty or "balance" not in df.columns:
        return pd.Series(dtype=float)
    return df["balance"] + df["position"] * df["price"] - df["fee"]


def compute_return(df: pd.DataFrame, book_size: float | None = None) -> float:
    """Compute total return.

    If *book_size* is provided, return is expressed as a fraction of book size.
    """
    equity = _get_equity(df)
    if len(equity) < 2:
        return 0.0
    ret = float(equity.iloc[-1] - equity.iloc[0])
    if book_size is not None and book_size > 0:
        ret /= book_size
    return ret


def compute_annual_return(
    df: pd.DataFrame,
    book_size: float | None = None,
    trading_days: int = 365,
) -> float:
    """Compute annualised return."""
    ret = compute_return(df, book_size)
    days = _get_total_days(df)
    if days > 0:
        ret = ret / days * trading_days
    return ret


def compute_sharpe_ratio(
    df: pd.DataFrame,
    trading_days: int = 365,
) -> float:
    """Compute Sharpe ratio (without risk-free rate).

    Uses daily sampling frequency derived from the data's time span.
    """
    equity = _get_equity(df)
    pnl = equity.diff().dropna()
    if len(pnl) < 2 or pnl.std() == 0:
        return 0.0
    n_per_day = _get_num_samples_per_day(df)
    c = n_per_day * trading_days
    return float(pnl.mean() / pnl.std() * np.sqrt(c))


def compute_sortino_ratio(
    df: pd.DataFrame,
    trading_days: int = 365,
) -> float:
    """Compute Sortino ratio (downside deviation only)."""
    equity = _get_equity(df)
    pnl = equity.diff().dropna()
    if len(pnl) < 2:
        return 0.0
    downside = np.sqrt(np.minimum(0, pnl).pow(2).mean())
    if downside == 0:
        return 0.0
    n_per_day = _get_num_samples_per_day(df)
    c = n_per_day * trading_days
    return float(pnl.mean() / downside * np.sqrt(c))


def compute_max_drawdown(df: pd.DataFrame, book_size: float | None = None) -> float:
    """Compute maximum drawdown (peak-to-trough decline).

    If *book_size* is provided, the drawdown is expressed as a fraction.
    """
    equity = _get_equity(df)
    if len(equity) < 2:
        return 0.0
    max_equity = equity.cummax()
    dd = equity - max_equity
    if book_size is not None and book_size > 0:
        dd = dd / book_size
    return float(abs(dd.min()))


def compute_return_over_mdd(df: pd.DataFrame) -> float:
    """Compute return divided by maximum drawdown."""
    ret = compute_return(df)
    mdd = compute_max_drawdown(df)
    return ret / mdd if mdd != 0 else 0.0


def compute_return_over_trade(df: pd.DataFrame) -> float:
    """Compute profit per unit of trading value."""
    ret = compute_return(df)
    tv = compute_trading_value(df)
    return ret / tv if tv != 0 else 0.0


def compute_num_trades(df: pd.DataFrame) -> int:
    """Compute total number of trades."""
    if df.empty or "num_trades" not in df.columns:
        return 0
    return int(df["num_trades"].sum())


def compute_trading_volume(df: pd.DataFrame) -> float:
    """Compute total trading volume (units traded)."""
    return float(df["trading_volume"].sum())


def compute_trading_value(df: pd.DataFrame) -> float:
    """Compute total trading value."""
    return float(df["trading_value"].sum())


def compute_max_position_value(df: pd.DataFrame) -> float:
    """Compute maximum absolute position value."""
    return float((df["position"].abs() * df["price"]).max())


def compute_mean_position_value(df: pd.DataFrame) -> float:
    """Compute average absolute position value."""
    return float((df["position"].abs() * df["price"]).mean())


# ── Helpers ──────────────────────────────────────────────────────────────


def _get_num_samples_per_day(df: pd.DataFrame) -> float:
    """Estimate number of samples per day based on the data."""
    if len(df) < 2:
        return 1.0
    timestamps = df["timestamp"].values
    intervals = np.diff(timestamps)
    if len(intervals) == 0:
        return 1.0
    median_interval = float(np.median(intervals))
    if median_interval <= 0:
        return 1.0
    return SECONDS_PER_DAY * 1e9 / median_interval  # timestamps are in ns


def _get_total_days(df: pd.DataFrame) -> float:
    """Compute total days spanned by the data."""
    if len(df) < 2:
        return 1.0
    return float((df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]) / 1e9 / SECONDS_PER_DAY)


def _resample(df: pd.DataFrame, frequency: str) -> pd.DataFrame:
    """Resample the DataFrame at a specified frequency.

    Numeric columns are aggregated by last value (except trade/volume cols
    which use sum).
    """
    if len(df) < 2:
        return df

    df = df.copy()
    df["_ts"] = pd.to_datetime(df["timestamp"], unit="ns")
    df = df.set_index("_ts")

    sum_cols = {"trading_value", "trading_volume", "num_trades",
                "trading_value_", "trading_volume_", "num_trades_"}
    agg: dict[str, str] = {}
    for col in df.columns:
        if col in sum_cols:
            agg[col] = "sum"
        else:
            agg[col] = "last"

    resampled = df.resample(frequency).agg(agg).dropna(how="all").reset_index(drop=True)
    return resampled


# ── Stats class ──────────────────────────────────────────────────────────


class Stats:
    """Container for computed performance metrics.

    Attributes:
        entire: The entire (possibly resampled) DataFrame.
        splits: List of per-partition metric dicts.
        kwargs: Keyword args passed to ``stats()``.
    """

    def __init__(self, entire: pd.DataFrame, splits: list[dict[str, Any]], kwargs: dict[str, Any]):
        self.entire = entire
        self.splits = splits
        self.kwargs = kwargs

    @property
    def earn(self) -> float:
        """Total earnings (final equity - initial equity)."""
        equity = _get_equity(self.entire)
        if len(equity) < 2:
            return 0.0
        return float(equity.iloc[-1] - equity.iloc[0])

    def summary(self) -> pd.DataFrame:
        """Return a DataFrame with all computed metrics."""
        return pd.DataFrame(self.splits)

    def __repr__(self) -> str:
        df = self.summary()
        return f"Stats(metrics={len(df.columns)})\n{df.to_string(index=False)}"


# ── Metrics registry ─────────────────────────────────────────────────────

DEFAULT_METRICS: dict[str, Any] = {
    "Return": ("compute_return", {"book_size": None}),
    "AnnualReturn": ("compute_annual_return", {"book_size": None, "trading_days": 365}),
    "SR": ("compute_sharpe_ratio", {"trading_days": 365}),
    "Sortino": ("compute_sortino_ratio", {"trading_days": 365}),
    "MaxDrawdown": ("compute_max_drawdown", {"book_size": None}),
    "NumTrades": ("compute_num_trades", {}),
    "TradingVolume": ("compute_trading_volume", {}),
    "TradingValue": ("compute_trading_value", {}),
    "ReturnOverMDD": ("compute_return_over_mdd", {}),
    "ReturnOverTrade": ("compute_return_over_trade", {}),
    "MaxPositionValue": ("compute_max_position_value", {}),
}


def compute_metrics(df: pd.DataFrame, metrics: dict[str, Any] | None = None,
                    **kwargs: Any) -> dict[str, Any]:
    """Compute a set of metrics on a DataFrame.

    Args:
        df: DataFrame with columns matching the metric functions' expectations
            (``timestamp``, ``price``, ``position``, ``balance``, ``fee``, etc.).
        metrics: Dict mapping metric names to ``(func_name, default_kwargs)``.
            Falls back to :const:`DEFAULT_METRICS` if ``None``.
        kwargs: Override default keyword arguments for all metrics
            (e.g. ``book_size=100_000``).

    Returns:
        Dict of ``{metric_name: computed_value}``.
    """
    if metrics is None:
        metrics = DEFAULT_METRICS

    merged_kwargs = dict(kwargs)
    result: dict[str, Any] = {
        "start": int(df["timestamp"].iloc[0]) if len(df) > 0 and "timestamp" in df.columns else 0,
        "end": int(df["timestamp"].iloc[-1]) if len(df) > 0 and "timestamp" in df.columns else 0,
    }

    if df.empty:
        return result

    for name, (func_name, default_kwargs) in metrics.items():
        func = globals().get(func_name)
        if func is None:
            continue
        local_kw = dict(default_kwargs)
        local_kw.update({k: v for k, v in merged_kwargs.items() if k in default_kwargs or k not in local_kw})
        # Only pass kwargs the function accepts
        import inspect
        sig = inspect.signature(func)
        filtered_kw = {k: v for k, v in local_kw.items() if k in sig.parameters}
        result[name] = func(df, **filtered_kw)

    return result


# ── Record handler (Polymarket-aware) ────────────────────────────────────


class PolyAssetRecord:
    """Polymarket-aware backtest record handler.

    Wraps a ``record_dtype`` numpy array from an hftbacktest backtest,
    applies settlement price fixing, computes equity, and provides
    ``stats()`` for metric computation.

    Args:
        record_arr: Numpy structured array with ``record_dtype``.
        settlement: If ``True`` (default), apply Polymarket settlement
            price fixing.
        contract_size: Contract size multiplier (default 1.0).
        time_unit: Time unit for timestamp conversion (default ``"ns"``).

    Example::

        record = np.load("backtest_result.npy")
        stats = PolyAssetRecord(record).resample("10s").stats(book_size=100_000)
        print(stats.summary())
    """

    def __init__(
        self,
        record_arr: np.ndarray,
        *,
        settlement: bool = True,
        contract_size: float = 1.0,
        time_unit: str = "ns",
    ):
        self._contract_size = contract_size
        self._time_unit = time_unit
        self._frequency: str | None = "10s"
        self._partition: str | None = None

        # Apply settlement price fixing
        arr = fix_record_prices(record_arr.copy(), settlement=settlement)

        # Build DataFrame
        self.df = pd.DataFrame({
            "timestamp": arr["timestamp"],
            "price": arr["price"],
            "position": arr["position"],
            "balance": arr["balance"],
            "fee": arr["fee"],
            "num_trades": arr["num_trades"],
            "trading_volume": arr["trading_volume"],
            "trading_value": arr["trading_value"],
        })

        # Derive derived columns
        self._prepare()

    def _prepare(self) -> None:
        """Compute derived columns for the record."""
        df = self.df

        # Equity without fees
        df["equity_wo_fee"] = df["balance"] + df["position"] * df["price"] * self._contract_size

        # Trading value diff
        df["trading_value_"] = df["trading_value"].diff().fillna(0)

        # Trading volume diff
        df["trading_volume_"] = df["trading_volume"].diff().fillna(0)

        # Num trades diff
        df["num_trades_"] = df["num_trades"].diff().fillna(0)

        self.df = df

    def contract_size(self, size: float) -> PolyAssetRecord:
        """Set contract size multiplier."""
        self._contract_size = size
        self._prepare()
        return self

    def time_unit(self, unit: str) -> PolyAssetRecord:
        """Set time unit for timestamp conversion."""
        self._time_unit = unit
        return self

    def resample(self, frequency: str) -> PolyAssetRecord:
        """Set resampling frequency (e.g. ``"10s"``, ``"1min"``)."""
        self._frequency = frequency
        return self

    def monthly(self) -> PolyAssetRecord:
        """Enable monthly partition."""
        self._partition = "monthly"
        return self

    def daily(self) -> PolyAssetRecord:
        """Enable daily partition."""
        self._partition = "daily"
        return self

    def stats(self, metrics: dict[str, Any] | None = None, **kwargs: Any) -> Stats:
        """Compute performance statistics.

        Args:
            metrics: Custom metrics dict (defaults to :const:`DEFAULT_METRICS`).
            kwargs: Override keyword arguments for metric functions
                (e.g. ``book_size=100_000``).

        Returns:
            A :class:`Stats` instance with all computed metrics.
        """
        if metrics is None:
            metrics = DEFAULT_METRICS

        df = self.df.sort_values("timestamp").reset_index(drop=True)

        # Resample if configured
        if self._frequency is not None:
            df = _resample(df, self._frequency)

        # Partition
        if self._partition == "monthly":
            df["_part"] = pd.to_datetime(df["timestamp"], unit="ns").dt.strftime("%Y%m")
            splits = [g.drop(columns="_part") for _, g in df.groupby("_part")]
        elif self._partition == "daily":
            df["_part"] = pd.to_datetime(df["timestamp"], unit="ns").dt.strftime("%Y%m%d")
            splits = [g.drop(columns="_part") for _, g in df.groupby("_part")]
        else:
            splits = []

        # Compute metrics per partition
        stats_list = [compute_metrics(g, metrics, **kwargs) for g in splits]
        # Compute for entire period
        stats_list.append(compute_metrics(df, metrics, **kwargs))

        return Stats(df, stats_list, kwargs)
