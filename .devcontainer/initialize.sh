#!/usr/bin/env bash
set -euo pipefail

# initializeCommand — runs on the host before the container exists, on every `up`.
# Presents host state in the shape the base image's plumbing consumes: reads into
# .git-plumbing/, host-discovered paths as `.host-*` symlinks devcontainer.json binds.
# See CLAUDE.md "Devcontainer host plumbing".

here="$(cd "$(dirname "$0")" && pwd)"
workspace="$(cd "$here/.." && pwd)"
link="$here/.host-git-common"
khlink="$here/.host-known-hosts"
signerslink="$here/.host-allowed-signers"
pathfile="$here/.git-plumbing/host-git-common-path"
tzfile="$here/.git-plumbing/host-timezone"
gitconfigfile="$here/.git-plumbing/host-gitconfig"
signersfallback="$here/.git-plumbing/empty-allowed-signers"

mkdir -p "$(dirname "$pathfile")"

cd "$workspace"

# Fail loud on missing git; the container side is PLUMBING_REQUIRE_GIT_CHECKOUT=1.
# ln -sfn replaces any existing symlink in place rather than nesting.
common="$(git rev-parse --path-format=absolute --git-common-dir)"
ln -sfn "$common" "$link"
printf '%s\n' "$common" >"$pathfile"

# Discover host IANA zone; empty result → the container keeps its default.
tz=""
if target="$(readlink /etc/localtime 2>/dev/null)"; then
  case "$target" in
    *zoneinfo/*) tz="${target##*zoneinfo/}" ;;
  esac
fi
if [ -z "$tz" ] && [ -r /etc/timezone ]; then
  tz="$(tr -d '[:space:]' </etc/timezone)"
fi
# Reject traversal / absolute paths: the container builds /usr/share/zoneinfo/$tz from this.
case "$tz" in
  /* | *..*) tz="" ;;
esac
printf '%s\n' "$tz" >"$tzfile"

# Snapshot host ~/.gitconfig for the base image to install at postStart when the Dev
# Containers extension hasn't already done so. Empty file if absent.
if [ -r "$HOME/.gitconfig" ]; then
  cp "$HOME/.gitconfig" "$gitconfigfile"
else
  : >"$gitconfigfile"
fi

# known_hosts: link the first UserKnownHostsFile (the one ssh appends to), so a host
# accepted in-container lands on the host. A non-absolute answer would dangle the bind.
khfile=""
read -r khfile _ <<<"$(ssh -G github.com 2>/dev/null | sed -n 's/^userknownhostsfile //p')" || true
case "$khfile" in
  /*) ;;
  *) khfile="$HOME/.ssh/known_hosts" ;;
esac
# The bind needs a real target; an empty one is what ssh would create on first use.
mkdir -p "$(dirname "$khfile")"
chmod 700 "$(dirname "$khfile")" 2>/dev/null || true
: >>"$khfile"
ln -sfn "$khfile" "$khlink"

# allowed_signers: link whatever gpg.ssh.allowedSignersFile names. Unset or unreadable
# falls back to an empty file we own, so the bind can't dangle.
signers="$(git config --type=path --get gpg.ssh.allowedSignersFile 2>/dev/null || true)"
if [ -n "$signers" ] && [ -r "$signers" ]; then
  ln -sfn "$signers" "$signerslink"
else
  : >>"$signersfallback"
  ln -sfn "$signersfallback" "$signerslink"
fi

# TEND(migration): drop with their .gitignore entries once every checkout has had an
# `up` since the bind mounts replaced these snapshots.
rm -f "$here/.git-plumbing/host-known-hosts" "$here/.git-plumbing/host-allowed-signers"

# Pre-create the magic ssh-agent socket placeholder on hosts where Docker
# Desktop isn't intercepting it (CI runners, plain Docker on Linux). Docker
# Desktop auto-forwards the host ssh-agent at /run/host-services/ssh-auth.sock
# even though that path isn't physically present on the host; elsewhere the
# bind declared in devcontainer.json fails before the container starts.
# Placeholder makes the bind succeed; SSH forwarding won't be functional
# there but the container can start (CI smoke jobs don't sign commits).
docker_info="$(docker info 2>/dev/null || true)"
if ! printf '%s' "$docker_info" | grep -q "Docker Desktop"; then
  if [ ! -e /run/host-services/ssh-auth.sock ]; then
    sudo mkdir -p /run/host-services
    sudo touch /run/host-services/ssh-auth.sock
  fi
fi
