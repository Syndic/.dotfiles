#!/usr/bin/env bash
# Prints the registry tag for the image this directory's Dockerfile builds.
# See CLAUDE.md "Homebrew molecule scenarios" for who publishes and pulls it.
set -euo pipefail
cd "$(dirname "$0")"
echo "dockerfile-$(sha256sum Dockerfile | cut -c1-12)"
