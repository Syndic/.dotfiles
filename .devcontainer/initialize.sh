#!/usr/bin/env bash
set -euo pipefail

# initializeCommand — runs on the host before the container exists, on every `up`.
# Presents host state in the shape the base image's plumbing consumes: reads into
# .git-plumbing/, host-discovered paths as `.host-*` symlinks devcontainer.json binds.
# See CLAUDE.md "Devcontainer host plumbing".
#
# The `initialize_*` decisions are functions so tests/bash can source this file.

# /etc/localtime's symlink target -> IANA zone name, or empty if it isn't a zoneinfo link.
initialize_zone_from_link() {
  case "$1" in
    *zoneinfo/*) printf '%s' "${1##*zoneinfo/}" ;;
    *) printf '' ;;
  esac
}

# Reject traversal / absolute paths: the container builds /usr/share/zoneinfo/$tz from this.
initialize_sanitize_tz() {
  case "$1" in
    /* | *..*) printf '' ;;
    *) printf '%s' "$1" ;;
  esac
}

# First path of an `ssh -G` list value (the one ssh appends to), or empty unless absolute:
# a literal `~` would dangle the bind with a Docker error nowhere near the cause.
initialize_first_abs_path() {
  local first=""
  read -r first _ <<<"${1:-}" || true
  case "$first" in
    /*) printf '%s' "$first" ;;
    *) printf '' ;;
  esac
}

# The configured allowed-signers file if readable, else our empty fallback, so the bind
# can't dangle.
initialize_signers_target() {
  if [ -n "$1" ] && [ -r "$1" ]; then
    printf '%s' "$1"
  else
    printf '%s' "$2"
  fi
}

# Sourcing (the tests) stops here.
[ "${BASH_SOURCE[0]}" = "${0}" ] || return 0

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
  tz="$(initialize_zone_from_link "$target")"
fi
if [ -z "$tz" ] && [ -r /etc/timezone ]; then
  tz="$(tr -d '[:space:]' </etc/timezone)"
fi
printf '%s\n' "$(initialize_sanitize_tz "$tz")" >"$tzfile"

# Snapshot host ~/.gitconfig for the base image to install at postStart when the Dev
# Containers extension hasn't already done so. Empty file if absent.
if [ -r "$HOME/.gitconfig" ]; then
  cp "$HOME/.gitconfig" "$gitconfigfile"
else
  : >"$gitconfigfile"
fi

# known_hosts: link the file ssh appends to, so a host accepted in-container lands on
# the host.
khfile="$(initialize_first_abs_path \
  "$(ssh -G github.com 2>/dev/null | sed -n 's/^userknownhostsfile //p')")"
[ -n "$khfile" ] || khfile="$HOME/.ssh/known_hosts"
# Tighten the directory only if we create it; an existing one keeps the user's mode.
khdir="$(dirname "$khfile")"
if [ ! -d "$khdir" ]; then
  mkdir -p "$khdir"
  chmod 700 "$khdir"
fi
# The bind needs a real target; an empty one is what ssh would create on first use.
: >>"$khfile"
ln -sfn "$khfile" "$khlink"

# allowed_signers: link whatever gpg.ssh.allowedSignersFile names.
signers="$(git config --type=path --get gpg.ssh.allowedSignersFile 2>/dev/null || true)"
signers_target="$(initialize_signers_target "$signers" "$signersfallback")"
[ "$signers_target" != "$signersfallback" ] || : >>"$signersfallback"
ln -sfn "$signers_target" "$signerslink"

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
