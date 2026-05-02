#!/usr/bin/env python3
"""
phase2.py - dotfiles setup for macOS

Called by install.sh after Xcode CLT is installed and the dotfiles repo is
cloned. Handles Homebrew, Ansible, host profile selection, and runs the
Ansible playbook.

Usage:
    python3 phase2.py [--host PROFILE]
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DOTFILES_DIR = Path.home() / ".dotfiles"
HOMEBREW_INSTALL_URL = (
    "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
)

# Homebrew installs to different paths on Apple Silicon vs Intel
BREW_PATHS = [
    Path("/opt/homebrew/bin/brew"),   # Apple Silicon
    Path("/usr/local/bin/brew"),      # Intel
]


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def info(msg: str) -> None:
    print(f"[info]  {msg}")


def warn(msg: str) -> None:
    print(f"[warn]  {msg}", file=sys.stderr)


def die(msg: str) -> None:
    print(f"[error] {msg}", file=sys.stderr)
    sys.exit(1)


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, raising CalledProcessError on non-zero exit."""
    return subprocess.run(args, check=True, **kwargs)


# ---------------------------------------------------------------------------
# Step 1: Homebrew
# ---------------------------------------------------------------------------


def find_brew() -> Path | None:
    """Return the path to brew if it is already installed, else None."""
    # Check PATH first (covers the case where brew is already in the shell env)
    if in_path := shutil.which("brew"):
        return Path(in_path)
    # Fall back to known install locations (brew may not be in PATH yet)
    for path in BREW_PATHS:
        if path.exists():
            return path
    return None


def brew_shellenv(brew: Path) -> None:
    """Evaluate brew shellenv to add brew to the current process environment."""
    import os

    result = subprocess.run(
        [str(brew), "shellenv"],
        check=True,
        capture_output=True,
        text=True,
    )
    # Parse 'export KEY=VALUE' lines and apply them to the current environment
    for line in result.stdout.splitlines():
        if line.startswith("export "):
            key, _, value = line[len("export "):].partition("=")
            os.environ[key] = value.strip('"').strip("'")


def setup_homebrew() -> None:
    brew = find_brew()

    if brew is not None:
        info("Homebrew already installed — running brew update...")
        run([str(brew), "update"])
    else:
        info("Installing Homebrew...")
        install_script = subprocess.run(
            ["curl", "-fsSL", HOMEBREW_INSTALL_URL],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        run(["/bin/bash", "-c", install_script])

        brew = find_brew()
        if brew is None:
            die("Homebrew installed but 'brew' not found in expected locations.")

        info("Homebrew installed.")

    # Make brew available for subsequent subprocess calls in this session
    brew_shellenv(brew)


# ---------------------------------------------------------------------------
# Step 2: Ansible
# ---------------------------------------------------------------------------


def setup_ansible() -> None:
    if shutil.which("ansible-playbook"):
        info("Ansible already installed.")
        return

    info("Installing Ansible via Homebrew...")
    run(["brew", "install", "ansible"])

    if not shutil.which("ansible-playbook"):
        die("Ansible not found after Homebrew install.")


# ---------------------------------------------------------------------------
# Step 3: Host profile
# ---------------------------------------------------------------------------


def resolve_host_profile(host_arg: str | None) -> str:
    if host_arg:
        info(f"Using host profile: {host_arg}")
        return host_arg

    profiles_dir = DOTFILES_DIR / "host_vars"
    print()
    print("Available host profiles:")

    profiles: list[str] = []
    if profiles_dir.is_dir():
        profiles = sorted(
            p.stem if p.is_file() else p.name
            for p in profiles_dir.iterdir()
        )
        for p in profiles:
            print(f"  - {p}")
    else:
        warn("No host_vars directory found - profile list unavailable.")

    print()
    try:
        profile = input("Enter host profile name: ").strip()
    except (EOFError, KeyboardInterrupt):
        die("No host profile specified.")

    if not profile:
        die("No host profile specified.")

    return profile


# ---------------------------------------------------------------------------
# Step 4: Run Ansible playbook
# ---------------------------------------------------------------------------


def run_playbook(host_profile: str) -> None:
    info(f"Running Ansible playbook for host profile '{host_profile}'...")
    run([
        "ansible-playbook",
        str(DOTFILES_DIR / "site.yml"),
        "--inventory", str(DOTFILES_DIR / "inventory.yml"),
        "--limit", host_profile,
    ])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure a macOS machine from the dotfiles repo."
    )
    parser.add_argument(
        "--host",
        metavar="PROFILE",
        help="Host profile name (must match a key in inventory.yml)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    setup_homebrew()
    setup_ansible()

    host_profile = resolve_host_profile(args.host)
    run_playbook(host_profile)


if __name__ == "__main__":
    main()
