#!/usr/bin/env python3
"""
e2e_assertions.py - checkpoint assertions for tests/e2e-roundtrip-linux.sh.

Invoked inside the container at each step boundary. Each subcommand
corresponds to one assertion group in the design doc:

    group-a   after first install
    group-b   after default uninstall (symlinks-only)
    group-c   after re-install (idempotency vs. group-a)
    group-d   after `uninstall.py --all --yes` (full teardown)

The script imports dotfiles_manager from ~/.dotfiles so the managed-link
manifest is enumerated by the same code install/uninstall use — not a
parallel bash reimplementation that could drift. Side effect: group-a
writes the manifest to /tmp/managed-links-A.txt for group-c to compare
against.

Exits 0 on all assertions passing, non-zero with a human-readable message
on first failure. No clever framework — print + sys.exit, that's it.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DOTFILES_DIR = Path.home() / ".dotfiles"
MARKER_FILE_A = Path("/tmp/managed-links-A.txt")
INSTALLED_HOST_MARKER = DOTFILES_DIR / ".installed-host"

# Make dotfiles_manager importable. The install lands the repo at
# ~/.dotfiles; we use its enumeration so "managed" matches production.
sys.path.insert(0, str(DOTFILES_DIR))


def fail(msg: str) -> None:
    print(f"ASSERT FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"  ok: {msg}")


def managed_links() -> list[str]:
    """Return the sorted list of managed symlink paths under $HOME.

    Uses find_stale_managed_symlinks with desired_link_paths=[] — i.e. every
    managed link is "stale," which is the enumeration we want.
    """
    from dotfiles_manager import find_stale_managed_symlinks

    resolved_root = DOTFILES_DIR.resolve(strict=False)
    links = find_stale_managed_symlinks(
        resolved_managed_root_dir=resolved_root,
        home_dir=Path.home(),
        desired_link_paths=[],
    )
    return sorted(link["path"] for link in links)


def assert_marker_file(host: str) -> None:
    if not INSTALLED_HOST_MARKER.is_file():
        fail(f"{INSTALLED_HOST_MARKER} missing — phase2 did not write it")
    recorded = INSTALLED_HOST_MARKER.read_text().strip()
    if recorded != host:
        fail(f"{INSTALLED_HOST_MARKER} contains {recorded!r}, expected {host!r}")
    ok(f"{INSTALLED_HOST_MARKER.name} = {host}")


def assert_brew_present() -> None:
    if shutil.which("brew") is None:
        fail("brew not on PATH after install")
    ok("brew on PATH")


def assert_ansible_present() -> None:
    if shutil.which("ansible") is None:
        fail("ansible not on PATH after install")
    ok("ansible on PATH")


def assert_brew_has_packages() -> None:
    """At least one brew formula should be installed after a real install."""
    res = subprocess.run(
        ["brew", "list", "--formula"], capture_output=True, text=True, check=False
    )
    if res.returncode != 0:
        fail(f"`brew list --formula` exited {res.returncode}: {res.stderr.strip()}")
    formulas = [line for line in res.stdout.splitlines() if line.strip()]
    if not formulas:
        fail("no brew formulas installed — `brew bundle` produced nothing")
    ok(f"brew has {len(formulas)} formula(s) installed")


def assert_marker_symlinked(marker_name: str) -> Path:
    marker = Path.home() / marker_name
    if not marker.is_symlink():
        fail(f"{marker} should be a managed symlink, but is not a symlink")
    target = os.readlink(marker)
    if not target.startswith(str(DOTFILES_DIR)):
        fail(f"{marker} -> {target}, expected target under {DOTFILES_DIR}")
    ok(f"{marker_name} -> {target}")
    return marker


def assert_backup_restored(marker_name: str, expected_content: str) -> None:
    marker = Path.home() / marker_name
    if marker.is_symlink():
        fail(f"{marker} should be a regular file after uninstall, found symlink")
    if not marker.is_file():
        fail(f"{marker} missing — backup-restore did not run")
    content = marker.read_text()
    if content != expected_content:
        fail(
            f"{marker} content {content!r} does not match the pre-install "
            f"original {expected_content!r}; backup-restore put back the wrong file"
        )
    ok(f"{marker_name} restored to original content ({expected_content!r})")

    # The .backup-N sibling should be gone — uninstall renames it back.
    leftover = sorted(
        p.name
        for p in marker.parent.iterdir()
        if p.name.startswith(f"{marker_name}.backup-")
    )
    if leftover:
        fail(f"backup sibling(s) still present after restore: {leftover}")
    ok(f"no {marker_name}.backup-* siblings remain")


def write_manifest(path: Path, links: list[str]) -> None:
    path.write_text("\n".join(links) + ("\n" if links else ""))
    ok(f"wrote managed-link manifest to {path} ({len(links)} link(s))")


def read_manifest(path: Path) -> list[str]:
    if not path.is_file():
        fail(f"expected manifest at {path}, missing")
    return [line for line in path.read_text().splitlines() if line]


# ---------------------------------------------------------------------------
# Assertion groups
# ---------------------------------------------------------------------------


def group_a(args: argparse.Namespace) -> None:
    """After first install."""
    assert_marker_file(args.host)
    assert_brew_present()
    assert_ansible_present()
    assert_brew_has_packages()
    assert_marker_symlinked(args.marker_name)

    links = managed_links()
    if not links:
        fail(
            "no managed symlinks found after install — fixture injection "
            "failed or the dotfiles role is not running"
        )
    write_manifest(MARKER_FILE_A, links)


def group_b(args: argparse.Namespace) -> None:
    """After default uninstall (no --host; symlinks-only)."""
    # uninstall.py should have logged that it read the profile from
    # .installed-host. This is the proof point that the default works.
    log = Path(args.log).read_text() if args.log else ""
    expected = f"from {INSTALLED_HOST_MARKER.name}: {args.host}"
    if expected not in log:
        fail(
            f"uninstall.py log did not mention {expected!r}; "
            f"the .installed-host default may have regressed.\n"
            f"--- log tail ---\n{log[-2000:]}"
        )
    ok(f"uninstall.py honored {INSTALLED_HOST_MARKER.name} -> {args.host}")

    links = managed_links()
    if links:
        fail(f"{len(links)} managed symlink(s) remain after default uninstall: {links}")
    ok("no managed symlinks remain under $HOME")

    # Default uninstall does NOT touch packages or brew.
    assert_brew_present()
    assert_ansible_present()
    assert_brew_has_packages()

    # Repo + marker file untouched by default uninstall.
    if not DOTFILES_DIR.is_dir():
        fail(f"{DOTFILES_DIR} should still exist after default uninstall")
    ok(f"{DOTFILES_DIR} still present")
    if not INSTALLED_HOST_MARKER.is_file():
        fail(f"{INSTALLED_HOST_MARKER} should still exist after default uninstall")
    ok(f"{INSTALLED_HOST_MARKER.name} still present")

    assert_backup_restored(args.marker_name, "user-original\n")


def group_c(args: argparse.Namespace) -> None:
    """After re-install — idempotency vs. group-a."""
    assert_marker_file(args.host)
    assert_brew_present()
    assert_ansible_present()
    assert_brew_has_packages()
    assert_marker_symlinked(args.marker_name)

    expected_links = read_manifest(MARKER_FILE_A)
    actual_links = managed_links()
    if actual_links != expected_links:
        only_a = set(expected_links) - set(actual_links)
        only_c = set(actual_links) - set(expected_links)
        fail(
            "managed-link manifest after re-install differs from after first install.\n"
            f"  links present after first install only: {sorted(only_a)}\n"
            f"  links present after re-install only:   {sorted(only_c)}"
        )
    ok(f"managed-link manifest matches group A ({len(actual_links)} link(s))")


def group_d(args: argparse.Namespace) -> None:
    """After uninstall.py --all --yes — full teardown."""
    log = Path(args.log).read_text() if args.log else ""

    # The repo-removal section prints the rm command rather than running it.
    # The path is rendered as the absolute home path of the user, so build it
    # from $HOME to keep the assertion stable across UIDs.
    expected_cmd = f"rm -rf {DOTFILES_DIR}"
    if expected_cmd not in log:
        fail(
            f"--all run did not print {expected_cmd!r}; the repo-removal "
            f"section may have regressed (or worse: actually deleted the repo).\n"
            f"--- log tail ---\n{log[-2000:]}"
        )
    ok(f"uninstall.py printed {expected_cmd!r} (did not execute it)")

    if not DOTFILES_DIR.is_dir():
        fail(
            f"{DOTFILES_DIR} is gone — `uninstall.py --all` is supposed to "
            f"print the rm command, not run it"
        )
    ok(f"{DOTFILES_DIR} still on disk (script printed, did not execute)")

    # Homebrew gone. ansible came from `brew install ansible`, so it goes too.
    if shutil.which("brew") is not None:
        fail("brew still on PATH after --homebrew uninstall")
    ok("brew gone from PATH")
    if shutil.which("ansible") is not None:
        fail("ansible still on PATH after Homebrew teardown")
    ok("ansible gone from PATH")

    # Managed symlinks all gone (default symlinks step still runs under --all).
    links = managed_links()
    if links:
        fail(f"{len(links)} managed symlink(s) remain after --all: {links}")
    ok("no managed symlinks remain under $HOME")

    assert_backup_restored(args.marker_name, "user-original\n")


GROUPS = {
    "group-a": group_a,
    "group-b": group_b,
    "group-c": group_c,
    "group-d": group_d,
}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("group", choices=sorted(GROUPS))
    parser.add_argument("--host", required=True)
    parser.add_argument("--marker-name", required=True,
                        help="basename of the synthetic e2e fixture under $HOME")
    parser.add_argument("--log", help="captured uninstall.py log, for groups b and d")
    args = parser.parse_args(argv)

    print(f"== assertions: {args.group} (host={args.host}) ==")
    GROUPS[args.group](args)
    print(f"== assertions: {args.group} PASS ==")


if __name__ == "__main__":
    main()
