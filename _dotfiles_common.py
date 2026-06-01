"""Shared helpers for phase2.py and uninstall.py.

See CLAUDE.md "Shared module: `_dotfiles_common.py`" for the rationale.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def announce(msg: str) -> None:
    print(f"\n\x1b[1;37;43m {msg} \x1b[0m")


def centered_announce(msg: str) -> None:
    terminal_cols = shutil.get_terminal_size().columns
    indent = max(0, (terminal_cols - (len(msg) + 2)) // 2)
    print(f"\n{' ' * indent}[1;37;43m {msg} [0m")


def info(msg: str) -> None:
    print(f"\x1b[1;37;44m info \x1b[0m  {msg}")


def warn(msg: str) -> None:
    print(f"\x1b[1;37;43m warn \x1b[0m  {msg}", file=sys.stderr)


def die(msg: str) -> None:
    print(f"\x1b[1;37;101m error \x1b[0m {msg}", file=sys.stderr)
    sys.exit(1)


def run(args: list, **kwargs) -> subprocess.CompletedProcess:
    """Run a command, raising CalledProcessError on non-zero exit."""
    return subprocess.run(args, check=True, **kwargs)


# ---------------------------------------------------------------------------
# Host profile resolution
# ---------------------------------------------------------------------------
def is_profile_entry(p: Path) -> bool:
    """Return True if `p` looks like an Ansible host_vars entry: either a
    YAML file (host_vars/<name>.yml) or a directory (host_vars/<name>/).
    Skips dotfiles and anything else (READMEs, .bak files, etc.)."""
    if p.name.startswith("."):
        return False
    if p.is_file():
        return p.suffix in (".yml", ".yaml")
    if p.is_dir():
        return True
    return False


def list_host_profiles(profiles_dir: Path) -> list:
    if not profiles_dir.is_dir():
        return []
    return sorted(
        p.stem if p.is_file() else p.name
        for p in profiles_dir.iterdir()
        if is_profile_entry(p)
    )


def resolve_host_profile(host_arg, profiles_dir: Path) -> str:
    """Resolve a host profile name. With host_arg set, validate it against
    profiles_dir and accept or die. Otherwise list profiles_dir entries and
    prompt for a selection."""
    profiles = list_host_profiles(profiles_dir)

    if host_arg:
        if host_arg in profiles:
            info(f"Using host profile: {host_arg}")
            return host_arg
        # A typo'd --host would otherwise reach `ansible-playbook --limit`
        # and produce "skipping: no hosts matched" with exit 0 — the user
        # walks away thinking the install ran. Fail loudly instead.
        if not profiles:
            die(
                f"No host profile named '{host_arg}' "
                f"(no host_vars/ profiles found in {profiles_dir})."
            )
        die(
            f"No host profile named '{host_arg}'. "
            f"Available: {', '.join(profiles)}"
        )

    if not profiles:
        die("No --host given and no host_vars/ profiles found to choose from.")

    if not sys.stdin.isatty():
        die("No --host given and no terminal available - pass --host PROFILE explicitly.")

    print("\nAvailable host profiles:")
    for i, p in enumerate(profiles, start=1):
        print(f"  {i}) {p}")

    prompt = f"Choose [1-{len(profiles)}] or name: "
    while True:
        try:
            choice = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            die("No host profile specified.")

        if not choice:
            continue

        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(profiles):
                profile = profiles[idx - 1]
                info(f"Using host profile: {profile}")
                return profile
            print(f"  -> {idx} is out of range. Try again.")
            continue

        if choice in profiles:
            info(f"Using host profile: {choice}")
            return choice

        print(f"  -> '{choice}' is not a valid profile. Try again.")
