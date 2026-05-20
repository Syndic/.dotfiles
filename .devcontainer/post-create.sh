#!/usr/bin/env bash
set -euo pipefail

# pytest runs the Python suite (tests/python); pre-commit drives the
# source-guard hook in .pre-commit-config.yaml. These install into the default
# interpreter — the pinned 3.9.6, matching the macOS CLT Python phase2.py runs
# under — so `./tests/run`'s bare `pytest` resolves correctly. CI installs
# pytest the same way (pip); see .github/workflows/tests.yml.
pip install --no-warn-script-location pytest pre-commit
pre-commit install

# Ansible tooling for the redhat.ansible extension, installed into one isolated
# pipx venv. Modern ansible-core/ansible-lint require Python >= 3.10, so they
# run on the latest-Python `additionalVersion` from the python feature, not the
# frozen 3.9.6 default. The feature installs additionalVersions under
# /usr/local/python/<version>/ without exposing them on PATH, so resolve the
# interpreter by path — the lone version directory that isn't the 3.9.6 primary.
latest_python="$(find /usr/local/python -maxdepth 1 -type d -name '3.*' ! -name 3.9.6)"

# Install into the user's home: the python feature points PIPX_HOME at
# /usr/local/py-utils, which is root-owned and not writable by the remote user.
export PIPX_HOME="$HOME/.local/share/pipx"
export PIPX_BIN_DIR="$HOME/.local/bin"

# --include-deps exposes the ansible-core console scripts (ansible,
# ansible-playbook, ...) — the `ansible` package itself ships none. ansible-lint
# is injected into the same venv so it lints against the bundled collections.
pipx install --include-deps --python "$latest_python/bin/python3" ansible
pipx inject --include-apps ansible ansible-lint
pipx ensurepath
