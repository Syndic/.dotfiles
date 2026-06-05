#!/usr/bin/env bash
set -euo pipefail

# Provision the dev/test environment with uv. uv installs prebuilt CPython
# (python-build-standalone) and creates venvs in seconds — replacing the
# devcontainers `python` feature, which compiled both interpreters from source
# on every image build. uv itself is baked into the image (see Dockerfile).
#
# Three independent environments, built in parallel:
#
#   ~/.venv          The frozen 3.9.6, mirroring the macOS CLT interpreter
#                    phase2.py runs under (see CLAUDE.md "Python 3.9 pin"). Holds
#                    pytest/pytest-cov for tests/python + the VS Code Testing
#                    panel, and is the default `python3` on PATH. The 3.9.6 here
#                    is FROZEN — it must match the CLT patch, so don't bump it.
#
#   ~/.venv-ansible  The Ansible dev stack — ansible, ansible-lint, yamllint,
#                    molecule, the docker driver — on the tooling Python. One
#                    venv so ansible-lint and molecule share the single
#                    ansible-core and its ~100 bundled collections; a second
#                    collection copy is what produced the duplicate-version
#                    warnings (#46/#48). yamllint rides the same venv (it's a
#                    dependency of ansible-lint anyway) so `./tests/run lint`
#                    finds both on one PATH. A plain venv rather than `uv tool`
#                    because only a venv exposes every package's entry points
#                    (ansible-playbook, ansible-galaxy, ansible-lint, molecule,
#                    yamllint) — `uv tool` exposes the primary package's scripts
#                    only.
#
#   pre-commit       Its own uv-managed tool venv (isolated hook runner).
#
# The PATH wiring that makes these resolve as bare commands lives in
# devcontainer.json (remoteEnv). Keep the two in step.

# The tooling Python. Tracks the molecule + lint CI jobs' python-version in
# .github/workflows/tests.yml; all kept in step by the customManager in
# renovate.json so local dev and CI agree on the interpreter.
# renovate: datasource=python-version depName=python
tooling_python='3.14'

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

setup_test_env() {
  uv venv --python 3.9.6 "$HOME/.venv"
  uv pip install --python "$HOME/.venv/bin/python" pytest pytest-cov
}

setup_ansible_env() {
  uv venv --python "$tooling_python" "$HOME/.venv-ansible"
  uv pip install --python "$HOME/.venv-ansible/bin/python" \
    ansible ansible-lint yamllint molecule 'molecule-plugins[docker]' docker requests

  # Galaxy collections declared in requirements.yml (geerlingguy.mac.dock for
  # the macos_defaults role, etc.) so `ansible-playbook --syntax-check site.yml`
  # resolves them at parse time. Mirrors phase2.install_galaxy_requirements().
  "$HOME/.venv-ansible/bin/ansible-galaxy" collection install -r "$repo_root/requirements.yml"

  # molecule's docker driver needs community.docker (+ its dep ansible.posix).
  # Both ship bundled in the `ansible` package above, so this is normally a
  # no-op ("Nothing to do" — no second copy written to ~/.ansible/collections,
  # which is exactly what would resurrect the duplicate-version warnings). We
  # state it anyway so the dependency survives a future `ansible` bundle trim.
  # No version pin / --upgrade on purpose — those could force a redundant write.
  "$HOME/.venv-ansible/bin/ansible-galaxy" collection install community.docker ansible.posix
}

setup_precommit() {
  uv tool install --python "$tooling_python" pre-commit
}

# Run the three groups concurrently. set -e doesn't propagate failures from
# backgrounded jobs, so capture each PID and wait on it explicitly, OR-ing the
# exit codes so any failure fails the script.
setup_test_env &
test_pid=$!
setup_ansible_env &
ansible_pid=$!
setup_precommit &
precommit_pid=$!

rc=0
wait "$test_pid"      || rc=$?
wait "$ansible_pid"   || rc=$?
wait "$precommit_pid" || rc=$?
[ "$rc" -eq 0 ] || exit "$rc"

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

  # Use bash's `-ef` (same-inode) test rather than string equality: in worktree
  # devcontainers the host-absolute path in `config.worktree` (e.g.
  # /Users/jjyanchar/.dotfiles/.git/hooks) is symlinked to /host-git-common/hooks
  # by the Dockerfile + the bind mount from initialize.sh, so the two strings
  # name the SAME directory through a symlink but compare unequal as text. `-ef`
  # resolves both and tests inode equality, so the redundant case is recognized
  # whether or not the worktree-fix symlink layer is in play.
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

# Wire up the git hooks defined in .pre-commit-config.yaml. pre-commit is on
# PATH via remoteEnv (~/.local/bin), but that PATH may not be in effect during
# postCreate, so call it by full path. The source-guard hook shells out to the
# default `python3` (now ~/.venv's 3.9.6) regardless of pre-commit's own venv.
"$HOME/.local/bin/pre-commit" install
