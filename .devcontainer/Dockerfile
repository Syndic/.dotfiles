# `debian` is a floating tag — the digest is what makes the build reproducible.
FROM mcr.microsoft.com/devcontainers/base:debian@sha256:71b6fe7c4e07ec747a94a72b2a17f2f8c286eaa7b1c59862888df764efb8b6c6

# Pinned tag bumped by Renovate's docker manager. post-create.sh drives uv.
COPY --from=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 /uv /uvx /usr/local/bin/

# bats for tests/bash (keep in sync with tests.yml); ripgrep for interactive use.
# Everything Python lives in uv venvs (post-create.sh), not apt.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bats \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Worktree git resolution + host timezone — see CLAUDE.md "Worktree git
# resolution" and "Host timezone plumbing". COPY the directory (not the
# files directly) because buildx errors on zero-match globs; the tracked
# README anchors it. CI's `devcontainer build` skips initializeCommand,
# so the files are absent there — `[ -s ]` guards keep that a no-op.
# Kept last so the apt layer above stays cached across worktrees.
COPY .devcontainer/.git-plumbing/ /tmp/git-plumbing/
RUN if [ -s /tmp/git-plumbing/host-git-common-path ]; then \
        p="$(cat /tmp/git-plumbing/host-git-common-path)"; \
        mkdir -p "$(dirname "$p")"; \
        ln -sfn /host-git-common "$p"; \
    fi; \
    if [ -s /tmp/git-plumbing/host-timezone ]; then \
        tz="$(cat /tmp/git-plumbing/host-timezone)"; \
        if [ -e "/usr/share/zoneinfo/$tz" ]; then \
            ln -sfn "/usr/share/zoneinfo/$tz" /etc/localtime; \
            echo "$tz" > /etc/timezone; \
            echo "TZ=$tz" >> /etc/environment; \
        fi; \
    fi; \
    rm -rf /tmp/git-plumbing
