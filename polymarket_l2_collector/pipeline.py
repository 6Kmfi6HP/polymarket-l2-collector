"""
Pipeline orchestration — runs the collector stages in order.

Mirrors poly_data's ``update_utils/pipeline.py`` which chains
markets → chain → process.  Here the stages are:

  1. Markets — ensure CLOB market list is downloaded
  2. Export  — consolidate all collected data into unified Parquet/CSV

Each stage is independently idempotent; rerunning only pulls deltas.

CLI::

    python -m polymarket_l2_collector.pipeline
    python -m polymarket_l2_collector.pipeline --skip-export
    python -m polymarket_l2_collector.pipeline --data-type orderbooks --output exports/orderbooks.parquet
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .clob_markets import download_markets_file
from .export_pipeline import export_pipeline, summary_report
from .logger_config import get_logger

logger = get_logger("pipeline")


def _line_buffer_stdout() -> None:
    """Flush stdout on every line so progress shows live when the output is
    piped (e.g. through ``uv run``), where Python would otherwise block-buffer
    it."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)


def _run(name: str, fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a stage with start/done logging."""
    print(f"[{name}] starting")
    try:
        result = fn(*args, **kwargs)
        print(f"[{name}] done")
        return result
    except Exception as e:
        print(f"[{name}] FAILED: {e}")
        raise


def run_pipeline(
    data_dir: str = "data",
    output: str = "exports/consolidated.parquet",
    data_type: str = "trades",
    dedup: bool = True,
    skip_export: bool = False,
    enrich: bool = False,
) -> int:
    """Run the full pipeline: markets → export.

    Args:
        data_dir: Root data directory.
        output: Output path for the export stage (.parquet or .csv).
        data_type: Data type to export ("trades" or "orderbooks").
        dedup: Remove duplicate rows during export.
        skip_export: If True, only run the markets stage.
        enrich: If True, attach market metadata (question, slug, outcomes)
            during the export stage.

    Returns:
        Number of rows exported (0 if skipped or nothing to export).
    """
    print("=" * 60)
    print("Polymarket L2 Collector — Pipeline")
    print("=" * 60)

    # 1. Markets — download if not already complete
    _run("markets", download_markets_file, output_dir=data_dir)

    # 2. Export — consolidate collected data
    if skip_export:
        print("[export] skipped (--skip-export)")
        # Still show a summary
        report = _run("summary", summary_report, data_dir)
        print(f"\n  Files: {report['total_files']}  Windows: {report['window_count']}")
        print(f"  By type: {report['by_type']}")
        print(f"  By coin: {report['by_coin']}")
        return 0

    export_count = _run(
        "export",
        export_pipeline,
        data_dir=data_dir,
        output=output,
        data_type=data_type,
        dedup=dedup,
        enrich=enrich,
    )

    print("=" * 60)
    if export_count > 0:
        print(f"✅ Pipeline complete — {export_count:,} rows → {output}")
    else:
        print("⚠️  Pipeline complete — nothing to export")
    print("=" * 60)

    return export_count


def main() -> None:
    """CLI entry point (``polymarket-pipeline`` command)."""
    _line_buffer_stdout()
    parser = argparse.ArgumentParser(
        description="Polymarket L2 Collector — full pipeline (markets → export)"
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Root data directory (default: data)",
    )
    parser.add_argument(
        "--output",
        default="exports/consolidated.parquet",
        help="Output path for export (.csv or .parquet, default: exports/consolidated.parquet)",
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
        help="Skip duplicate removal during export",
    )
    parser.add_argument(
        "--skip-export",
        action="store_true",
        help="Only run the markets stage, skip export",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Attach market metadata (question, slug, outcomes) via Gamma API",
    )
    args = parser.parse_args()

    run_pipeline(
        data_dir=args.data_dir,
        output=args.output,
        data_type=args.data_type,
        dedup=not args.no_dedup,
        skip_export=args.skip_export,
        enrich=args.enrich,
    )


if __name__ == "__main__":
    main()
