import os
from pathlib import Path

import pytest

from dotfiles_manager import (
    assert_no_nested_dotfiles_dirs,
    assert_no_symlinks_in_source,
    backup_path_info,
    build_source_manifest,
    find_stale_managed_symlinks,
    next_backup_path,
    parse_backup_index,
)


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


def test_backup_path_info_reports_index(tmp_path: Path) -> None:
    target = tmp_path / ".zshrc"
    (tmp_path / ".zshrc.backup-1").touch()

    assert backup_path_info(target) == {
        "index": 2,
        "path": str(tmp_path / ".zshrc.backup-2"),
    }


def test_parse_backup_index_returns_none_for_non_backup_name() -> None:
    assert parse_backup_index(".zshrc", ".zshrc") is None
    assert parse_backup_index(".vimrc.backup-1", ".zshrc") is None
    assert parse_backup_index(".zshrc.bak-1", ".zshrc") is None


def test_parse_backup_index_returns_none_for_non_digit_suffix() -> None:
    assert parse_backup_index(".zshrc.backup-foo", ".zshrc") is None
    assert parse_backup_index(".zshrc.backup-1a", ".zshrc") is None


def test_parse_backup_index_returns_index_for_digit_suffix() -> None:
    assert parse_backup_index(".zshrc.backup-1", ".zshrc") == 1
    assert parse_backup_index(".zshrc.backup-42", ".zshrc") == 42


def test_parse_backup_index_returns_none_for_empty_suffix() -> None:
    # Belt-and-suspenders: "".isdigit() is False, so a bare trailing dash
    # doesn't get mistaken for index 0.
    assert "".isdigit() is False
    assert parse_backup_index(".zshrc.backup-", ".zshrc") is None


def test_assert_no_nested_dotfiles_dirs_rejects_nested_repo_copy(tmp_path: Path) -> None:
    source_root = tmp_path / "home_source"
    nested_repo = source_root / ".config" / ".dotfiles"
    nested_repo.mkdir(parents=True)

    with pytest.raises(ValueError, match="nested '.dotfiles' directories"):
        assert_no_nested_dotfiles_dirs(source_root)


def test_assert_no_symlinks_in_source_rejects_file_symlink(tmp_path: Path) -> None:
    source_root = tmp_path / "home_source"
    write_file(source_root / ".zshrc", "real zshrc")
    (source_root / ".zprofile").symlink_to(source_root / ".zshrc")

    with pytest.raises(ValueError, match="contains symlinks"):
        assert_no_symlinks_in_source(source_root)


def test_assert_no_symlinks_in_source_rejects_directory_symlink(tmp_path: Path) -> None:
    source_root = tmp_path / "home_source"
    write_file(source_root / "real" / "config.toml", "real config")
    (source_root / ".config").symlink_to(source_root / "real")

    with pytest.raises(ValueError, match="contains symlinks"):
        assert_no_symlinks_in_source(source_root)


def test_build_source_manifest_rejects_symlink_in_source(tmp_path: Path) -> None:
    common_root = tmp_path / "home_source" / "common"
    host_root = tmp_path / "home_source" / "hosts" / "mini26"
    home_dir = tmp_path / "home"

    write_file(common_root / ".zshrc", "common zshrc")
    (common_root / ".zprofile").symlink_to(common_root / ".zshrc")

    with pytest.raises(ValueError, match="contains symlinks"):
        build_source_manifest(
            source_dirs=[common_root, host_root],
            managed_root_dir=tmp_path / "home_source",
            home_dir=home_dir,
        )


def test_build_source_manifest_layers_common_groups_host(tmp_path: Path) -> None:
    """Multi-layer merge: common < group1 < group2 < host, later layers
    override earlier ones at the same relative path."""
    common_root = tmp_path / "home_source" / "common"
    group_purpose_root = tmp_path / "home_source" / "groups" / "personal"
    group_os_root = tmp_path / "home_source" / "groups" / "macos"
    host_root = tmp_path / "home_source" / "hosts" / "laptop24"
    home_dir = tmp_path / "home"

    # common-only entry, plus a value that every layer overrides.
    write_file(common_root / ".zshrc", "common zshrc")
    write_file(common_root / ".config" / "shared.conf", "common shared")
    # group_purpose overrides .config/shared.conf and adds purpose-only file.
    write_file(group_purpose_root / ".config" / "shared.conf", "purpose shared")
    write_file(group_purpose_root / ".config" / "purpose-only.conf", "purpose only")
    # group_os overrides .config/shared.conf again and adds an os-only file.
    write_file(group_os_root / ".config" / "shared.conf", "os shared")
    write_file(group_os_root / ".config" / "os-only.conf", "os only")
    # host overrides .config/shared.conf and adds a host-only file.
    write_file(host_root / ".config" / "shared.conf", "host shared")
    write_file(host_root / ".config" / "host-only.conf", "host only")

    manifest = build_source_manifest(
        source_dirs=[common_root, group_purpose_root, group_os_root, host_root],
        managed_root_dir=tmp_path / "home_source",
        home_dir=home_dir,
    )

    assert [entry["rel"] for entry in manifest["directory_slots"]] == [".config"]

    rel_to_src = {entry["rel"]: entry["src"] for entry in manifest["link_slots"]}
    # Each contributor lands a file the later layers don't touch.
    assert rel_to_src[".zshrc"] == str(common_root / ".zshrc")
    assert rel_to_src[".config/purpose-only.conf"] == str(
        group_purpose_root / ".config" / "purpose-only.conf"
    )
    assert rel_to_src[".config/os-only.conf"] == str(
        group_os_root / ".config" / "os-only.conf"
    )
    assert rel_to_src[".config/host-only.conf"] == str(
        host_root / ".config" / "host-only.conf"
    )
    # The contested rel goes to the last layer that defined it (host).
    assert rel_to_src[".config/shared.conf"] == str(
        host_root / ".config" / "shared.conf"
    )

    # managed_targets enumerates every layer's candidate, in layer order.
    shared = next(
        entry for entry in manifest["link_slots"] if entry["rel"] == ".config/shared.conf"
    )
    assert shared["managed_targets"] == [
        str(common_root / ".config" / "shared.conf"),
        str(group_purpose_root / ".config" / "shared.conf"),
        str(group_os_root / ".config" / "shared.conf"),
        str(host_root / ".config" / "shared.conf"),
    ]
    assert manifest["stale_links"] == []


def test_build_source_manifest_host_file_shadows_common_subtree(tmp_path: Path) -> None:
    common_root = tmp_path / "home_source" / "common"
    host_root = tmp_path / "home_source" / "hosts" / "mini18"
    home_dir = tmp_path / "home"

    write_file(common_root / ".config" / "nvim" / "init.lua", "set number")
    write_file(host_root / ".config" / "nvim", "host file")

    manifest = build_source_manifest(
        source_dirs=[common_root, host_root],
        managed_root_dir=tmp_path / "home_source",
        home_dir=home_dir,
    )

    assert [entry["rel"] for entry in manifest["directory_slots"]] == [".config"]
    assert manifest["link_slots"] == [
        {
            "dest": str(home_dir / ".config" / "nvim"),
            "managed_root": str((tmp_path / "home_source").resolve()),
            "managed_targets": [
                str(common_root / ".config" / "nvim"),
                str(host_root / ".config" / "nvim"),
            ],
            "rel": ".config/nvim",
            "src": str(host_root / ".config" / "nvim"),
        }
    ]
    assert manifest["stale_links"] == []


def test_build_source_manifest_host_directory_overrides_common_file(tmp_path: Path) -> None:
    common_root = tmp_path / "home_source" / "common"
    host_root = tmp_path / "home_source" / "hosts" / "mini26"
    home_dir = tmp_path / "home"

    write_file(common_root / ".config" / "tool", "common file")
    write_file(host_root / ".config" / "tool" / "config.toml", "host child")

    manifest = build_source_manifest(
        source_dirs=[common_root, host_root],
        managed_root_dir=tmp_path / "home_source",
        home_dir=home_dir,
    )

    assert manifest["directory_slots"] == [
        {
            "dest": str(home_dir / ".config"),
            "managed_root": str((tmp_path / "home_source").resolve()),
            "managed_targets": [
                str(common_root / ".config"),
                str(host_root / ".config"),
            ],
            "rel": ".config",
            "src": str(host_root / ".config"),
        },
        {
            "dest": str(home_dir / ".config/tool"),
            "managed_root": str((tmp_path / "home_source").resolve()),
            "managed_targets": [
                str(common_root / ".config" / "tool"),
                str(host_root / ".config" / "tool"),
            ],
            "rel": ".config/tool",
            "src": str(host_root / ".config" / "tool"),
        },
    ]
    assert manifest["link_slots"] == [
        {
            "dest": str(home_dir / ".config" / "tool" / "config.toml"),
            "managed_root": str((tmp_path / "home_source").resolve()),
            "managed_targets": [
                str(common_root / ".config" / "tool" / "config.toml"),
                str(host_root / ".config" / "tool" / "config.toml"),
            ],
            "rel": ".config/tool/config.toml",
            "src": str(host_root / ".config" / "tool" / "config.toml"),
        }
    ]
    assert manifest["stale_links"] == []


def test_find_stale_managed_symlinks_ignores_foreign_links(tmp_path: Path) -> None:
    common_root = tmp_path / "home_source" / "common"
    host_root = tmp_path / "home_source" / "hosts" / "mini18"
    home_dir = tmp_path / "home"

    write_file(common_root / ".zshrc", "common zshrc")
    home_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / ".zshrc").symlink_to("/tmp/somewhere-else")

    assert (
        find_stale_managed_symlinks(
            resolved_managed_root_dir=(tmp_path / "other-root").resolve(strict=False),
            home_dir=home_dir,
            desired_link_paths=[],
        )
        == []
    )


def test_build_source_manifest_reports_stale_managed_symlinks(tmp_path: Path) -> None:
    common_root = tmp_path / "home_source" / "common"
    host_root = tmp_path / "home_source" / "hosts" / "mini26"
    home_dir = tmp_path / "home"

    # .zshrc stays in common; .config/shared.conf was previously linked from
    # an earlier run but is no longer present in any source layer — exercise
    # the stale-symlink branch by leaving the home-side symlink in place
    # without a corresponding source entry.
    write_file(common_root / ".zshrc", "common zshrc")
    stray_source = tmp_path / "home_source" / "stray" / "shared.conf"
    write_file(stray_source, "stray shared")
    home_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / ".zshrc").symlink_to(common_root / ".zshrc")
    (home_dir / ".config").mkdir(parents=True, exist_ok=True)
    (home_dir / ".config" / "shared.conf").symlink_to(stray_source)

    manifest = build_source_manifest(
        source_dirs=[common_root, host_root],
        managed_root_dir=tmp_path / "home_source",
        home_dir=home_dir,
    )

    assert manifest["stale_links"] == [
        {
            "path": str(home_dir / ".config" / "shared.conf"),
            "rel": ".config/shared.conf",
            "resolved_target": str(stray_source.resolve(strict=False)),
            "target": str(stray_source),
        }
    ]


def test_stale_symlink_to_unexpected_managed_repo_path_is_still_managed(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    common_root = repo_root / "home_source" / "common"
    host_root = repo_root / "home_source" / "hosts" / "mini26"
    home_dir = tmp_path / "home"

    write_file(common_root / ".zshrc", "common zshrc")
    write_file(repo_root / "README.md", "repo readme")
    home_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / ".zshrc").symlink_to(repo_root / "README.md")

    manifest = build_source_manifest(
        source_dirs=[common_root, host_root],
        managed_root_dir=repo_root,
        home_dir=home_dir,
    )

    assert manifest["stale_links"] == []

    assert manifest["link_slots"] == [
        {
            "dest": str(home_dir / ".zshrc"),
            "managed_root": str(repo_root.resolve()),
            "managed_targets": [
                str(common_root / ".zshrc"),
                str(host_root / ".zshrc"),
            ],
            "rel": ".zshrc",
            "src": str(common_root / ".zshrc"),
        }
    ]


def test_find_stale_managed_symlinks_resolves_relative_targets(tmp_path: Path) -> None:
    """Home symlinks with a relative target are resolved against the link's
    own parent before deciding whether they point into the managed repo."""
    managed_root = tmp_path / "repo"
    target_file = managed_root / "home_source" / "common" / ".zshrc"
    write_file(target_file, "common zshrc")

    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True)
    link = home_dir / ".zshrc"
    link.symlink_to(os.path.relpath(target_file, home_dir))

    stale = find_stale_managed_symlinks(
        resolved_managed_root_dir=managed_root.resolve(strict=False),
        home_dir=home_dir,
        desired_link_paths=[],
    )

    assert [item["rel"] for item in stale] == [".zshrc"]
    assert not Path(stale[0]["target"]).is_absolute()
    assert stale[0]["resolved_target"] == str(target_file.resolve(strict=False))


def test_repo_home_source_tree_has_no_nested_dotfiles_dirs() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    assert_no_nested_dotfiles_dirs(repo_root / "home_source")


def test_repo_home_source_tree_has_no_symlinks() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    assert_no_symlinks_in_source(repo_root / "home_source")
