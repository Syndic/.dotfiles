#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$here/.." && pwd)"

# First: everything below runs git against the worktree, which resolves only once the
# base image's plumbing has bridged the common dir. See CLAUDE.md "Devcontainer host
# plumbing".
PLUMBING_WORKSPACE="$repo_root" \
  PLUMBING_DIR="$here/.git-plumbing" \
  PLUMBING_REQUIRE_GIT_CHECKOUT=1 \
  /usr/local/bin/devcontainer-plumbing post-create

# Provision dev/test venvs with uv, one per interpreter — full rationale in
# CLAUDE.md "Python 3.9 pin":
#   ~/.venv-runtime  frozen 3.9.6, pytest (runtime run), default python3 on PATH
#   ~/.venv-tooling  tooling_python: ansible-core, ansible-lint, yamllint,
#                    molecule (one venv so they share ansible-core and avoid
#                    duplicate-collection warnings #46/#48), pytest for the
#                    tooling run, and pre-commit
# PATH wiring lives in devcontainer.json's remoteEnv — keep both in step.

# Tracked with the molecule + lint CI jobs' python-version by renovate.json.
# renovate: datasource=python-version depName=python
tooling_python='3.14'

# All pip installs come from pinned requirements files (Renovate-managed).
# ansible-core, not `ansible` — the bundle's collections would be a second
# resolution root. See CLAUDE.md "Galaxy collections come from requirements
# files, not a bundle" and "Dependency updates".
setup_runtime_env() {
  uv venv --python 3.9.6 "$HOME/.venv-runtime"
  uv pip install --python "$HOME/.venv-runtime/bin/python" -r "$repo_root/test-requirements.txt"
}

setup_tooling_env() {
  uv venv --python "$tooling_python" "$HOME/.venv-tooling"
  uv pip install --python "$HOME/.venv-tooling/bin/python" \
    -r "$repo_root/lint-requirements.txt" \
    -r "$repo_root/molecule-requirements.txt" \
    -r "$repo_root/tooling-test-requirements.txt" \
    -r "$repo_root/pre-commit-requirements.txt"

  # Runtime collections (mirrors phase2.install_galaxy_requirements()) plus the
  # test-only ones molecule's docker driver needs.
  "$HOME/.venv-tooling/bin/ansible-galaxy" collection install -r "$repo_root/requirements.yml"
  "$HOME/.venv-tooling/bin/ansible-galaxy" collection install -r "$repo_root/requirements-dev.yml"
}

# set -e doesn't propagate from backgrounded jobs — capture PIDs, OR exit codes.
setup_runtime_env &
runtime_pid=$!
setup_tooling_env &
tooling_pid=$!

rc=0
wait "$runtime_pid" || rc=$?
wait "$tooling_pid" || rc=$?
[ "$rc" -eq 0 ] || exit "$rc"

# pre-commit refuses to `install` when core.hooksPath is set. Clear it when
# redundant (equals git's default); leave + warn otherwise (might be a custom
# hooks dir the user wants). Scope the unset to --worktree if available so
# global config is never touched.
hooks_path="$(git config --get core.hooksPath || true)"
if [ -n "$hooks_path" ]; then
  default_hooks_path="$(git rev-parse --path-format=absolute --git-common-dir)/hooks"

  # `-ef` (same-inode) not string-equality: the worktree-fix symlink layer
  # (initialize.sh + devcontainer-plumbing) makes the two paths name the same dir via a
  # symlink, so they compare unequal as text but resolve to the same inode.
  if [ "$hooks_path" -ef "$default_hooks_path" ]; then
    if [ "$(git config --get extensions.worktreeConfig || true)" = "true" ]; then
      git config --worktree --unset core.hooksPath
    else
      git config --unset core.hooksPath
    fi
    echo "post-create: unset redundant core.hooksPath (equalled git's default $default_hooks_path)" >&2
  else
    echo "post-create: core.hooksPath is set to a non-default path ($hooks_path) - leaving it alone" >&2
    echo "post-create: 'pre-commit install' may fail; clear it manually if that's not intended" >&2
  fi
fi

# Full path: postCreate may not see remoteEnv's PATH yet.
"$HOME/.venv-tooling/bin/pre-commit" install
