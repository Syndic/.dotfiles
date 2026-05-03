#!/usr/bin/env python3
"""
phase2.py - dotfiles setup for macOS

Called by install.sh after Xcode CLT is installed and the dotfiles repo is
cloned. Handles Homebrew, Ansible, host profile selection, and runs the
Ansible playbook.

Usage:
    python3 phase2.py [--host PROFILE]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DOTFILES_DIR = Path.home() / ".dotfiles"
HOMEBREW_INSTALL_URL = "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"

# Homebrew installs to different paths on Apple Silicon vs Intel
BREW_PATHS = [
    Path("/opt/homebrew/bin/brew"),   # Apple Silicon
    Path("/usr/local/bin/brew"),      # Intel
]


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def announce(msg: str) -> None:
    print(f"\n[1;37;43m {msg} [0m")

def centered_announce(msg: str) -> None:
    terminal_cols = shutil.get_terminal_size().columns
    indent = max(0, (terminal_cols - len(msg)) // 2)
    print(f"\n{' ' * indent}\u001b[1;37;43m {msg} \u001b[0m")

def info(msg: str) -> None:
    print(f"[1;37;44m info [0m  {msg}")


def warn(msg: str) -> None:
    print(f"[1;37;43m warn [0m  {msg}", file=sys.stderr)


def die(msg: str) -> None:
    print(f"[1;37;101m error [0m {msg}", file=sys.stderr)
    sys.exit(1)

def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, raising CalledProcessError on non-zero exit."""
    return subprocess.run(args, check=True, **kwargs)

# ---------------------------------------------------------------------------
# Step 0: Argument parsing
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure a macOS machine from the dotfiles repo."
    )
    parser.add_argument(
        "--host",
        metavar="PROFILE",
        help="Use the host profile named PROFILE (in host_vars/). "
        "If omitted, you will be prompted to choose one.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Step 1: Display Kilobyte
# ---------------------------------------------------------------------------
def display_kilobyte() -> None:
    terminal_cols = shutil.get_terminal_size().columns
    art_dir = DOTFILES_DIR / "ascii_art"

    texts = []
    for p in art_dir.glob("kilobyte*.txt"):
        try:
            width = int(p.stem.removeprefix("kilobyte"))
            texts.append((width, p))
        except ValueError:
            pass

    if not texts:
        return

    texts.sort()

    # Find largest that fits, defaulting to the smallest available
    best_width, best_path = texts[0]
    for w, p in texts:
        if w <= terminal_cols:
            best_width, best_path = w, p

    indent = max(0, (terminal_cols - best_width) // 2)
    indent_str = " " * indent

    with open(best_path, "r") as f:
        for line in f:
            print(indent_str + line.rstrip("\r\n"))

# ---------------------------------------------------------------------------
# Step 2: Prepare Homebrew
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
        info("Homebrew already installed - running brew update...")
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
# Step 3: Prepare Ansible
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
# Step 4: Select host profile
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


def resolve_host_profile(host_arg: str | None) -> str:
    if host_arg:
        info(f"Using host profile: {host_arg}")
        return host_arg

    profiles_dir = DOTFILES_DIR / "host_vars"
    profiles: list[str] = []
    if profiles_dir.is_dir():
        profiles = sorted(
            p.stem if p.is_file() else p.name
            for p in profiles_dir.iterdir()
            if is_profile_entry(p)
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

        # Numeric selection
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(profiles):
                profile = profiles[idx - 1]
                info(f"Using host profile: {profile}")
                return profile
            print(f"  -> {idx} is out of range. Try again.")
            continue

        # Exact name match
        if choice in profiles:
            info(f"Using host profile: {choice}")
            return choice

        print(f"  -> '{choice}' is not a valid profile. Try again.")


# ---------------------------------------------------------------------------
# Step 5: Run Ansible playbook
# ---------------------------------------------------------------------------
def run_playbook(host_profile: str) -> None:
    run([
        "ansible-playbook",
        str(DOTFILES_DIR / "site.yml"),
        "--inventory", str(DOTFILES_DIR / "inventory.yml"),
        "--limit", host_profile,
    ])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()

    display_kilobyte()
    centered_announce(f"SIT. STAY. SUBMIT.")

    setup_homebrew()
    setup_ansible()
    host_profile = resolve_host_profile(args.host)

    announce(f"Tools ready - Running Playbook")
    run_playbook(host_profile)


if __name__ == "__main__":
    main()
