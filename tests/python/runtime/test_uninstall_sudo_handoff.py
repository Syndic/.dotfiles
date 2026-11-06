"""Tests for uninstall.py's sudo-password capture and handoff to ansible-playbook.

Symmetric to test_sudo_handoff.py on the install side. Contract:
  - capture_sudo_password() always pops SUDO_PASSWORD from os.environ, so it
    can't leak into any later subprocess uninstall.py spawns.
  - When not needed_for_become, return None and don't touch sudo.
  - When needed: prefer env, then passwordless, then interactive tty prompt.
  - build_playbook_actions(...).do() passes the captured password to
    ansible-playbook ONLY via the subprocess env (ANSIBLE_BECOME_PASS),
    never in argv and never via the parent os.environ.
"""
from __future__ import annotations

import argparse
import os

import pytest

import uninstall


# ---------------------------------------------------------------------------
# capture_sudo_password
# ---------------------------------------------------------------------------
def test_capture_returns_none_and_pops_env_when_not_needed(monkeypatch):
    """Even when sudo isn't needed for this run, SUDO_PASSWORD must come out
    of os.environ — otherwise it would inherit into any subprocess and we
    lose the defense-in-depth phase 2 relies on."""
    monkeypatch.setenv("SUDO_PASSWORD", "hunter2")
    assert uninstall.capture_sudo_password(needed_for_become=False) is None
    assert "SUDO_PASSWORD" not in os.environ


def test_capture_returns_env_password_when_validated(monkeypatch):
    monkeypatch.setenv("SUDO_PASSWORD", "hunter2")
    # Don't actually shell out to sudo in tests.
    monkeypatch.setattr(uninstall, "_sudo_validates", lambda pw: pw == "hunter2")
    monkeypatch.setattr(uninstall, "_sudo_passwordless", lambda: False)
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
    assert uninstall.capture_sudo_password(needed_for_become=True) == "hunter2"
    assert "SUDO_PASSWORD" not in os.environ


def test_capture_dies_when_env_password_invalid(monkeypatch):
    monkeypatch.setenv("SUDO_PASSWORD", "wrong")
    monkeypatch.setattr(uninstall, "_sudo_validates", lambda pw: False)
    monkeypatch.setattr(uninstall, "_sudo_passwordless", lambda: False)
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
    with pytest.raises(SystemExit) as exc:
        uninstall.capture_sudo_password(needed_for_become=True)
    assert exc.value.code == 1


def test_capture_returns_none_when_passwordless_sudo(monkeypatch):
    monkeypatch.delenv("SUDO_PASSWORD", raising=False)
    monkeypatch.setattr(uninstall, "_sudo_passwordless", lambda: True)
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
    assert uninstall.capture_sudo_password(needed_for_become=True) is None


def test_capture_returns_none_when_root(monkeypatch):
    monkeypatch.delenv("SUDO_PASSWORD", raising=False)
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    # _sudo_passwordless must not even be consulted (no escalation needed).
    monkeypatch.setattr(
        uninstall, "_sudo_passwordless",
        lambda: pytest.fail("should not check passwordless when running as root"),
    )
    assert uninstall.capture_sudo_password(needed_for_become=True) is None


def test_capture_dies_when_no_tty_and_no_env_password(monkeypatch):
    monkeypatch.delenv("SUDO_PASSWORD", raising=False)
    monkeypatch.setattr(uninstall, "_sudo_passwordless", lambda: False)
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)

    class NotATty:
        def isatty(self):
            return False

    monkeypatch.setattr("sys.stdin", NotATty())
    with pytest.raises(SystemExit) as exc:
        uninstall.capture_sudo_password(needed_for_become=True)
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# _needs_become_password
# ---------------------------------------------------------------------------
def _args(**overrides) -> argparse.Namespace:
    defaults = dict(
        brew_packages=False, apt_packages=False, flatpak_packages=False,
        ansible=False, homebrew=False, repo=False, skip_symlinks=False,
        yes=False, host=None, all=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_needs_become_false_on_macos(monkeypatch):
    monkeypatch.setattr(uninstall.platform, "system", lambda: "Darwin")
    assert uninstall._needs_become_password(_args(apt_packages=True)) is False
    assert uninstall._needs_become_password(_args(flatpak_packages=True)) is False


def test_needs_become_false_on_linux_for_brew_only(monkeypatch):
    monkeypatch.setattr(uninstall.platform, "system", lambda: "Linux")
    # brew uninstall doesn't need sudo (no `become` on the homebrew role).
    assert uninstall._needs_become_password(_args(brew_packages=True)) is False


def test_needs_become_true_on_linux_for_apt(monkeypatch):
    monkeypatch.setattr(uninstall.platform, "system", lambda: "Linux")
    assert uninstall._needs_become_password(_args(apt_packages=True)) is True


def test_needs_become_true_on_linux_for_flatpak(monkeypatch):
    monkeypatch.setattr(uninstall.platform, "system", lambda: "Linux")
    assert uninstall._needs_become_password(_args(flatpak_packages=True)) is True


# ---------------------------------------------------------------------------
# build_playbook_actions env handoff
# ---------------------------------------------------------------------------
class _RunSpy:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))


def test_do_playbook_with_password_sets_ansible_become_pass(monkeypatch):
    spy = _RunSpy()
    monkeypatch.setattr(uninstall, "run", spy)
    monkeypatch.setattr(uninstall.shutil, "which", lambda _: "/usr/bin/ansible-playbook")

    _, do = uninstall.build_playbook_actions(
        "devbox", brew=False, apt=True, flatpak=False, sudo_password="hunter2"
    )
    do()

    assert len(spy.calls) == 1
    args, kwargs = spy.calls[0]
    assert args[0] == "ansible-playbook"
    assert "--limit" in args and "devbox" in args
    assert "--tags" in args
    # Password must not appear in argv (would show in `ps`).
    assert "hunter2" not in args
    assert kwargs["env"]["ANSIBLE_BECOME_PASS"] == "hunter2"


def test_do_playbook_without_password_passes_no_env_kwarg(monkeypatch):
    spy = _RunSpy()
    monkeypatch.setattr(uninstall, "run", spy)
    monkeypatch.setattr(uninstall.shutil, "which", lambda _: "/usr/bin/ansible-playbook")

    _, do = uninstall.build_playbook_actions(
        "devbox", brew=True, apt=False, flatpak=False, sudo_password=None
    )
    do()

    assert len(spy.calls) == 1
    _, kwargs = spy.calls[0]
    assert "env" not in kwargs


def test_do_playbook_does_not_leak_become_pass_to_parent_environ(monkeypatch):
    spy = _RunSpy()
    monkeypatch.setattr(uninstall, "run", spy)
    monkeypatch.setattr(uninstall.shutil, "which", lambda _: "/usr/bin/ansible-playbook")
    monkeypatch.delenv("ANSIBLE_BECOME_PASS", raising=False)

    _, do = uninstall.build_playbook_actions(
        "devbox", brew=False, apt=True, flatpak=False, sudo_password="hunter2"
    )
    do()

    assert "ANSIBLE_BECOME_PASS" not in os.environ
