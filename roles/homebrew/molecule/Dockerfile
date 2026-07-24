# Shared base image for every roles/homebrew/molecule/* scenario.
#
# Built either locally by `./tests/run molecule` or pulled from ghcr (see
# .github/workflows/publish-molecule-images.yml), then tagged as
# `dotfiles-homebrew-molecule:local`. Each scenario references that local
# tag with `pre_build_image: true`. The molecule scenarios then exec into
# a container that already has Linuxbrew installed — a fresh `brew install`
# script run costs ~5min and would dominate every scenario's setup
# otherwise.
#
# Edits to this file rebuild locally on the next `tests/run molecule` and
# trigger the publish-molecule-images workflow on merge to main (which
# re-publishes the `:latest` tag CI pulls).
#
# Why not extend geerlingguy/docker-debian12-ansible: the homebrew role
# doesn't need systemd / init / privileged mode (no `become:`, no service
# management), so a smaller debian:slim base is enough. ansible's docker
# connection just needs python3 in the container.
#
# Why a `linuxbrew` user: brew refuses to install or run as root on Linux.
# Scenarios connect ansible as this user via `ansible_user: linuxbrew` in
# each molecule.yml. No sudo: the homebrew role has no `become:` and the
# converges never escalate.
# Digest-pinned: `bookworm-slim` floats as Debian ships point releases.
FROM debian:bookworm-slim@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        file \
        git \
        procps \
        python3 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash linuxbrew

USER linuxbrew
WORKDIR /home/linuxbrew

RUN /bin/bash -c "NONINTERACTIVE=1 $(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Pre-install the formula the `gates` scenario starts with already-satisfied.
# Kept here (not in the scenario's converge) so the scenario container starts
# in the satisfied state — that's what exercises the `brew bundle check`
# short-circuit added in ae021b2.
RUN eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)" \
    && brew install hello

# Make brew discoverable from non-login shells (ansible.builtin.command uses
# direct exec, no shell rc loading). HOMEBREW_PREFIX / _CELLAR / _REPOSITORY
# don't need explicit ENV — brew computes them from its own binary location.
ENV PATH="/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin:${PATH}"
