"""Tests for phase2.brew_shellenv.

The point of brew_shellenv is to make `brew` and brew-installed binaries
reachable on PATH for subsequent subprocess calls (the `brew install ansible`
that comes next, and brew's own shell-outs that need /usr/bin tools like
`readlink`). The previous implementation parsed `brew shellenv` output and
stored the literal `${PATH+:$PATH}` as part of PATH, clobbering /usr/bin and
breaking brew. These tests pin down the new direct-PATH approach.
"""
from __future__ import annotations

import os
from pathlib import Path

import phase2


def test_prepends_brew_bin_and_sbin_to_path(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    phase2.brew_shellenv(Path("/home/linuxbrew/.linuxbrew/bin/brew"))

    parts = os.environ["PATH"].split(os.pathsep)
    assert parts[0] == "/home/linuxbrew/.linuxbrew/bin"
    assert parts[1] == "/home/linuxbrew/.linuxbrew/sbin"
    # Existing PATH must still be there — we PREPEND, not REPLACE.
    assert "/usr/bin" in parts
    assert "/bin" in parts


def test_preserves_existing_path(monkeypatch):
    """Critical regression guard: the broken version stored literal
    `${PATH+:$PATH}` in PATH, which lost /usr/bin and broke any subprocess
    that needed standard tools (e.g. brew shelling out to readlink)."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    phase2.brew_shellenv(Path("/opt/homebrew/bin/brew"))

    assert "${PATH+:$PATH}" not in os.environ["PATH"]
    assert "$PATH" not in os.environ["PATH"]
    assert "/usr/bin" in os.environ["PATH"].split(os.pathsep)


def test_idempotent_when_brew_already_on_path(monkeypatch):
    """Calling shellenv twice (or with brew already in PATH from a prior
    install) shouldn't keep prepending the same entries."""
    monkeypatch.setenv("PATH", "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/bin:/bin")
    phase2.brew_shellenv(Path("/opt/homebrew/bin/brew"))

    parts = os.environ["PATH"].split(os.pathsep)
    # Brew dirs should appear exactly once each.
    assert parts.count("/opt/homebrew/bin") == 1
    assert parts.count("/opt/homebrew/sbin") == 1


def test_works_with_intel_macos_prefix(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    phase2.brew_shellenv(Path("/usr/local/bin/brew"))

    parts = os.environ["PATH"].split(os.pathsep)
    assert "/usr/local/bin" in parts
    assert "/usr/local/sbin" in parts


def test_works_with_linuxbrew_single_user_prefix(monkeypatch, tmp_path):
    """Single-user Linuxbrew lives under $HOME/.linuxbrew."""
    brew = tmp_path / ".linuxbrew" / "bin" / "brew"
    monkeypatch.setenv("PATH", "/usr/bin")
    phase2.brew_shellenv(brew)

    parts = os.environ["PATH"].split(os.pathsep)
    assert str(tmp_path / ".linuxbrew" / "bin") in parts
    assert str(tmp_path / ".linuxbrew" / "sbin") in parts
