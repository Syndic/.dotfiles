#!/usr/bin/env bash
set -euo pipefail

# Install host snapshots the Dev Containers extension would otherwise bridge
# itself (devcontainer CLI case). See CLAUDE.md "Signed commits under
# devcontainer CLI".

here="$(cd "$(dirname "$0")" && pwd)"

# Install a ~/.ssh snapshot only when the destination is missing/empty (lets
# VS Code win when it's involved). ~/.ssh must be 0700 or SSH ignores it.
install_ssh_snapshot() {
  local src="$1" dst="$2"
  if [ ! -s "$dst" ] && [ -s "$src" ]; then
    mkdir -p "$HOME/.ssh"
    chmod 700 "$HOME/.ssh"
    cp "$src" "$dst"
    chmod 644 "$dst"
  fi
}

gitconfig_src="$here/.git-plumbing/host-gitconfig"
if [ ! -s "$HOME/.gitconfig" ] && [ -s "$gitconfig_src" ]; then
  cp "$gitconfig_src" "$HOME/.gitconfig"
fi

install_ssh_snapshot "$here/.git-plumbing/host-known-hosts" "$HOME/.ssh/known_hosts"
install_ssh_snapshot "$here/.git-plumbing/host-allowed-signers" "$HOME/.ssh/allowed_signers"

# Repoint the copied gitconfig at the installed copy. Keyed on the destination
# file so it also fixes the VS Code path (bridges gitconfig, not what it names).
if [ -s "$HOME/.ssh/allowed_signers" ]; then
  git config --global gpg.ssh.allowedSignersFile "$HOME/.ssh/allowed_signers"
fi

# Docker Desktop bind-mounts the magic ssh-agent socket root-owned mode 660,
# so the non-root remoteUser can't connect until we re-own it.
sock=/run/host-services/ssh-auth.sock
if [ -S "$sock" ] && [ "$(stat -c '%u' "$sock")" != "$(id -u)" ]; then
  sudo chown "$(id -u):$(id -g)" "$sock"
fi
