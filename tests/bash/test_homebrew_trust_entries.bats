#!/usr/bin/env bats
# roles/homebrew/files/trust-brewfile-entries.sh against a stub `brew`.
# See CLAUDE.md "Third-party Brewfile entries are trusted by the role".

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
SCRIPT="$REPO_ROOT/roles/homebrew/files/trust-brewfile-entries.sh"

setup() {
  WORK="$(mktemp -d)"
  export BREW_LOG="$WORK/brew.log" TAPS_DIR="$WORK/taps" DEPS_DIR="$WORK/deps" TRUSTED="$WORK/trusted"
  mkdir -p "$WORK/bin" "$TAPS_DIR" "$DEPS_DIR"
  touch "$BREW_LOG" "$TRUSTED"
  # Records every call; `deps` answers from $DEPS_DIR/<name with / as _>.
  cat > "$WORK/bin/brew" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$BREW_LOG"
name="${*: -1}"
case "$1" in
  --repository) echo "$TAPS_DIR/$2" ;;
  tap) mkdir -p "$TAPS_DIR/$2" ;;
  trust)
    if grep -qxF "$name" "$TRUSTED"; then echo "Already trusted formula: $name"
    else echo "$name" >> "$TRUSTED"; echo "Trusted formula: $name"; fi ;;
  deps)
    [ "$name" = "$FAIL_DEPS_FOR" ] && exit 1
    f="$DEPS_DIR/$(echo "$name" | tr / _)"
    [ -f "$f" ] && cat "$f"
    true ;;
esac
EOF
  chmod +x "$WORK/bin/brew"
  PATH="$WORK/bin:$PATH"
}

teardown() {
  rm -rf "$WORK"
}

deps() { printf '%s\n' "${@:2}" > "$DEPS_DIR/$(echo "$1" | tr / _)"; }

@test "trusts qualified third-party entries by type, and nothing else" {
  mkdir -p "$TAPS_DIR/acme/tap"
  cat > "$WORK/Brewfile" <<'EOF'
tap "acme/tap"
brew "jq"
brew "acme/tap/tool"
# brew "acme/tap/commented"
cask "acme/tap/app", greedy: true
brew "homebrew/core/wget"
cask "firefox"
EOF
  run "$SCRIPT" "$WORK/Brewfile"
  [ "$status" -eq 0 ]
  [ "$(grep '^trust' "$BREW_LOG")" = "$(printf 'trust --formula acme/tap/tool\ntrust --cask acme/tap/app')" ]
  ! grep -q '^tap ' "$BREW_LOG"
}

@test "walks third-party dependencies across taps, skipping core ones" {
  mkdir -p "$TAPS_DIR/acme/tap"
  printf 'tap "acme/tap"\nbrew "acme/tap/meta"\ncask "acme/tap/app"\n' > "$WORK/Brewfile"
  deps acme/tap/meta kubectl acme/tap/cli other/tap/lib homebrew/core/curl
  deps acme/tap/cli acme/tap/meta
  deps acme/tap/app acme/tap/helper
  run "$SCRIPT" "$WORK/Brewfile"
  [ "$status" -eq 0 ]
  [ "$(grep '^trust' "$BREW_LOG")" = "$(printf '%s\n' \
    'trust --formula acme/tap/meta' 'trust --cask acme/tap/app' 'trust --formula acme/tap/cli' \
    'trust --formula other/tap/lib' 'trust acme/tap/helper')" ]
  grep -qx 'tap other/tap' "$BREW_LOG"
  grep -qx 'deps --direct --include-build --formula acme/tap/meta' "$BREW_LOG"
}

@test "taps a missing tap with the Brewfile's remote before trusting from it" {
  printf 'tap "acme/tap", "https://example.invalid/acme.git"\nbrew "acme/tap/tool"\n' > "$WORK/Brewfile"
  run "$SCRIPT" "$WORK/Brewfile"
  [ "$status" -eq 0 ]
  [ "$(grep -E '^(tap|trust) ' "$BREW_LOG")" = \
    "$(printf 'tap acme/tap https://example.invalid/acme.git\ntrust --formula acme/tap/tool')" ]
  [[ "$output" == *"Tapped acme/tap"* ]]
}

@test "a second run taps and trusts nothing new" {
  printf 'tap "acme/tap"\nbrew "acme/tap/tool"\n' > "$WORK/Brewfile"
  deps acme/tap/tool acme/tap/lib
  run "$SCRIPT" "$WORK/Brewfile"
  [[ "$output" == *"Trusted formula: acme/tap/lib"* ]]
  run "$SCRIPT" "$WORK/Brewfile"
  [ "$status" -eq 0 ]
  ! grep -qE '^(Tapped|Trusted) ' <<< "$output"
}

@test "a failing brew deps fails the script" {
  mkdir -p "$TAPS_DIR/acme/tap"
  printf 'brew "acme/tap/tool"\n' > "$WORK/Brewfile"
  FAIL_DEPS_FOR=acme/tap/tool run "$SCRIPT" "$WORK/Brewfile"
  [ "$status" -ne 0 ]
}

@test "a Brewfile with no third-party entries calls nothing but the parse" {
  printf 'brew "jq"\ncask "firefox"\ntap "homebrew/cask-fonts"\n' > "$WORK/Brewfile"
  run "$SCRIPT" "$WORK/Brewfile"
  [ "$status" -eq 0 ]
  [ ! -s "$BREW_LOG" ]
}

@test "a formula and a cask sharing a token are both trusted" {
  mkdir -p "$TAPS_DIR/acme/tap"
  printf 'brew "acme/tap/foo"\ncask "acme/tap/foo"\n' > "$WORK/Brewfile"
  run "$SCRIPT" "$WORK/Brewfile"
  [ "$status" -eq 0 ]
  [ "$(grep '^trust' "$BREW_LOG")" = "$(printf 'trust --formula acme/tap/foo\ntrust --cask acme/tap/foo')" ]
}

@test "each tap is looked up once per run" {
  mkdir -p "$TAPS_DIR/acme/tap"
  printf 'tap "acme/tap"\nbrew "acme/tap/a"\nbrew "acme/tap/b"\n' > "$WORK/Brewfile"
  deps acme/tap/a acme/tap/c
  run "$SCRIPT" "$WORK/Brewfile"
  [ "$status" -eq 0 ]
  [ "$(grep -c '^--repository acme/tap$' "$BREW_LOG")" -eq 1 ]
}
