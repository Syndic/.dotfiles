#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install.sh — minimal phase 1 bootstrap shim
#
# Responsibilities:
#   1. Ensure prerequisites for phase 2 are installed:
#        - macOS:  Xcode Command Line Tools (git + /usr/bin/python3).
#        - Linux:  apt packages git, python3, curl, ca-certificates, plus
#                  Homebrew's documented Linux build prerequisites
#                  build-essential, procps, file — phase 2 installs
#                  Linuxbrew and they must be present beforehand.
#   2. Clone or update the dotfiles repo into ~/.dotfiles.
#   3. Hand off to ~/.dotfiles/phase2.py for everything else.
#
# Usage (curl | bash):
#   curl -fsSL https://install.yanch.ar | bash -s -- --host PROFILE
# ---------------------------------------------------------------------------
set -euo pipefail

# DOTFILES_REPO is override-able so the e2e harness can point install.sh at
# a local source repo instead of the public one.
DOTFILES_REPO="${DOTFILES_REPO:-https://github.com/Syndic/.dotfiles}"
DOTFILES_DIR="${HOME}/.dotfiles"

# Override-able for tests; default is the system Python (macOS CLT or
# apt-installed python3 on Linux — both land at /usr/bin/python3).
PYTHON3="${PYTHON3:-/usr/bin/python3}"

announce() { printf "\n[1;37;43m $* [0m\n"; }
info() { printf "[1;37;44m info [0m  $*\n"; }
die()  { printf "[1;37;101m error [0m $*\n" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Step 0: Opening message
# ---------------------------------------------------------------------------
announce "Joshua Yanchar's Dotfile Setup"

# ---------------------------------------------------------------------------
# Step 1: Install phase-2 prerequisites
# Must happen in bash — git and a usable python3 may both be missing on a
# fresh box, and on macOS /usr/bin/python3 is a stub until CLT is installed.
# ---------------------------------------------------------------------------
OS="$(uname -s)"

case "$OS" in
  Darwin)
    if xcode-select -p &>/dev/null; then
      info "Xcode Command Line Tools already installed."
    else
      info "Installing Xcode Command Line Tools..."

      # softwareupdate lists CLT packages only when this sentinel file is present
      touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress

      PROD=$(softwareupdate -l 2>/dev/null \
        | grep -E '\*.*Command Line Tools for Xcode' \
        | sort -V \
        | tail -1 \
        | sed 's/^[[:space:]]*\* Label: //' \
        | sed 's/^[[:space:]]*//')

      rm -f /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress

      if [[ -z "$PROD" ]]; then
        die "Could not find Command Line Tools in softwareupdate output." \
          $'\nRun: xcode-select --install\nThen re-run this script.'
      fi

      softwareupdate --install "$PROD" --agree-to-license \
        || die "softwareupdate failed. Run 'xcode-select --install' manually, then re-run."

      info "Xcode Command Line Tools installed."
    fi
    ;;
  Linux)
    # build-essential / procps / file are Homebrew's documented Linux build
    # prerequisites. They MUST be installed here — phase 2 installs Linuxbrew
    # and runs `brew install ansible` before the Ansible playbook (and thus
    # any apt role) ever runs, and the Homebrew installer does not install
    # them itself.
    #
    # Sudo strategy: probe once, prompt at most once, never rely on sudo's
    # timestamp cache to bridge install.sh's apt step and phase 2's later
    # Ansible become. The captured password (if any) is exported to phase 2
    # in $SUDO_PASSWORD so phase 2 can hand it to ansible-playbook via the
    # ANSIBLE_BECOME_PASS env on that subprocess only.
    if [[ "$(id -u)" -eq 0 ]]; then
      SUDO_NEEDED=false                # running as root; no escalation required
    elif [[ -n "${SUDO_PASSWORD:-}" ]]; then
      SUDO_NEEDED=true                 # caller pre-provided (e.g. test harness)
      # validate the supplied password before continuing
      printf '%s\n' "$SUDO_PASSWORD" | sudo -S -p '' -k true 2>/dev/null \
        || die "Provided SUDO_PASSWORD failed sudo authentication."
    elif sudo -n true 2>/dev/null; then
      SUDO_NEEDED=true                 # passwordless sudo configured
      SUDO_PASSWORD=""
    else
      SUDO_NEEDED=true
      # Real open() probe — `[[ -r /dev/tty ]]` lies in tty-less contexts
      # because the path exists in /dev but open() still fails.
      if ! (exec < /dev/tty) 2>/dev/null; then
        die "sudo password required but no tty available. Either configure passwordless sudo for $USER, or pre-export SUDO_PASSWORD, or run from a terminal."
      fi
      info "Linux install needs sudo for apt-get and the Ansible playbook."
      printf '\e[1;37;44m sudo \e[0m  password for %s: ' "$USER" >&2
      IFS= read -rs SUDO_PASSWORD < /dev/tty
      printf '\n' >&2
      printf '%s\n' "$SUDO_PASSWORD" | sudo -S -p '' -k true 2>/dev/null \
        || die "sudo authentication failed."
    fi

    # Sudo-aware apt-get wrapper. Always passes DEBIAN_FRONTEND through sudo's
    # VAR=val argument form (sudo strips most env vars by default).
    sudo_apt() {
      if ! $SUDO_NEEDED; then
        DEBIAN_FRONTEND=noninteractive apt-get "$@"
      elif [[ -z "${SUDO_PASSWORD:-}" ]]; then
        sudo DEBIAN_FRONTEND=noninteractive apt-get "$@"
      else
        printf '%s\n' "$SUDO_PASSWORD" \
          | sudo -S -p '' DEBIAN_FRONTEND=noninteractive apt-get "$@"
      fi
    }

    info "Installing Linux prerequisites via apt-get..."
    sudo_apt update                   || die "apt-get update failed."
    sudo_apt install -y \
      git python3 curl ca-certificates build-essential procps file \
                                       || die "apt-get install failed."
    info "Linux prerequisites installed."

    # Hand off to phase 2 if we captured a password. (Empty / unset means
    # passwordless sudo or root, neither of which needs Ansible to know.)
    if [[ -n "${SUDO_PASSWORD:-}" ]]; then
      export SUDO_PASSWORD
    fi
    ;;
  *)
    die "Unsupported OS: $OS (this script supports macOS and Linux)."
    ;;
esac

# ---------------------------------------------------------------------------
# Step 2: Clone or update dotfiles repo
# git is available now that prerequisites are installed.
# ---------------------------------------------------------------------------

if [[ -d "${DOTFILES_DIR}/.git" ]]; then
  info "Dotfiles repo already present - pulling latest..."
  git -C "${DOTFILES_DIR}" pull --ff-only \
    || die "git pull failed. Resolve conflicts in ${DOTFILES_DIR} and re-run."
else
  info "Cloning dotfiles repo to ${DOTFILES_DIR}..."
  git clone "${DOTFILES_REPO}" "${DOTFILES_DIR}" \
    || die "git clone failed. Check network access and try again."
fi

# ---------------------------------------------------------------------------
# Step 3: Hand off to Python
# /usr/bin/python3 is the system Python, reliable now that prerequisites are
# installed (macOS CLT or Linux apt python3 package).
# phase2.py handles Homebrew, Ansible, host profile selection, and playbook.
#
# Reattach stdin to the controlling terminal when available, so phase2.py's
# interactive prompts work under `curl | bash` (where bash's stdin is the
# install-script pipe, not the user's keyboard). Skip the redirect in
# tty-less contexts so non-interactive runs with --host still launch
# - phase2.py reports the missing-tty case itself.
#
# NOTE: `[[ -r /dev/tty ]]` is unreliable — the file exists in /dev but open() fails
# when the process has no controlling terminal. Probe the redirect in a
# subshell first, scoping 2>/dev/null to just the probe, then do the real
# exec with stderr intact so phase2.py's prompts and errors reach the user.
# (Wrapping the real exec in a 2>/dev/null group would survive into the
# exec'd process and silently swallow input()'s prompt and any die() output.)
# ---------------------------------------------------------------------------
if (exec < /dev/tty) 2>/dev/null; then
  exec "$PYTHON3" "${DOTFILES_DIR}/phase2.py" "$@" < /dev/tty
else
  exec "$PYTHON3" "${DOTFILES_DIR}/phase2.py" "$@"
fi
