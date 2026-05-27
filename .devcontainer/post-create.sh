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
# ansible-playbook, ...) — the `ansible` package itself ships none. ansible-lint
# is injected into the same venv so it lints against the bundled collections.
pipx install --include-deps --python "$latest_python/bin/python3" ansible
pipx inject --include-apps ansible ansible-lint
pipx install --python "$latest_python/bin/python3" pre-commit

# molecule drives per-role Ansible scenarios under tests/run molecule (and the
# molecule CI job). It needs Python >= 3.10 — same constraint as ansible-core,
# so it rides the same pipx + latest-Python pattern. No --include-deps here:
# molecule's only console script *is* `molecule` itself, and exposing its
# ansible-core dependency's scripts (ansible, ansible-playbook, ...) would
# conflict with the `ansible` pipx install above (which owns those names on
# PATH on purpose, because that venv has the full ansible package with all
# bundled collections). The docker driver lives in the molecule-plugins[docker]
# extra and is injected next.
pipx install --python "$latest_python/bin/python3" molecule
pipx inject molecule 'molecule-plugins[docker]'
# community.docker's container modules (used by molecule's docker driver's
# create/destroy playbooks) need the `docker` and `requests` Python packages
# *in the venv whose ansible-playbook executes them*. That's the `ansible`
# pipx venv (its console scripts win on PATH), not molecule's. Inject there.
pipx inject ansible docker requests
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

# Dev-only Galaxy collections for molecule's docker driver. Kept *out* of
# requirements.yml because that file is the production dependency list
# (installed on every host by phase2.install_galaxy_requirements).
# community.docker + ansible.posix are only needed by molecule's
# create/destroy playbooks, which never run during a real install.
#
# Install via *molecule's* pipx ansible-galaxy, not the `ansible` venv's.
# The `ansible` pip package bundles these collections inside its own
# site-packages, so its ansible-galaxy considers the requirement
# already-satisfied and reports "Nothing to do" — leaving the install
# location empty. Molecule's venv has ansible-core only (no bundle),
# so its ansible-galaxy actually performs the install.
#
# Target path is a dedicated dir, not the default ~/.ansible/collections.
# That dir is on *both* venvs' default search paths, so installing there
# means the `ansible` venv sees the user copy alongside its bundled copy
# and emits a "Another version of X was found installed..." warning every
# time ansible-lint runs. Routing the install to ~/.config/molecule-collections
# instead — and pointing molecule at it via ANSIBLE_COLLECTIONS_PATH in
# each scenario's molecule.yml — keeps ansible-lint's view clean while
# still letting molecule find the collections at scenario time.
"$PIPX_HOME/venvs/molecule/bin/ansible-galaxy" collection install \
  -p "$HOME/.config/molecule-collections" \
  community.docker ansible.posix

# Wire up the git hooks defined in .pre-commit-config.yaml. pre-commit lives in
# PIPX_BIN_DIR, which is not necessarily on PATH yet, so call it by full path.
"$PIPX_BIN_DIR/pre-commit" install
