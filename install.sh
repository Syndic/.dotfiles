#!/usr/bin/env bash
# install.sh — phase 1 bootstrap shim.
# Usage (curl | bash): curl -fsSL https://install.yanch.ar | bash -s -- --host PROFILE
# See CLAUDE.md "The two-language split is intentional" for why phase 1 is bash.
set -euo pipefail

# DOTFILES_REPO is override-able so the e2e harness can point install.sh at
# a local source repo instead of the public one.
DOTFILES_REPO="${DOTFILES_REPO:-https://github.com/Syndic/.dotfiles}"
DOTFILES_DIR="${HOME}/.dotfiles"

# Override-able for tests; default is the system Python (macOS CLT or
# apt-installed python3 on Linux — both land at /usr/bin/python3).
PYTHON3="${PYTHON3:-/usr/bin/python3}"

announce() { printf "\n[1;37;43m $* [0m\n" >&2; }
info() { printf "[1;37;44m info [0m  $*\n" >&2; }
die()  { printf "[1;37;101m error [0m $*\n" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Step 0: Opening message
# ---------------------------------------------------------------------------
announce "Joshua Yanchar's Dotfile Setup"

# ---------------------------------------------------------------------------
# Step 1: Install phase-2 prerequisites (macOS CLT or Linux apt packages)
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
    # build-essential / procps / file are Homebrew's Linux build prereqs;
    # the Homebrew installer doesn't pull them itself. Sudo flow (probe
    # once, prompt at most once, hand off via $SUDO_PASSWORD): see CLAUDE.md
    # "Sudo / become on Linux".
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
        die "sudo password required but no tty available. Either configure passwordless sudo for ${USER:-$(id -un)}, or pre-export SUDO_PASSWORD, or run from a terminal."
      fi
      info "Linux install needs sudo for apt-get and the Ansible playbook."
      printf '\e[1;37;44m sudo \e[0m  password for %s: ' "${USER:-$(id -un)}" >&2
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
# ---------------------------------------------------------------------------
# /dev/tty probe-and-fallback — see CLAUDE.md "The /dev/tty probe-and-fallback".
# Don't move 2>/dev/null onto the real exec; it would survive into the exec'd
# Python and swallow input()'s prompts.
if (exec < /dev/tty) 2>/dev/null; then
  exec "$PYTHON3" "${DOTFILES_DIR}/phase2.py" "$@" < /dev/tty
else
  exec "$PYTHON3" "${DOTFILES_DIR}/phase2.py" "$@"
fi
