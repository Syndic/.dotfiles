#!/usr/bin/env bats
# ---------------------------------------------------------------------------
# Black-box tests for install.sh.
#
# Strategy: build a tmpdir with stubs for every external binary install.sh
# touches (xcode-select, git, softwareupdate, python3), point HOME and
# PYTHON3 at it, and run install.sh end-to-end. We verify exit code, stdout
# and stderr content, and the args + stdin state that reached the python stub.
#
# Note on tty paths: the bats subprocess naturally has no controlling
# terminal, so install.sh's /dev/tty probe fails and the fallback exec runs.
# That's actually what we want to exercise here — the no-tty fallback is the
# harder-to-discover regression. The tty-success path (where /dev/tty opens
# and stdin is a real terminal) is covered indirectly by the Python prompt-
# loop tests, which simulate `isatty=True` and exercise input() end-to-end.
# ---------------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"

setup() {
  TEST_HOME="$(mktemp -d)"
  STUB_BIN="$TEST_HOME/bin"
  mkdir -p "$STUB_BIN"

  # Pre-create the dotfiles repo with a .git dir so install.sh skips git clone
  # and takes the "already cloned" branch (which runs `git pull`).
  mkdir -p "$TEST_HOME/.dotfiles/.git"

  # xcode-select: returns success so the CLT-install path is skipped.
  cat > "$STUB_BIN/xcode-select" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB

  # git: a no-op (we only care that install.sh calls it without erroring).
  cat > "$STUB_BIN/git" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB

  # softwareupdate: shouldn't get called since xcode-select returned success,
  # but stub it anyway so a regression doesn't reach the real binary.
  cat > "$STUB_BIN/softwareupdate" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB

  # Fake python3: writes the args and stdin tty status to a log file, exit 0.
  cat > "$STUB_BIN/fake_python3" <<STUB
#!/usr/bin/env bash
printf '%s\n' "\$@" > "$TEST_HOME/python_args.log"
if [[ -t 0 ]]; then
  echo "tty" > "$TEST_HOME/python_stdin.log"
else
  echo "pipe" > "$TEST_HOME/python_stdin.log"
fi
exit 0
STUB

  chmod +x "$STUB_BIN"/*

  export HOME="$TEST_HOME"
  export PATH="$STUB_BIN:$PATH"
  export PYTHON3="$STUB_BIN/fake_python3"
}

teardown() {
  rm -rf "$TEST_HOME"
}

# Helper: assert the args log contains a given line (one arg per line).
assert_arg_present() {
  local needle="$1"
  if ! grep -Fxq -- "$needle" "$TEST_HOME/python_args.log"; then
    echo "expected arg '$needle' in python_args.log:"
    cat "$TEST_HOME/python_args.log"
    return 1
  fi
}

# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------

@test "install.sh runs end-to-end with stubs and exits 0" {
  run bash "$REPO_ROOT/install.sh"
  [ "$status" -eq 0 ]
}

@test "install.sh announces the opening message" {
  run bash "$REPO_ROOT/install.sh"
  [[ "$output" == *"Joshua Yanchar's Dotfile Setup"* ]]
}

@test "install.sh reports CLT already installed when xcode-select returns 0" {
  run bash "$REPO_ROOT/install.sh"
  [[ "$output" == *"Xcode Command Line Tools already installed"* ]]
}

@test "install.sh reports repo already present (skips clone)" {
  run bash "$REPO_ROOT/install.sh"
  [[ "$output" == *"Dotfiles repo already present"* ]]
}

@test "install.sh announces phase 2 handoff" {
  run bash "$REPO_ROOT/install.sh"
  [[ "$output" == *"Running phase 2"* ]]
}

@test "install.sh actually invokes \$PYTHON3 with phase2.py" {
  run bash "$REPO_ROOT/install.sh"
  [ "$status" -eq 0 ]
  [ -f "$TEST_HOME/python_args.log" ]
  grep -q "phase2.py" "$TEST_HOME/python_args.log"
}

# ---------------------------------------------------------------------------
# Argument passthrough
# ---------------------------------------------------------------------------

@test "install.sh forwards --host PROFILE to python" {
  run bash "$REPO_ROOT/install.sh" --host laptop24
  [ "$status" -eq 0 ]
  assert_arg_present "--host"
  assert_arg_present "laptop24"
}

@test "install.sh forwards multiple args verbatim" {
  run bash "$REPO_ROOT/install.sh" --host m18 --extra value
  [ "$status" -eq 0 ]
  assert_arg_present "--host"
  assert_arg_present "m18"
  assert_arg_present "--extra"
  assert_arg_present "value"
}

@test "install.sh forwards arg containing spaces as a single arg" {
  run bash "$REPO_ROOT/install.sh" --host "two words"
  [ "$status" -eq 0 ]
  assert_arg_present "two words"
}

@test "install.sh works with no args (python receives just the script path)" {
  run bash "$REPO_ROOT/install.sh"
  [ "$status" -eq 0 ]
  # Only one arg should be in the log: the phase2.py path
  [ "$(wc -l < "$TEST_HOME/python_args.log" | tr -d ' ')" -eq 1 ]
}

# ---------------------------------------------------------------------------
# /dev/tty probe-and-fallback
#
# These tests run install.sh in a context with NO controlling terminal,
# forcing the /dev/tty probe to fail and the fallback exec to run. The
# `no_tty` helper (Python os.setsid + exec) guarantees that regardless of
# whether the bats runner inherited a tty (true in a real terminal, false
# in CI / agent subprocesses).
#
# We don't assert on python's stdin tty-status because os.setsid() detaches
# the controlling terminal but doesn't change inherited fds — so `[[ -t 0 ]]`
# inside python can still be true on the fallback path. Instead we verify
# observable behavior: exit code, args reaching python, no error leaks.
# Without a working probe-and-fallback, install.sh would die with a redirect
# failure under set -euo pipefail.
# ---------------------------------------------------------------------------

NO_TTY="$BATS_TEST_DIRNAME/helpers/no_tty"

@test "install.sh exits cleanly when /dev/tty isn't openable" {
  run "$NO_TTY" bash "$REPO_ROOT/install.sh" --host x
  [ "$status" -eq 0 ]
  # Fallback path must have actually run — python stub records its invocation.
  [ -f "$TEST_HOME/python_args.log" ]
}

@test "no-tty fallback does not leak 'Device not configured' to output" {
  run "$NO_TTY" bash "$REPO_ROOT/install.sh" --host x
  [[ "$output" != *"Device not configured"* ]]
  [[ "$output" != *"/dev/tty"* ]]
}

@test "no-tty fallback still forwards args to python" {
  run "$NO_TTY" bash "$REPO_ROOT/install.sh" --host laptop24
  [ "$status" -eq 0 ]
  assert_arg_present "--host"
  assert_arg_present "laptop24"
}

# ---------------------------------------------------------------------------
# Helpers — observed via real script output
# ---------------------------------------------------------------------------

@test "info messages use blue background ANSI escape" {
  run bash "$REPO_ROOT/install.sh"
  [[ "$output" == *$'\e[1;37;44m info \e[0m'* ]]
}

@test "announce messages use yellow background ANSI escape" {
  run bash "$REPO_ROOT/install.sh"
  [[ "$output" == *$'\e[1;37;43m'* ]]
}

# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------

@test "install.sh exits non-zero with a die() message when git pull fails" {
  cat > "$STUB_BIN/git" <<'STUB'
#!/usr/bin/env bash
exit 1
STUB
  chmod +x "$STUB_BIN/git"

  run bash "$REPO_ROOT/install.sh"
  [ "$status" -ne 0 ]
  [[ "$output" == *"git pull failed"* ]]
}

@test "die() output uses red background ANSI escape on stderr" {
  cat > "$STUB_BIN/git" <<'STUB'
#!/usr/bin/env bash
exit 1
STUB
  chmod +x "$STUB_BIN/git"

  run bash "$REPO_ROOT/install.sh"
  [[ "$output" == *$'\e[1;37;101m error \e[0m'* ]]
}
