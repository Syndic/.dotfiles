# Shared base image carrying the container-side host plumbing — see CLAUDE.md
# "Devcontainer host plumbing". Tag for Renovate to compare against, digest for the
# reproducible pull.
FROM ghcr.io/syndic/unnatural_designs-devcontainer-base:latest@sha256:565888d5556d6d0d54a8864361adbfb8561937b47422d9bef5c1b00525e907e1

# Pinned tag bumped by Renovate's docker manager. post-create.sh drives uv.
COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /uvx /usr/local/bin/

# bats for tests/bash (keep in sync with tests.yml); ripgrep for interactive use.
# Everything Python lives in uv venvs (post-create.sh), not apt.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bats \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*
