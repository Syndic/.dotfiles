# Shared base image carrying the container-side host plumbing — see CLAUDE.md
# "Devcontainer host plumbing". Tag for Renovate to compare against, digest for the
# reproducible pull.
FROM ghcr.io/syndic/unnatural_designs-devcontainer-base:latest@sha256:f1e35b7958c1fe48720181456209a01bb43d188ea73f6ee4647b613f758b1dbc

# Pinned tag bumped by Renovate's docker manager. post-create.sh drives uv.
COPY --from=ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f /uv /uvx /usr/local/bin/

# bats for tests/bash (keep in sync with tests.yml); ripgrep for interactive use.
# Everything Python lives in uv venvs (post-create.sh), not apt.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bats \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*
