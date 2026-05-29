FROM mcr.microsoft.com/devcontainers/base:debian

# bats-core for the bash test suite (tests/bash) — CI installs the same apt
# package, keep in sync with .github/workflows/tests.yml. pipx installs the
# Ansible tooling into isolated venvs (see post-create.sh).
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bats \
        pipx \
    && rm -rf /var/lib/apt/lists/*

# Make a git worktree's metadata resolve in-container at the SAME absolute path
# it has on the host. The worktree's .git file names <main-repo>/.git/... (a host
# path the CLI doesn't mount); .devcontainer/initialize.sh discovers that common
# dir on the host and persists it to .host-git-common-path (which lands in the
# build context). Here we recreate that exact host-absolute path inside the image
# as a symlink to /host-git-common — the static path devcontainer.json binds the
# real common dir to at runtime. Result: git reads the real .git file contents
# and follows the host-absolute pointer natively, with no GIT_* overrides.
#
# The .pat[h] glob makes the COPY a no-op when the file is absent (e.g. a plain
# `docker build` without the initializeCommand), and an empty file (non-git
# checkout) skips the symlink. Kept last so the apt layer above stays cached when
# the path — and thus this layer — changes between worktrees.
COPY .devcontainer/.host-git-common-pat[h] /tmp/host-git-common-path
RUN if [ -s /tmp/host-git-common-path ]; then \
        p="$(cat /tmp/host-git-common-path)"; \
        mkdir -p "$(dirname "$p")"; \
        ln -sfn /host-git-common "$p"; \
    fi; \
    rm -f /tmp/host-git-common-path
