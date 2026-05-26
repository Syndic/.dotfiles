"""Tests for phase2.run_playbook — verify that the opt-out flags
(`--no-upgrade` → args.upgrade=False, `--no-dock` → args.dock=False)
actually reach the ansible-playbook invocation as the matching
`-e <var>=false` overrides, and that a stock run does NOT inject either
override (the role defaults are both true, so the implicit case should
leave the command line clean)."""

from typing import Any

import phase2


def _capture_run(monkeypatch) -> list[list[str]]:
    """Monkeypatch phase2.run to record argv lists instead of executing."""
    captured: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> None:
        captured.append(list(cmd))

    monkeypatch.setattr(phase2, "run", fake_run)
    return captured


def test_default_run_omits_override_flags(monkeypatch):
    captured = _capture_run(monkeypatch)
    phase2.run_playbook("laptop24")
    assert len(captured) == 1
    cmd = captured[0]
    assert "homebrew_upgrade_outdated=false" not in " ".join(cmd)
    assert "configure_dock=false" not in " ".join(cmd)
    assert "--extra-vars" not in cmd


def test_no_upgrade_injects_extra_var(monkeypatch):
    captured = _capture_run(monkeypatch)
    phase2.run_playbook("laptop24", upgrade=False)
    assert len(captured) == 1
    cmd = captured[0]
    extra_vars = [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "--extra-vars"]
    assert "homebrew_upgrade_outdated=false" in extra_vars
    assert "configure_dock=false" not in extra_vars


def test_no_dock_injects_extra_var(monkeypatch):
    captured = _capture_run(monkeypatch)
    phase2.run_playbook("laptop24", dock=False)
    assert len(captured) == 1
    cmd = captured[0]
    extra_vars = [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "--extra-vars"]
    assert "configure_dock=false" in extra_vars
    assert "homebrew_upgrade_outdated=false" not in extra_vars


def test_both_opt_outs_inject_both_extra_vars(monkeypatch):
    captured = _capture_run(monkeypatch)
    phase2.run_playbook("laptop24", upgrade=False, dock=False)
    assert len(captured) == 1
    cmd = captured[0]
    extra_vars = [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "--extra-vars"]
    assert "homebrew_upgrade_outdated=false" in extra_vars
    assert "configure_dock=false" in extra_vars
