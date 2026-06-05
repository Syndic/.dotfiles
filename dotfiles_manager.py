"""Helpers for the dotfiles Ansible role and its repo-level checks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence


def find_nested_dotfiles_dirs(source_root: Path) -> List[Path]:
    """Return nested directories named '.dotfiles' below source_root."""
    if not source_root.is_dir():
        return []

    return sorted(path for path in source_root.rglob(".dotfiles") if path.is_dir())


def assert_no_nested_dotfiles_dirs(source_root: Path) -> None:
    """Raise when the source tree contains a nested '.dotfiles' directory."""
    offenders = find_nested_dotfiles_dirs(source_root)
    if not offenders:
        return

    formatted = "\n".join(str(path) for path in offenders)
    raise ValueError(
        "Refusing to link a source tree that contains nested '.dotfiles' directories:\n"
        f"{formatted}"
    )


def find_symlinks_in_source(source_root: Path) -> List[Path]:
    """Return symlink paths below source_root (symlinked directories are not descended)."""
    return [
        Path(entry["src"])
        for entry in iter_source_entries(source_root)
        if entry["type"] == "link"
    ]


def assert_no_symlinks_in_source(source_root: Path) -> None:
    """Raise when the source tree contains symlinks.

    home_source must hold only plain files and directories. A symlink there
    would be linked into $HOME as a symlink-to-a-symlink chain, and because
    managed-link detection resolves the whole chain, a source symlink whose
    target escapes the repo silently breaks stale-link cleanup and retargeting.
    """
    offenders = find_symlinks_in_source(source_root)
    if not offenders:
        return

    formatted = "\n".join(str(path) for path in offenders)
    raise ValueError(
        "Refusing to link a source tree that contains symlinks "
        "(home_source must hold only plain files and directories):\n"
        f"{formatted}"
    )


def parse_backup_index(sibling_name: str, target_name: str) -> Optional[int]:
    """Return the integer index from '<target_name>.backup-N' filenames, or
    None if sibling_name isn't a backup of target_name.

    Canonical parser for the '.backup-N' naming scheme. Consumers that need to
    find the next available index (backup_path_info) or the highest existing
    index (uninstall._latest_backup) both build on this — keeping the
    "is this a backup file? what index?" decision in one place so the parse
    and format sides can't drift.
    """
    prefix = f"{target_name}.backup-"
    if not sibling_name.startswith(prefix):
        return None
    suffix = sibling_name[len(prefix):]
    # `"".isdigit()` is False, so empty-suffix '<name>.backup-' returns None.
    return int(suffix) if suffix.isdigit() else None


def backup_path_info(target_path: Path) -> Dict[str, object]:
    """Return backup path metadata for the next available '<name>.backup-N' path."""
    parent = target_path.parent
    highest_seen = 0

    if parent.is_dir():
        for sibling in parent.iterdir():
            idx = parse_backup_index(sibling.name, target_path.name)
            if idx is not None:
                highest_seen = max(highest_seen, idx)

    next_index = highest_seen + 1
    backup_path = target_path.with_name(f"{target_path.name}.backup-{next_index}")

    return {"path": str(backup_path), "index": next_index}


def next_backup_path(target_path: Path) -> Path:
    """Return the next available '<name>.backup-N' path for target_path."""
    return Path(str(backup_path_info(target_path)["path"]))


def normalize_relative_path(path_text: str) -> str:
    """Normalize a repo-relative path and reject absolute or parent-traversing paths."""
    candidate = Path(path_text)
    if candidate.is_absolute():
        raise ValueError("Expected a relative path, got absolute path: {path}".format(path=path_text))

    normalized_parts = []
    for part in candidate.parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError(
                "Expected a relative path without '..' segments: {path}".format(path=path_text)
            )
        normalized_parts.append(part)

    return "/".join(normalized_parts)


def is_excluded(relative_path: str, excludes: Sequence[str]) -> bool:
    """Return true when relative_path is excluded directly or by an excluded parent."""
    relative_path = normalize_relative_path(relative_path)

    for excluded_path in excludes:
        normalized_exclude = normalize_relative_path(excluded_path)
        if not normalized_exclude:
            continue
        if relative_path == normalized_exclude:
            return True
        if relative_path.startswith(normalized_exclude + "/"):
            return True

    return False


def iter_source_entries(source_root: Path) -> List[Dict[str, str]]:
    """Return source entries below source_root without following symlinked directories."""
    if not source_root.is_dir():
        return []

    entries = []
    stack = [("", source_root)]

    while stack:
        relative_parent, absolute_parent = stack.pop()
        with os.scandir(absolute_parent) as scandir_entries:
            children = sorted(scandir_entries, key=lambda entry: entry.name, reverse=True)

        for child in children:
            relative_path = child.name if not relative_parent else relative_parent + "/" + child.name
            absolute_path = Path(child.path)

            if child.is_symlink():
                entries.append({"rel": relative_path, "src": str(absolute_path), "type": "link"})
                continue

            if child.is_dir(follow_symlinks=False):
                entries.append({"rel": relative_path, "src": str(absolute_path), "type": "directory"})
                stack.append((relative_path, absolute_path))
                continue

            if child.is_file(follow_symlinks=False):
                entries.append({"rel": relative_path, "src": str(absolute_path), "type": "file"})
                continue

            raise ValueError(
                "Unsupported filesystem object in dotfiles source tree: {path}".format(
                    path=absolute_path
                )
            )

    return sorted(entries, key=lambda entry: (entry["rel"].count("/"), entry["rel"], entry["type"]))


def iter_home_symlinks(home_dir: Path) -> List[Dict[str, str]]:
    """Return symlinks below home_dir without following symlinked directories."""
    if not home_dir.is_dir():
        return []

    symlinks = []
    stack = [("", home_dir)]

    while stack:
        relative_parent, absolute_parent = stack.pop()
        with os.scandir(absolute_parent) as scandir_entries:
            children = sorted(scandir_entries, key=lambda entry: entry.name, reverse=True)

        for child in children:
            relative_path = child.name if not relative_parent else relative_parent + "/" + child.name
            absolute_path = Path(child.path)

            if child.is_symlink():
                raw_target = os.readlink(absolute_path)
                if Path(raw_target).is_absolute():
                    resolved_target = str(Path(raw_target).resolve(strict=False))
                else:
                    resolved_target = str((absolute_path.parent / raw_target).resolve(strict=False))
                symlinks.append(
                    {
                        "path": str(absolute_path),
                        "rel": relative_path,
                        "target": raw_target,
                        "resolved_target": resolved_target,
                    }
                )
                continue

            if child.is_dir(follow_symlinks=False):
                stack.append((relative_path, absolute_path))

    return sorted(symlinks, key=lambda item: item["rel"])


def managed_target_candidates(
    common_source_dir: Path,
    host_source_dir: Path,
    relative_path: str,
) -> List[str]:
    """Return all repo-side source paths this tool could manage for relative_path."""
    relative = Path(normalize_relative_path(relative_path))
    return [str(common_source_dir / relative), str(host_source_dir / relative)]


def path_is_within_root(path: Path, root: Path) -> bool:
    """Return true when path is equal to root or nested below it."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_managed_link_target(
    resolved_link_target: str,
    resolved_managed_root_dir: Path,
) -> bool:
    """Return true when a resolved link target points anywhere inside the managed repo root."""
    if not resolved_link_target:
        return False

    return path_is_within_root(Path(resolved_link_target), resolved_managed_root_dir)


def find_stale_managed_symlinks(
    resolved_managed_root_dir: Path,
    home_dir: Path,
    desired_link_paths: Sequence[str],
) -> List[Dict[str, str]]:
    """Return managed symlinks under home_dir that should no longer exist."""
    desired_links = {normalize_relative_path(path_text) for path_text in desired_link_paths}
    stale_symlinks = []

    for symlink in iter_home_symlinks(home_dir):
        if normalize_relative_path(symlink["rel"]) in desired_links:
            continue

        if is_managed_link_target(
            symlink["resolved_target"],
            resolved_managed_root_dir=resolved_managed_root_dir,
        ):
            stale_symlinks.append(symlink)

    return stale_symlinks


def _remove_descendants(entries: Dict[str, Dict[str, str]], relative_path: str) -> None:
    prefix = relative_path + "/"
    for rel in list(entries):
        if rel.startswith(prefix):
            del entries[rel]


def _ancestor_paths(relative_path: str) -> List[str]:
    parts = normalize_relative_path(relative_path).split("/")
    if parts == [""]:
        return []

    ancestors = []
    for index in range(1, len(parts)):
        ancestors.append("/".join(parts[:index]))
    return ancestors


def _merge_entry(
    merged_entries: Dict[str, Dict[str, str]],
    entry: Dict[str, str],
) -> None:
    relative_path = entry["rel"]
    entry_type = entry["type"]

    for ancestor in _ancestor_paths(relative_path):
        ancestor_entry = merged_entries.get(ancestor)
        if ancestor_entry is not None and ancestor_entry["type"] != "directory":
            del merged_entries[ancestor]

    if entry_type != "directory":
        _remove_descendants(merged_entries, relative_path)

    merged_entries[relative_path] = entry


def build_source_manifest(
    common_source_dir: Path,
    host_source_dir: Path,
    managed_root_dir: Path,
    home_dir: Path,
    excludes: Sequence[str],
) -> Dict[str, List[Dict[str, str]]]:
    """Build the effective directory/link plan for common + host overlay sources."""
    assert_no_nested_dotfiles_dirs(common_source_dir)
    assert_no_nested_dotfiles_dirs(host_source_dir)
    assert_no_symlinks_in_source(common_source_dir)
    assert_no_symlinks_in_source(host_source_dir)

    resolved_managed_root_dir = managed_root_dir.resolve(strict=False)
    normalized_excludes = [normalize_relative_path(path_text) for path_text in excludes]
    merged_entries = {}  # type: Dict[str, Dict[str, str]]

    for entry in iter_source_entries(common_source_dir):
        if is_excluded(entry["rel"], normalized_excludes):
            continue
        _merge_entry(merged_entries, entry)

    for entry in iter_source_entries(host_source_dir):
        _merge_entry(merged_entries, entry)

    directories = []
    links = []

    for relative_path in sorted(merged_entries):
        entry = merged_entries[relative_path]
        destination = str(home_dir / Path(relative_path))
        managed_targets = managed_target_candidates(
            common_source_dir=common_source_dir,
            host_source_dir=host_source_dir,
            relative_path=relative_path,
        )

        if entry["type"] == "directory":
            directories.append(
                {
                    "src": entry["src"],
                    "rel": relative_path,
                    "dest": destination,
                    "managed_root": str(resolved_managed_root_dir),
                    "managed_targets": managed_targets,
                }
            )
            continue

        links.append(
            {
                "src": entry["src"],
                "rel": relative_path,
                "dest": destination,
                "managed_root": str(resolved_managed_root_dir),
                "managed_targets": managed_targets,
            }
        )

    stale_links = find_stale_managed_symlinks(
        resolved_managed_root_dir=resolved_managed_root_dir,
        home_dir=home_dir,
        desired_link_paths=[entry["rel"] for entry in links],
    )

    return {"directories": directories, "links": links, "stale_links": stale_links}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser(
        "check",
        help="fail if the dotfiles source tree contains nested '.dotfiles' directories or symlinks",
    )
    check_parser.add_argument("source_dir", type=Path)

    backup_parser = subparsers.add_parser(
        "next-backup",
        help="print the next available '<name>.backup-N' path for a target",
    )
    backup_parser.add_argument("target_path", type=Path)

    backup_info_parser = subparsers.add_parser(
        "backup-info",
        help="print JSON describing the next available '<name>.backup-N' path for a target",
    )
    backup_info_parser.add_argument("target_path", type=Path)

    manifest_parser = subparsers.add_parser(
        "build-manifest",
        help="build the effective directory/link manifest for home_source overlays",
    )
    manifest_parser.add_argument("--common-dir", type=Path, required=True)
    manifest_parser.add_argument("--host-dir", type=Path, required=True)
    manifest_parser.add_argument("--managed-root", type=Path, required=True)
    manifest_parser.add_argument("--home-dir", type=Path, required=True)
    manifest_parser.add_argument("--excludes-json", default="[]")

    return parser


def _run_check(source_dir: Path) -> int:
    try:
        assert_no_nested_dotfiles_dirs(source_dir)
        assert_no_symlinks_in_source(source_dir)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    return 0


def _run_next_backup(target_path: Path) -> int:
    print(next_backup_path(target_path))
    return 0


def _run_backup_info(target_path: Path) -> int:
    print(json.dumps(backup_path_info(target_path), sort_keys=True))
    return 0


def _run_build_manifest(
    common_dir: Path,
    host_dir: Path,
    managed_root: Path,
    home_dir: Path,
    excludes_json: str,
) -> int:
    try:
        raw_excludes = json.loads(excludes_json)
        if isinstance(raw_excludes, str):
            raw_excludes = json.loads(raw_excludes)
        if not isinstance(raw_excludes, list) or not all(
            isinstance(item, str) for item in raw_excludes
        ):
            raise ValueError("Expected excludes JSON to decode to a list of strings")

        manifest = build_source_manifest(
            common_source_dir=common_dir,
            host_source_dir=host_dir,
            managed_root_dir=managed_root,
            home_dir=home_dir,
            excludes=raw_excludes,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(json.dumps(manifest, sort_keys=True))
    return 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)

    if args.command == "check":
        return _run_check(args.source_dir)
    if args.command == "next-backup":
        return _run_next_backup(args.target_path)
    if args.command == "backup-info":
        return _run_backup_info(args.target_path)
    if args.command == "build-manifest":
        return _run_build_manifest(
            common_dir=args.common_dir,
            host_dir=args.host_dir,
            managed_root=args.managed_root,
            home_dir=args.home_dir,
            excludes_json=args.excludes_json,
        )

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
