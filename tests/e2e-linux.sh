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
#
# The companion harness tests/e2e-roundtrip-linux.sh runs install ↔
# uninstall ↔ install ↔ uninstall to catch regressions where the uninstall
# path falls out of sync with the install path. Both scripts share the
# Docker plumbing in tests/lib/e2e-common.sh.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/e2e-common.sh
source "$REPO_ROOT/tests/lib/e2e-common.sh"

IMAGE="${E2E_IMAGE:-debian:stable}"
HOST_PROFILE="${E2E_HOST:-devbox}"

e2e_require_docker

PAYLOAD="$(mktemp)"
trap 'rm -f "$PAYLOAD"; [[ -n "$e2e_TMP_DIR" ]] && rm -rf "$e2e_TMP_DIR"' EXIT

cat > "$PAYLOAD" <<'PAYLOAD_EOF'
set -euo pipefail
bash /srv/source/install.sh --host "$HOST_PROFILE"
PAYLOAD_EOF

echo "==> Running install.sh end-to-end inside $IMAGE (host profile: $HOST_PROFILE) ..."
e2e_run_in_container "$REPO_ROOT" "$IMAGE" "$HOST_PROFILE" "$PAYLOAD"
echo "==> e2e-linux: PASS"
