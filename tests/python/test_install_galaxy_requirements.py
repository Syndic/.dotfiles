"""Tests for phase2.install_galaxy_requirements — verify it shells out
to ansible-galaxy when requirements.yml exists, and no-ops when it
doesn't. The actual Galaxy fetch is not exercised (network-dependent,
covered in e2e)."""

from pathlib import Path
from typing import Any

import phase2


def _capture_run(monkeypatch) -> list[list[str]]:
    captured: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> None:
        captured.append(list(cmd))

    monkeypatch.setattr(phase2, "run", fake_run)
    return captured


def test_install_galaxy_requirements_runs_collection_install(monkeypatch, tmp_path):
    req = tmp_path / "requirements.yml"
    req.write_text("---\ncollections:\n  - name: community.general\n")
    monkeypatch.setattr(phase2, "DOTFILES_DIR", tmp_path)

    captured = _capture_run(monkeypatch)
    phase2.install_galaxy_requirements()

    assert len(captured) == 1
    cmd = captured[0]
    assert cmd[:4] == ["ansible-galaxy", "collection", "install", "-r"]
    assert cmd[4] == str(req)


def test_install_galaxy_requirements_noops_without_file(monkeypatch, tmp_path):
    monkeypatch.setattr(phase2, "DOTFILES_DIR", tmp_path)
    captured = _capture_run(monkeypatch)

    phase2.install_galaxy_requirements()

    assert captured == []


def test_repo_requirements_yml_declares_expected_collections() -> None:
    """Lock in the two collections the macos_defaults role depends on:
    community.general for osx_defaults, geerlingguy.mac for the dock role."""
    repo_root = Path(__file__).resolve().parents[2]
    text = (repo_root / "requirements.yml").read_text()

    assert "community.general" in text
    assert "geerlingguy.mac" in text
