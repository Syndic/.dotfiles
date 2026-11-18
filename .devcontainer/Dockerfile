# Shared base image carrying the container-side host plumbing — see CLAUDE.md
# "Devcontainer host plumbing". Tag for Renovate to compare against, digest for the
# reproducible pull.
FROM ghcr.io/syndic/unnatural_designs-devcontainer-base:latest@sha256:2e7d2f810614a8e1111fe1a9279c9d6601e6e636d317b4e0534c04a3050108c9

# Pinned tag bumped by Renovate's docker manager. post-create.sh drives uv.
COPY --from=ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d /uv /uvx /usr/local/bin/

# bats for tests/bash (keep in sync with tests.yml); ripgrep for interactive use.
# Everything Python lives in uv venvs (post-create.sh), not apt.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bats \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*
