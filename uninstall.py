#!/usr/bin/env python3
"""
uninstall.py - inverse of install.sh + phase2.py.

By default, removes every symlink in $HOME whose target lives inside the
managed dotfiles repo, and restores the most-recent <name>.backup-N sibling
for each removed path. Opt-in flags broaden the teardown to package
installations and Homebrew / the repo itself.

Usage:
    python3 ~/.dotfiles/uninstall.py [--host PROFILE] [flags]

The plan is printed first; one y/N confirmation covers all actions. Pass
--yes to skip the prompt (scripted use). Without a tty and without --yes,
the plan is printed and nothing is done.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from _dotfiles_common import (
    announce,
    die,
    info,
    list_host_profiles,
    resolve_host_profile as _resolve_host_profile,
    run,
    warn,
)
from dotfiles_manager import (
    backup_path_info,
    find_stale_managed_symlinks,
)

DOTFILES_DIR = Path.home() / ".dotfiles"
INSTALLED_HOST_MARKER = DOTFILES_DIR / ".installed-host"
HOMEBREW_UNINSTALL_URL = (
    "https://raw.githubusercontent.com/Homebrew/install/HEAD/uninstall.sh"
)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reverse what install.sh and phase2.py did on this host. "
            "By default removes managed symlinks and restores .backup-N "
            "siblings. Flags broaden the teardown."
        )
    )
    parser.add_argument(
        "--host",
        metavar="PROFILE",
        help=(
            "Host profile to scope package removal to. Defaults to the "
            "profile recorded by phase2 in ~/.dotfiles/.installed-host; "
            "falls back to the interactive picker."
        ),
    )
    parser.add_argument("--brew-packages", action="store_true",
                        help="Uninstall packages listed in the layered Brewfiles.")
    parser.add_argument("--apt-packages", action="store_true",
                        help="Uninstall apt packages from the layered apt lists (Linux).")
    parser.add_argument("--flatpak-packages", action="store_true",
                        help="Uninstall flatpaks from the layered flatpak lists (Linux).")
    parser.add_argument("--ansible", action="store_true",
                        help="brew uninstall ansible.")
    parser.add_argument("--homebrew", action="store_true",
                        help="Run the official Homebrew uninstall script.")
    parser.add_argument("--repo", action="store_true",
                        help="Print the command to remove ~/.dotfiles (does not delete).")
    parser.add_argument("--all", action="store_true",
                        help="Equivalent to passing every removal flag above.")
    parser.add_argument("--skip-symlinks", action="store_true",
                        help="Do not remove managed symlinks (only act on the flags passed).")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip the confirmation prompt.")
    args = parser.parse_args(argv)

    if args.all:
        args.brew_packages = True
        args.apt_packages = True
        args.flatpak_packages = True
        args.ansible = True
        args.homebrew = True
        args.repo = True

    return args


# ---------------------------------------------------------------------------
# Host profile resolution
# ---------------------------------------------------------------------------
def read_recorded_host() -> str | None:
    """Return the profile written by phase2 after a successful install, or
    None if the marker file is missing/empty/unreadable."""
    try:
        text = INSTALLED_HOST_MARKER.read_text().strip()
    except OSError:
        return None
    return text or None


def resolve_host(host_arg) -> str:
    if host_arg:
        info(f"Using host profile: {host_arg}")
        return host_arg
    profiles_dir = DOTFILES_DIR / "host_vars"
    recorded = read_recorded_host()
    if recorded:
        # Marker may be stale (profile renamed/removed); validate before use.
        if recorded in list_host_profiles(profiles_dir):
            info(f"Using host profile from {INSTALLED_HOST_MARKER.name}: {recorded}")
            return recorded
        warn(
            f"Recorded host profile {recorded!r} (from {INSTALLED_HOST_MARKER.name}) "
            f"is no longer in {profiles_dir.name}/; falling back to the picker."
        )
    return _resolve_host_profile(None, profiles_dir)


# ---------------------------------------------------------------------------
# Action planning
# Each builder returns (preview_lines, do_callable). Sections are appended in
# execution order in main(); see the numbered comments there.
# ---------------------------------------------------------------------------
def build_symlink_actions(home: Path, managed_root: Path):
    """Return (preview_lines, do_callable) for the symlink + backup-restore step.

    preview_lines is a list of human-readable strings describing each link
    that will be removed (and whether a backup will be restored). do_callable
    takes no arguments and performs the work."""
    resolved_root = managed_root.resolve(strict=False)
    managed_links = find_stale_managed_symlinks(
        resolved_managed_root_dir=resolved_root,
        home_dir=home,
        desired_link_paths=[],
    )

    preview = []
    for link in managed_links:
        path = link["path"]
        backup = _latest_backup(Path(path))
        if backup is None:
            preview.append(f"  remove symlink   {path}  ->  {link['target']}")
        else:
            preview.append(
                f"  remove symlink   {path}  ->  {link['target']}"
                f"\n                   then restore backup: {backup}"
            )

    def do_symlinks():
        for link in managed_links:
            path = Path(link["path"])
            try:
                path.unlink()
                info(f"removed {path}")
            except FileNotFoundError:
                warn(f"{path} already gone")
                continue
            backup = _latest_backup(path)
            if backup is not None:
                os.rename(backup, path)
                info(f"restored {backup.name} -> {path.name}")

    return preview, do_symlinks


def _latest_backup(target_path: Path) -> Path | None:
    """Return the highest-indexed <name>.backup-N sibling, or None.

    Mirrors dotfiles_manager.backup_path_info's naming."""
    parent = target_path.parent
    prefix = f"{target_path.name}.backup-"
    best = None
    best_idx = 0
    if parent.is_dir():
        for sibling in parent.iterdir():
            if not sibling.name.startswith(prefix):
                continue
            suffix = sibling.name[len(prefix):]
            if suffix.isdigit() and int(suffix) > best_idx:
                best_idx = int(suffix)
                best = sibling
    return best


def build_playbook_actions(host: str, brew: bool, apt: bool, flatpak: bool):
    """If any package-removal flag is set, return one action that invokes
    uninstall.yml with the matching --tags. Returns (preview, callable) or
    (None, None) when nothing is requested."""
    tags = []
    if brew:
        tags.append("brew_packages")
    if apt:
        tags.append("apt_packages")
    if flatpak:
        tags.append("flatpak_packages")
    if not tags:
        return None, None

    preview = [f"  run ansible-playbook uninstall.yml --tags {','.join(tags)} --limit {host}"]

    def do_playbook():
        if not shutil.which("ansible-playbook"):
            die("ansible-playbook not found - cannot uninstall packages.")
        cmd = [
            "ansible-playbook",
            str(DOTFILES_DIR / "uninstall.yml"),
            "--inventory", str(DOTFILES_DIR / "inventory.yml"),
            "--limit", host,
            "--tags", ",".join(tags),
        ]
        run(cmd)

    return preview, do_playbook


def build_ansible_action():
    if not shutil.which("brew"):
        return [f"  brew uninstall ansible  (skipped: brew not in PATH)"], lambda: None
    preview = ["  brew uninstall ansible"]

    def do_ansible():
        # Ignore "not installed" errors; uninstall should be idempotent.
        subprocess.run(["brew", "uninstall", "ansible"], check=False)

    return preview, do_ansible


def build_homebrew_action():
    preview = [
        "  curl -fsSL Homebrew/uninstall.sh | bash  (interactive: removes Homebrew itself)",
    ]

    def do_homebrew():
        script = subprocess.run(
            ["curl", "-fsSL", HOMEBREW_UNINSTALL_URL],
            check=True, capture_output=True, text=True,
        ).stdout
        # Pass --force so the upstream script doesn't re-prompt — the user
        # already confirmed at our overall y/N gate.
        subprocess.run(["/bin/bash", "-c", script, "uninstall.sh", "--force"], check=False)

    return preview, do_homebrew


def build_repo_action():
    preview = [
        f"  print 'rm -rf {DOTFILES_DIR}' for you to run yourself "
        f"(this script does NOT self-delete)",
    ]

    def do_repo():
        print()
        announce(f"To remove the dotfiles checkout, run:")
        print(f"  rm -rf {DOTFILES_DIR}")
        print()

    return preview, do_repo


# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------
def confirm(skip_prompt: bool) -> bool:
    """Return True iff the user has authorized the plan. --yes auto-confirms.
    A non-tty caller without --yes is treated as inert (False, no error).
    """
    if skip_prompt:
        return True
    if not sys.stdin.isatty():
        info("No tty and no --yes - plan printed above. Re-run with --yes to apply.")
        return False
    try:
        answer = input("Proceed? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv=None) -> None:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    args = parse_args(argv)
    host = resolve_host(args.host)

    sections = []  # list of (header, preview_lines, callable)

    # 1. Package removal (needs the package managers still present)
    pb_preview, pb_do = build_playbook_actions(
        host, args.brew_packages, args.apt_packages, args.flatpak_packages
    )
    if pb_do is not None:
        sections.append(("Uninstall packages", pb_preview, pb_do))

    # 2. Ansible itself (after the playbook above)
    if args.ansible:
        prev, do = build_ansible_action()
        sections.append(("Uninstall Ansible", prev, do))

    # 3. Managed symlinks + backup restore (default; opt out with --skip-symlinks)
    if not args.skip_symlinks:
        prev, do = build_symlink_actions(Path.home(), DOTFILES_DIR)
        if prev:
            sections.append(("Remove managed symlinks", prev, do))
        else:
            sections.append((
                "Remove managed symlinks",
                ["  (no managed symlinks found under $HOME)"],
                do,
            ))

    # 4. Homebrew itself (after anything that needs brew)
    if args.homebrew:
        prev, do = build_homebrew_action()
        sections.append(("Uninstall Homebrew", prev, do))

    # 5. Repo (print only; user removes it themselves)
    if args.repo:
        prev, do = build_repo_action()
        sections.append(("Remove dotfiles checkout", prev, do))

    if not sections:
        info("Nothing to do.")
        return

    announce("Uninstall plan")
    for header, preview, _ in sections:
        print(f"\n{header}:")
        for line in preview:
            print(line)
    print()

    if not confirm(args.yes):
        info("Aborted; no changes made.")
        return

    for header, _, do in sections:
        announce(header)
        do()

    print()
    info("Done.")


if __name__ == "__main__":
    main()
