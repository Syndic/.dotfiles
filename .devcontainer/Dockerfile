# `debian` is a floating tag — the digest is what makes the build reproducible.
FROM mcr.microsoft.com/devcontainers/base:debian@sha256:1f851004adcd3dff3776b4a1da86727cf52280b0fdc9d5b0568c9c7d74274286

# Pinned tag bumped by Renovate's docker manager. post-create.sh drives uv.
COPY --from=ghcr.io/astral-sh/uv:0.12.13@sha256:b485bd65cc2cf1c9a93b3554012c9c3778cf7b1b5fd3d3096ce9e1226c97e1e6 /uv /uvx /usr/local/bin/

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
