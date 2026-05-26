"""Tests for phase2.run_playbook — verify that the `--no-upgrade` flag
(parsed into args.upgrade=False) actually reaches the ansible-playbook
invocation as `-e homebrew_upgrade_outdated=false`, and that a stock
run does NOT inject the override (the role default is true, so the
implicit case should leave the command line clean)."""

from typing import Any

import phase2


def _capture_run(monkeypatch) -> list[list[str]]:
    """Monkeypatch phase2.run to record argv lists instead of executing."""
    captured: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> None:
        captured.append(list(cmd))

    monkeypatch.setattr(phase2, "run", fake_run)
    return captured


def test_default_run_omits_upgrade_override(monkeypatch):
    captured = _capture_run(monkeypatch)
    phase2.run_playbook("laptop24")
    assert len(captured) == 1
    cmd = captured[0]
    assert "homebrew_upgrade_outdated=false" not in " ".join(cmd)
    assert "--extra-vars" not in cmd


def test_no_upgrade_injects_extra_var(monkeypatch):
    captured = _capture_run(monkeypatch)
    phase2.run_playbook("laptop24", upgrade=False)
    assert len(captured) == 1
    cmd = captured[0]
    assert "--extra-vars" in cmd
    idx = cmd.index("--extra-vars")
    assert cmd[idx + 1] == "homebrew_upgrade_outdated=false"
