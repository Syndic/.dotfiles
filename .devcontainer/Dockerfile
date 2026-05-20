FROM mcr.microsoft.com/devcontainers/base:debian

# bats-core for the bash test suite (tests/bash). CI installs the same apt
# package — keep this in sync with .github/workflows/tests.yml.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bats \
    && rm -rf /var/lib/apt/lists/*
