#!/usr/bin/env bash
set -euo pipefail

# Re-apply host facts on every container start, plus the base image's signing bridge,
# which runs at this verb only. See CLAUDE.md "Devcontainer host plumbing".
here="$(cd "$(dirname "$0")" && pwd)"
PLUMBING_WORKSPACE="$(cd "$here/.." && pwd)" \
  PLUMBING_DIR="$here/.git-plumbing" \
  PLUMBING_REQUIRE_GIT_CHECKOUT=1 \
  /usr/local/bin/devcontainer-plumbing post-start
