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

## Use the devcontainer for dev tooling

This repo ships a Debian devcontainer (`.devcontainer/`) that's the
intended environment for any work that needs dev tools beyond the
bootstrap path. `bats` is apt-installed in the Dockerfile; `post-create.sh`
builds uv venvs holding ansible, ansible-lint, yamllint, pytest, pre-commit,
and molecule — so contributing requires nothing on the host.

Run dev tooling from inside the devcontainer, not the host. If a tool
you need isn't there yet, add it to `post-create.sh` rather than
installing on the host — the devcontainer *is* the local environment
for this project, and "I can't validate because the tool isn't on the
host" is the wrong reflex here.

The exceptions are the bootstrap surfaces themselves — `install.sh` and
`phase2.py` — which by design must run on a clean host with only the
prereqs they install themselves. Those get exercised end-to-end by
`tests/e2e-linux.sh` (also containerized).

## Comment style — lean terse, and feel free to tighten what's already here

Default to short, single-line comments that name the non-obvious WHY at
the line they describe. Don't mirror the dense rationale-prose blocks
that already exist in many files here (especially under `.devcontainer/`,
`phase2.py`, `tests/run`) — those are historical, not a style to match.
The architectural rationale for those mechanisms lives in this CLAUDE.md;
inline comments should at most point to the relevant section, not restate
it.

Two mechanical tells catch a misplaced comment at write-time, with no
judgment call — don't wait to be reminded of the principle, apply the
test:

- **It names files or mechanisms other than the one it sits in.** A
  comment that has to explain other parts of the system to justify
  itself is describing an *arrangement*, not a local gotcha — and
  arrangements belong in this CLAUDE.md. Leave a one-line pointer at the
  code. (A publish-workflow comment that explains the molecule gates
  scenario is describing something outside its own file.)
- **Its rationale runs past ~2 lines.** That length is architecture, not
  a line-local surprise; it has a home here.

And when one change edits both a design doc and logic described by it,
the implementation file gets a pointer — never a second copy of the same
rationale. That co-edit is exactly when duplication gets created.

When editing a file whose existing comments feel oversized for the rent
they pay, tightening them as part of the change is welcome and doesn't
need a separate task. Leave the load-bearing facts; cut the prose around
them. (If you're unsure whether a comment is load-bearing, surface the
proposed cut before applying it.)

## Devcontainer host plumbing

The container-side plumbing — worktree git resolution, the host timezone, the
shared git index across two stat domains, `gc.worktreePruneExpire`, and signed
commits under the `devcontainer` CLI — ships in a shared base image built and
published by [Syndic/unnatural_designs](https://github.com/Syndic/unnatural_designs).
Its canonical home is that repo's `meta/devcontainer-base/README.md`; read it
there rather than a copy here. What is local to this repo:

- **`.devcontainer/Dockerfile` `FROM`s the image at a pinned tag + digest**
  and layers uv, bats and ripgrep on top. This repo doesn't build the image,
  so the pin is an ordinary dependency: Renovate's docker manager bumps it in
  the floating-tag digest batch (see "Base image pins"), and
  `devcontainer.yml` gates the bump. A plain `FROM`, not the base README's
  `ARG BASE_IMAGE` override shape — nothing here would set the override.
  `test_devcontainer_from_shared_base_image_with_tag_and_digest` guards the
  reference.
- **Both hooks call `/usr/local/bin/devcontainer-plumbing` first**, passing
  `PLUMBING_WORKSPACE` / `PLUMBING_DIR` and **`PLUMBING_REQUIRE_GIT_CHECKOUT=1`**:
  a workspace with no git common dir is a bootstrap failure here, so
  `initialize.sh` and the container side both fail loud on it.
  `post-start.sh` is only that call; the signing bridge runs from the image at
  the `post-start` verb. `test_devcontainer_hooks_run_the_base_image_plumbing_fail_loud`
  guards both hooks.
- **`.devcontainer/initialize.sh` is the host stub**, per-consumer by design
  (shared code shouldn't run on a developer's host). It writes
  `.git-plumbing/` and the `.host-*` symlinks `devcontainer.json` binds:
  the git common dir, `known_hosts` (writable, found via `ssh -G`), and the
  file `gpg.ssh.allowedSignersFile` names (read-only).
  `test_devcontainer_binds_ssh_files_with_the_intended_writability` guards
  the binds; `tests/bash/test_devcontainer_initialize.bats` sources the script
  for its host-side decisions (zone parsing, the `known_hosts` path, the
  allowed-signers fallback).
- **The agent-socket bind is Docker-Desktop-specific.** Elsewhere (CI runners,
  plain Docker) `initialize.sh` `sudo touch`es a placeholder at
  `/run/host-services/ssh-auth.sock` so the bind succeeds; agent forwarding
  doesn't work there, which the smoke job doesn't need.

`gc.worktreePruneExpire = never` stops the automatic prune on the host too, so
stale worktree entries persist. Clear them with `/dev-cleanup` on the host
(`unnatural-designs-agent-tools`), which unregisters missing worktrees one entry
at a time and refuses to run in a container. Don't run `git worktree prune`:
inside the container every sibling looks missing, and it drops them all.

`devcontainer.yml`'s smoke job asserts the dispatcher and library exist, that
both hooks stamped, the three git config values, `~/.ssh` at mode 700, and the
two binds' writability. Nothing in this repo produces any of those, so together
they prove the `FROM` took effect and both hooks ran it. The `git config --file`
form skips repo discovery, which would trip git's dubious-ownership check (the
runner uid differs from the container uid).

## Devcontainer lock regeneration

`.devcontainer/devcontainer-lock.json` pins each devcontainer *feature*
(`version` + `resolved` digest + `integrity`), keyed by the **exact reference
string including the tag** (`ghcr.io/devcontainers/features/git:1.3.7`).
Renovate's `devcontainer` manager rewrites that tag on an upgrade but never
touches the lock — Mend-hosted Renovate can't run `postUpgradeTasks`. Left
alone, every Renovate devcontainer PR lands with a stale lock.

**Features are pinned to full `MAJOR.MINOR.PATCH` tags** (in
`devcontainer.json`), not floating majors. Specific version tags are immutable,
so their resolved digest never drifts, and *every* upgrade — patch included —
becomes an explicit Renovate edit to `devcontainer.json` that the regeneration
below can react to. This is deliberate: it trades a few more (reviewed) Renovate
edits — batched into the non-major group rather than one PR each, see
"Dependency updates" — for a lock that never silently ages behind a floating
tag.

`regenerate_devcontainer_lock.py` (repo root) closes the gap. It runs
`devcontainer upgrade --workspace-folder <ws> --dry-run` — which resolves every
current reference to stdout with **no Docker build** — then reconciles that
fresh resolution against the committed lock:

- Keep the committed entry for any reference key already locked (an *unchanged*
  reference — never re-pin it, so nothing can flap).
- Adopt the freshly-resolved entry for a key absent from the committed lock.
  Because the tag is part of the key, a Renovate version bump is a **key swap**:
  the new `…/git:1.3.8` is absent from the committed lock (which still holds
  `…/git:1.3.7`), so it's adopted; the old key, absent from the fresh
  resolution, is dropped.
- `serialize` = `json.dumps(indent=2) + "\n"`, which reproduces the CLI's lock
  format byte-for-byte, so regenerated and CLI-written locks diff cleanly.

`devcontainer upgrade --dry-run` is chosen over a plain `devcontainer build`:
`build`/`up` writes the lock only on a *full successful image build* (needs
Docker and would run this repo's host-specific `initializeCommand` worktree
plumbing), whereas `--dry-run` is a registry-only resolve. The reconcile is what
keeps `--dry-run`'s full re-resolution from flapping unchanged digests — do
**not** commit `upgrade`'s output directly. The pure functions
(`parse_features`, `reconcile`, `serialize`) carry all the logic and are unit-
tested in `tests/python/runtime/test_regenerate_devcontainer_lock.py`; the
driver's subprocess wiring is exercised by the workflow on real Renovate PRs.

`.github/workflows/renovate-devcontainer-lock.yml` runs it: on `pull_request`
touching `.devcontainer/devcontainer.json`, gated to `github.actor ==
'renovate[bot]'`, it installs `@devcontainers/cli`, runs the script, and commits
the regenerated lock back onto the PR branch. The commit is made by the
**`commit-file-via-app` composite action referenced cross-repo from the public
`Syndic/unnatural_designs` repo** (`@main` — that repo has no tags to pin-track,
and the user owns it and keeps it stable). Floating on `@main` means changes to
the action reach this repo without review; the failure mode is a red check on
the next Renovate devcontainer PR, not a silent break. It is the one `uses:` in
the repo that isn't SHA-pinned — a `pinDigests: false` carve-out keeps it that
way; see "GitHub Action pins". The action's README (in
`unnatural_designs`, beside its `action.yml`) documents the input surface as a
public contract and lists this repo as a consumer. That action commits via the
GraphQL `createCommitOnBranch` mutation with a GitHub-App token, which is
**server-side web-flow signed** — the only bot push that satisfies this repo's
signed-commit branch protection. The push is attributed to the App (not
`renovate[bot]`), so `devcontainer.yml`'s smoke build retriggers and validates
the bumped feature actually builds, while *this* workflow does not retrigger
(the actor guard fails) — no loop. `renovate.json`'s `gitIgnoredAuthors` lists
the App's bot email so Renovate doesn't treat the lock commit as a foreign edit
and abandon the branch.

A `devcontainer-lock-consistency` **pre-commit hook** guards the *manual*-edit
path the Renovate workflow doesn't cover (a human adding/removing/bumping a
feature by hand). It runs `regenerate_devcontainer_lock.py --verify-refs`, an
**offline** check that just compares the feature reference keys in
`devcontainer.json` against the lock's keys — no CLI, no network, so it fits
pre-commit's fast/local model. It can't regenerate (that needs the registry);
on a mismatch it fails with the copy/paste `python3
regenerate_devcontainer_lock.py` command. `config_feature_refs` (JSONC-tolerant)
and the diff/message helpers are unit-tested alongside the reconcile logic.

**One-time infra prerequisite (external — the workflow is inert until done):**
reuse the existing `unnatural-designs-renovate-helper` GitHub App — install it
on `Syndic/.dotfiles`, then add repo **variable** `RENOVATE_HELPER_CLIENT_ID`
and repo **secret** `RENOVATE_HELPER_PRIVATE_KEY`. If the helper App is ever
recreated, the `gitIgnoredAuthors` email in `renovate.json` must be updated in
lockstep.

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
install.sh), CI (`uv venv --python 3.9.6` in the `python` job of
`.github/workflows/tests.yml`), and the devcontainer (`uv venv --python 3.9.6`
in `.devcontainer/post-create.sh`), both pinned to the exact CLT patch. Keep all
three in step; `test_ci_runtime_python_matches_the_devcontainer` guards the two
`uv venv` lines.

The devcontainer provisions Python with **uv**, not the devcontainers `python`
feature. uv fetches prebuilt CPython from python-build-standalone — including
3.9.6 — so the frozen pin costs a download, not a from-source compile (the bulk
of the old startup time; the feature compiled both interpreters every build).
uv is baked into the image in `.devcontainer/Dockerfile`
(`COPY --from=ghcr.io/astral-sh/uv:<pin>`); `post-create.sh` drives it.

`post-create.sh` builds two venvs in parallel, one per interpreter: `~/.venv-runtime`
(the frozen 3.9.6 — the runtime pytest run + the default `python3` on PATH) and
`~/.venv-tooling` (`tooling_python` — everything else: the Ansible dev stack,
`ansible-core`, `ansible-lint`, `molecule`, the docker driver, all in one venv
so they share a single ansible-core, since a second copy is what produced the
duplicate-version warnings, #46/#48; plus pytest for the tooling run and
`pre-commit`). Both are plain venvs rather than `uv tool` installs because only
a venv exposes every package's entry points (`ansible-playbook`,
`ansible-galaxy`, `ansible-lint`, `molecule`) and installs from a requirements
file. pre-commit can share the tooling venv because every hook is `language:
system` — it builds no hook environments, and its hooks' `python3` still
resolves to the frozen 3.9.6 through PATH. Their bin dirs are put on PATH via
`remoteEnv` in `devcontainer.json` — keep that layout and `post-create.sh` in
step.

Package versions come from pinned `*-requirements.txt` files at the repo root
(`test-` for `~/.venv-runtime`, `lint-` + `molecule-` + `tooling-test-` + `pre-commit-`
for `~/.venv-tooling`), which the matching CI jobs in `tests.yml` install from
too — one pinned source per tooling set, shared between devcontainer and CI
(the `python-tooling` job installs all four `~/.venv-tooling` files; see "Two
pytest runs"). All are Renovate-managed — see "Dependency updates".

CI installs them with uv too: each Python job in `tests.yml` runs one shared
`astral-sh/setup-uv` step (a YAML anchor). The tooling-Python jobs then run
`uv pip install --system -r …` into the setup-python interpreter. The `python`
job uses no setup-python, because setup-python ships no 3.9 build for the
current `ubuntu-latest`. It builds a 3.9.6 venv with uv, the CI copy of
`~/.venv-runtime`, and installs into that. The venv is needed because uv refuses
`--system` installs into a Python it manages. setup-uv's `version:` must equal the devcontainer's
`COPY --from=ghcr.io/astral-sh/uv:<tag>`; how Renovate keeps the two together
is under "Dependency updates". setup-uv's cache is off (`enable-cache:
false`), because an uncached install of these pinned files already takes
only a few seconds.

Only the **runtime** pytest run is pinned: tests of code a user's Mac runs as
`python3` — the repo-root modules and the plugin's host scripts. Tests of dev
tooling run on `tooling_python` instead; the split is under "Tests" ("Two pytest
runs").

`test-requirements.txt` feeds that frozen 3.9 run (both `~/.venv-runtime` and the
`python` CI job), so a `packageRule` in `renovate.json` caps pytest at
`allowedVersions: <9` — pytest 9 dropped 3.9 (needs >= 3.10) with no 8.x
backport, so an un-capped bump PR fails `pip install` forever.
`lint-`/`molecule-`/`tooling-test-requirements.txt` run under `tooling_python`
and carry no such cap.

`allowedVersions` is deliberate over `constraints.python`. Two traps make
`constraints` the wrong tool here: it only filters when `constraintsFiltering`
is also set to `strict` (it **defaults to `none`**, so the constraint is inert
on its own), and Renovate reads the constraint value back as a `tool-constraint`
dependency and opens PRs bumping it to the latest Python — the cap fighting
itself. `allowedVersions` is a plain version filter always applied to regular
updates, with neither failure mode. It's pytest-specific by design;
`pytest-cov`/`coverage` still support 3.9, and a similar one-line cap gets added
if either drops it (a failing bump PR is the signal). Security bumps bypass
`packageRules` entirely (any of them) — those are handled by dismissing the
GitHub Dependabot alert, which also drops them from the feed Renovate reads.

The Ansible-tooling interpreter is `tooling_python` in `post-create.sh` (it just
needs >= 3.10) — not part of the pin. Renovate keeps it current while leaving
`3.9.6` frozen; the wiring is in `renovate.json` (a `customManager` for
`tooling_python`, matching only the annotated assignment so the frozen 3.9.6 in
the same file is never touched; a second keeping every annotated
`python-version` in tests.yml — the tooling-Python jobs — in step, with the
github-actions manager's own extraction of them disabled so that customManager is
their one owner). The frozen 3.9.6 lives in plain `uv venv --python 3.9.6` lines
(post-create.sh and tests.yml) that no Renovate manager matches, so it stays put
without a disable rule.

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

## Galaxy collections come from requirements files, not a bundle

The PyPI `ansible` package is ansible-core *plus* ~100 bundled collections
shipped inside its own `site-packages/ansible_collections`. That directory is
always on ansible's resolution path, so any collection also installed by
`ansible-galaxy` (which writes to `~/.ansible/collections`) exists in two roots
— and every `ansible-lint` / `ansible-playbook` run prints `WARNING  Another
version of '<collection>' … was found installed in …, only the first one will
be used`. Same-version copies still warn; the warning is about the *arrangement*,
not a version conflict.

So **every dev/CI environment installs `ansible-core`, never `ansible`**, and
gets its collections from a requirements file. One root, no warnings, and an
undeclared collection dependency fails loudly instead of being masked by the
bundle. Two files, split by who consumes them:

- **`requirements.yml`** — runtime deps of the playbook (`community.general`
  for `osx_defaults`/`flatpak`, `geerlingguy.mac` for the dock role). Installed
  by `phase2.install_galaxy_requirements()` on every user host, by
  `post-create.sh`, and by CI's `lint` + `molecule` jobs.
- **`requirements-dev.yml`** — test-only deps (`community.docker`,
  `ansible.posix`, both needed by molecule's docker driver, not by any role).
  Installed by `post-create.sh` and CI's `molecule` job only. **Deliberately
  not installed by `phase2.py`** — a dotfiles bootstrap has no business
  downloading a Docker collection it never uses. Don't "simplify" by folding
  it into `requirements.yml`.

`tests/python/tooling/test_galaxy_requirements_consumers_agree.py` gates all of
it: both consumers install every root `requirements*.yml`, phase 2 names only the
runtime one, and no `pip install` line anywhere reintroduces the bare `ansible`
bundle.

Production is the one place the bundle still appears — `phase2.setup_ansible()`
runs `brew install ansible` (Homebrew has no `ansible-core` formula). It stays
warning-free by luck of ordering rather than by structure: modern
`ansible-galaxy` skips a requirement already satisfied anywhere on the search
path, so `community.general` is never re-fetched into a second root there. If
that behavior ever changes, the fix is a brew-installed `ansible-core`
equivalent, not weakening the requirements files.

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

`uninstall.py` carries the symmetric handoff in `capture_sudo_password()`
(uninstall.py): it pops `SUDO_PASSWORD` from `os.environ` unconditionally
(defense-in-depth, even when not needed), then — only when the run will hit
a `become: true` task (Linux + `--apt-packages` or `--flatpak-packages`) —
prefers the env value, falls back to `sudo -n true`, and finally prompts
via `getpass`. The captured value is held in a local and passed to the
ansible-playbook subprocess via `env={"ANSIBLE_BECOME_PASS": ...}`. Capture
runs **after** `resolve_host` and **before** the plan is printed, so the
no-tty / bad-password failure modes surface before any work happens.

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
print identically and prompt identically. So does `ansible_playbook_env`, the
env both hand `ansible-playbook`: `ANSIBLE_CONFIG` (why: see "Lint") plus the
subprocess-scoped `ANSIBLE_BECOME_PASS` (see "Sudo / become on Linux"). Safe because both scripts run *after*
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

## Lint

`yamllint` and `ansible-lint` gate every PR via the `lint` job in
`tests.yml` and run locally as pre-commit hooks. Configs:

- `ansible.cfg` (repo root) — sets `inventory`, `roles_path`, and
  YAML-formatted task output (`stdout_callback = default` with
  `callback_result_format = yaml`). Ansible looks for `ansible.cfg` in the
  **current directory**, not next to the playbook, so whether a run uses this
  file depends on where it starts:
  - **Runs started in the repo root** (`ansible-lint`, a hand-typed
    `ansible-playbook`) find it on their own.
  - **The bootstrap's playbook runs** (`phase2.run_playbook` and
    `uninstall.py`'s package removal) start wherever the user ran
    `install.sh` or `uninstall.py`, so they name it explicitly in
    `ANSIBLE_CONFIG`, via `_dotfiles_common.ansible_playbook_env`.
  - **Molecule never uses it.** Molecule sets `ANSIBLE_CONFIG` to an
    `ansible.cfg` it writes for each scenario, so every
    `roles/*/molecule/*/molecule.yml` sets `callback_result_format: yaml`
    itself, under `provisioner.config_options.defaults`.

  `test_ansible_playbook_runs_under_the_root_config` runs the real
  `ansible-playbook` under this file the first two ways.
  `test_ansible_cfg_stdout_callback_is_builtin` checks that the callback ships
  with ansible-core, and `test_molecule_scenarios_mirror_the_root_result_format`
  checks each scenario's copy of the result format.
- `.yamllint` — deliberately strict: `extends: default` and *tightens* it.
  Booleans must be `true`/`false` (no `yes`/`no`/`on`/`off`); octal scalars
  are forbidden outright; line-length is a hard error at 120 (no warning
  escape hatch — 120 not 80 because Ansible task bodies and Jinja run long).
  Only two rules are loosened, both forced by the ecosystem: `braces`
  (`max-spaces-inside: 1`) so Jinja `{{ var }}` isn't flagged, and the
  `comments` rules (`min-spaces-from-content: 1`, `comments-indentation:
  disable`) to match ansible-lint's embedded yamllint — diverging there
  would permanently disable ansible-lint's `--fix` mode. `home_source/` is
  ignored (user dotfile content, not Ansible YAML).
- `.ansible-lint` — set to the strictest **`production`** profile. The repo
  passed it clean on first run, so we lock in the highest bar rather than
  leave headroom for regressions. If a future change genuinely can't meet a
  production rule, dial the profile back to `safety` / `moderate` rather than
  scattering `# noqa` markers. `skip_list: [yaml]` because yamllint runs as
  its own step; the embedded ansible-lint yaml check would double-report.
  `home_source/`, `tests/`, `.github/`, and molecule scratch dirs are
  excluded.

Run locally via `./tests/run lint` (devcontainer; both tools live in the
`~/.venv-tooling` uv venv `post-create.sh` builds, alongside ansible-core and
the requirements-file collections — see "Galaxy collections come from
requirements files, not a bundle"). The yamllint and ansible-lint
pre-commit hooks are `repo: local` / `language: system`, running those same
venv binaries — so `lint-requirements.txt` (plus the ansible-core pin in
`molecule-requirements.txt`, which CI's `lint` job installs alongside it) is
the one pin for local and CI lint. Don't switch them back to upstream
`repo:` + `rev:` hooks: each builds its own env with an unpinned
ansible-core, and Renovate's `pre-commit` manager is off by default, so the
`rev:` never moves. `test_precommit_lint_hooks_run_the_pinned_venv_tools`
guards it. The cost: the hooks need that venv on PATH, so commit from inside
the devcontainer (`devcontainer exec … git commit`); a host commit touching
YAML fails `Executable \`yamllint\` not found`.

Adding a new YAML file or role: it'll get linted automatically. If a
rule flags something genuinely wrong with the *rule* (not the code),
update `.yamllint` / `.ansible-lint` rather than scattering `# noqa`
markers.

## Tests

Required for behavior changes. Three suites: bats (bash), pytest (Python, as
two runs — see "Two pytest runs"), and molecule (per-role Ansible scenarios).
Lint runs as a fourth suite (`./tests/run lint`); see the section above.

Run them from the devcontainer (`bats` comes from `.devcontainer/Dockerfile`;
`.devcontainer/post-create.sh` builds the uv venvs holding pytest, pre-commit,
molecule, ansible-lint, and yamllint).

```sh
./tests/run                          # everything (python + bash + lint + molecule)
./tests/run fast                     # python + bash + lint (skip molecule — no docker)
./tests/run python                   # both pytest runs, in parallel
./tests/run bash                     # bats only
./tests/run lint                     # yamllint + ansible-lint
./tests/run molecule                 # every molecule scenario, in parallel (needs docker)
./tests/run molecule <role>          # one role's scenarios, in parallel (used by the CI matrix)
```

`tests/run` imports `announce` / `info` / `warn` / `die` from
`_dotfiles_common` so the bracket-style banners stay consistent with
the bootstrap.

**Multi-suite invocations (`all`, `fast`, `python`, `molecule`) run every suite in parallel**,
buffering each suite's output to a tempfile. On a tty, a live dashboard
shows the tail of each running suite's log — capped at
`MAX_LIVE_LINES_PER_SUITE` (default 20) per suite, compressed equally
across suites when the viewport can't fit that many for everyone (down
to zero, headers only, if the terminal is tight). Refreshed every
`TICK` (default 2) seconds via cursor-up + erase. The dashboard uses
a three-tier colored hierarchy mirroring `_dotfiles_common`'s palette:

- **Dashboard header** — yellow background `announce`-style banner
  (`live · HH:MM:SS · X/N suites complete`), the top-level section
  boundary. Otherwise the previous render's separators would be easy to
  confuse with suite content scrolling past.
- **Suite header** (one per running suite, above its tail block) — blue
  background `info`-style banner (`<name> · <elapsed>`), the labeled
  sub-section. Plain `[name | elapsed]` was easy to lose in molecule's
  verbose colored scenario logs; the colored bracket reads as a section
  start against any surrounding noise.
- **Completion banner** (above each suite's full output as it flushes) —
  yellow `announce`-style for PASS, red (`die`-style) for FAIL. Becomes
  permanent scrollback as the dashboard redraws above.

When everyone's done, the summary prints with per-suite green/red
badges. Exit is non-zero iff any suite failed.

On a non-tty (CI, piped) the live dashboard is skipped — completed-suite
output still flushes as soon as each finishes (in completion order), the
summary still prints at the end. The exit code semantics are identical.

On SIGINT/SIGTERM (including a CI cancel or job timeout) the still-running
suites are terminated and their partial logs flushed under a red
`INTERRUPTED` banner before the tempdir is removed; exit is 130. Without
that, a hung scenario would leave nothing in the CI log, since every
suite's output is buffered until it exits.

Single-suite invocations (`bash`, `lint`) preserve fail-fast
semantics — no parallelism, no summary, exit code propagates directly.

Two trade-offs the parallel mode pays:

1. **Run-all-then-summarize.** A failing earlier suite no longer aborts
   the run, so the others still run against a tree that may already be
   invalid. The full picture is worth more than the early abort.
2. **Homebrew base image prep is lifted out of the molecule shard** and
   runs serially before the parallel block starts. Parallel `docker build`
   / `docker tag` against the same `:local` tag would race, and the bash
   shards' output would interleave on stdout (we buffer per-suite, but the
   docker daemon writes to its own log streams). Prepare hooks are
   deduplicated, so the three homebrew scenario suites share one image
   prep. The summary's `molecule:homebrew/*` times then reflect test work
   only, not image prep.

CI runs all three on Ubuntu as separate `pull_request` jobs (pytest as two:
`python` and `python-tooling`). Molecule lives
under `roles/<role>/molecule/<scenario>/` per role; today the dotfiles, apt,
flatpak, homebrew, and claude_code roles are covered. apt and flatpak add an
`empty_groups/` scenario beside `default/`; **homebrew has three** (`default`,
`multi_layer`, `gates`) — see "Homebrew molecule scenarios" below. The bare `./tests/run` runs everything;
use `./tests/run fast` when you don't have Docker (or don't want to pay the
~5-min molecule cost) and just need the python/bash gates.

**Molecule CI is sharded across roles** via a `strategy.matrix` in
`tests.yml` — one runner per role, all in parallel. The previous single
job was wall-clock-bound by the slowest role (homebrew, which builds a
Linuxbrew base image inline); sharding lets the lighter roles return in
1-2 min while homebrew runs in its own cell. **Within a shard, each scenario
is its own `tests/run` suite** (`molecule:<role>/<scenario>`, one `molecule
test -s` each), so a role's scenarios run concurrently and the shard costs its
slowest scenario rather than the sum. This works because every scenario's
platform `name:` is unique — keep it that way when adding one, or two
scenarios' containers collide. Each shard's first step after setup-python
backgrounds `./tests/run pull <role>`, which pulls every digest-pinned
`image:` in the role's scenarios (plus homebrew's published base) so the
pulls overlap the pip and Galaxy installs instead of landing inside
molecule's `create`. Best-effort: its log is printed at the end of the
job, and a failed or unfinished pull just leaves molecule to pull as
before.
The roles list is duplicated
in two places — `MOLECULE_ROLES` in `tests/run` for local runs, and
`matrix.role` in `tests.yml` for CI shard discovery — adding a new molecule-
covered role requires updating both. **`tests/python/tooling/test_molecule_role_lists_agree.py`
gates this**: it scans `roles/*/molecule/` on disk and asserts both lists
match, so forgetting to update one (or only updating one) fails CI
immediately rather than silently shipping mismatched local/CI coverage.
`fail-fast: false` is set on the matrix so a failure in one shard doesn't
cancel the siblings; we want every failing role surfaced in a single CI run.

**Branch protection should require `molecule-all`, not the per-role
checks.** The `molecule-all` job `needs: molecule` (so it runs after every
shard) and `if: always()` (so it runs even when shards fail) — it asserts
`needs.molecule.result == 'success'` and exits non-zero otherwise. With
this aggregator wired up, adding a new role only requires updating the two
lists above; the required-check name (`molecule-all`) stays stable.
Without it, branch protection would have to enumerate `molecule (dotfiles)`,
`molecule (apt)`, ..., and adding a role would mean updating the
protection rule too.

Why molecule on top of the e2e harnesses: the e2e suite is gated to manual
`workflow_dispatch` because of its runtime, so per-PR coverage of role-level
behavior would otherwise be zero. The molecule scenarios are fast enough to
gate every PR. The dotfiles scenario in particular exercises the symlink +
backup paths that have historically leaked regressions.

The flatpak molecule scenario is intentionally **composition-only** — it
mirrors the role's per-set `lookup('vars', ...)` resolve loop and the
final concatenation, then asserts the result, but mocks the real
flatpak install (which would blow the per-scenario time budget). If
either the role's resolve loop or its install task `name:` expression
changes, update `roles/flatpak/molecule/default/converge.yml` in
lockstep with `roles/flatpak/tasks/main.yml`.

### Two pytest runs

The 3.9 pin (see "Python 3.9 pin") only needs to cover code that a user's Mac
executes as `python3`, so pytest runs twice, split by directory:

- **Runtime run** — `tests/python/runtime/` plus
  `unnatural-designs-agent-tools/tests/` (the plugin's tests stay in its folder
  so it extracts unchanged). Tests of `phase2`, `_dotfiles_common`, `uninstall`,
  `dotfiles_manager`, `regenerate_devcontainer_lock`, and the plugin's
  `dev_cleanup`. Runs on the frozen 3.9.6 with pytest 8: `~/.venv-runtime`, the
  `python` CI job, and bare `pytest` (`pytest.ini`'s `testpaths`). Running the
  tests on 3.9 is what proves those modules still parse and run there.
  `regenerate_devcontainer_lock` is runtime even though its workflow uses the
  runner's `python3`: its pre-commit hook runs it as `python3`, which is 3.9.6
  in the devcontainer and on a Mac.
- **Tooling run** — `tests/python/tooling/`: `tests/run`, CI/Renovate/config
  layout, role-file shape checks. Runs on `tooling_python` with uncapped pytest
  (`tooling-test-requirements.txt`): `~/.venv-tooling`, the `python-tooling` CI
  job, and `pytest tests/python/tooling`. The CI job installs every requirements
  file `~/.venv-tooling` does (lint + molecule + tooling-test + pre-commit), so a
  tooling test that imports, say, `yaml` sees it in both places;
  `test_ci_tooling_run_installs_what_the_local_tooling_venv_has` guards that.
  VS Code's Test Explorer shows only the runtime run (its interpreter is
  `~/.venv-runtime`, which can't load `tests/run`); run the tooling tests via
  `./tests/run python`. `tests/python/tooling/conftest.py`
  loads `tests/run` (syntax too new for 3.9, no `.py` suffix) via
  `SourceFileLoader` and registers it as the module `tests_run`, so its tests
  import the real thing rather than regex its source. The molecule `image:` parser lives in
  `tests/run` for the same reason — its pin guards import it from there.

`./tests/run python` runs both as parallel suites: the runtime run via
`pytest` on PATH (`~/.venv-runtime/bin` comes first in `remoteEnv`), the tooling run
via `tests/run`'s own interpreter (`sys.executable -m pytest`) — the
shebang's `python3.14` resolves to `~/.venv-tooling`'s, the one interpreter
guaranteed able to load `tests/run`.

`tests/python/tooling/test_pytest_run_split.py` keeps the split honest: every
test file under `tests/python/` (at any depth) sits under `runtime/` or
`tooling/`, no tooling test imports a runtime module
(repo-root `*.py` or the plugin's `scripts/`, discovered from disk), and every
runtime test imports one. A test that imports `phase2` therefore can't land in
the run that wouldn't catch a 3.9 regression.

### Homebrew molecule scenarios

Three scenarios under `roles/homebrew/molecule/`, all sharing a single
base image built locally by `./tests/run molecule` from
`roles/homebrew/molecule/Dockerfile` and tagged
`dotfiles-homebrew-molecule:local`. The image bakes Linuxbrew + a
pre-installed `hello` formula; building it cold costs ~5 min, but the
docker layer cache makes rebuilds near-free locally, and CI pulls a
published copy (below). Each scenario references the tag with
`pre_build_image: true`.

The image deliberately diverges from the apt/dotfiles/flatpak base
(`geerlingguy/docker-debian12-ansible`): the homebrew role has no
`become:` and doesn't manage services, so a plain `debian:trixie-slim`
with `python3` and a non-root `linuxbrew` user (brew refuses to run as
root on Linux) is enough. Scenarios connect ansible via
`ansible_user: linuxbrew` in `provisioner.inventory.host_vars`.

**The base must have glibc and libstdc++ at least as new as Homebrew's
Linux CI baseline** (`LINUX_GLIBC_CI_VERSION` / `LINUX_LIBSTDCXX_CI_VERSION`
in brew's `os.rb` — Ubuntu 24.04's today). Below it, brew installs its own
`glibc` + `gcc` (and `binutils`, `isl`, `mpfr`, …) as a dependency of
*every* formula. On bookworm (glibc 2.36) that was ~620MB of Cellar,
doubling the image to 731MB compressed and making the pull the biggest
fixed cost in the homebrew shard. trixie (2.41) clears the baseline, and
`brew deps <formula>` comes back empty for the scenarios' formulae.

What each scenario covers:

- **`default/`** — one-formula Brewfile, happy path. The idempotence
  re-converge is the regression cover for the `brew bundle check` gate
  in `ae021b2` — without the gate, the install task would always report
  CHANGED on second run.
- **`multi_layer/`** — every Brewfile layer populated (common +
  group_purpose + group_os + host), one distinct formula each. Mirrors
  production's `group_sets: [purpose, os]`. Asserts every formula ends
  up installed. Regression cover for `0861663`: the install task's
  `loop_var` indirection must resolve `item.item` to the path string;
  if that breaks, the assertions in `verify.yml` fail. The common layer also
  installs a cask from a local tap whose archive is a `file://` URL, so the
  cask path (install, `brew bundle check`, idempotent re-run) is covered on
  Linuxbrew with no network. It runs with `HOMEBREW_NO_AUTO_UPDATE` (production
  updates in `phase2.py` first), so it needs the image's Homebrew to have
  `brew trust`.
- **`gates/`** — two converges in one play file against a single
  container. First play (`homebrew_upgrade_outdated: true`, default)
  asserts the install task is gated off (image satisfies the Brewfile)
  and the outdated check *ran* (was not gated off). Second play
  (`homebrew_upgrade_outdated: false`) asserts the outdated check
  itself is skipped. Inline `post_tasks` introspect
  `homebrew_bundle_result` / `homebrew_outdated` — that's where those
  registered vars are in scope. `verify.yml` carries one external check
  (the baked formula survives both converges); the gate semantics
  themselves can only be observed via the registered task results.
  The true-path play deliberately does **not** assert `brew outdated`
  returned nothing: whether upstream has bumped a baked formula is live
  package state, not the gate's behavior, and asserting on it coupled
  the scenario to base-image freshness (a stale image reporting an
  outdated transitive dep — e.g. `isl` via `gcc` — turned the scenario
  red). The monthly image rebuild (below) keeps that upgrade path cheap;
  the assertion change keeps it correct regardless.

The single-container, two-play gates layout shares the image-install
cost across both gate paths and lets the second play's pre-state inherit
from the first — exactly the contract under test. Splitting into two
scenarios would double the setup cost for no additional coverage.

**Homebrew base image is prepared by `prepare_homebrew_image` in
`tests/run`,** gated to the homebrew shard so the lighter matrix cells
don't pay for an image they never use. Two paths, same outcome (an image
tagged `dotfiles-homebrew-molecule:local`, which every scenario's
`molecule.yml` references):

- **Pull from ghcr** when `MOLECULE_HOMEBREW_IMAGE_REPO` is set. CI sets
  it (job-level, in `tests.yml`) to
  `ghcr.io/syndic/dotfiles-homebrew-molecule` (lowercased; ghcr requires
  it), and `tests/run` appends the tag `roles/homebrew/molecule/image-tag.sh`
  prints: `dockerfile-<first 12 hex of the Dockerfile's sha256>`. The
  published image is built + pushed by
  `.github/workflows/publish-molecule-images.yml` under that same tag (via
  the same script, plus `sha-<short>`) on pushes to `main`
  that touch the Dockerfile, **plus a monthly `schedule:` rebuild** that
  bounds base-image staleness so the gates scenario's upgrade path
  doesn't accumulate `brew upgrade` work as the baked formulae drift
  from live upstream. `MOLECULE_HOMEBREW_IMAGE` (a full ref) overrides
  both the repo and the computed tag, e.g. to pull a `sha-<short>` build
  while bisecting a regression.
- **Local `docker build`** otherwise (no env var) or as a fallback when
  the pull fails (registry hiccup, or no image published for this
  Dockerfile yet).

The content-addressed tag is what makes a PR that edits the Dockerfile —
including every Renovate bump of its base digest — test its *own*
Dockerfile: its hash has no published image, so the pull misses and the
fallback builds it. Pulling `:latest` instead would succeed with main's
image and silently test the old one. The pull is best-effort; failure
quietly drops to build. Don't replace it with a hard pull — that would
couple PR CI to the publish workflow having already shipped, and break
Dockerfile-editing PRs. The cost: the first `main` run after such a merge
races the publish workflow and usually builds locally once.

The published package must be set to **public** in the GitHub UI
(Packages → Settings → Change visibility) so fork PRs can pull
anonymously. Switching to private would require docker/login-action in
tests.yml's molecule job and would break fork PRs (where GITHUB_TOKEN is
anonymous). One-time manual step per published package.

If a second role ever needs comparable per-role setup, that's the signal
to extract a convention (e.g., a `molecule/prepare.sh` `tests/run`
discovers and runs before each role's `molecule test`) rather than
adding a second gated branch. Until then, the inline path is correct-
altitude — generalizing on one data point would be premature.

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

## Dependency updates

**Pin everything that can be pinned; let Renovate move the versions.** Across
the repo — devcontainer features (full `MAJOR.MINOR.PATCH`), the frozen Python,
uv (the devcontainer's Docker tag and CI's setup-uv `version:`), base images
(tag + digest), Galaxy
collections in `requirements.yml` / `requirements-dev.yml`, and pip tooling in
`*-requirements.txt` — a dependency is pinned to an exact version and every bump
arrives as a reviewable Renovate PR. Pinning keeps
a fresh install reproducible (the versions CI passed are the versions a user's
bootstrap gets) and makes each upgrade an explicit reviewed edit rather than
silent drift. Don't reintroduce "unpinned so it tracks latest" for anything
Renovate can manage — latest-without-review is exactly what the pins buy back as
PRs. Homebrew is the one unavoidable exception: it's a rolling-release manager
with no clean way to pin a formula to an arbitrary version, so the Brewfiles
carry no pins by tooling constraint, not by preference — don't generalize that
to anything else.

Pip tooling (`test-`/`lint-`/`molecule-`/`tooling-test-`/`pre-commit-requirements.txt`) is named
`<purpose>-requirements.txt` so Renovate's built-in pip manager matches it with no extra config; the
Galaxy files need the `ansible-galaxy` widening below because their names don't match that manager's
default. Both consumers — `post-create.sh` venvs and the `tests.yml` jobs — install from these
files; `tests/python/tooling/test_galaxy_requirements_consumers_agree.py` guards that every
collection and pip requirement is pinned and that no consumer installs bare packages or the full
`ansible` bundle.

`renovate.json` batches **every non-major update into one PR** via a
catch-all `packageRule` (`matchUpdateTypes: [minor, patch]`, groupName
`all non-major dependencies`). Majors don't match it, so each lands on
its own branch and gets reviewed alone.

The **`requirements-dev.yml` pin needs an explicit Renovate file pattern.** The
built-in `ansible-galaxy` manager only matches `requirements.yml` /
`requirements.yaml` (and `galaxy.yml`) by default, so `requirements-dev.yml`
would be invisible to it. The top-level `ansible-galaxy.managerFilePatterns`
key in `renovate.json` widens the match to `requirements(-dev)?.yml`;
`requirements.yml` stays covered either way. A pin without that widening is a
pin nothing updates — the trap the file's own header warns about.

**The uv pin has one Renovate owner.** The devcontainer's `COPY
--from=ghcr.io/astral-sh/uv` and CI's setup-uv `version:` share the docker
depName `ghcr.io/astral-sh/uv` (the workflow side via a `customManager`), so
one update moves both. The github-actions manager would also track the
setup-uv input on its own, through github-releases `astral-sh/uv`; a
`packageRule` disables that, because uv's GitHub release lands before its ghcr
image, and a run in that gap would bump the CI pin alone.
`test_ci_uv_matches_the_devcontainer_and_renovate_tracks_it` guards the
agreement, the single owner, and the disable rule.

Grouping is by **update type, not by manager**. Manager is the wrong axis:
what decides whether a bump is safe to merge is how far it moves the
version, not which tool parses the file — so a manager-axis grouping
re-fragments every time a new pin style is added. Before this rule
existed there was no grouping at all, and the uv docker tag alone
accounted for 11 of the repo's first 24 Renovate PRs.

Two things about the rule are load-bearing:

- **Its position in `packageRules` decides who wins.** Renovate merges
  matching rules in order, last writer wins, and preset rules from
  `config:recommended` merge in *ahead* of the repo's own. So the catch-all
  overrides every grouping rule before it — that's how it swallows preset
  groups into the batch — and is overridden by every rule after it. A
  grouping rule that can match minor or patch and sits after the catch-all
  is a **carve-out**: it deliberately pulls those updates back out of the
  batch (today, Python minors and pre-1.0 minors — below). Every carve-out
  must come after the catch-all; one placed ahead of it is silently inert.
  Rules that set no
  `groupName` (`enabled`, `allowedVersions`, …) can go anywhere.
  `test_renovate_carve_outs_follow_the_catch_all` selects rules by
  shape (sets a `groupName`, can match `minor` or `patch` — no
  `matchUpdateTypes` counts as matching everything), so a new carve-out is
  covered without editing the test.
- **It's written out rather than pulled in as `group:allNonMajor`.** A
  preset's `packageRules` merge ahead of the repo's, which would put the
  catch-all *first* and let any repo rule override it.

`pin` and `digest` are deliberately **not** in `matchUpdateTypes`. A digest
update means a re-tag — the same version string resolving to a new SHA —
which is the supply-chain signal worth its own PR, not something to bury in
a batch of routine bumps.

The trade-off accepted: one bad dependency blocks the rest of the batch.
When a class of update is known to block it, that class gets a carve-out
rather than the batch being dismantled.

**Python minors are carved out** into their own `python-minor` PR. A new
interpreter minor can outrun the pinned tooling — Python 3.15 landed before
any stable ansible-core could import under it, turning every lint, molecule,
and devcontainer check in the batch red. On its own branch the bump can sit
red until upstream catches up while the rest of the batch merges. The rule
matches `depName=python`, which every tracked tooling-Python site shares
(`tooling_python`, the `tests.yml` `python-version`s, the `tests/run`
shebang), so they move together. Patches stay in the batch, but every one of
those pins is `MAJOR.MINOR`, so Renovate never proposes one.

**Pre-1.0 minors are carved out** into a `pre-1-0-minor` PR. Under 0.x semver
the minor *is* the breaking bump — uv ships its breaking changes as 0.x minors
— but Renovate still classes it `minor`, so the catch-all would batch it as
routine. The rule keys on `matchCurrentVersion: /^v?0\./`, so it covers every
0.x dependency (uv, `devcontainers/ci`) and lets go on its own once one
reaches 1.0. Patches stay in the batch.

**`ignorePaths` is overridden** with `config:recommended`'s list minus
`**/tests/**`. That preset (via `:ignoreModulesAndTests`) skips every file
under `tests/`, which hides the `tests/run` shebang pin from its
customManager. `ignorePaths` isn't mergeable, so the repo's list replaces the
preset's rather than adding to it. `test_renovate_file_patterns_reach_files_ignore_paths_keep`
asserts every `managerFilePatterns` entry reaches a tracked file outside
`ignorePaths`, so a manager aimed at an ignored path fails the tooling run.

Two Renovate-adjacent mechanisms have their own sections: the devcontainer
feature pinning policy and lock regeneration under "Devcontainer lock
regeneration", and the frozen-vs-tracked Python pins under "Python 3.9 pin".

### GitHub Action pins

Every `uses:` under `.github/` is SHA-pinned with a **full three-component
semver comment** — `actions/checkout@3d3c42e5… # v7.0.1`. The SHA is what
Actions resolves (a tag is mutable; a commit is not); the comment is what
Renovate reads to compute the next version, and what a human reads to know
what's pinned. `helpers:pinGitHubActionDigestsToSemver` in `extends` is what
keeps the comment accurate through updates.

**The comment must carry all three components.** A bare-major comment
(`# v7`) tracks the *floating* `v7` tag, so every `v7.x` release moves the
SHA underneath a fixed version string — which Renovate reports as a `digest`
update. Since `digest` is excluded from the non-major batch (above), that
turns every routine upgrade into its own PR wearing a supply-chain signal's
clothing, which is precisely backwards.

**It does not self-heal.** The preset's versioning regex makes minor and
patch optional, so `v7` and `v7.0.0` compare *equal* and Renovate never
offers the rewrite. The preset can keep a full-semver comment accurate
through updates; it cannot expand one after the initial pin. So a
hand-written `uses:` that lands as `@v7` stays wrong until someone notices.
`test_workflow_actions_are_sha_pinned_to_full_semver` is the guard — adding
an action with a bare-major or 2-component comment fails the python suite.

One deliberate exception: the cross-repo `commit-file-via-app` action floats
on `@main` (see "Devcontainer lock regeneration" for why), so a
`pinDigests: false` carve-out in `renovate.json` exempts it and the test
allowlists it.

### Base image pins

Every registry-pulled container base is pinned to a **digest**, not a bare
tag: `.devcontainer/Dockerfile` (the shared
`ghcr.io/syndic/unnatural_designs-devcontainer-base:latest` and the `COPY --from`
uv image), `roles/homebrew/molecule/Dockerfile`
(`debian:trixie-slim`), and the six non-homebrew molecule scenarios
(`geerlingguy/docker-debian12-ansible:latest`). The tag stays for
readability; the `@sha256:…` is what actually makes the pull reproducible.
`test_molecule_base_images_are_digest_pinned` enforces this for the molecule
scenarios (the homebrew scenarios are exempt — they reference a locally-built
`:local` image, not a registry pull).

Three of these can't be pinned any other way: `geerlingguy/docker-debian12-
ansible` publishes **only** a `latest` tag; the shared devcontainer base's other
tags are per-commit `sha-…` tags Renovate can't order, so `latest` is the only one
it can track; and the molecule Debian base floats by design as point releases
ship. So the digest is the
sole stable handle — without it a rebuilt `latest` silently changes the test
substrate, which is the failure mode already recorded under "Homebrew
molecule scenarios" (a stale base turned the gates scenario red).

The Renovate wiring is two parts:

- **A `customManager`** matching `roles/*/molecule/*/molecule.yml`. That file
  is parsed by no built-in manager, so without it the pinned digest would
  freeze forever. It keys on a `# renovate:` annotation above each `image:`
  line and captures datasource / depName / tag / digest. The Dockerfile pins
  need no customManager — Renovate's `dockerfile` manager already reads
  `FROM` and `COPY --from`. It **must** set `versioningTemplate: docker`: a
  customManager with no `versioning` capture group and no template defaults to
  `semver-coerced`, which is the wrong scheme for a docker image tag (a bare
  `latest` is not a semver version). The built-in `dockerfile` manager defaults
  to `docker` for the same images; the customManager has to be told.
  `test_renovate_custom_manager_tracks_molecule_images` guards the setting.
- **A digest-batching `packageRule`** that funnels digest updates on these
  three packages into the `all non-major dependencies` batch. This is the
  one deliberate crack in "digest gets its own PR" (see "Dependency
  updates"): on a *floating* tag a moving digest is the routine update
  mechanism, not a re-tag, so a solo PR per digest would be pure noise. The
  rule is scoped to exactly these package names by design — an immutable
  version tag (say a future `debian:12.11`) keeps the default solo-PR digest
  treatment, because there a moving digest really would be a re-tag worth its
  own review. The rule shares the catch-all's `groupName` and sits *before*
  it; both assign the same group, so order between them is immaterial (the
  catch-all's minor/patch matcher never matches a digest anyway).

**Pin the multi-platform *index* digest, never a single-arch *child*.** A
docker `@sha256:` can name either a manifest *list* (index — one digest
covering every platform, each host selecting its own child at pull time) or a
single arch's *child* manifest. They are indistinguishable by string; check
with `docker buildx imagetools inspect <ref>@<digest> --raw` and read
`mediaType` (`…index.v1+json` / `…manifest.list.v2+json` = index;
`…manifest.v1+json` / `…manifest.v2+json` = child). A child pin locks the
scenario to one architecture: an amd64 child pulls fine but fails
`exec format error` on an arm64 host without amd64 emulation — e.g. a dev's
Apple-Silicon devcontainer, whose DinD daemon is arm64. CI (amd64 runners)
wouldn't notice, which is how it hides. Renovate will **not** heal it: its
docker datasource reads the *current* digest's architecture and re-pins the
same-arch child on every bump when it finds one, or tracks the index when it
doesn't — so the pin's kind is sticky and must be set right by hand. This bit
us once: the #107 canary rewrote these pins to the amd64 child (there was no
retrievable historical *index* digest for geerlingguy's single `latest` tag),
Renovate then arch-matched `latest` straight back to that same child and
reported no update — a false "not managed" that was really "correctly
unchanged". `test_molecule_images_pin_index_not_child_digest` classifies each
pin against the registry (skips offline, enforced in CI) so a child digest
can't slip back in behind a passing `@sha256`-present check.

## Claude Code plugin (`unnatural-designs-agent-tools/`)

`unnatural-designs-agent-tools/` is a Claude Code plugin that is also its own
one-plugin marketplace: `.claude-plugin/marketplace.json` lists a single entry
with `source: "./"`, beside the plugin's `.claude-plugin/plugin.json`, `skills/`,
`scripts/`, and `tests/`. It's laid out so moving the folder to its own repo
extracts it unchanged — so nothing inside it may reference a path outside it,
and its design notes live in its
[README](unnatural-designs-agent-tools/README.md) (including the `dev-cleanup`
script's tiers, session guard, and fail-closed apply). Personal skills and
commands live here, not in `~/.claude/commands/` or `~/.claude/skills/`, so the
repo is their only home.

`unnatural-designs-agent-tools/scripts/` runs on the **host**, not in the
devcontainer, so it is standard-library Python kept 3.9-compatible (same
constraint as `phase2.py`); its tests in `unnatural-designs-agent-tools/tests/`
run in the devcontainer as part of the runtime pytest run (`pytest.ini`'s
`testpaths` lists it for both `./tests/run python` and CI's `python` job).

The `claude_code` role registers it as a **`directory` marketplace** (absolute
`path`, from `playbook_dir`, so the `~/.dotfiles` checkout in real use).
Claude Code loads a relative-path plugin from a directory marketplace in place
rather than copying it to the plugin cache, so edits take effect at the next
session start or `/reload-plugins` with no push, reinstall, or version bump.

`~/.claude/settings.json` is **merged, never symlinked**: Claude Code writes the
file itself (permissions, `/config` choices) and keeps it mode 0600. The role
owns exactly three kinds of entry and leaves every other key alone. The first
two are derived from `marketplace.json` so the names have one home:

- `extraKnownMarketplaces.<marketplace>` — replaced whole, never deep-merged, so
  a stale entry under the same name (say a `github` source left over from an
  extraction) can't survive as a hybrid of two sources.
- `enabledPlugins["<plugin>@<marketplace>"]` — set to `true` only when absent;
  an existing value wins, so a `/plugin disable` (which writes `false`) sticks
  across playbook runs.
- `permissions.allow` rules listed in `roles/claude_code/files/permissions-allow.json`
  — each appended only when absent, never reordering or removing other rules.
  Today that's `mcp__ccd_pr__set_monitor`, which `implement-work-item` calls to
  turn on Auto-fix for the PR it opens; auto mode can deny it otherwise. The rule
  only pre-approves the call; Auto-fix stays off until a session makes it. A
  skill's `allowed-tools` doesn't fit: its grant ends with the invoking turn,
  and the skill often reaches that call in a later one. The list is JSON so
  `uninstall.py` reads the same file.

Idempotency compares parsed JSON rather than bytes, so Claude Code reformatting
the file doesn't make the next run report CHANGED. The role fails closed on a
settings file that is a symlink (writing would replace the link and strand its
target), isn't a JSON object, or has a `permissions.allow` that isn't a list.
The molecule scenario covers each of these, plus unowned keys (including
siblings under the owned keys) surviving.

`uninstall.py` reverses it by default, in Python for the same
survives-`--ansible` reason as symlink removal: it unregisters every `directory`
marketplace whose path is inside the checkout, the `enabledPlugins` keys
naming it, and the role's allow rules. Without that, removing the checkout would
leave every Claude Code session failing to load a marketplace that no longer exists.

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
  Linux hosts). `host_dotfiles` is also available for a non-default
  home_source overlay root, but the role defaults to
  `home_source/hosts/<inventory_hostname>/` so an empty or absent host
  override doesn't need a declaration. Adding a new host means a
  `host_vars/<name>.yml` + a Brewfile, plus assigning the host to one
  group per group-set (today just `purpose: personal | work` — see
  `inventory.yml` for the current set list).
- The universal Brewfile layer lives at `brewfiles/common.Brewfile`.
- Group Brewfile layers live in `brewfiles/groups/`.
- **Package-layering variable naming convention.** Canonical spec lives in
  `group_vars/all.yml` — the comment block at the top defines the scope
  prefixes (`common_`, `group_<set>_`, `host_`), the `group_sets`
  indirection, the standard role-side `set_fact` + `lookup('vars', ...)`
  pattern, and the fail-loud-on-typo invariant. One non-obvious gotcha
  worth keeping here so it doesn't drift: don't switch to `extract` over a
  dict-typed `vars` — `vars` as a dict is deprecated in ansible-core and
  will be removed in 2.24, so the per-set `set_fact` loop is the
  supported pattern despite being longer.
- **Role gating uses runtime facts, not inventory groups.** `site.yml` keys
  off `ansible_facts['system']` / `ansible_facts['os_family']`, so the
  `os` group set (`macos` | `linux`) controls layered _values_, not
  whether a role runs. A host misfiled into the wrong os group gets the
  wrong Brewfile but still runs the right roles. Use the
  `ansible_facts[...]` form, not bare `ansible_*` — the bare top-level
  facts fire the `INJECT_FACTS_AS_VARS` deprecation in modern
  ansible-core and will stop working in 2.24.
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
- **macOS defaults role.** Hybrid approach: bulk settings go through
  `community.general.osx_defaults` (one list entry per key, layered via
  `common_macos_defaults` + `group_<set>_macos_defaults` for each set +
  `host_macos_defaults`) so re-runs report CHANGED only when a key
  actually flips. Dock layout is on by default
  (`macos_defaults_configure_dock: true` in the role's defaults) and
  delegates to `geerlingguy.mac.dock`, which is a no-op when the
  layered `dockitems_persist` / `dockitems_remove` lists are empty and
  shells out to `dockutil` when either has entries. `dockutil` lives
  in `brewfiles/groups/macos.Brewfile` (the `os`-set's macos layer),
  same as anything else that's macOS-only.
  Per-run opt-out is `--no-dock` on `install.sh` / `phase2.py`, which
  sets `-e macos_defaults_configure_dock=false` on the
  `ansible-playbook` call (mirrors `--no-upgrade`). For a stable
  opt-out, set `macos_defaults_configure_dock: false` in
  `host_vars/<host>.yml`.
  Settings that the module can't express
  (`nvram`, `pmset`, `systemsetup`, scripted dockutil sequences) drop
  into a shell escape hatch — point `macos_defaults_extras_script` at a
  path and the role runs it `changed_when: false`. The script itself
  must be idempotent; Ansible has no visibility into what it does. The
  two Galaxy collection deps (`community.general`, `geerlingguy.mac`)
  are declared in `requirements.yml` at the repo root and installed by
  `phase2.install_galaxy_requirements()` between `setup_ansible` and
  the playbook run. The dock task uses `import_role` (parse-time
  resolution), not `include_role` — so the collection must be installed
  locally before `ansible-playbook --syntax-check` works. The normal
  install path handles this automatically; the devcontainer runs the
  same `ansible-galaxy collection install` in `post-create.sh`; for
  ad-hoc host invocations of `ansible-playbook` outside phase 2, run
  the galaxy install once by hand. The trade is deliberate: parse-time
  resolution catches a missing/renamed/version-skewed collection at
  syntax-check time rather than partway through a Darwin run.
- The `home_source/` tree holds the files symlinked into `$HOME`. Same
  three-layer shape as the package vars: `common/` + per-group
  `groups/<group>/` (one per active group set) + per-host `hosts/<name>/`,
  resolved via the `common_dotfiles` / `group_<set>_dotfiles` /
  `host_dotfiles` vars. Later layers override earlier ones at the same
  relative path. The role stat-and-skips absent layers, so a tree with
  only `common/` (today's state) is fine. It must contain **only plain
  files and directories** — no symlinks (they'd be linked as a
  symlink-to-symlink chain and break managed-link detection) and no
  nested `.dotfiles` directories. Both are enforced by
  `dotfiles_manager.py check` (the `dotfiles-source-guard` pre-commit
  hook) and again at runtime in `build_source_manifest`.
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
