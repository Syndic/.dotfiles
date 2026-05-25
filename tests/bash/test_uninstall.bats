#!/usr/bin/env bats
# ---------------------------------------------------------------------------
# Black-box tests for uninstall.py.
#
# These are intentionally shallow: the heavy lifting (symlink detection,
# backup restore, confirmation gate, action planning) is covered in
# tests/python/test_uninstall.py. Bats covers the things you can only
# observe through the binary: --help shape, exit codes, no-tty inertness.
# ---------------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"

setup() {
  TEST_HOME="$(mktemp -d)"
  # Pretend the repo lives under $TEST_HOME so the script's DOTFILES_DIR
  # ($HOME/.dotfiles) points at a real checkout. Symlink the real repo in.
  ln -s "$REPO_ROOT" "$TEST_HOME/.dotfiles"
  export HOME="$TEST_HOME"
}

teardown() {
  rm -rf "$TEST_HOME"
}

@test "--help exits 0 and lists every flag" {
  run python3 "$REPO_ROOT/uninstall.py" --help
  [ "$status" -eq 0 ]
  for flag in --brew-packages --apt-packages --flatpak-packages \
              --ansible --homebrew --repo --all --skip-symlinks --yes; do
    [[ "$output" == *"$flag"* ]] || {
      echo "missing $flag in help output" >&2
      false
    }
  done
}

@test "no tty + no --yes is inert (exit 0, plan printed, no actions)" {
  # Drop a fake managed symlink into the test home and confirm uninstall
  # does NOT remove it.
  mkdir -p "$TEST_HOME/.dotfiles/home_source"
  printf "managed-target\n" > "$TEST_HOME/.dotfiles/home_source/_bats_fixture"
  ln -s "$TEST_HOME/.dotfiles/home_source/_bats_fixture" "$TEST_HOME/.bats_fixture_link"

  # Redirect stdin from /dev/null so the subprocess always sees a non-tty
  # stdin. Without this, when bats runs in pretty mode (from a real
  # terminal), `run` inherits bats's controlling tty — sys.stdin.isatty()
  # inside uninstall.py returns True, the no-tty branch never fires, and
  # the script blocks on input("Proceed? [y/N]: ") instead of printing the
  # "Re-run with --yes" message this test is checking for.
  run python3 "$REPO_ROOT/uninstall.py" --host fake < /dev/null
  [ "$status" -eq 0 ]
  [[ "$output" == *"Uninstall plan"* ]]
  [[ "$output" == *"Re-run with --yes"* ]]
  # The link must still exist — confirm() returned False, no action taken.
  [ -L "$TEST_HOME/.bats_fixture_link" ]

  # Cleanup the fixture file we dropped into the source repo.
  rm -f "$TEST_HOME/.dotfiles/home_source/_bats_fixture"
  rm -f "$TEST_HOME/.bats_fixture_link"
}
