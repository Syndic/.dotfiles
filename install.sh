#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install.sh — minimal phase 1 bootstrap shim
#
# Responsibilities:
#   1. Ensure Xcode Command Line Tools are installed (required for git + python3)
#   2. Clone or update the dotfiles repo into ~/.dotfiles
#   3. Hand off to ~/.dotfiles/phase2.py for everything else
#
# Usage (curl | bash):
#   curl -fsSL https://install.yanch.ar | bash -s -- --host <profile>
# ---------------------------------------------------------------------------
set -euo pipefail

DOTFILES_REPO="https://github.com/Syndic/.dotfiles"
DOTFILES_DIR="${HOME}/.dotfiles"

info() { echo "[info]  $*"; }
die()  { echo "[error] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Step 1: Xcode Command Line Tools
# Must happen in bash — /usr/bin/python3 is unreliable until CLT is installed.
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Step 2: Clone or update dotfiles repo
# git is available now that CLT is installed.
# ---------------------------------------------------------------------------

if [[ -d "${DOTFILES_DIR}/.git" ]]; then
  info "Dotfiles repo already present — pulling latest..."
  git -C "${DOTFILES_DIR}" pull --ff-only \
    || die "git pull failed. Resolve conflicts in ${DOTFILES_DIR} and re-run."
else
  info "Cloning dotfiles repo to ${DOTFILES_DIR}..."
  git clone "${DOTFILES_REPO}" "${DOTFILES_DIR}" \
    || die "git clone failed. Check network access and try again."
fi

# ---------------------------------------------------------------------------
# Step 3: Hand off to Python
# /usr/bin/python3 is the system Python, reliable now that CLT is installed.
# phase2.py handles Homebrew, Ansible, host profile selection, and playbook.
# ---------------------------------------------------------------------------

exec /usr/bin/python3 "${DOTFILES_DIR}/phase2.py" "$@"
