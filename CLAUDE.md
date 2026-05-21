# Project Instructions

Joshua Yanchar's macOS dotfiles. Installed by

```
curl -fsSL https://install.yanch.ar | bash -s -- --host PROFILE
```

`install.yanch.ar` is a Cloudflare redirect to `install.sh` on `main`. The
script installs Xcode Command Line Tools, clones this repo to `~/.dotfiles`,
and hands off to `phase2.py`. Phase 2 installs Homebrew, installs Ansible,
selects (or accepts) a host profile, and runs the Ansible playbook. **Ansible
does the actual work** — package installs, macOS defaults, dotfile symlinks,
certs, SSH config, etc. The bash + Python layers are just bootstrap.

## The two-language split is intentional

`install.sh` (bash) and `phase2.py` (Python) are two phases of the same
bootstrap. The split is load-bearing; don't try to consolidate.

- **Bash exists because of timing.** Phase 1 runs from `curl | bash` with no
  repo on disk and possibly no usable Python. On a brand-new macOS machine,
  `/usr/bin/python3` exists but is a stub that pops a graphical CLT installer
  dialog if invoked. Bash is the only language guaranteed to work before CLT
  is installed.
- **Python takes over the moment the repo is on disk.** After CLT is installed
  and the repo is cloned, `install.sh` execs into `/usr/bin/python3 phase2.py`.

Concrete consequences:

- `install.sh` must stay self-contained — it can't `source` repo files because
  the repo isn't there for most of its execution.
- `install.sh`'s only responsibilities are: ensure CLT, clone/pull repo, exec
  Python. Resist adding anything else there.
- `phase2.py` is glue between bash and Ansible. **Most behavior belongs in
  Ansible roles, not phase 2.** Cert install, dotfile symlinks, package
  installs, macOS defaults — all are Ansible-native. Phase 2 should stay thin.

## Python 3.9 pin

Phase 2 runs under the macOS system Python from Xcode CLT — currently 3.9.6.
The pin is enforced in three places: the runtime (`/usr/bin/python3` in
install.sh), CI (`python-version: '3.9'` in `.github/workflows/tests.yml`),
and the devcontainer (the `python` feature's `version`, pinned to the exact
CLT patch `3.9.6`, in `.devcontainer/devcontainer.json`). Keep all three in
step.

The devcontainer *also* installs the latest Python via that feature's
`additionalVersions` — but that one is not part of the pin. It exists solely
for the Ansible tooling (`ansible`, `ansible-lint`), which `post-create.sh`
installs into isolated pipx venvs because modern ansible-core/ansible-lint
require Python >= 3.10. Renovate keeps that latest pin current while leaving
`3.9.6` frozen; the wiring is in `renovate.json` (a disabled `devcontainer`
manager rule for the frozen pin, plus a `customManager` for the latest one).

`from __future__ import annotations` is at the top of `phase2.py`, so type
hints can use 3.10+ syntax (`X | None`, etc.) — they're evaluated lazily.
**Runtime code must remain 3.9-compatible.** No `match` statements, no
parenthesized context managers, no `Self` imports, no `ExceptionGroup`. The
failure mode is "fresh-Mac bootstrap dies at parse time, after CLT install" —
the worst possible UX moment.

The pin is also load-bearing as an architectural constraint. Modern Python
features are tempting; their absence helps keep phase 2 small and shell-out-
heavy, which is what it should be. If you genuinely need newer Python (e.g.
a third-party library that Ansible can't reasonably replace), the right move
is splitting phase 2 into a "minimal bootstrap" portion that installs a
Homebrew Python and a "real work" portion that re-execs under that newer
Python — *not* relaxing the 3.9 pin in place.

## The /dev/tty probe-and-fallback

The tail of `install.sh` is:

```bash
if (exec < /dev/tty) 2>/dev/null; then
  exec "$PYTHON3" "${DOTFILES_DIR}/phase2.py" "$@" < /dev/tty
else
  exec "$PYTHON3" "${DOTFILES_DIR}/phase2.py" "$@"
fi
```

This pattern is subtle. Each piece is there for a reason:

- **The probe.** Under `curl | bash`, bash's stdin is the script-delivery
  pipe, not the user's keyboard. We attach Python's stdin to the controlling
  terminal (`/dev/tty`) so interactive prompts work. But `/dev/tty` isn't
  always openable (cron, `ssh -T`, launchd). `[[ -r /dev/tty ]]` is unreliable
  because the file *exists* in /dev but `open()` fails. The subshell
  `(exec < /dev/tty)` is a real probe: success iff the redirect would work.
- **`2>/dev/null` is on the probe, not the real exec.** Wrapping the success-
  path exec in `{ ... } 2>/dev/null` looks equivalent but isn't — the redirect
  survives into the exec'd Python process and silently swallows its prompts
  (Python's `input()` writes prompts via libedit on macOS, which goes to
  stderr). This bug ate a debugging session before we figured it out.
- **The fallback.** When `/dev/tty` isn't openable, exec without the redirect.
  Python then sees `sys.stdin.isatty() == False` and either uses `--host`
  non-interactively or dies with "no terminal available - pass --host
  PROFILE" — never silently EOFs.

Don't simplify without understanding all three pieces. The bats suite covers
the no-tty fallback; the success path (real tty + redirect) isn't covered
because portable PTY simulation in bats is awkward.

## Tests

Required for behavior changes. Both bats (bash) and pytest (Python).

```sh
brew bundle --file=tests/Brewfile   # one-time: installs bats-core + pytest
./tests/run                          # full suite
./tests/run python                   # pytest only
./tests/run bash                     # bats only
```

CI runs both suites on Ubuntu. Linux is fine because nothing tested is macOS-
specific (we deliberately don't test the xcode-select / softwareupdate paths).

**Out-of-scope for tests** — change these with extra care since there's no
automated check:

- `xcode-select` and `softwareupdate` paths in `install.sh`
- Subprocess-heavy functions in `phase2.py`: `setup_homebrew`,
  `setup_ansible`, `run_playbook`, `brew_shellenv`
- The tty *success* path of `install.sh` (only the no-tty fallback is tested)

## CI

PR-only: triggers on `pull_request` to `main` and `push` to `main`. Pushes to
feature branches don't run CI by design — the gate is "must pass before merge
to main." If a feature branch shows no CI run, that's expected, not broken.

## Conventions

- Output helpers exist in both bash (`announce`, `info`, `die`) and Python
  (`announce`, `centered_announce`, `info`, `warn`, `die`) with parallel ANSI
  styling. Keep them consistent — a user shouldn't be able to tell which
  language printed a line.
- `host_vars/<name>.yml` and `brewfiles/hosts/<name>.Brewfile` are the
  per-host pivots. Adding a new host means a file in each, plus assigning the
  host to either the `personal` or `work` inventory group.
- The universal Brewfile layer lives at `brewfiles/common.Brewfile`.
- Group Brewfile layers live in `brewfiles/groups/`.
- `tests/Brewfile` is dev-only (bats, pytest). Don't conflate it with
  `brewfiles/` — the latter is what Ansible installs on hosts at runtime.
- The `home_source/` tree (`common/` plus `hosts/<name>/` overlays) holds the
  files symlinked into `$HOME`. It must contain **only plain files and
  directories** — no symlinks (they'd be linked as a symlink-to-symlink chain
  and break managed-link detection) and no nested `.dotfiles` directories.
  Both are enforced by `dotfiles_manager.py check` (the `dotfiles-source-guard`
  pre-commit hook) and again at runtime in `build_source_manifest`.
- The `PYTHON3` env var in `install.sh` exists so the bats suite can
  substitute a stub. Default (`/usr/bin/python3`) is unchanged for users.
