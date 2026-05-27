# Brewfile layer for the `macos` group in the `os` group set.
# If a package is macOS-only, it goes here. Includes:
#   - macOS-only formulae (e.g. `depends_on :macos`)
#   - casks (cask is a macOS-only format)
#   - anything you only want installed on Macs
# Installed only on hosts that are members of the `macos` group (per
# inventory.yml).

# dockutil — required by the geerlingguy.mac.dock role (consumed by
# roles/macos_defaults when `macos_defaults_configure_dock: true` and
# either `dockitems_persist` or `dockitems_remove` is non-empty).
brew "dockutil"

cask "font-roboto-mono-nerd-font"
# Terminal emulator that uses platform-native UI and GPU acceleration
cask "ghostty"
