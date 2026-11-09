"""Tests for phase2's sudo-password capture and handoff to ansible-playbook.

The contract:
  - capture_sudo_password() pops SUDO_PASSWORD from os.environ so it doesn't
    leak into Homebrew / brew subprocesses inherited by phase 2.
  - run_playbook() passes the captured password to ansible-playbook ONLY via
    the subprocess env (as ANSIBLE_BECOME_PASS), never via os.environ on the
    parent process and never on the command line.
"""
from __future__ import annotations

import phase2


# ---------------------------------------------------------------------------
# capture_sudo_password
# ---------------------------------------------------------------------------

def test_capture_returns_value_and_removes_from_environ(monkeypatch):
    monkeypatch.setenv("SUDO_PASSWORD", "hunter2")
    captured = phase2.capture_sudo_password()
    assert captured == "hunter2"
    # The key is gone from os.environ after capture.
    import os
    assert "SUDO_PASSWORD" not in os.environ


def test_capture_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("SUDO_PASSWORD", raising=False)
    assert phase2.capture_sudo_password() is None


def test_capture_treats_empty_string_as_none(monkeypatch):
    """Passwordless sudo path: install.sh may export SUDO_PASSWORD='' or
    skip the export. Either way, phase 2 should not treat empty as a real
    password (would set ANSIBLE_BECOME_PASS='' and confuse Ansible)."""
    monkeypatch.setenv("SUDO_PASSWORD", "")
    assert phase2.capture_sudo_password() is None
    import os
    assert "SUDO_PASSWORD" not in os.environ


# ---------------------------------------------------------------------------
# run_playbook env handling
# ---------------------------------------------------------------------------

class _SubprocessCallSpy:
    """Captures the args + kwargs passed to phase2.run (which wraps subprocess.run)."""
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))


def test_run_playbook_with_password_sets_ansible_become_pass(monkeypatch):
    spy = _SubprocessCallSpy()
    monkeypatch.setattr(phase2, "run", spy)
    phase2.run_playbook("devbox", sudo_password="hunter2")

    assert len(spy.calls) == 1
    args, kwargs = spy.calls[0]
    assert args[0] == "ansible-playbook"
    assert "--limit" in args and "devbox" in args
    # Password must NOT appear in argv (would show in `ps`).
    assert "hunter2" not in args
    # Password IS handed in via the subprocess env, not the parent process env.
    assert kwargs["env"]["ANSIBLE_BECOME_PASS"] == "hunter2"


def test_run_playbook_without_password_passes_no_env_override(monkeypatch):
    spy = _SubprocessCallSpy()
    monkeypatch.setattr(phase2, "run", spy)
    phase2.run_playbook("laptop24", sudo_password=None)

    assert len(spy.calls) == 1
    args, kwargs = spy.calls[0]
    # No env= kwarg means inherit parent env (and ANSIBLE_BECOME_PASS is
    # not set by phase 2 in os.environ).
    assert "env" not in kwargs


def test_run_playbook_does_not_set_ansible_become_pass_in_parent_environ(monkeypatch):
    """Even when handing the password to ansible, phase 2 must never set
    ANSIBLE_BECOME_PASS in its own os.environ — that would leak it to brew,
    git, or any other subprocess we spawn later."""
    spy = _SubprocessCallSpy()
    monkeypatch.setattr(phase2, "run", spy)
    monkeypatch.delenv("ANSIBLE_BECOME_PASS", raising=False)

    phase2.run_playbook("devbox", sudo_password="hunter2")

    import os
    assert "ANSIBLE_BECOME_PASS" not in os.environ
