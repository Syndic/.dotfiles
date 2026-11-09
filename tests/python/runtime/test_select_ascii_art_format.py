"""Tests for terminal capability detection in phase2.select_ascii_art_format."""
import phase2


def test_colorterm_truecolor_uses_truecolor(monkeypatch):
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.delenv("TERM", raising=False)

    assert phase2.select_ascii_art_format() == phase2.ASCII_ART_TRUECOLOR_SUBDIR


def test_direct_terminfo_name_uses_truecolor(monkeypatch):
    monkeypatch.delenv("COLORTERM", raising=False)
    monkeypatch.setenv("TERM", "xterm-direct")

    assert phase2.select_ascii_art_format() == phase2.ASCII_ART_TRUECOLOR_SUBDIR


def test_unknown_terminal_falls_back_to_256color(monkeypatch):
    monkeypatch.delenv("COLORTERM", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")

    assert phase2.select_ascii_art_format() == phase2.ASCII_ART_256_COLOR_SUBDIR


def test_term_program_does_not_override_capabilities(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    monkeypatch.delenv("COLORTERM", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")

    assert phase2.select_ascii_art_format() == phase2.ASCII_ART_256_COLOR_SUBDIR
