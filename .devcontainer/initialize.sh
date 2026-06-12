#!/usr/bin/env bash
set -euo pipefail

# initializeCommand: discover host-side git common dir + IANA timezone and
# drop them in .git-plumbing/ for the Dockerfile to consume.
# Full rationale: CLAUDE.md "Worktree git resolution" + "Host timezone plumbing".

here="$(cd "$(dirname "$0")" && pwd)"
workspace="$(cd "$here/.." && pwd)"
link="$here/.host-git-common"
pathfile="$here/.git-plumbing/host-git-common-path"
tzfile="$here/.git-plumbing/host-timezone"
gitconfigfile="$here/.git-plumbing/host-gitconfig"

mkdir -p "$(dirname "$pathfile")"

cd "$workspace"

# Fail loud on missing git (see CLAUDE.md "Worktree git resolution").
# ln -sfn replaces any existing symlink in place rather than nesting.
common="$(git rev-parse --path-format=absolute --git-common-dir)"
ln -sfn "$common" "$link"
printf '%s\n' "$common" >"$pathfile"

# Discover host IANA zone; empty result → Dockerfile falls back to image default.
tz=""
if target="$(readlink /etc/localtime 2>/dev/null)"; then
  case "$target" in
    *zoneinfo/*) tz="${target##*zoneinfo/}" ;;
  esac
fi
if [ -z "$tz" ] && [ -r /etc/timezone ]; then
  tz="$(tr -d '[:space:]' </etc/timezone)"
fi
# Reject traversal / absolute paths so a hostile localtime symlink can't
# redirect the Dockerfile's /usr/share/zoneinfo/$tz construction.
case "$tz" in
  /* | *..*) tz="" ;;
esac
printf '%s\n' "$tz" >"$tzfile"

# Snapshot host ~/.gitconfig for post-start.sh to install when the Dev
# Containers extension hasn't already done so. Empty file if absent.
if [ -r "$HOME/.gitconfig" ]; then
  cp "$HOME/.gitconfig" "$gitconfigfile"
else
  : >"$gitconfigfile"
fi

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
