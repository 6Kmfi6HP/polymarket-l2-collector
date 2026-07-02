"""
Unit tests for shared utility functions — read_last_line and friends.

Ported from poly_data's test_process_live.py::TestReadLastLine.
"""

from __future__ import annotations

from polymarket_l2_collector.utils import read_last_line


class TestReadLastLine:
    """Reading the last line of a file without loading it entirely."""

    def test_multiple_lines(self, tmp_path) -> None:
        p = tmp_path / "f.csv"
        p.write_text("a,1\nb,2\nc,3\n")
        assert read_last_line(str(p)) == "c,3"

    def test_no_trailing_newline(self, tmp_path) -> None:
        p = tmp_path / "f.csv"
        p.write_text("a,1\nb,2")
        assert read_last_line(str(p)) == "b,2"

    def test_single_line(self, tmp_path) -> None:
        p = tmp_path / "f.csv"
        p.write_text("only,row\n")
        assert read_last_line(str(p)) == "only,row"

    def test_empty_file(self, tmp_path) -> None:
        p = tmp_path / "f.csv"
        p.write_text("")
        assert read_last_line(str(p)) == ""

    def test_line_longer_than_chunk(self, tmp_path) -> None:
        """Last line exceeds the 4096-byte seek block → must keep walking back."""
        p = tmp_path / "f.csv"
        last = "x" * 10000
        p.write_text("first\n" + last + "\n")
        assert read_last_line(str(p)) == last

    def test_only_newlines(self, tmp_path) -> None:
        p = tmp_path / "f.csv"
        p.write_text("\n\n\n")
        assert read_last_line(str(p)) == ""

    def test_single_char_line(self, tmp_path) -> None:
        p = tmp_path / "f.csv"
        p.write_text("a\n")
        assert read_last_line(str(p)) == "a"

    def test_utf8_content(self, tmp_path) -> None:
        p = tmp_path / "f.csv"
        p.write_text("header\n中文,行情,€100\n")
        assert read_last_line(str(p)) == "中文,行情,€100"

    def test_missing_file(self, tmp_path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            read_last_line(str(tmp_path / "nonexistent.csv"))
