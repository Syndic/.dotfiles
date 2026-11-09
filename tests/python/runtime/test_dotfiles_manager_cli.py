"""Tests for dotfiles_manager's CLI layer — main() and the subcommand
dispatchers (_run_check / _run_next_backup / _run_backup_info /
_run_build_manifest), plus normalize_relative_path's rejection branches.

These exercise the argparse glue and exit-code contract that Ansible relies
on; the underlying helpers are covered in test_dotfiles_manager.py."""
import json
from pathlib import Path

import pytest

import dotfiles_manager
from dotfiles_manager import normalize_relative_path


def write_file(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------
def test_check_returns_0_for_clean_tree(tmp_path, capsys):
    source = tmp_path / "home_source"
    write_file(source / ".zshrc", "clean")

    assert dotfiles_manager.main(["check", str(source)]) == 0
    assert capsys.readouterr().err == ""


def test_check_returns_1_and_reports_nested_dotfiles(tmp_path, capsys):
    source = tmp_path / "home_source"
    (source / ".config" / ".dotfiles").mkdir(parents=True)

    assert dotfiles_manager.main(["check", str(source)]) == 1
    err = capsys.readouterr().err
    assert "nested '.dotfiles' directories" in err
    assert str(source / ".config" / ".dotfiles") in err


# ---------------------------------------------------------------------------
# next-backup
# ---------------------------------------------------------------------------
def test_next_backup_prints_next_path(tmp_path, capsys):
    target = tmp_path / ".zshrc"
    (tmp_path / ".zshrc.backup-1").touch()

    assert dotfiles_manager.main(["next-backup", str(target)]) == 0
    assert capsys.readouterr().out.strip() == str(tmp_path / ".zshrc.backup-2")


# ---------------------------------------------------------------------------
# backup-info
# ---------------------------------------------------------------------------
def test_backup_info_prints_json(tmp_path, capsys):
    target = tmp_path / ".zshrc"
    (tmp_path / ".zshrc.backup-1").touch()
    (tmp_path / ".zshrc.backup-2").touch()

    assert dotfiles_manager.main(["backup-info", str(target)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "index": 3,
        "path": str(tmp_path / ".zshrc.backup-3"),
    }


# ---------------------------------------------------------------------------
# build-manifest
# ---------------------------------------------------------------------------
def _manifest_argv(tmp_path):
    common = tmp_path / "home_source" / "common"
    host = tmp_path / "home_source" / "hosts" / "laptop24"
    write_file(common / ".zshrc", "common zshrc")
    write_file(host / ".gitconfig", "host gitconfig")
    return [
        "build-manifest",
        "--source-dir", str(common),
        "--source-dir", str(host),
        "--managed-root", str(tmp_path / "home_source"),
        "--home-dir", str(tmp_path / "home"),
    ]


def test_build_manifest_prints_manifest_json(tmp_path, capsys):
    assert dotfiles_manager.main(_manifest_argv(tmp_path)) == 0

    manifest = json.loads(capsys.readouterr().out)
    assert set(manifest) == {"directory_slots", "link_slots", "stale_links"}
    rels = sorted(link_slot["rel"] for link_slot in manifest["link_slots"])
    assert rels == [".gitconfig", ".zshrc"]


def test_build_manifest_accepts_many_source_dirs(tmp_path, capsys):
    """--source-dir is repeatable; later layers override earlier ones."""
    common = tmp_path / "home_source" / "common"
    group_root = tmp_path / "home_source" / "groups" / "personal"
    host = tmp_path / "home_source" / "hosts" / "laptop24"
    write_file(common / ".zshrc", "common")
    write_file(group_root / ".zshrc", "group")
    write_file(host / ".zshrc", "host")

    argv = [
        "build-manifest",
        "--source-dir", str(common),
        "--source-dir", str(group_root),
        "--source-dir", str(host),
        "--managed-root", str(tmp_path / "home_source"),
        "--home-dir", str(tmp_path / "home"),
    ]
    assert dotfiles_manager.main(argv) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert [link_slot["src"] for link_slot in manifest["link_slots"]] == [
        str(host / ".zshrc")
    ]


def test_build_manifest_reports_nested_dotfiles(tmp_path, capsys):
    common = tmp_path / "home_source" / "common"
    host = tmp_path / "home_source" / "hosts" / "laptop24"
    (common / ".config" / ".dotfiles").mkdir(parents=True)
    host.mkdir(parents=True)

    argv = [
        "build-manifest",
        "--source-dir", str(common),
        "--source-dir", str(host),
        "--managed-root", str(tmp_path / "home_source"),
        "--home-dir", str(tmp_path / "home"),
    ]
    assert dotfiles_manager.main(argv) == 1
    assert "nested '.dotfiles' directories" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# argparse contract
# ---------------------------------------------------------------------------
def test_main_requires_a_subcommand(capsys):
    with pytest.raises(SystemExit) as exc:
        dotfiles_manager.main([])
    assert exc.value.code == 2  # argparse usage error


def test_main_rejects_unknown_subcommand(capsys):
    with pytest.raises(SystemExit) as exc:
        dotfiles_manager.main(["frobnicate"])
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# normalize_relative_path — rejection branches
# ---------------------------------------------------------------------------
def test_normalize_relative_path_rejects_absolute_paths():
    with pytest.raises(ValueError, match="absolute path"):
        normalize_relative_path("/etc/passwd")


def test_normalize_relative_path_rejects_parent_traversal():
    with pytest.raises(ValueError, match="without '..' segments"):
        normalize_relative_path("a/../../b")


def test_normalize_relative_path_collapses_dot_and_empty_segments():
    assert normalize_relative_path("./a//b/") == "a/b"
