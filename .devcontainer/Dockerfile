# `debian` is a floating tag — the digest is what makes the build reproducible.
FROM mcr.microsoft.com/devcontainers/base:debian@sha256:6ee2b4097c75d33e9a94d941577a3286e5d629434fba384688b06daeeaaeac99

# Pinned tag bumped by Renovate's docker manager. post-create.sh drives uv.
COPY --from=ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 /uv /uvx /usr/local/bin/

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
