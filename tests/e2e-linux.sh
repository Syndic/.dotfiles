#!/usr/bin/env bash
# End-to-end Linux test: runs install.sh → phase2.py → Ansible playbook
# inside a fresh Debian container, using THIS local checkout as the source
# repo. The CI workflow at .github/workflows/e2e-linux.yml is a thin wrapper
# that just invokes this script.
#
# Requirements:
#   - A reachable Docker daemon (Docker Desktop or Colima on macOS works).
#
# Configuration via env vars:
#   E2E_IMAGE  base image (default: debian:stable)
#   E2E_HOST   host profile to install (default: devbox)
#
# This test is intentionally slow — it does a real Homebrew (Linuxbrew)
# install, a real `brew install ansible`, and a real playbook run. Expect
# several minutes on first invocation.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${E2E_IMAGE:-debian:stable}"
HOST_PROFILE="${E2E_HOST:-devbox}"

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker not found in PATH. Install Docker Desktop / Colima first." >&2
  exit 2
fi

if ! docker info >/dev/null 2>&1; then
  echo "error: docker daemon not reachable. Start Docker Desktop / Colima first." >&2
  exit 2
fi

# Snapshot the local checkout as a tarball; the container re-inits it as a
# git repo so install.sh can clone from it without any network access.
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
TARBALL="$TMP_DIR/dotfiles.tar"
tar --exclude='./.git' --exclude='./.claude' -cf "$TARBALL" -C "$REPO_ROOT" .

echo "==> Running install.sh end-to-end inside $IMAGE (host profile: $HOST_PROFILE) ..."

docker run --rm \
  -v "$TARBALL:/srv/dotfiles.tar:ro" \
  -e HOST_PROFILE="$HOST_PROFILE" \
  "$IMAGE" \
  bash -euo pipefail -c '
    # Phase 0 (test harness, not install.sh): bring up enough tooling to
    # stage a local "remote" and create the non-root sudo user. install.sh
    # does its own apt install for its real prerequisites.
    apt-get update >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      sudo tar git ca-certificates >/dev/null

    # Linuxbrew refuses to run as root, so install.sh + phase2.py execute as
    # a non-root user with passwordless sudo.
    useradd -m -s /bin/bash testuser
    echo "testuser ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/testuser
    chmod 0440 /etc/sudoers.d/testuser

    # Stage the local checkout as a local git "remote" at /srv/source so
    # install.sh can DOTFILES_REPO-clone from it offline.
    mkdir -p /srv/source
    tar -xf /srv/dotfiles.tar -C /srv/source
    cd /srv/source
    git init -q -b main
    git -c user.email=e2e@e2e -c user.name=e2e add -A
    git -c user.email=e2e@e2e -c user.name=e2e commit -q -m "e2e snapshot"
    chown -R testuser /srv/source

    # Run install.sh as testuser. DOTFILES_REPO points at the local source.
    su - testuser -c "DOTFILES_REPO=/srv/source bash /srv/source/install.sh --host $HOST_PROFILE"
  '

echo "==> e2e-linux: PASS"
