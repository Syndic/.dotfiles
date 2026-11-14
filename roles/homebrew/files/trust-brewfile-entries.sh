#!/usr/bin/env bash
# Trust a Brewfile's third-party formulae and casks, plus their third-party
# dependencies, before `brew bundle` loads them. One Brewfile per call.
# See CLAUDE.md "Third-party Brewfile entries are trusted by the role".
# Runs on macOS's bash 3.2: no mapfile or ${x,,}.
set -euo pipefail

brewfile="$1"
tap_re='^[[:space:]]*tap[[:space:]]+"([^"]+)"([[:space:]]*,[[:space:]]*"([^"]+)")?'
entry_re='^[[:space:]]*(brew|cask)[[:space:]]+"([^"/]+/[^"/]+/[^"]+)"'
qualified_re='^[^/[:space:]]+/[^/[:space:]]+/[^/[:space:]]+$'

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
tap_of() { printf '%s' "$1" | cut -d/ -f1-2; }
official() { case "$(lower "$1")" in homebrew/*) return 0 ;; *) return 1 ;; esac; }
# Membership in a newline-delimited set (bash 3.2 has no associative arrays).
in_set() { case "$1" in *$'\n'"$2"$'\n'*) return 0 ;; *) return 1 ;; esac; }

# `brew trust` and `brew deps` both need the tap on disk.
taps_checked=$'\n'
ensure_tapped() {
  local tap="$1" url="${2:-}" key
  key="$(lower "$tap")"
  official "$tap" && return 0
  in_set "$taps_checked" "$key" && return 0
  taps_checked="$taps_checked$key"$'\n'
  [ -d "$(brew --repository "$tap")" ] && return 0
  if [ -n "$url" ]; then
    brew tap "$tap" "$url" >&2
  else
    brew tap "$tap" >&2
  fi
  echo "Tapped $tap"
}

# Taps first, with any custom remote the Brewfile names.
queue=()
while IFS= read -r line || [ -n "$line" ]; do
  if [[ $line =~ $tap_re ]]; then
    ensure_tapped "${BASH_REMATCH[1]}" "${BASH_REMATCH[3]}"
  elif [[ $line =~ $entry_re ]]; then
    kind="${BASH_REMATCH[1]/brew/formula}"
    official "${BASH_REMATCH[2]}" || queue+=("$kind ${BASH_REMATCH[2]}")
  fi
done < "$brewfile"

# Walk third-party dependencies; trust is per item and doesn't cover them.
seen=$'\n'
i=0
while [ "$i" -lt "${#queue[@]}" ]; do
  kind="${queue[$i]%% *}"
  name="${queue[$i]#* }"
  i=$((i + 1))
  # Keyed by kind too: a formula and a cask can share a token in one tap.
  key="$kind $(lower "$name")"
  in_set "$seen" "$key" && continue
  seen="$seen$key"$'\n'

  ensure_tapped "$(tap_of "$name")"
  flag=()
  [ "$kind" = any ] || flag=("--$kind")
  brew trust ${flag[@]+"${flag[@]}"} "$name"

  # A cask's dependencies can be formulae or casks; let brew resolve which.
  dep_kind=formula
  [ "$kind" = formula ] || dep_kind=any
  # No --full-name: it loads each dependency, which an untrusted one refuses.
  deps="$(brew deps --direct --include-build ${flag[@]+"${flag[@]}"} "$name")"
  while IFS= read -r dep; do
    [[ $dep =~ $qualified_re ]] || continue
    official "$dep" || queue+=("$dep_kind $dep")
  done <<< "$deps"
done
