# Shared base image for every roles/homebrew/molecule/* scenario, tagged
# `dotfiles-homebrew-molecule:local`. How it's built, published, and pulled:
# CLAUDE.md "Homebrew molecule scenarios".
#
# Why a `linuxbrew` user: brew refuses to install or run as root on Linux.
# Scenarios connect ansible as this user via `ansible_user: linuxbrew` in
# each molecule.yml. No sudo: the homebrew role has no `become:` and the
# converges never escalate.
#
# trixie, not bookworm: brew adds its own glibc + gcc to every formula when
# the host's glibc is older than its CI baseline (2.39); bookworm has 2.36.
# Digest-pinned: `trixie-slim` floats as Debian ships point releases.
FROM debian:trixie-slim@sha256:f6b08b09a05725f9431502d3b5714f5c4576e82c1a84fa1debe0c24a7e0c3ec4

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
# short-circuit added in ae021b2. Downloaded bottles are dead weight in the
# image; the cache's api/ stays so scenarios don't re-fetch the formula index.
RUN eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)" \
    && brew install hello \
    && rm -rf "$(brew --cache)"/downloads "$(brew --cache)"/*.tar.gz

# Make brew discoverable from non-login shells (ansible.builtin.command uses
# direct exec, no shell rc loading). HOMEBREW_PREFIX / _CELLAR / _REPOSITORY
# don't need explicit ENV — brew computes them from its own binary location.
ENV PATH="/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin:${PATH}"
