"""
Unit tests for the pipeline orchestrator — stage sequencing, logging, CLI.
"""

from __future__ import annotations

from unittest.mock import patch

from polymarket_l2_collector.pipeline import run_pipeline


class TestRunPipeline:
    """Pipeline orchestration — runs stages in order."""

    def test_runs_markets_and_export(self, tmp_path) -> None:
        """Both stages run when skip_export is False."""
        with (
            patch("polymarket_l2_collector.pipeline.download_markets_file") as mock_markets,
            patch("polymarket_l2_collector.pipeline.export_pipeline", return_value=42) as mock_export,
        ):
            result = run_pipeline(data_dir=str(tmp_path), output=f"{tmp_path}/out.parquet")
            assert result == 42
            mock_markets.assert_called_once_with(output_dir=str(tmp_path))
            mock_export.assert_called_once_with(
                data_dir=str(tmp_path),
                output=f"{tmp_path}/out.parquet",
                data_type="trades",
                dedup=True,
            )

    def test_skip_export(self, tmp_path) -> None:
        """When skip_export is True, only markets stage runs."""
        with (
            patch("polymarket_l2_collector.pipeline.download_markets_file") as mock_markets,
            patch("polymarket_l2_collector.pipeline.export_pipeline") as mock_export,
            patch("polymarket_l2_collector.pipeline.summary_report", return_value={
                "total_files": 5, "window_count": 3, "by_type": {"trades": 5}, "by_coin": {"btc": 5},
            }) as mock_summary,
        ):
            result = run_pipeline(data_dir=str(tmp_path), skip_export=True)
            assert result == 0  # export skipped → return 0
            mock_markets.assert_called_once()
            mock_export.assert_not_called()
            mock_summary.assert_called_once()

    def test_passes_dedup_flag(self, tmp_path) -> None:
        """False dedup flag is handed through (no-dedup mode)."""
        with patch("polymarket_l2_collector.pipeline.export_pipeline", return_value=10) as mock_export:
            run_pipeline(
                data_dir=str(tmp_path),
                output=f"{tmp_path}/out.parquet",
                dedup=False,
            )
            mock_export.assert_called_once_with(
                data_dir=str(tmp_path),
                output=f"{tmp_path}/out.parquet",
                data_type="trades",
                dedup=False,
            )

    def test_passes_data_type(self, tmp_path) -> None:
        """Data type 'orderbooks' is handed through to export."""
        with patch("polymarket_l2_collector.pipeline.export_pipeline", return_value=10) as mock_export:
            run_pipeline(
                data_dir=str(tmp_path),
                output=f"{tmp_path}/out.parquet",
                data_type="orderbooks",
            )
            mock_export.assert_called_once_with(
                data_dir=str(tmp_path),
                output=f"{tmp_path}/out.parquet",
                data_type="orderbooks",
                dedup=True,
            )


class TestMainCli:
    """CLI entry-point tests."""

    def test_main_default_args(self, tmp_path) -> None:
        """CLI with no arguments uses sensible defaults."""
        from polymarket_l2_collector.pipeline import main

        with patch(
            "polymarket_l2_collector.pipeline.run_pipeline",
        ) as mock_run:
            with patch("sys.argv", ["pipeline"]):
                main()
            mock_run.assert_called_once_with(
                data_dir="data",
                output="exports/consolidated.parquet",
                data_type="trades",
                dedup=True,
                skip_export=False,
            )

    def test_main_with_flags(self, tmp_path) -> None:
        """CLI flags are propagated correctly."""
        from polymarket_l2_collector.pipeline import main

        with patch(
            "polymarket_l2_collector.pipeline.run_pipeline",
        ) as mock_run:
            with patch(
                "sys.argv",
                ["pipeline", "--data-dir", "/tmp/x", "--output", "/tmp/x.parquet",
                 "--data-type", "orderbooks", "--no-dedup", "--skip-export"],
            ):
                main()
            mock_run.assert_called_once_with(
                data_dir="/tmp/x",
                output="/tmp/x.parquet",
                data_type="orderbooks",
                dedup=False,
                skip_export=True,
            )

    def test_main_skip_export_flag(self, tmp_path) -> None:
        """--skip-export flag is propagated."""
        from polymarket_l2_collector.pipeline import main

        with patch(
            "polymarket_l2_collector.pipeline.run_pipeline",
        ) as mock_run:
            with patch("sys.argv", ["pipeline", "--skip-export"]):
                main()
            mock_run.assert_called_once_with(
                data_dir="data",
                output="exports/consolidated.parquet",
                data_type="trades",
                dedup=True,
                skip_export=True,
            )
