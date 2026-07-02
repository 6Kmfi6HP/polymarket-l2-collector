"""
Shared utility functions for Polymarket L2 collector.

Reduces code duplication across modules by providing common helpers
in one place.
"""

from __future__ import annotations

import os


def read_last_line(path: str) -> str:
    """Return the last non-empty line of a (possibly huge) text file without
    loading it entirely — seek backwards from EOF in chunks.

    A cross-platform replacement for shelling out to ``tail``.

    Args:
        path: Path to the text file.

    Returns:
        The last non-empty line, or ``""`` if the file is empty.
    """
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        if pos == 0:
            return ""
        buf = b""
        while pos > 0:
            step = min(4096, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + buf
            stripped = buf.rstrip(b"\r\n")
            nl = stripped.rfind(b"\n")
            if nl != -1:
                return stripped[nl + 1:].decode("utf-8", errors="replace")
        return buf.rstrip(b"\r\n").decode("utf-8", errors="replace")
