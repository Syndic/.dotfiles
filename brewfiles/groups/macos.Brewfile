# Brewfile layer for the `macos` group in the `os` group set.
# Installed only on hosts that are members of the `macos` group (per
# inventory.yml). Packages that exist on Linuxbrew but are macOS-only
# in spirit go in `brewfiles/common.Brewfile` if they self-skip on
# Linuxbrew (e.g. macOS-only formulae carrying `depends_on :macos`).
# This file is for tooling whose place is unambiguously macOS-only at
# the architecture level.

# dockutil — required by the geerlingguy.mac.dock role (consumed by
# roles/macos_defaults when `macos_defaults_configure_dock: true` and
# either `dockitems_persist` or `dockitems_remove` is non-empty).
brew "dockutil"
