#!/usr/bin/env bash
set -euo pipefail

# devcontainer.json `initializeCommand` — runs ON THE HOST, before the container
# is created/started, on every `devcontainer up`. Its job: make the repo's git
# metadata reachable inside the container at a STATIC, predictable location, for
# ANY checkout layout (full clone, the main worktree, or a linked worktree living
# anywhere on disk).
#
# Why this exists. When the `devcontainer` CLI opens a git *worktree*, the
# worktree's `.git` is a FILE reading `gitdir: <main-repo>/.git/worktrees/<name>`
# — a host-absolute path outside the workspace. That path isn't mounted, so every
# in-container git command fails. (VS Code's Dev Containers extension special-
# cases this; the CLI does not.) The fix has to discover the real git dir at
# launch time and feed it to the container.
#
# The constraint that shapes the mechanism: devcontainer.json's `mounts`,
# `runArgs`, and `build.args` are resolved at config-parse time and can only
# interpolate `${localEnv:VAR}` / `${localWorkspaceFolder}` — NOT anything an
# initializeCommand computes (a child process can't set the CLI's env). So we
# can't hand a freshly-discovered absolute path straight to a mount. Instead we
# turn the dynamic path into a STATIC one the config can name unconditionally:
#
#   1. Drop a symlink at a fixed, workspace-relative path
#      (.devcontainer/.host-git-common) pointing at the real common dir. Docker
#      follows the symlink host-side when it binds it, so the mount SOURCE is
#      always "${localWorkspaceFolder}/.devcontainer/.host-git-common" (static)
#      while the TARGET on disk is wherever the main repo actually is.
#   2. Bind that symlink to a fixed container path (/host-git-common) in
#      devcontainer.json's `mounts`.
#   3. Because the mount TARGET (/host-git-common) won't match the absolute path
#      baked into the worktree's `.git` file, point git at it explicitly via
#      GIT_COMMON_DIR / GIT_DIR / GIT_WORK_TREE, written here to a gitignored
#      env file that devcontainer.json feeds to the container with
#      `runArgs: ["--env-file", ...]`. With those set, git ignores the `.git`
#      file's stale absolute pointer entirely.
#
# Both artifacts are gitignored and regenerated on every `up`, so nothing the
# host tracks is touched and the values can never go stale. No system-wide env
# var is involved, and the scheme works for several worktrees concurrently:
# each worktree carries its own symlink/env file, and each container binds its
# own /host-git-common, so there is no cross-container collision.

here="$(cd "$(dirname "$0")" && pwd)"        # the .devcontainer dir (host abs)
workspace="$(cd "$here/.." && pwd)"          # repo/worktree root (host abs)
link="$here/.host-git-common"
envfile="$here/.git.env"

cd "$workspace"

if common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; then
  gitdir="$(git rev-parse --path-format=absolute --git-dir)"
  # For a linked worktree, gitdir is "<common>/worktrees/<name>" — capture the
  # "/worktrees/<name>" tail so we can rebuild it under the static mount target.
  # For a full clone or the main worktree, gitdir == common and the tail is "".
  suffix="${gitdir#"$common"}"

  # ln -sfn: replace any existing symlink in place (don't nest a new link inside
  # an old one) so re-runs after the main repo moves point at the new location.
  ln -sfn "$common" "$link"

  # GIT_WORK_TREE is the workspace path AS SEEN IN THE CONTAINER. devcontainer.json
  # mounts the workspace at its real host path (workspaceFolder/workspaceMount =
  # ${localWorkspaceFolder}), so the container path equals this host path.
  {
    printf 'GIT_COMMON_DIR=%s\n' "/host-git-common"
    printf 'GIT_DIR=%s\n' "/host-git-common${suffix}"
    printf 'GIT_WORK_TREE=%s\n' "$workspace"
  } >"$envfile"
else
  # Not a git checkout (shouldn't happen for this repo, but stay safe): make the
  # mount source a real-but-empty dir so Docker doesn't auto-create a stray path,
  # and leave the env file empty so git falls back to normal discovery (which
  # then no-ops, and post-create.sh's guarded `pre-commit install` skips).
  rm -rf "$link"
  mkdir -p "$link"
  : >"$envfile"
fi
