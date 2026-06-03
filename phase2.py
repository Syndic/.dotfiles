#!/usr/bin/env python3
"""
phase2.py - dotfiles setup (macOS and Linux)

Called by install.sh after phase-1 prerequisites are installed (macOS Xcode
CLT or Linux apt packages) and the dotfiles repo is cloned. Handles Homebrew
(Linuxbrew on Linux), Ansible, host profile selection, and runs the Ansible
playbook.

Usage:
    python3 phase2.py [--host PROFILE]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from _dotfiles_common import (
    announce_warning,
    centered_announce_warning,
    die,
    info,
    is_profile_entry,
    run,
    warn,
)
from _dotfiles_common import resolve_host_profile as _resolve_host_profile

DOTFILES_DIR = Path.home() / ".dotfiles"
INSTALLED_HOST_MARKER = DOTFILES_DIR / ".installed-host"
ASCII_ART_SUBDIR = "ascii_art"
ASCII_ART_TRUECOLOR_SUBDIR = "truecolor"
ASCII_ART_256_COLOR_SUBDIR = "256color"

HOMEBREW_INSTALL_URL = "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"

# Homebrew installs to different default prefixes per platform.
BREW_PATHS = [
    Path("/opt/homebrew/bin/brew"),                  # macOS Apple Silicon
    Path("/usr/local/bin/brew"),                     # macOS Intel
    Path("/home/linuxbrew/.linuxbrew/bin/brew"),     # Linuxbrew (multi-user)
    Path.home() / ".linuxbrew" / "bin" / "brew",     # Linuxbrew (single-user)
]


# ---------------------------------------------------------------------------
# Step 0: Argument parsing
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure a machine (macOS or Linux) from the dotfiles repo."
    )
    parser.add_argument(
        "--host",
        metavar="PROFILE",
        help="Use the host profile named PROFILE (in host_vars/). "
        "If omitted, you will be prompted to choose one.",
    )
    parser.add_argument(
        "--no-upgrade",
        dest="upgrade",
        action="store_false",
        default=True,
        help="Skip the `brew upgrade` pass that normally runs after "
        "`brew bundle install`. Useful for fast re-runs that should "
        "only pick up Brewfile changes, not refresh existing packages.",
    )
    parser.add_argument(
        "--no-dock",
        dest="dock",
        action="store_false",
        default=True,
        help="Skip the macOS Dock layout step (geerlingguy.mac.dock) "
        "during the macos_defaults role. Useful when running on a host "
        "that doesn't have `dockutil` installed yet, or for a quick "
        "re-run that shouldn't shuffle the Dock. No effect on Linux.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Step 1: Display Kilobyte
# ---------------------------------------------------------------------------
def select_ascii_art_format() -> str:
    """Select the folder with ascii art in an appropriate format for the terminal emulator.

    Older versions of Apple's built-in Terminal do not support truecolor (24-bit RGB) control
    sequences, so art that looks best in a modern terminal emulator can render badly there. Newer
    Terminal.app releases on macOS 26+ do support 24-bit color.

    Currently, the options are ASCII_ART_TRUECOLOR_SUBDIR and ASCII_ART_256_COLOR_SUBDIR.
    """
    colorterm = os.environ.get("COLORTERM", "").lower()
    term = os.environ.get("TERM", "")

    if colorterm in {"truecolor", "24bit"} or term.endswith("-direct"):
        return ASCII_ART_TRUECOLOR_SUBDIR

    return ASCII_ART_256_COLOR_SUBDIR

def display_kilobyte(format_subdir: str) -> None:
    terminal_cols = shutil.get_terminal_size().columns
    art_dir = DOTFILES_DIR / ASCII_ART_SUBDIR / format_subdir

    texts = []
    for p in art_dir.glob("kilobyte*.txt"):
        try:
            width = int(p.stem.removeprefix("kilobyte"))
            texts.append((width, p))
        except ValueError:
            pass

    texts.sort()

    if not texts:
        warn("No kilobyte ascii art found.")
        return

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

    centered_announce_warning(f"SIT. STAY. SUBMIT.")


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
    """Make brew (and brew-installed binaries) reachable on PATH for child
    processes — most importantly the `brew install ansible` call that comes
    next and brew's own subprocess shell-outs (which use PATH to find
    `readlink`, `grep`, etc.).

    We don't try to parse `brew shellenv` output. Its PATH line is of the
    form

        export PATH="/opt/homebrew/bin:/opt/homebrew/sbin${PATH+:$PATH}"

    and a naive KEY=VALUE parse stores the literal `${PATH+:$PATH}` as part
    of PATH, which clobbers /usr/bin etc. and then breaks brew itself when
    its first internal subprocess can't find `readlink`. Compute the right
    PATH directly from brew's location instead.
    """
    brew_prefix = brew.parent.parent  # .../bin/brew  →  .../
    brew_dirs = [brew_prefix / "bin", brew_prefix / "sbin"]
    current_path = os.environ.get("PATH", "").split(os.pathsep)
    additions = [str(d) for d in brew_dirs if str(d) not in current_path]
    if additions:
        os.environ["PATH"] = os.pathsep.join(additions + current_path)


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


def install_galaxy_requirements() -> None:
    """Install Galaxy collection deps declared in requirements.yml.

    Idempotent: ansible-galaxy verifies already-installed collections
    and only fetches missing ones, so re-running is cheap. Silently
    no-ops if requirements.yml is absent — the role layer may not need
    any external collections at all in some forks."""
    req = DOTFILES_DIR / "requirements.yml"
    if not req.exists():
        return

    info("Installing Ansible Galaxy collections from requirements.yml...")
    run(["ansible-galaxy", "collection", "install", "-r", str(req)])


# ---------------------------------------------------------------------------
# Step 4: Select host profile
# ---------------------------------------------------------------------------
def resolve_host_profile(host_arg: str | None) -> str:
    """Thin wrapper over _dotfiles_common.resolve_host_profile that supplies
    this script's notion of where host_vars/ lives. Kept here so tests can
    monkeypatch phase2.DOTFILES_DIR and get the expected behavior."""
    return _resolve_host_profile(host_arg, DOTFILES_DIR / "host_vars")


# ---------------------------------------------------------------------------
# Step 5: Run Ansible playbook
# ---------------------------------------------------------------------------
def run_playbook(
    host_profile: str,
    sudo_password: str | None = None,
    upgrade: bool = True,
    dock: bool = True,
) -> None:
    cmd = [
        "ansible-playbook",
        str(DOTFILES_DIR / "site.yml"),
        "--inventory", str(DOTFILES_DIR / "inventory.yml"),
        "--limit", host_profile,
    ]
    # The role defaults are homebrew_upgrade_outdated=true and
    # macos_defaults_configure_dock=true; only inject the override when the
    # user passed --no-upgrade / --no-dock. Keeping the default implicit
    # means a stock install command lines up with whatever the role
    # defaults say, with no `-e` plumbing to keep in sync.
    if not upgrade:
        cmd += ["--extra-vars", "homebrew_upgrade_outdated=false"]
    if not dock:
        cmd += ["--extra-vars", "macos_defaults_configure_dock=false"]
    if sudo_password:
        # Pass the captured sudo password as ANSIBLE_BECOME_PASS, scoped to
        # this subprocess only — not set in our own os.environ.
        env = os.environ.copy()
        env["ANSIBLE_BECOME_PASS"] = sudo_password
        run(cmd, env=env)
    else:
        run(cmd)


def capture_sudo_password() -> str | None:
    """Return the sudo password handed off by install.sh, removing it from
    our environment so it doesn't leak into Homebrew installer subprocesses,
    brew, ansible's pre-playbook setup, etc. The returned value is held only
    in memory and only passed back out via run_playbook's subprocess env."""
    return os.environ.pop("SUDO_PASSWORD", None) or None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    # See CLAUDE.md "Output buffering" — interleaves status lines with
    # subprocess output in CI/docker logs.
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    args = parse_args()

    # Pop SUDO_PASSWORD before anything else can inherit it (Homebrew installer,
    # brew, etc.). See CLAUDE.md "Sudo / become on Linux".
    sudo_password = capture_sudo_password()

    display_kilobyte(select_ascii_art_format())

    setup_homebrew()
    setup_ansible()
    install_galaxy_requirements()
    host_profile = resolve_host_profile(args.host)

    announce_warning(f"Tools ready - Running Playbook")
    run_playbook(
        host_profile,
        sudo_password=sudo_password,
        upgrade=args.upgrade,
        dock=args.dock,
    )

    # Record the profile so uninstall.py can default to it without re-prompting.
    record_installed_host(host_profile)


def record_installed_host(host_profile: str) -> None:
    """Persist the host profile used for this install. Best-effort: a write
    failure here doesn't undo a successful playbook run, so warn and move on."""
    try:
        INSTALLED_HOST_MARKER.write_text(host_profile + "\n")
    except OSError as exc:
        warn(f"Could not record installed host profile at {INSTALLED_HOST_MARKER}: {exc}")


if __name__ == "__main__":
    main()
