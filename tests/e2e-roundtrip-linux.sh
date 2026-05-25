#!/usr/bin/env bash
# End-to-end Linux round-trip test: install → uninstall → install → uninstall --all,
# inside a fresh Debian container, using THIS local checkout as the source
# repo. Catches regressions where uninstall.py / uninstall.yml drift out of
# sync with install.sh / phase2.py / site.yml.
#
# Shares Docker plumbing with tests/e2e-linux.sh via tests/lib/e2e-common.sh.
# Wired to .github/workflows/e2e-linux.yml as a workflow_dispatch-only job
# alongside the install-only e2e — both are too slow for push/pull_request.
#
# Requirements:
#   - A reachable Docker daemon (Docker Desktop or Colima on macOS works).
#
# Configuration via env vars:
#   E2E_IMAGE  base image (default: debian:stable)
#   E2E_HOST   host profile to install (default: devbox)
#
# Runtime: roughly 10-20 minutes on a fresh Debian — install dominates,
# and we run it twice. Plus a full --all teardown that includes the
# Homebrew uninstall.
#
# What it asserts is in tests/lib/e2e_assertions.py. The bash side here is
# the choreographer; the assertion logic lives in Python so it can re-use
# dotfiles_manager.find_stale_managed_symlinks for the managed-link manifest
# (the install code is the source of truth for what "managed" means).
#
# Scope:
#   - Linux (Debian) only. macOS round-trip is a separate problem.
#   - Round-trip property, not install-side correctness in isolation —
#     that's tests/e2e-linux.sh.
#   - Backup-restore is exercised via a synthetic fixture injected here,
#     not via whatever files happen to be in home_source/ today.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/e2e-common.sh
source "$REPO_ROOT/tests/lib/e2e-common.sh"

IMAGE="${E2E_IMAGE:-debian:stable}"
HOST_PROFILE="${E2E_HOST:-devbox}"

e2e_require_docker

ASSERTIONS_SRC="$REPO_ROOT/tests/lib/e2e_assertions.py"
if [[ ! -f "$ASSERTIONS_SRC" ]]; then
  echo "error: missing $ASSERTIONS_SRC" >&2
  exit 2
fi

PAYLOAD="$(mktemp)"
trap 'rm -f "$PAYLOAD"; [[ -n "$e2e_TMP_DIR" ]] && rm -rf "$e2e_TMP_DIR"' EXIT

# The payload runs as testuser inside the container, with the staged repo at
# /srv/source already committed, and DOTFILES_REPO + HOST_PROFILE exported.
cat > "$PAYLOAD" <<'PAYLOAD_EOF'
set -euo pipefail

ASSERT="python3 /srv/assertions.py"
MARKER_NAME=".dotfiles-e2e-marker"
MARKER_SRC="/srv/source/home_source/common/$MARKER_NAME"
MARKER_DST="$HOME/$MARKER_NAME"

phase() {
  echo
  echo "============================================================"
  echo "==> $*"
  echo "============================================================"
}

# Source Homebrew's shellenv so brew + brew-installed tools (ansible) land
# on PATH. install.sh + phase2.py have brew on PATH while they run, but our
# post-install payload is a fresh bash subshell that doesn't source
# .zprofile. Mirrors the prefix probe in home_source/common/.zprofile.
load_brew_shellenv() {
  local prefix
  for prefix in /home/linuxbrew/.linuxbrew "$HOME/.linuxbrew" /opt/homebrew /usr/local; do
    if [[ -x "$prefix/bin/brew" ]]; then
      eval "$("$prefix/bin/brew" shellenv)"
      return 0
    fi
  done
  return 0  # brew may legitimately be absent after --homebrew teardown
}

# ---------------------------------------------------------------------------
# Fixture injection.
#
# Inject a synthetic marker into the staged repo's home_source/common/ and
# pre-create a file at the matching $HOME path. This guarantees deterministic
# coverage of:
#   - install creating a managed symlink and backing up the pre-existing file
#   - uninstall removing the symlink and restoring the backup
#
# The fixture is committed to /srv/source's git history so that install.sh's
# `git clone $DOTFILES_REPO` picks it up (uncommitted working-tree changes
# are invisible to clone). It never touches the host repo.
# ---------------------------------------------------------------------------
phase "Injecting e2e fixture into staged repo + \$HOME"
mkdir -p /srv/source/home_source/common
echo "managed-by-dotfiles" > "$MARKER_SRC"
git -C /srv/source -c user.email=e2e@e2e -c user.name=e2e add "home_source/common/$MARKER_NAME"
git -C /srv/source -c user.email=e2e@e2e -c user.name=e2e commit -q -m "e2e fixture"

echo "user-original" > "$MARKER_DST"
echo "  staged fixture content at $MARKER_SRC"
echo "  pre-existing content at $MARKER_DST"

# ---------------------------------------------------------------------------
# Step 2: first install.
# ---------------------------------------------------------------------------
phase "Step 2: install.sh --host $HOST_PROFILE"
bash /srv/source/install.sh --host "$HOST_PROFILE"
load_brew_shellenv

$ASSERT group-a --host "$HOST_PROFILE" --marker-name "$MARKER_NAME"

# Save the post-install managed-link manifest for the idempotency check in
# group C. assertions.py writes it to /tmp/managed-links-A.txt as a side
# effect of group-a.

# ---------------------------------------------------------------------------
# Step 3: default uninstall.
#
# No --host on purpose: uninstall.py should read the profile from
# ~/.dotfiles/.installed-host written by phase2 in step 2. Default flags
# (symlinks-only); packages, brew, ansible stay.
# ---------------------------------------------------------------------------
phase "Step 3: uninstall.py --yes (no --host, default flags)"
LOG3=/tmp/uninstall-step3.log
python3 "$HOME/.dotfiles/uninstall.py" --yes 2>&1 | tee "$LOG3"

$ASSERT group-b --host "$HOST_PROFILE" --marker-name "$MARKER_NAME" --log "$LOG3"

# ---------------------------------------------------------------------------
# Step 5: re-install (idempotency).
#
# Should produce byte-identical managed-link manifest as step 2. Backup of
# the (now-restored) marker file should land at .backup-1 again.
# ---------------------------------------------------------------------------
phase "Step 5: install.sh --host $HOST_PROFILE (re-run)"
bash /srv/source/install.sh --host "$HOST_PROFILE"
load_brew_shellenv

$ASSERT group-c --host "$HOST_PROFILE" --marker-name "$MARKER_NAME"

# ---------------------------------------------------------------------------
# Step 6: full teardown.
#
# --all = --brew-packages --apt-packages --flatpak-packages --ansible
#         --homebrew --repo. --yes scripts past the prompt. Repo removal is
# print-only (uninstall.py prints `rm -rf ~/.dotfiles` rather than executing).
# ---------------------------------------------------------------------------
phase "Step 6: uninstall.py --host $HOST_PROFILE --all --yes"
# uninstall.py --all shells out to ansible-playbook (package removal) and
# brew (ansible teardown + the Homebrew uninstall script). Both live in
# Linuxbrew's bin, so they need shellenv loaded.
load_brew_shellenv
LOG6=/tmp/uninstall-step6.log
python3 "$HOME/.dotfiles/uninstall.py" --host "$HOST_PROFILE" --all --yes 2>&1 | tee "$LOG6"

$ASSERT group-d --host "$HOST_PROFILE" --marker-name "$MARKER_NAME" --log "$LOG6"

echo
echo "==> e2e-roundtrip-linux: PASS"
PAYLOAD_EOF

echo "==> Running install ↔ uninstall round-trip inside $IMAGE (host profile: $HOST_PROFILE) ..."
e2e_run_in_container \
  "$REPO_ROOT" "$IMAGE" "$HOST_PROFILE" "$PAYLOAD" \
  "$ASSERTIONS_SRC:/srv/assertions.py:ro"

echo "==> e2e-roundtrip-linux: PASS"
