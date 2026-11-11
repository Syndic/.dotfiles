#!/usr/bin/env bats
# .devcontainer/initialize.sh's host-side decisions. See CLAUDE.md "Devcontainer host plumbing".

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"

setup() {
  # shellcheck source=/dev/null
  . "$REPO_ROOT/.devcontainer/initialize.sh"
  set +euo pipefail  # the script's own options would leak into bats
  WORK="$(mktemp -d)"
}

teardown() {
  rm -rf "$WORK"
}

@test "zone comes from a zoneinfo symlink target" {
  [ "$(initialize_zone_from_link /var/db/timezone/zoneinfo/America/Los_Angeles)" = "America/Los_Angeles" ]
  [ "$(initialize_zone_from_link /usr/share/zoneinfo/Etc/UTC)" = "Etc/UTC" ]
}

@test "zone is empty for a non-zoneinfo target" {
  [ -z "$(initialize_zone_from_link /etc/somewhere-else)" ]
}

@test "absolute and traversing zones are rejected" {
  [ -z "$(initialize_sanitize_tz /etc/passwd)" ]
  [ -z "$(initialize_sanitize_tz ../../etc/passwd)" ]
  [ "$(initialize_sanitize_tz Europe/Berlin)" = "Europe/Berlin" ]
}

@test "known_hosts takes the first entry of the ssh -G list" {
  [ "$(initialize_first_abs_path '/home/u/.ssh/known_hosts /home/u/.ssh/known_hosts2')" = "/home/u/.ssh/known_hosts" ]
}

@test "a non-absolute or empty known_hosts answer is empty, so the caller falls back" {
  [ -z "$(initialize_first_abs_path '~/.ssh/known_hosts /etc/x')" ]
  [ -z "$(initialize_first_abs_path '')" ]
  [ -z "$(initialize_first_abs_path)" ]
}

@test "allowed_signers links the configured file when it is readable" {
  : >"$WORK/signers"
  [ "$(initialize_signers_target "$WORK/signers" "$WORK/fallback")" = "$WORK/signers" ]
}

@test "allowed_signers falls back when unset or missing" {
  [ "$(initialize_signers_target "" "$WORK/fallback")" = "$WORK/fallback" ]
  [ "$(initialize_signers_target "$WORK/absent" "$WORK/fallback")" = "$WORK/fallback" ]
}
