#!/usr/bin/env bash
set -euo pipefail

# pytest runs the Python suite (tests/python) under the default interpreter —
# the pinned 3.9.6 — so `./tests/run`'s bare `pytest` resolves correctly. CI
# installs pytest the same way (pip); see .github/workflows/tests.yml.
# pytest-cov backs the VS Code Testing panel's "Run with Coverage". The 3.9.6
# source build bundles a 2021-era pip, so upgrade it first to a current release.
pip install --no-warn-script-location --upgrade pip
pip install --no-warn-script-location pytest pytest-cov

# Dev tooling installed into pipx venvs on the latest Python (the python
# feature's `additionalVersion`). Modern ansible-core/ansible-lint require
# Python >= 3.10; pre-commit is just a hook runner — the source-guard hook
# in .pre-commit-config.yaml shells out to the default `python3` regardless
# of pre-commit's own interpreter. The feature installs additionalVersions
# under /usr/local/python/<version>/ without exposing them on PATH, so
# resolve the interpreter by path — the lone version directory that isn't
# the 3.9.6 primary.
latest_python="$(find /usr/local/python -maxdepth 1 -type d -name '3.*' ! -name 3.9.6)"

# Install into the user's home: the python feature points PIPX_HOME at
# /usr/local/py-utils, which is root-owned and not writable by the remote user.
export PIPX_HOME="$HOME/.local/share/pipx"
export PIPX_BIN_DIR="$HOME/.local/bin"

# --include-deps exposes the ansible-core console scripts (ansible,
# ansible-playbook, ...) — the `ansible` package itself ships none.
pipx install --include-deps --python "$latest_python/bin/python3" ansible

# Everything else that drives Ansible — ansible-lint and molecule — is
# *injected into the same venv* rather than installed standalone. The win:
# they share the one ansible-core and the one set of bundled collections
# that the `ansible` package ships (community.docker, ansible.posix,
# community.general, ... ~100 of them). That's what molecule's docker
# driver needs, so there's nothing extra to `ansible-galaxy install` and
# no second venv whose separate collection copies would shadow-conflict
# with the bundled ones (which is what produced the duplicate-version
# warnings when molecule lived in its own venv).
#
# --include-apps surfaces each injected package's own console scripts
# (`ansible-lint`, `molecule`); their deps' scripts are not exposed, so
# there's no fight over the `ansible-*` names the base install already owns.
# molecule-plugins[docker] provides the docker driver; docker + requests
# are the Python libs community.docker's container modules import.
pipx inject --include-apps ansible \
  ansible-lint molecule 'molecule-plugins[docker]' docker requests

pipx install --python "$latest_python/bin/python3" pre-commit
# We were getting a warning about the relevant paths already being on PATH, so we don't need to call
# `pipx ensurepath` here. If we did, it would be:
# pipx ensurepath

# Install the Galaxy collections declared in requirements.yml so
# `ansible-playbook --syntax-check site.yml` resolves third-party roles
# (e.g. geerlingguy.mac.dock, used by the macos_defaults role) at parse
# time without a separate one-off step. Mirrors what
# `phase2.install_galaxy_requirements()` does on a real host install,
# but scoped to the devcontainer's pipx-installed ansible. Idempotent —
# `ansible-galaxy collection install` is a no-op when everything's
# already at the requested version.
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
"$PIPX_BIN_DIR/ansible-galaxy" collection install -r "$repo_root/requirements.yml"

# No separate install for molecule's docker-driver collections
# (community.docker, ansible.posix): they ship bundled inside the `ansible`
# pip package, and molecule shares that venv (see the inject above), so it
# finds them with nothing extra to install.

# Wire up the git hooks defined in .pre-commit-config.yaml. pre-commit lives in
# PIPX_BIN_DIR, which is not necessarily on PATH yet, so call it by full path.
"$PIPX_BIN_DIR/pre-commit" install
