"""Tests for phase2's output helpers — confirm routing (stdout vs stderr) and
ANSI escape codes are present so visual styling lands on the right stream."""
import os
import shutil
import pytest

import phase2


def _pin_terminal_cols(monkeypatch, cols):
    """Pin shutil.get_terminal_size() to a known column count. Uses
    os.terminal_size so the fake supports tuple unpacking, which pytest
    itself relies on when it queries the terminal width for its own layout."""
    fake_size = os.terminal_size((cols, 24))
    monkeypatch.setattr(shutil, "get_terminal_size", lambda *a, **k: fake_size)


def test_announce_writes_to_stdout(capsys):
    phase2.announce("Header")
    out = capsys.readouterr()
    assert "Header" in out.out
    assert out.err == ""
    assert "\x1b[1;37;43m" in out.out  # yellow background


def test_info_writes_to_stdout(capsys):
    phase2.info("hello")
    out = capsys.readouterr()
    assert "hello" in out.out
    assert out.err == ""
    assert "\x1b[1;37;44m" in out.out  # blue background
    assert "\x1b[0m" in out.out         # reset


def test_warn_writes_to_stderr(capsys):
    phase2.warn("careful")
    out = capsys.readouterr()
    assert out.out == ""
    assert "careful" in out.err
    assert "\x1b[1;37;43m" in out.err


def test_die_writes_to_stderr_and_exits_1(capsys):
    with pytest.raises(SystemExit) as exc:
        phase2.die("boom")
    assert exc.value.code == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "boom" in out.err
    assert "\x1b[1;37;101m" in out.err  # red background


def test_centered_announce_writes_to_stdout(capsys, monkeypatch):
    _pin_terminal_cols(monkeypatch, 80)
    phase2.centered_announce("hello")
    out = capsys.readouterr()
    assert "hello" in out.out
    assert out.err == ""
    assert "\x1b[1;37;43m" in out.out  # yellow background


def test_centered_announce_indents_proportional_to_terminal(capsys, monkeypatch):
    """The visible block is ' MSG ' (the ANSI banner literally pads the
    message with one space on each side), so the indent should be
    (cols - (len(msg) + 2)) // 2 to truly center the visible block."""
    _pin_terminal_cols(monkeypatch, 80)
    phase2.centered_announce("hello")
    lines = capsys.readouterr().out.splitlines()
    # Expect: ["", "<indent><ansi> hello <reset>"]
    assert lines[0] == ""
    expected_indent = (80 - (len("hello") + 2)) // 2
    assert lines[1].startswith(" " * expected_indent + "\x1b[")


def test_centered_announce_clamps_indent_to_zero_when_msg_wider_than_terminal(
    capsys, monkeypatch
):
    """A message longer than the terminal must not produce a negative indent."""
    _pin_terminal_cols(monkeypatch, 5)
    phase2.centered_announce("longer than the terminal")
    out = capsys.readouterr().out
    assert "longer than the terminal" in out
    # The line with the message should not start with whitespace from a
    # negative-pad bug.
    line = [ln for ln in out.splitlines() if "longer" in ln][0]
    assert not line.startswith(" ")
