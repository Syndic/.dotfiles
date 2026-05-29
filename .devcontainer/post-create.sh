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

# Everything else that drives Ansible — ansible-lint, yamllint, molecule — is
# *injected into the same venv* rather than installed standalone. The win:
# they share the one ansible-core and the one set of bundled collections
# that the `ansible` package ships (community.docker, ansible.posix,
# community.general, ... ~100 of them). One venv means no second copy of a
# collection to shadow-conflict with the bundled one — which is what
# produced the duplicate-version warnings back when molecule lived in its
# own venv and we had to install its collections separately. ansible-lint in
# particular resolves playbook imports against those bundled collections, so
# it has to live alongside ansible; yamllint rides the same venv for symmetry
# (so `./tests/run lint` finds both on one PATH).
#
# Three injects, split by how their console scripts (if any) get exposed:
#   - ansible-lint and molecule ship apps (`ansible-lint`, `molecule`).
#     --include-apps surfaces them; their deps' scripts are not exposed, so
#     there's no fight over the `ansible-*` names the base install already owns.
#   - yamllint ALSO ships an app (`yamllint`) and would seem to belong on the
#     line above — but yamllint is a *dependency* of ansible-lint. When named
#     alongside ansible-lint in one inject, pipx pulls it in transitively and
#     classifies it as a dep, so --include-apps silently skips its console
#     script (the app never lands in PIPX_BIN_DIR and `yamllint` / `./tests/run
#     lint` aren't on PATH). Injecting it on its own with --force makes pipx
#     treat it as a top-level package and symlink the app. --force is required
#     precisely because ansible-lint already satisfied the requirement: a plain
#     re-inject reports "already injected" and exposes nothing.
#   - molecule-plugins[docker] (the docker driver) and docker + requests (the
#     Python libs community.docker's container modules import) are libraries
#     with no console scripts. pipx errors under --include-apps when asked to
#     expose apps for an app-less package, so inject these without the flag.
pipx inject --include-apps ansible ansible-lint molecule
pipx inject --include-apps --force ansible yamllint
pipx inject ansible 'molecule-plugins[docker]' docker requests

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

# molecule's docker driver needs community.docker (and its dep ansible.posix).
# These ship bundled in the `ansible` package, which molecule shares (see the
# inject above), so this is normally a no-op — `ansible-galaxy` finds the
# bundled copy satisfying the requirement and reports "Nothing to do" without
# writing a second copy to ~/.ansible/collections (a second copy is exactly
# what would resurrect the duplicate-version warnings). We install explicitly
# anyway so the dependency is *stated*, not assumed: if a future `ansible`
# release trims these out of its bundle, this line fetches them instead of the
# scenarios silently breaking. No version pin / --upgrade on purpose — those
# could force a write even when the bundled copy is fine.
"$PIPX_BIN_DIR/ansible-galaxy" collection install community.docker ansible.posix

# Wire up the git hooks defined in .pre-commit-config.yaml. pre-commit lives in
# PIPX_BIN_DIR, which is not necessarily on PATH yet, so call it by full path.
#
# Guarded on git actually resolving the repo. In a git *worktree*, `.git` is a
# file pointing at `<main-repo>/.git/worktrees/<name>` — a host absolute path.
# The devcontainer mounts only the worktree folder, so that path doesn't exist
# in-container and every git command fails ("not a git repository: ..."). The
# VS Code Dev Containers extension special-cases worktrees and mounts the main
# git dir; the `devcontainer` CLI (which is what spins this container up here)
# does not. pre-commit can't install — or run — without a resolvable git dir,
# so skip rather than abort post-create: a broken last step would mark the
# whole container build as failed over a convenience hook. The checks are still
# enforced in CI on every PR, and run locally via `./tests/run lint` (which
# invokes yamllint + ansible-lint directly, no git needed). Where git *does*
# resolve (full clone, or VS Code's worktree handling) this runs as before.
if git rev-parse --git-dir >/dev/null 2>&1; then
  # pre-commit refuses to `install` when core.hooksPath is set — it can't own a
  # hooks dir it doesn't control. We've observed core.hooksPath set on this repo
  # to the very path git would use by default ($(git_common_dir)/hooks), making
  # it a redundant no-op that only serves to block the install. Defensively
  # clear it, but *only* when it's redundant: if it points somewhere else it was
  # set deliberately (a custom hooks dir), so leave it and warn rather than
  # silently clobbering intent. The unset is scoped with --worktree when the
  # repo has per-worktree config enabled (extensions.worktreeConfig), else it
  # falls back to the standard --local; either way it never touches global config.
  hooks_path="$(git config --get core.hooksPath || true)"
  if [ -n "$hooks_path" ]; then
    default_hooks_path="$(git rev-parse --path-format=absolute --git-common-dir)/hooks"
    if [ "$hooks_path" = "$default_hooks_path" ]; then
      if [ "$(git config --get extensions.worktreeConfig || true)" = "true" ]; then
        git config --worktree --unset core.hooksPath
      else
        git config --unset core.hooksPath
      fi
      echo "post-create: unset redundant core.hooksPath (equalled git's default $default_hooks_path)" >&2
    else
      echo "post-create: core.hooksPath is set to a non-default path ($hooks_path) — leaving it alone" >&2
      echo "post-create: 'pre-commit install' may fail; clear it manually if that's not intended" >&2
    fi
  fi
  "$PIPX_BIN_DIR/pre-commit" install
else
  echo "post-create: skipping 'pre-commit install' — git dir not reachable in-container" >&2
  echo "post-create: (this is a worktree whose .git points to an unmounted host path)" >&2
  echo "post-create: lint locally with './tests/run lint'; hooks still gate every PR in CI" >&2
fi
