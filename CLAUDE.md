# Project Instructions

Joshua Yanchar's dotfiles. Supports macOS and Debian/Ubuntu Linux.

The shape: a two-phase bootstrap (`install.sh` → `phase2.py`) hands off to an
Ansible playbook that does the actual work — package installs (brew, apt,
flatpak), macOS defaults, dotfile symlinks, certs, SSH config. The bash +
Python layers are just bootstrap; most behavior belongs in Ansible roles.

The inverse is `uninstall.py` + the companion `uninstall.yml` playbook —
see "Uninstall" below.

Phase 1 (`install.sh`) detects the OS and installs phase-2 prereqs (Xcode
Command Line Tools on macOS; `git`, `python3`, `curl`, `ca-certificates`,
and Homebrew's Linux build deps `build-essential procps file` on
Debian/Ubuntu), clones the repo to `~/.dotfiles`, and execs `phase2.py`.
Phase 2 installs Homebrew (Linuxbrew on Linux), installs Ansible via brew,
picks a host profile, and runs the playbook.

See [README.md](README.md) for the user-facing install command and project
overview.

## The two-language split is intentional

`install.sh` (bash) and `phase2.py` (Python) are two phases of the same
bootstrap. The split is load-bearing; don't try to consolidate.

- **Bash exists because of timing.** Phase 1 runs from `curl | bash` with no
  repo on disk and possibly no usable Python. On a brand-new macOS machine,
  `/usr/bin/python3` exists but is a stub that pops a graphical CLT installer
  dialog if invoked. On a fresh Debian/Ubuntu container, `python3` may not
  be installed at all until phase 1 has apt-installed it. Either way, bash
  is the only language guaranteed before phase 1 finishes.
- **Python takes over the moment the repo is on disk.** After prereqs are
  installed and the repo is cloned, `install.sh` execs into
  `/usr/bin/python3 phase2.py`.

Concrete consequences:

- `install.sh` must stay self-contained — it can't `source` repo files because
  the repo isn't there for most of its execution.
- `install.sh`'s only responsibilities are: install platform-specific phase-2
  prereqs (CLT on macOS / apt packages on Linux), clone/pull repo, exec
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

## Sudo / become on Linux

Linux installs need sudo twice: once in `install.sh` for `apt-get install
<phase-2 prereqs>`, then later in Ansible for the `apt` role's `become: true`.
The flow is structured so the user gets **at most one password prompt**, the
password never sits in any parent-process env (where Homebrew, brew, git,
etc. would inherit it), and nothing depends on sudo's timestamp cache
staying warm across the Homebrew install.

1. **`install.sh`, Linux branch.** Picks one of four paths up front:
   - `id -u == 0` → no sudo needed.
   - `SUDO_PASSWORD` already set in env (test harness, automation) → validate
     it.
   - `sudo -n true` succeeds → passwordless sudo is configured, no prompt.
   - Otherwise → real `/dev/tty` open probe, then one `read -rs`, validated
     with `sudo -S -k true`.

   All privileged `apt-get` calls then go through a small `sudo_apt` wrapper
   that knows which form to use (`apt-get` directly / `sudo apt-get` /
   `sudo -S apt-get` with the password piped in). If a password was captured,
   install.sh exports `SUDO_PASSWORD` to phase 2's env.

2. **`phase2.py`.** First thing in `main()` is
   `os.environ.pop("SUDO_PASSWORD", None)`. The value is held in a local
   variable and **never put back into `os.environ`** — that's what stops it
   from leaking into the Homebrew installer, brew, or any other subprocess
   phase 2 spawns. The captured password is passed only to the
   `ansible-playbook` subprocess, via `subprocess.run(env=...)` setting
   `ANSIBLE_BECOME_PASS`.

Don't pass the password on the command line (visible in `ps`). Don't put it
back in `os.environ` for convenience. Don't lean on sudo's timestamp cache
to bridge install.sh's apt step and Ansible's later become — phase 2's
Homebrew install can easily run longer than sudo's 15-minute default.

## Uninstall

`uninstall.py` reverses what install put on the host. By default it removes
managed symlinks and restores `.backup-N` siblings; opt-in flags broaden the
teardown to packages, Homebrew itself, and the checkout. See README for the
flag surface.

The implementation is intentionally split:

- **Symlink removal + backup restore lives in Python** (`uninstall.py`,
  reusing `dotfiles_manager.find_stale_managed_symlinks`). Two reasons:
  it must keep working if `--ansible` removed Ansible earlier in the same
  run, and the existing Python primitive already encodes "any symlink in
  `$HOME` resolving inside the managed root is ours" — wrapping that in
  Ansible just to shell back to Python is pure plumbing. `--homebrew`,
  `--ansible`, `--repo` are in Python for the same standalone-survives
  reason.
- **Package removal lives in Ansible** (`uninstall.yml` + per-role
  `tasks/uninstall.yml`). This keeps the layered `group_vars`/`host_vars`
  YAML resolution where Ansible already handles it, instead of forcing
  Python to grow a YAML dependency or duplicate the resolution.

This asymmetry is principled — don't "fix" it by moving symlink removal
into a `roles/dotfiles/tasks/uninstall.yml`. The cost is ~50 lines of YAML
duplicating ~30 lines of Python *and* a bootstrapping concern (default
behavior depending on Ansible being installed).

### The `.installed-host` marker

After a successful playbook run, `phase2.py` writes the chosen profile to
`~/.dotfiles/.installed-host` (one line, profile name). `uninstall.py` reads
it as the default for `--host` so the user doesn't have to re-pick during a
destructive op. The marker is gitignored. The file is durable state and can
drift — `uninstall.py` validates the recorded value against the current
`host_vars/` listing and falls back to the interactive picker (with a
warning naming the stale value and the marker file) if the profile is gone.

### Shared module: `_dotfiles_common.py`

Output helpers (`announce` / `centered_announce` / `info` / `warn` / `die` /
`run`) and host-profile resolution (`is_profile_entry`, `resolve_host_profile`,
`list_host_profiles`) live in `_dotfiles_common.py` so install and uninstall
print identically and prompt identically. Safe because both scripts run *after*
the repo is on disk — the constraint that keeps phase 1 self-contained (no
`source`-ing repo files) doesn't apply here. The `install.sh` ↔ `phase2.py`
split is still the load-bearing one; `_dotfiles_common.py` only spans Python.

### `changed_when` on uninstall tasks

Mirror the install side. The homebrew install task keys `changed_when` off
`'Installing'` / `'Upgrading'` appearing in the `brew bundle` stdout; the
uninstall task keys off `'Uninstalling'` in the `brew uninstall` stdout.
`changed_when: true` was a real bug here — the task is idempotent
(re-running finds nothing and `|| true` swallows the error), so reporting
CHANGED forever defeats Ansible's idempotency reporting.

## Output buffering

Both bash and Python full-buffer stdout when it isn't a tty (CI logs, docker
logs, anything piped or redirected). Without compensation, status lines sit
in the writing process's buffer until exit while curl, brew, ansible-playbook
etc. write directly to the underlying fd — and the captured log ends up with
each status line arriving *after* the subprocess output it was meant to
describe. Two compensations are in place; don't undo them:

- **`install.sh`**: `announce` and `info` write to **stderr** (`>&2`), not
  stdout. Stderr is unbuffered by libc convention, so each printf lands in
  the stream immediately. `die` always did this. If you add new bash status
  helpers, do the same.
- **`phase2.py`**: the first thing in `main()` is
  `sys.stdout.reconfigure(line_buffering=True)` (and same for stderr). Each
  `print(...)` then flushes at `\n`, so status text lands before the next
  subprocess writes.

The symptom of regressing either: the kilobyte splash and "Installing
Homebrew…" lines arrive at the very end of the captured log.

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

Two end-to-end harnesses live under `tests/`, both running inside a fresh
Debian container as a non-root sudo user. They share Docker plumbing via
`tests/lib/e2e-common.sh` — the shared library handles the tarball
snapshot, the `useradd testuser` + sudoers, the testuser-side `git init` /
commit (root-extract-then-chown would trip `git`'s dubious-ownership
check on macOS-built tarballs), and the `COLORTERM` / `COLUMNS`
re-injection across the `su - testuser` boundary because login-mode `su`
clears the env by default — leave that alone.

- **`tests/e2e-linux.sh`** (install-only). Runs `install.sh` → `phase2.py`
  → playbook end-to-end. ~5-10 min.
- **`tests/e2e-roundtrip-linux.sh`** (install ↔ uninstall ↔ install ↔
  `uninstall --all`). Catches regressions where `uninstall.py` /
  `uninstall.yml` fall out of sync with the install path. ~10-20 min.
  Assertion logic lives in `tests/lib/e2e_assertions.py`, which imports
  `dotfiles_manager.find_stale_managed_symlinks` from the installed repo
  so the managed-link manifest is enumerated by the same code production
  uses (no parallel bash reimplementation that could drift). The harness
  injects a synthetic fixture (`home_source/common/.dotfiles-e2e-marker`)
  inside the container — not in the host repo — so backup-restore is
  exercised deterministically regardless of what `home_source/` ships.

Both are **slow** (real Homebrew + `brew install ansible` + full
playbook, twice for the round-trip plus a `--homebrew` teardown), so
neither is wired to `push` or `pull_request`. Runs locally with just
Docker; runs in CI via the manual `workflow_dispatch` jobs at
`.github/workflows/e2e-linux.yml`. Same scripts in both contexts.

**Out-of-scope for tests** — change these with extra care since there's no
automated check:

- `xcode-select` and `softwareupdate` paths in `install.sh`.
- The tty *success* path of `install.sh` (only the no-tty fallback is tested).
- `setup_homebrew`, `setup_ansible`, `run_playbook` in `phase2.py` — untested
  at the unit level, but exercised end-to-end by `tests/e2e-linux.sh` and
  `tests/e2e-roundtrip-linux.sh` on Linux. The macOS-side equivalents are
  still genuinely untested.
- Package-removal Ansible tasks (`roles/{apt,flatpak,homebrew}/tasks/uninstall.yml`)
  and the `--homebrew` / `--ansible` shell-outs in `uninstall.py` are
  exercised end-to-end on Linux by `tests/e2e-roundtrip-linux.sh`
  (`--all` teardown), but not at the unit level. The
  symlink/backup-restore core and the action planner *are* unit-tested.
  macOS-side equivalents are untested.
- macOS round-trip (install ↔ uninstall). The Linux round-trip harness
  covers the cross-cutting symmetry, but `xcode-select`,
  `softwareupdate`, the Homebrew uninstall script on Darwin, and macOS
  defaults rollback all run zero CI checks.

## CI

`tests.yml` is PR-only: triggers on `pull_request` to `main` and `push` to
`main`. Pushes to feature branches don't run CI by design — the gate is "must
pass before merge to main." If a feature branch shows no CI run, that's
expected, not broken.

A second workflow, `.github/workflows/e2e-linux.yml`, holds two
**`workflow_dispatch`-only** jobs: `e2e` (wraps `tests/e2e-linux.sh`) and
`e2e-roundtrip` (wraps `tests/e2e-roundtrip-linux.sh`). Both fire nothing
automatically; trigger from the Actions tab when you want a real-Linux
check — a single dispatch runs both jobs in parallel. Kept in its own
workflow file so the manual trigger doesn't entangle the `tests.yml`
gate.

## Conventions

- Output helpers exist in both bash (`announce`, `info`, `die` — all write
  to stderr) and Python (`announce`, `centered_announce`, `info`, `warn`,
  `die` — both streams line-buffered after `main()` start) with parallel
  ANSI styling. Keep them consistent — a user shouldn't be able to tell
  which language printed a line. See the "Output buffering" section before
  changing which stream they write to.
- `host_vars/<name>.yml` is the per-host pivot. It points at
  `brewfiles/hosts/<name>.Brewfile` (file-based brew layer) and optionally
  sets `host_apt: [...]` / `host_flatpak: [...]` (list-based layers for
  Linux hosts). Adding a new host means a `host_vars/<name>.yml` + a
  Brewfile, plus assigning the host to one group per group-set (today just
  `purpose: personal | work` — see `inventory.yml` for the current set
  list).
- The universal Brewfile layer lives at `brewfiles/common.Brewfile`.
- Group Brewfile layers live in `brewfiles/groups/`.
- **Package-layering variable naming convention.** Three scopes per backend
  (brewfile / apt / flatpak), encoded as a name prefix: `common_<thing>`
  (all hosts; `group_vars/all.yml`), `group_<set>_<thing>` (per-group within
  a set; `group_vars/<group>.yml`), `host_<thing>`
  (`host_vars/<host>.yml`). Set-prefixing on the group layer is what lets a
  second group axis (e.g. an OS axis) compose with `purpose` later instead
  of colliding. Full spec in `group_vars/all.yml`.
- **Role gating uses runtime facts, not inventory groups.** `site.yml` keys
  off `ansible_facts['system']` / `ansible_facts['os_family']`, so
  adding/removing OS-axis inventory groups doesn't change what runs. Use
  the `ansible_facts[...]` form, not bare `ansible_*` — the bare top-level
  facts fire the `INJECT_FACTS_AS_VARS` deprecation in modern ansible-core
  and will stop working in 2.24.
- `tests/Brewfile` is dev-only (bats, pytest). Don't conflate it with
  `brewfiles/` — the latter is what Ansible installs on hosts at runtime.
- **Homebrew role idempotency gate.** Each per-layer `brew bundle install`
  is gated on `brew bundle check` (cheap, no per-formula network probe);
  the install only runs when the check exits non-zero. After all per-layer
  installs, a single `brew upgrade` pass runs (gated on `brew outdated`
  having output, so an up-to-date machine reports nothing CHANGED).
  Controlled by `homebrew_upgrade_outdated`, **default true** — a stock
  install leaves the machine fully up to date. The opt-out is per-run via
  `--no-upgrade` on `install.sh` / `phase2.py`, which sets
  `-e homebrew_upgrade_outdated=false` on the `ansible-playbook` call;
  there is no host_vars-level opt-out by design, because "skip upgrades"
  is a transient runtime choice, not a stable property of the host.
  There's no `brew bundle cleanup --force` step — removing anything not in
  a Brewfile would nuke ad-hoc `brew install` packages outside this repo.
- The `home_source/` tree (`common/` plus `hosts/<name>/` overlays) holds
  the files symlinked into `$HOME`. It must contain **only plain files and
  directories** — no symlinks (they'd be linked as a symlink-to-symlink
  chain and break managed-link detection) and no nested `.dotfiles`
  directories. Both are enforced by `dotfiles_manager.py check` (the
  `dotfiles-source-guard` pre-commit hook) and again at runtime in
  `build_source_manifest`.
- **Don't hardcode brew prefixes in `home_source/` shell rc files.** macOS
  Apple Silicon (`/opt/homebrew`), macOS Intel (`/usr/local`), and Linuxbrew
  (`/home/linuxbrew/.linuxbrew` or `~/.linuxbrew`) all differ.
  `home_source/common/.zprofile` probes them in a loop; new files should
  use `$(brew --prefix)` or the same probe pattern.
- The `PYTHON3` env var in `install.sh` exists so the bats suite can
  substitute a stub. Default (`/usr/bin/python3`) is unchanged for users.
- `DOTFILES_REPO` env override on `install.sh` lets the e2e harness clone
  from a local source instead of GitHub. Generally useful for forks and
  offline tests.
