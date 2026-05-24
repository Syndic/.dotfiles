
# Bring Homebrew into PATH and set HOMEBREW_*. Probe the known install
# prefixes in order so the same file works on macOS (Apple Silicon, then
# Intel) and Linuxbrew (multi-user, then single-user under $HOME).
for __brew in \
  /opt/homebrew/bin/brew \
  /usr/local/bin/brew \
  /home/linuxbrew/.linuxbrew/bin/brew \
  "$HOME/.linuxbrew/bin/brew"; do
  if [[ -x $__brew ]]; then
    eval "$("$__brew" shellenv)"
    break
  fi
done
unset __brew
