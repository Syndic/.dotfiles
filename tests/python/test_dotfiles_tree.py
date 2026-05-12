from pathlib import Path

import pytest

from dotfiles_tree import assert_no_nested_dotfiles_dirs, build_source_manifest, next_backup_path


def write_file(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_next_backup_path_starts_at_1(tmp_path: Path) -> None:
    target = tmp_path / ".zshrc"

    assert next_backup_path(target) == tmp_path / ".zshrc.backup-1"


def test_next_backup_path_uses_next_highest_integer(tmp_path: Path) -> None:
    target = tmp_path / ".zshrc"
    target.touch()
    (tmp_path / ".zshrc.backup-1").touch()
    (tmp_path / ".zshrc.backup-3").touch()
    (tmp_path / ".zshrc.backup-old").touch()
    (tmp_path / ".zshrc.backup-03").touch()

    assert next_backup_path(target) == tmp_path / ".zshrc.backup-4"


def test_assert_no_nested_dotfiles_dirs_rejects_nested_repo_copy(tmp_path: Path) -> None:
    source_root = tmp_path / "home_source"
    nested_repo = source_root / ".config" / ".dotfiles"
    nested_repo.mkdir(parents=True)

    with pytest.raises(ValueError, match="nested '.dotfiles' directories"):
        assert_no_nested_dotfiles_dirs(source_root)


def test_build_source_manifest_applies_overlays_and_excludes(tmp_path: Path) -> None:
    common_root = tmp_path / "home_source" / "common"
    host_root = tmp_path / "home_source" / "hosts" / "laptop24"
    home_dir = tmp_path / "home"

    write_file(common_root / ".zshrc", "common zshrc")
    write_file(common_root / ".config" / "shared.conf", "shared")
    write_file(common_root / ".config" / "override.conf", "common override")
    write_file(common_root / ".cache" / "ignored.txt", "ignored")
    write_file(host_root / ".config" / "override.conf", "host override")
    write_file(host_root / ".config" / "host-only.conf", "host only")

    manifest = build_source_manifest(
        common_source_dir=common_root,
        host_source_dir=host_root,
        home_dir=home_dir,
        excludes=[".cache", ".config/shared.conf"],
    )

    assert [entry["rel"] for entry in manifest["directories"]] == [".config"]
    assert manifest["links"] == [
        {
            "dest": str(home_dir / ".config" / "host-only.conf"),
            "rel": ".config/host-only.conf",
            "src": str(host_root / ".config" / "host-only.conf"),
        },
        {
            "dest": str(home_dir / ".config" / "override.conf"),
            "rel": ".config/override.conf",
            "src": str(host_root / ".config" / "override.conf"),
        },
        {
            "dest": str(home_dir / ".zshrc"),
            "rel": ".zshrc",
            "src": str(common_root / ".zshrc"),
        },
    ]


def test_build_source_manifest_host_file_shadows_common_subtree(tmp_path: Path) -> None:
    common_root = tmp_path / "home_source" / "common"
    host_root = tmp_path / "home_source" / "hosts" / "mini18"
    home_dir = tmp_path / "home"

    write_file(common_root / ".config" / "nvim" / "init.lua", "set number")
    write_file(host_root / ".config" / "nvim", "host file")

    manifest = build_source_manifest(
        common_source_dir=common_root,
        host_source_dir=host_root,
        home_dir=home_dir,
        excludes=[],
    )

    assert [entry["rel"] for entry in manifest["directories"]] == [".config"]
    assert manifest["links"] == [
        {
            "dest": str(home_dir / ".config" / "nvim"),
            "rel": ".config/nvim",
            "src": str(host_root / ".config" / "nvim"),
        }
    ]


def test_build_source_manifest_host_directory_overrides_common_file(tmp_path: Path) -> None:
    common_root = tmp_path / "home_source" / "common"
    host_root = tmp_path / "home_source" / "hosts" / "mini26"
    home_dir = tmp_path / "home"

    write_file(common_root / ".config" / "tool", "common file")
    write_file(host_root / ".config" / "tool" / "config.toml", "host child")

    manifest = build_source_manifest(
        common_source_dir=common_root,
        host_source_dir=host_root,
        home_dir=home_dir,
        excludes=[],
    )

    assert [entry["rel"] for entry in manifest["directories"]] == [".config", ".config/tool"]
    assert manifest["links"] == [
        {
            "dest": str(home_dir / ".config" / "tool" / "config.toml"),
            "rel": ".config/tool/config.toml",
            "src": str(host_root / ".config" / "tool" / "config.toml"),
        }
    ]


def test_repo_home_source_tree_has_no_nested_dotfiles_dirs() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    assert_no_nested_dotfiles_dirs(repo_root / "home_source")
