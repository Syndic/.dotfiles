"""Tests for phase2.display_kilobyte — picks the largest kilobyte<N>.txt
that fits in the current terminal width and prints it centered."""
import os
import shutil
import pytest

import phase2


@pytest.fixture
def fake_art_dir(tmp_path, monkeypatch):
    """Create tmp_path/ascii_art/ with three sized kilobyte files plus junk
    that should be filtered out, and point phase2.DOTFILES_DIR at tmp_path."""
    art_dir = tmp_path / "ascii_art"
    art_dir.mkdir()
    # Distinguishable single-line bodies so we can tell which file rendered.
    (art_dir / "kilobyte40.txt").write_text("FORTY\n")
    (art_dir / "kilobyte80.txt").write_text("EIGHTY\n")
    (art_dir / "kilobyte160.txt").write_text("ONE-SIXTY\n")
    # Junk that should be skipped by the int() filter.
    (art_dir / "kilobyte.txt").write_text("NO-NUMBER\n")
    (art_dir / "kilobyte_xl.txt").write_text("NOT-A-NUMBER\n")
    (art_dir / "README.md").write_text("# notes\n")
    monkeypatch.setattr(phase2, "DOTFILES_DIR", tmp_path)
    return art_dir


def set_terminal_cols(monkeypatch, cols):
    """Pin shutil.get_terminal_size() to a known column count.
    Use os.terminal_size (the real NamedTuple) so the fake supports both
    attribute access (.columns) and tuple unpacking — pytest itself calls
    get_terminal_size() for its own layout and expects the latter."""
    fake_size = os.terminal_size((cols, 24))
    monkeypatch.setattr(shutil, "get_terminal_size", lambda *a, **k: fake_size)


# ---------------------------------------------------------------------------
# Selection logic
# ---------------------------------------------------------------------------


def test_picks_largest_that_fits(fake_art_dir, monkeypatch, capsys):
    set_terminal_cols(monkeypatch, 100)
    phase2.display_kilobyte()
    out = capsys.readouterr().out
    assert "EIGHTY" in out          # 80 fits
    assert "FORTY" not in out
    assert "ONE-SIXTY" not in out   # 160 > 100, doesn't fit


def test_picks_widest_when_all_fit(fake_art_dir, monkeypatch, capsys):
    set_terminal_cols(monkeypatch, 200)
    phase2.display_kilobyte()
    out = capsys.readouterr().out
    assert "ONE-SIXTY" in out
    assert "EIGHTY" not in out
    assert "FORTY" not in out


def test_exact_terminal_width_fits(fake_art_dir, monkeypatch, capsys):
    """A file whose width exactly matches the terminal should still fit."""
    set_terminal_cols(monkeypatch, 80)
    phase2.display_kilobyte()
    out = capsys.readouterr().out
    assert "EIGHTY" in out


def test_falls_back_to_smallest_when_nothing_fits(fake_art_dir, monkeypatch, capsys):
    """Even if no file fits, we still render the smallest one (always show
    the corgi). Indent is clamped so we don't crash on negative padding."""
    set_terminal_cols(monkeypatch, 10)
    phase2.display_kilobyte()
    out = capsys.readouterr().out
    assert "FORTY" in out
    assert "EIGHTY" not in out
    assert "ONE-SIXTY" not in out


# ---------------------------------------------------------------------------
# Centering
# ---------------------------------------------------------------------------


def test_centers_output(fake_art_dir, monkeypatch, capsys):
    """term=100, picked file=80 wide → indent=(100-80)//2=10 spaces."""
    set_terminal_cols(monkeypatch, 100)
    phase2.display_kilobyte()
    out = capsys.readouterr().out
    assert out.startswith(" " * 10 + "EIGHTY")


def test_no_indent_when_art_wider_than_terminal(fake_art_dir, monkeypatch, capsys):
    """When fallback-to-smallest kicks in and the file is wider than the
    terminal, indent should clamp to 0 instead of going negative."""
    set_terminal_cols(monkeypatch, 10)
    phase2.display_kilobyte()
    out = capsys.readouterr().out
    # FORTY is 40-wide, terminal is 10 — no leading whitespace.
    assert out.startswith("FORTY")


# ---------------------------------------------------------------------------
# Empty / missing / junk-only directories
# ---------------------------------------------------------------------------


def test_no_output_when_art_dir_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(phase2, "DOTFILES_DIR", tmp_path)  # no ascii_art/
    set_terminal_cols(monkeypatch, 100)
    phase2.display_kilobyte()
    assert capsys.readouterr().out == ""


def test_no_output_when_art_dir_empty(tmp_path, monkeypatch, capsys):
    (tmp_path / "ascii_art").mkdir()
    monkeypatch.setattr(phase2, "DOTFILES_DIR", tmp_path)
    set_terminal_cols(monkeypatch, 100)
    phase2.display_kilobyte()
    assert capsys.readouterr().out == ""


def test_no_output_when_only_junk_files(tmp_path, monkeypatch, capsys):
    """Files that don't have a numeric width suffix are silently skipped."""
    art_dir = tmp_path / "ascii_art"
    art_dir.mkdir()
    (art_dir / "kilobyte.txt").write_text("no number\n")
    (art_dir / "kilobyte_xl.txt").write_text("not a number\n")
    (art_dir / "README.md").write_text("# notes\n")
    monkeypatch.setattr(phase2, "DOTFILES_DIR", tmp_path)
    set_terminal_cols(monkeypatch, 100)
    phase2.display_kilobyte()
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def test_strips_crlf_line_endings(fake_art_dir, monkeypatch, capsys):
    """CRLF source files (Windows-saved art) shouldn't leak ^M into output."""
    (fake_art_dir / "kilobyte80.txt").write_text("LINE-A\r\nLINE-B\r\n")
    set_terminal_cols(monkeypatch, 100)
    phase2.display_kilobyte()
    out = capsys.readouterr().out
    assert "\r" not in out
    assert "LINE-A" in out
    assert "LINE-B" in out


def test_handles_multiline_art(fake_art_dir, monkeypatch, capsys):
    """Each line of the file becomes one printed line, each indented."""
    (fake_art_dir / "kilobyte80.txt").write_text("L1\nL2\nL3\n")
    set_terminal_cols(monkeypatch, 100)
    phase2.display_kilobyte()
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert lines[0].endswith("L1")
    assert lines[1].endswith("L2")
    assert lines[2].endswith("L3")
    # Same indent on every line.
    assert lines[0].rstrip("L1") == lines[1].rstrip("L2") == lines[2].rstrip("L3")
