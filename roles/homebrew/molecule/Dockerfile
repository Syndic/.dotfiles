# Shared base image for every roles/homebrew/molecule/* scenario.
#
# Built locally by `./tests/run molecule` and tagged
# `dotfiles-homebrew-molecule:local`; each scenario references that tag with
# `pre_build_image: true`. The molecule scenarios then exec into a container
# that already has Linuxbrew installed — a fresh `brew install` script run
# costs ~5min and would dominate every scenario's setup otherwise.
#
# Followup: bake-and-publish this image to ghcr (see PR description) so CI
# pulls instead of rebuilds. The local `docker build` here exists in part to
# define the contract that ghcr image will satisfy.
#
# Why not extend geerlingguy/docker-debian12-ansible: the homebrew role
# doesn't need systemd / init / privileged mode (no `become:`, no service
# management), so a smaller debian:slim base is enough. ansible's docker
# connection just needs python3 in the container.
#
# Why a `linuxbrew` user: brew refuses to install or run as root on Linux.
# Scenarios connect ansible as this user via `ansible_user: linuxbrew` in
# each molecule.yml.
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        file \
        git \
        procps \
        python3 \
        sudo \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash linuxbrew \
    && echo 'linuxbrew ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/linuxbrew

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
# direct exec, no shell rc loading).
ENV PATH="/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin:${PATH}"
ENV HOMEBREW_PREFIX="/home/linuxbrew/.linuxbrew"
ENV HOMEBREW_CELLAR="/home/linuxbrew/.linuxbrew/Cellar"
ENV HOMEBREW_REPOSITORY="/home/linuxbrew/.linuxbrew/Homebrew"
