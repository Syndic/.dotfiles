#!/usr/bin/env bash
set -euo pipefail

# pytest runs the Python suite (tests/python); pre-commit drives the
# source-guard hook in .pre-commit-config.yaml. CI installs pytest the same
# way (pip) — see .github/workflows/tests.yml. These land in the python
# feature's prefix, which is already on PATH, so `./tests/run` finds them.
pip install --no-warn-script-location pytest pre-commit

# Wire up the git hooks defined in .pre-commit-config.yaml.
pre-commit install
