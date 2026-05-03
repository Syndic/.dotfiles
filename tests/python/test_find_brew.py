"""Tests for phase2.find_brew — locates an existing Homebrew install."""
from pathlib import Path

import phase2


def test_finds_brew_via_path(monkeypatch):
    """If `brew` is in PATH, return that path immediately."""
    monkeypatch.setattr(
        phase2.shutil, "which",
        lambda name: "/some/path/brew" if name == "brew" else None,
    )
    assert phase2.find_brew() == Path("/some/path/brew")


def test_falls_back_to_known_locations(monkeypatch, tmp_path):
    """If `brew` isn't in PATH, check the Apple-Silicon / Intel install paths."""
    fake_brew = tmp_path / "brew"
    fake_brew.write_text("")
    monkeypatch.setattr(phase2.shutil, "which", lambda name: None)
    monkeypatch.setattr(phase2, "BREW_PATHS", [Path("/nonexistent"), fake_brew])
    assert phase2.find_brew() == fake_brew


def test_returns_none_when_brew_missing(monkeypatch, tmp_path):
    """If brew isn't on PATH and isn't in any known location, return None."""
    monkeypatch.setattr(phase2.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        phase2, "BREW_PATHS",
        [tmp_path / "missing1", tmp_path / "missing2"],
    )
    assert phase2.find_brew() is None
