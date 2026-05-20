FROM mcr.microsoft.com/devcontainers/base:debian

# bats-core for the bash test suite (tests/bash) — CI installs the same apt
# package, keep in sync with .github/workflows/tests.yml. pipx installs the
# Ansible tooling into isolated venvs (see post-create.sh).
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bats \
        pipx \
    && rm -rf /var/lib/apt/lists/*
