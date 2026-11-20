# Dotfiles

Bootstraps a macOS or Debian/Ubuntu machine and keeps its packages, settings and dotfiles in line with this repo.

## Language

**Baseline environment**:
What a freshly set-up supported machine provides before the bootstrap installs anything: macOS with the Xcode Command Line Tools (whose `python3` is 3.9), or Debian/Ubuntu with phase 1's apt prerequisites. Bootstrap and uninstall code that runs before a current Python is installed is limited to what it offers.
_Avoid_: runtime
