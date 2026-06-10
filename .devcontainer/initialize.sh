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
