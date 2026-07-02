#!/usr/bin/env python3
"""
[deprecated] Use ``python -m polymarket_l2_collector.main`` instead.

This stub is kept for backward compatibility.
"""
import warnings

warnings.warn(
    "Run via 'python -m polymarket_l2_collector.main' instead",
    DeprecationWarning,
    stacklevel=2,
)

from polymarket_l2_collector.main import main  # noqa: E402

main()
