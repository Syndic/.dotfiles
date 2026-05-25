"""Tests for uninstall.py — the inverse of phase2 + Ansible playbook.

Covers the parts that don't shell out to brew/apt/flatpak/ansible-playbook:
managed-symlink detection, backup restoration, host marker reading, the
confirmation gate, and the --repo print-only behavior. The package-removal
paths are subprocess-heavy and fall under the documented "out-of-scope for
tests" set in CLAUDE.md."""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

import uninstall


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    """Build a tmpdir laid out like a real install:
        <tmp>/dotfiles/                   (the managed root)
            home_source/common/foo
            home_source/common/.config/bar
        <tmp>/home/                       (acts as $HOME)
            .foo -> <tmp>/dotfiles/home_source/common/foo
            .config/bar -> <tmp>/dotfiles/home_source/common/.config/bar
            .keep_me  (regular file, must be untouched)
            .other_link -> /tmp/somewhere  (unmanaged symlink, must be untouched)
    Returns (home, managed_root)."""
    managed_root = tmp_path / "dotfiles"
    src = managed_root / "home_source" / "common"
    src.mkdir(parents=True)
    (src / "foo").write_text("FOO from repo\n")
    (src / ".config").mkdir()
    (src / ".config" / "bar").write_text("BAR from repo\n")

    home = tmp_path / "home"
    home.mkdir()
    (home / ".foo").symlink_to(src / "foo")
    (home / ".config").mkdir()
    (home / ".config" / "bar").symlink_to(src / ".config" / "bar")
    (home / ".keep_me").write_text("user data, do not touch\n")
    (home / ".other_link").symlink_to(Path("/tmp/somewhere_outside"))

    monkeypatch.setattr(uninstall, "DOTFILES_DIR", managed_root)
    monkeypatch.setattr(
        uninstall, "INSTALLED_HOST_MARKER", managed_root / ".installed-host"
    )
    return home, managed_root


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def test_all_expands_to_every_removal_flag():
    args = uninstall.parse_args(["--all"])
    assert args.brew_packages
    assert args.apt_packages
    assert args.flatpak_packages
    assert args.ansible
    assert args.homebrew
    assert args.repo


def test_default_args_have_no_removal_flags_set():
    args = uninstall.parse_args([])
    assert not args.brew_packages
    assert not args.apt_packages
    assert not args.flatpak_packages
    assert not args.ansible
    assert not args.homebrew
    assert not args.repo


# ---------------------------------------------------------------------------
# Backup discovery
# ---------------------------------------------------------------------------
def test_latest_backup_picks_highest_index(tmp_path):
    target = tmp_path / "foo"
    (tmp_path / "foo.backup-1").write_text("old")
    (tmp_path / "foo.backup-3").write_text("newer")
    (tmp_path / "foo.backup-2").write_text("middle")
    assert uninstall._latest_backup(target) == tmp_path / "foo.backup-3"


def test_latest_backup_returns_none_when_absent(tmp_path):
    assert uninstall._latest_backup(tmp_path / "no-such") is None


def test_latest_backup_ignores_non_numeric_suffix(tmp_path):
    target = tmp_path / "foo"
    (tmp_path / "foo.backup-abc").write_text("junk")
    assert uninstall._latest_backup(target) is None


# ---------------------------------------------------------------------------
# Symlink detection
# ---------------------------------------------------------------------------
def test_build_symlink_actions_finds_only_managed_links(fake_install):
    home, managed_root = fake_install
    preview, _ = uninstall.build_symlink_actions(home, managed_root)
    text = "\n".join(preview)
    assert ".foo" in text
    assert "bar" in text
    # Untouched entries must not appear.
    assert ".keep_me" not in text
    assert ".other_link" not in text


def test_symlinks_do_callable_removes_and_does_not_touch_user_files(fake_install):
    home, managed_root = fake_install
    _, do = uninstall.build_symlink_actions(home, managed_root)
    do()
    assert not (home / ".foo").exists()
    assert not (home / ".config" / "bar").exists()
    # Unmanaged entries must survive.
    assert (home / ".keep_me").is_file()
    assert (home / ".other_link").is_symlink()


def test_symlinks_restore_highest_indexed_backup(fake_install):
    home, managed_root = fake_install
    # Stage older + newer backups for .foo
    (home / ".foo.backup-1").write_text("ancient pre-install foo\n")
    (home / ".foo.backup-3").write_text("most recent pre-install foo\n")
    _, do = uninstall.build_symlink_actions(home, managed_root)
    do()
    assert (home / ".foo").read_text() == "most recent pre-install foo\n"
    # Lower-indexed backups stay put; they represent older displaced state.
    assert (home / ".foo.backup-1").read_text() == "ancient pre-install foo\n"


# ---------------------------------------------------------------------------
# Host marker
# ---------------------------------------------------------------------------
def test_read_recorded_host_returns_marker_contents(fake_install):
    _, managed_root = fake_install
    (managed_root / ".installed-host").write_text("laptop24\n")
    assert uninstall.read_recorded_host() == "laptop24"


def test_read_recorded_host_returns_none_when_missing(fake_install):
    assert uninstall.read_recorded_host() is None


def test_read_recorded_host_returns_none_for_empty_marker(fake_install):
    _, managed_root = fake_install
    (managed_root / ".installed-host").write_text("   \n")
    assert uninstall.read_recorded_host() is None


def test_resolve_host_uses_recorded_when_profile_still_exists(fake_install, capsys):
    _, managed_root = fake_install
    (managed_root / "host_vars").mkdir()
    (managed_root / "host_vars" / "mini26.yml").write_text("")
    (managed_root / ".installed-host").write_text("mini26\n")
    assert uninstall.resolve_host(None) == "mini26"
    # The "from .installed-host" info line confirms the marker path was used.
    out = capsys.readouterr().out
    assert "from .installed-host" in out


def test_resolve_host_warns_and_falls_back_when_recorded_profile_is_gone(
    fake_install, monkeypatch, capsys
):
    """The marker is durable state — the recorded profile may have been
    renamed or deleted since install. Validating against the current
    host_vars/ listing keeps us from passing a bad value to ansible-playbook
    later, where it surfaces as a confusing --limit error."""
    _, managed_root = fake_install
    (managed_root / "host_vars").mkdir()
    # Two real profiles, neither of which matches what the marker recorded.
    (managed_root / "host_vars" / "laptop24.yml").write_text("")
    (managed_root / "host_vars" / "mini26.yml").write_text("")
    (managed_root / ".installed-host").write_text("renamed_away\n")

    # Feed the interactive picker so the fallback can resolve.
    stream = io.StringIO("mini26\n")
    stream.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", stream)

    chosen = uninstall.resolve_host(None)
    assert chosen == "mini26"
    captured = capsys.readouterr()
    # The warning routes through warn() (stderr) and names both the stale
    # value and the marker file, so the user can find and fix the drift.
    assert "renamed_away" in captured.err
    assert ".installed-host" in captured.err
    assert "no longer" in captured.err


# ---------------------------------------------------------------------------
# Confirmation gate
# ---------------------------------------------------------------------------
def _stdin_with_tty(monkeypatch, payload: str, is_tty: bool):
    stream = io.StringIO(payload)
    stream.isatty = lambda: is_tty
    monkeypatch.setattr(sys, "stdin", stream)


def test_confirm_yes_flag_bypasses_prompt():
    assert uninstall.confirm(skip_prompt=True) is True


def test_confirm_no_tty_without_yes_is_inert(monkeypatch, capsys):
    _stdin_with_tty(monkeypatch, "", is_tty=False)
    assert uninstall.confirm(skip_prompt=False) is False
    # The "re-run with --yes" message routes through info() (stdout).
    out = capsys.readouterr().out
    assert "--yes" in out


def test_confirm_y_accepted(monkeypatch):
    _stdin_with_tty(monkeypatch, "y\n", is_tty=True)
    assert uninstall.confirm(skip_prompt=False) is True


def test_confirm_n_rejected(monkeypatch):
    _stdin_with_tty(monkeypatch, "n\n", is_tty=True)
    assert uninstall.confirm(skip_prompt=False) is False


def test_confirm_empty_treated_as_no(monkeypatch):
    _stdin_with_tty(monkeypatch, "\n", is_tty=True)
    assert uninstall.confirm(skip_prompt=False) is False


# ---------------------------------------------------------------------------
# --repo print-only behavior
# ---------------------------------------------------------------------------
def test_repo_action_prints_command_and_does_not_delete(fake_install, capsys):
    _, managed_root = fake_install
    preview, do = uninstall.build_repo_action()
    do()
    out = capsys.readouterr().out
    assert "rm -rf" in out
    assert str(uninstall.DOTFILES_DIR) in out
    # The repo dir must still exist.
    assert managed_root.is_dir()


# ---------------------------------------------------------------------------
# End-to-end via main() — inert path with no flags and no tty
# ---------------------------------------------------------------------------
def test_main_inert_without_tty_prints_plan_and_does_not_act(fake_install, monkeypatch, capsys):
    home, _ = fake_install
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    _stdin_with_tty(monkeypatch, "", is_tty=False)
    uninstall.main(["--host", "fake"])
    out = capsys.readouterr().out
    assert "Uninstall plan" in out
    # Managed links must still be present — confirm() returned False.
    assert (home / ".foo").is_symlink()
    assert (home / ".config" / "bar").is_symlink()


def test_main_yes_applies_symlink_removal(fake_install, monkeypatch, capsys):
    home, _ = fake_install
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    uninstall.main(["--host", "fake", "--yes"])
    assert not (home / ".foo").exists()
    assert not (home / ".config" / "bar").exists()
    assert (home / ".keep_me").is_file()
