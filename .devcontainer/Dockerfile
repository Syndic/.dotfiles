FROM mcr.microsoft.com/devcontainers/base:debian

# uv provides prebuilt CPython (python-build-standalone) plus fast venv/tool
# installs. It replaces the devcontainers `python` feature, which compiled both
# the frozen 3.9.6 and the tooling interpreter from source on every image build
# — the bulk of the old startup cost. post-create.sh drives uv to build the
# dev/test venvs. The pinned tag is bumped by Renovate's docker manager.
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /uvx /usr/local/bin/

# bats-core for the bash test suite (tests/bash) — CI installs the same apt
# package, keep in sync with .github/workflows/tests.yml. Everything Python
# (pytest, ansible, ansible-lint, molecule, pre-commit) is installed by
# post-create.sh via uv, not apt/pipx.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bats \
    && rm -rf /var/lib/apt/lists/*

# Make a git worktree's metadata resolve in-container at the SAME absolute path
# it has on the host. The worktree's .git file names <main-repo>/.git/... (a host
# path the CLI doesn't mount); .devcontainer/initialize.sh discovers that common
# dir on the host and persists it to .git-plumbing/host-git-common-path (which
# lands in the build context). Here we recreate that exact host-absolute path
# inside the image as a symlink to /host-git-common — the static path
# devcontainer.json binds the real common dir to at runtime. Result: git reads
# the real .git file contents and follows the host-absolute pointer natively,
# with no GIT_* overrides.
#
# COPY the *directory* (anchored by a tracked README) rather than the path file
# directly: buildx errors on a COPY whose source glob matches zero files, so the
# classic .pat[h] optional-COPY trick isn't portable. CI's `devcontainer build`
# never runs initializeCommand, so the path file is absent there; the shell
# `[ -s ... ]` test inside the RUN keeps that case a clean no-op. An empty path
# file (non-git checkout) is treated the same. Kept last so the apt layer above
# stays cached when the path — and thus this layer — changes between worktrees.
COPY .devcontainer/.git-plumbing/ /tmp/git-plumbing/
RUN if [ -s /tmp/git-plumbing/host-git-common-path ]; then \
        p="$(cat /tmp/git-plumbing/host-git-common-path)"; \
        mkdir -p "$(dirname "$p")"; \
        ln -sfn /host-git-common "$p"; \
    fi; \
    rm -rf /tmp/git-plumbing
