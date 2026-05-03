"""Tests for phase2's output helpers — confirm routing (stdout vs stderr) and
ANSI escape codes are present so visual styling lands on the right stream."""
import pytest

import phase2


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
