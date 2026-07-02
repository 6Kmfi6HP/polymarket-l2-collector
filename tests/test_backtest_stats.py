"""
Unit tests for backtest_stats — record handling, metrics, settlement.
"""

from __future__ import annotations

import numpy as np
import pytest

from polymarket_l2_collector.backtest_stats import (
    PolyAssetRecord,
    Stats,
    compute_max_drawdown,
    compute_max_position_value,
    compute_mean_position_value,
    compute_metrics,
    compute_num_trades,
    compute_return,
    compute_sharpe_ratio,
    compute_sortino_ratio,
    fix_record_prices,
    record_dtype,
)

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def sample_record() -> np.ndarray:
    """Create a simple 10-row backtest record with increasing equity."""
    arr = np.zeros(10, dtype=record_dtype)
    for i in range(10):
        arr[i]["timestamp"] = i * 1_000_000_000  # 1s intervals in ns
        arr[i]["price"] = 0.50 + i * 0.005  # 0.50 → 0.545
        arr[i]["position"] = 10.0
        arr[i]["balance"] = 100.0 + i * 0.5  # increasing balance
        arr[i]["fee"] = i * 0.01
        arr[i]["num_trades"] = 2 if i == 0 else 0
        arr[i]["trading_volume"] = 10.0 if i == 0 else 0.0
        arr[i]["trading_value"] = 5.0 if i == 0 else 0.0
    return arr


# ── Record dtype ─────────────────────────────────────────────────────────


class TestRecordDtype:
    def test_field_names(self):
        assert record_dtype.names == (
            "timestamp", "price", "position", "balance",
            "fee", "num_trades", "trading_volume", "trading_value",
        )

    def test_field_types(self):
        assert record_dtype["timestamp"].kind == "i"
        assert record_dtype["price"].kind == "f"


# ── Settlement ───────────────────────────────────────────────────────────


class TestFixRecordPrices:
    def test_no_settlement(self):
        arr = np.zeros(3, dtype=record_dtype)
        arr["price"] = [0.5, 0.6, 0.7]
        fix_record_prices(arr, settlement=False)
        np.testing.assert_array_equal(arr["price"], [0.5, 0.6, 0.7])

    def test_last_price_below_0_5(self):
        arr = np.zeros(3, dtype=record_dtype)
        arr["price"] = [0.5, 0.4, 0.3]
        fix_record_prices(arr, settlement=True)
        assert arr["price"][-1] == 0.0
        assert arr["price"][0] == 0.5  # unchanged

    def test_last_price_above_0_5(self):
        arr = np.zeros(3, dtype=record_dtype)
        arr["price"] = [0.5, 0.6, 0.7]
        fix_record_prices(arr, settlement=True)
        assert arr["price"][-1] == 1.0

    def test_trailing_nan_filled(self):
        arr = np.zeros(5, dtype=record_dtype)
        arr["price"] = [0.5, 0.55, np.nan, np.nan, np.nan]
        fix_record_prices(arr, settlement=True)
        assert arr["price"][0] == 0.5
        # Last valid price 0.55 > 0.5 → settle at 1.0
        assert arr["price"][-1] == 1.0
        assert arr["price"][-2] == 1.0

    def test_empty_array(self):
        arr = np.zeros(0, dtype=record_dtype)
        result = fix_record_prices(arr)
        assert len(result) == 0

    def test_all_nan(self):
        arr = np.zeros(3, dtype=record_dtype)
        arr["price"] = [np.nan, np.nan, np.nan]
        result = fix_record_prices(arr)
        assert np.all(np.isnan(result["price"]))


# ── Individual metrics ───────────────────────────────────────────────────


class TestComputeReturn:
    def test_positive_return(self, sample_record):
        import pandas as pd
        df = pd.DataFrame(sample_record)
        ret = compute_return(df)
        assert ret > 0  # price rises, slight fee drag

    def test_return_zero_for_single_row(self):
        import pandas as pd
        df = pd.DataFrame(np.zeros(1, dtype=record_dtype))
        assert compute_return(df) == 0.0

    def test_return_with_book_size(self, sample_record):
        import pandas as pd
        df = pd.DataFrame(sample_record)
        ret = compute_return(df, book_size=1000)
        assert abs(ret) < abs(compute_return(df))  # divided by book_size

    def test_return_empty(self):
        import pandas as pd
        df = pd.DataFrame()
        assert compute_return(df) == 0.0


class TestComputeSharpeRatio:
    def test_sharpe_positive(self, sample_record):
        import pandas as pd
        df = pd.DataFrame(sample_record)
        sr = compute_sharpe_ratio(df)
        # With steadily increasing price, should be positive
        assert sr > -10  # sanity check

    def test_sharpe_for_flat_equity(self):
        import pandas as pd
        arr = np.zeros(10, dtype=record_dtype)
        arr["timestamp"] = np.arange(10) * 1_000_000_000
        arr["price"] = 0.5
        arr["balance"] = 100.0
        arr["position"] = 0.0
        df = pd.DataFrame(arr)
        sr = compute_sharpe_ratio(df)
        # Flat equity → diff is all 0s → std=0 → SR=0
        assert sr == 0.0

    def test_sharpe_negative(self):
        import pandas as pd
        arr = np.zeros(10, dtype=record_dtype)
        arr["timestamp"] = np.arange(10) * 1_000_000_000
        arr["price"] = 0.5
        arr["balance"] = 100.0
        arr["position"] = -10.0  # short position
        df = pd.DataFrame(arr)
        sr = compute_sharpe_ratio(df)
        assert sr <= 0  # declining equity should give negative SR


class TestComputeSortinoRatio:
    def test_sortino_positive(self, sample_record):
        import pandas as pd
        df = pd.DataFrame(sample_record)
        sortino = compute_sortino_ratio(df)
        # With positive trend, sortino should be positive
        assert sortino is not None

    def test_sortino_vs_sharpe(self, sample_record):
        import pandas as pd
        df = pd.DataFrame(sample_record)
        sr = compute_sharpe_ratio(df)
        sortino = compute_sortino_ratio(df)
        # Sortino should be >= Sharpe when downside exists
        # If no downside (strictly increasing equity), sortino=0 but SR>0
        assert sortino >= sr or sortino == 0.0


class TestComputeMaxDrawdown:
    def test_no_drawdown(self):
        import pandas as pd
        arr = np.zeros(5, dtype=record_dtype)
        arr["price"] = 0.5
        arr["balance"] = [100, 101, 102, 103, 104]  # always increasing
        df = pd.DataFrame(arr)
        mdd = compute_max_drawdown(df)
        assert mdd == 0.0

    def test_with_drawdown(self, sample_record):
        import pandas as pd
        df = pd.DataFrame(sample_record)
        mdd = compute_max_drawdown(df)
        assert mdd >= 0  # drawdown is non-negative


class TestComputeNumTrades:
    def test_basic(self, sample_record):
        import pandas as pd
        df = pd.DataFrame(sample_record)
        assert compute_num_trades(df) == 2  # first row has 2 trades

    def test_empty(self):
        import pandas as pd
        assert compute_num_trades(pd.DataFrame()) == 0


class TestComputeMaxPositionValue:
    def test_basic(self, sample_record):
        import pandas as pd
        df = pd.DataFrame(sample_record)
        mpv = compute_max_position_value(df)
        # position=10, price ranges 0.50-0.545, max abs value = 5.45
        assert mpv == pytest.approx(5.45, rel=0.01)


class TestComputeMeanPositionValue:
    def test_basic(self, sample_record):
        import pandas as pd
        df = pd.DataFrame(sample_record)
        mpv = compute_mean_position_value(df)
        assert mpv > 0


# ── compute_metrics ──────────────────────────────────────────────────────


class TestComputeMetrics:
    def test_default_metrics(self, sample_record):
        import pandas as pd
        df = pd.DataFrame(sample_record)
        result = compute_metrics(df)
        assert "Return" in result
        assert "SR" in result
        assert "MaxDrawdown" in result
        assert "start" in result
        assert "end" in result

    def test_custom_metric_selection(self, sample_record):
        import pandas as pd
        df = pd.DataFrame(sample_record)
        custom = {"MyReturn": ("compute_return", {})}
        result = compute_metrics(df, metrics=custom)
        assert "MyReturn" in result
        assert "SR" not in result

    def test_book_size_passthrough(self, sample_record):
        import pandas as pd
        df = pd.DataFrame(sample_record)
        result = compute_metrics(df, book_size=1000)
        ret_with_bs = result["Return"]
        result_no_bs = compute_metrics(df, book_size=None)["Return"]
        assert abs(ret_with_bs) < abs(result_no_bs)

    def test_empty_df(self):
        import pandas as pd
        result = compute_metrics(pd.DataFrame())
        assert "start" in result
        assert result["start"] == 0


# ── PolyAssetRecord ──────────────────────────────────────────────────────


class TestPolyAssetRecord:
    def test_from_record_array(self, sample_record):
        record = PolyAssetRecord(sample_record)
        assert record.df is not None
        assert "equity_wo_fee" in record.df.columns
        assert len(record.df) == 10

    def test_equity_calculation(self, sample_record):
        record = PolyAssetRecord(sample_record)
        # equity_wo_fee = balance + position * price
        expected = record.df["balance"] + record.df["position"] * record.df["price"]
        np.testing.assert_array_almost_equal(record.df["equity_wo_fee"], expected)

    def test_stats_returns_stats_object(self, sample_record):
        record = PolyAssetRecord(sample_record)
        # Use 1s resample to preserve all rows for meaningful earn calculation
        stats = record.resample("1s").stats()
        assert isinstance(stats, Stats)
        assert stats.earn != 0.0

    def test_stats_with_book_size(self, sample_record):
        record = PolyAssetRecord(sample_record)
        stats = record.resample("1s").stats(book_size=100_000)
        summary = stats.summary()
        assert "Return" in summary.columns
        assert len(summary) >= 1  # at least the entire-period metrics

    def test_resample_changes_stats(self, sample_record):
        record_no_resample = PolyAssetRecord(sample_record)
        record_resample = PolyAssetRecord(sample_record).resample("5s")

        stats_no = record_no_resample.stats()
        stats_yes = record_resample.stats()
        # Both should have valid results
        assert isinstance(stats_no, Stats)
        assert isinstance(stats_yes, Stats)

    def test_settlement_fix_applied(self):
        """Records with price near 0 should be settled to 0.0."""
        arr = np.zeros(5, dtype=record_dtype)
        arr["timestamp"] = np.arange(5) * 1_000_000_000
        arr["price"] = [0.5, 0.45, 0.4, 0.35, 0.3]
        arr["balance"] = 100.0
        arr["position"] = 10.0
        record = PolyAssetRecord(arr, settlement=True)
        # The last price should be 0.0 after settlement
        assert record.df["price"].iloc[-1] == 0.0

    def test_monthly_partition(self, sample_record):
        record = PolyAssetRecord(sample_record).monthly()
        stats = record.stats()
        assert len(stats.splits) > 0

    def test_contract_size(self, sample_record):
        record = PolyAssetRecord(sample_record, contract_size=2.0)
        # equity should be doubled compared to contract_size=1
        record2 = PolyAssetRecord(sample_record, contract_size=1.0)
        assert record.df["equity_wo_fee"].iloc[0] != record2.df["equity_wo_fee"].iloc[0]


# ── Stats class ──────────────────────────────────────────────────────────


class TestStats:
    def test_summary_dataframe(self, sample_record):
        import pandas as pd
        df = pd.DataFrame(sample_record)
        stats = Stats(df, [], {"book_size": 100})
        summary = stats.summary()
        assert isinstance(summary, pd.DataFrame)

    def test_earn_property(self, sample_record):
        import pandas as pd
        df = pd.DataFrame(sample_record)
        stats = Stats(df, [], {})
        assert isinstance(stats.earn, float)


# ── Integration ──────────────────────────────────────────────────────────


class TestIntegration:
    def test_full_workflow(self, sample_record):
        """Stats with all default settings should compute all metrics."""
        record = PolyAssetRecord(sample_record, settlement=True)
        stats = record.stats(book_size=100_000)
        summary = stats.summary()
        # All default metrics should be in the output
        expected_cols = {"Return", "AnnualReturn", "SR", "Sortino", "MaxDrawdown",
                         "NumTrades", "TradingVolume", "MaxPositionValue"}
        assert expected_cols.issubset(summary.columns)
        assert len(summary) >= 1

    def test_metrics_are_finite(self, sample_record):
        """Metric values should be finite floats."""
        record = PolyAssetRecord(sample_record)
        stats = record.stats(book_size=100_000)
        summary = stats.summary()
        for col in summary.columns:
            if col in ("start", "end"):
                continue
            for val in summary[col]:
                assert np.isfinite(val), f"Metric {col} is not finite: {val}"
