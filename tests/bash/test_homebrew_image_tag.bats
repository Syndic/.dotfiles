#!/usr/bin/env bats
# roles/homebrew/molecule/image-tag.sh: the content-addressed tag CI pulls and
# the publish workflow pushes. See CLAUDE.md "Homebrew molecule scenarios".

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
SCRIPT="$REPO_ROOT/roles/homebrew/molecule/image-tag.sh"

setup() {
  WORK="$(mktemp -d)"
  cp "$SCRIPT" "$WORK/image-tag.sh"
}

teardown() {
  rm -rf "$WORK"
}

@test "tag is dockerfile- plus the first 12 hex of the Dockerfile's sha256" {
  run "$SCRIPT"
  [ "$status" -eq 0 ]
  expected="dockerfile-$(sha256sum "$REPO_ROOT/roles/homebrew/molecule/Dockerfile" | cut -c1-12)"
  [ "$output" = "$expected" ]
}

@test "tag changes when the Dockerfile does" {
  echo "FROM scratch" > "$WORK/Dockerfile"
  run "$WORK/image-tag.sh"
  first="$output"
  echo "LABEL x=y" >> "$WORK/Dockerfile"
  run "$WORK/image-tag.sh"
  [ "$status" -eq 0 ]
  [[ "$first" =~ ^dockerfile-[0-9a-f]{12}$ ]]
  [ "$output" != "$first" ]
}

@test "tag doesn't depend on the caller's working directory" {
  echo "FROM scratch" > "$WORK/Dockerfile"
  run "$WORK/image-tag.sh"
  from_elsewhere="$output"
  cd "$WORK"
  run ./image-tag.sh
  [ "$output" = "$from_elsewhere" ]
}
