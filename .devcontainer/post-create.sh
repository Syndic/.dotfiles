#!/usr/bin/env bash
set -euo pipefail

# pytest runs the Python suite (tests/python) under the default interpreter —
# the pinned 3.9.6, matching the macOS CLT Python phase2.py runs under — so the
# suite exercises the code on the interpreter a real bootstrap uses, and
# `./tests/run`'s bare `pytest` resolves correctly. CI installs pytest the same
# way (pip); see .github/workflows/tests.yml. The 3.9.6 source build bundles a
# 2021-era pip, so upgrade it first to a current release.
pip install --no-warn-script-location --upgrade pip
pip install --no-warn-script-location pytest

# Dev tooling that need not match the 3.9.6 runtime, installed into pipx venvs
# on the latest Python (the python feature's `additionalVersion`). Modern
# ansible-core/ansible-lint require Python >= 3.10; pre-commit is just a hook
# runner — the source-guard hook in .pre-commit-config.yaml shells out to the
# default `python3` regardless of pre-commit's own interpreter. The feature
# installs additionalVersions under /usr/local/python/<version>/ without
# exposing them on PATH, so resolve the interpreter by path — the lone version
# directory that isn't the 3.9.6 primary.
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
pipx install --python "$latest_python/bin/python3" pre-commit
pipx ensurepath

# Wire up the git hooks defined in .pre-commit-config.yaml. pre-commit lives in
# PIPX_BIN_DIR, which is not necessarily on PATH yet, so call it by full path.
"$PIPX_BIN_DIR/pre-commit" install
