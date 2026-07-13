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

**Worktree git resolution.** When the devcontainer is brought up on a git
*worktree* via the `devcontainer` CLI (how this project's containers are
typically launched), git would not resolve inside the container by default:
the worktree's `.git` is a file pointing at `<main-repo>/.git/worktrees/<name>`,
a host path that isn't mounted, and the CLI — unlike VS Code's Dev Containers
extension — doesn't special-case worktrees. The devcontainer closes that gap
so the git common dir is reachable in-container **at the same absolute path it
has on the host**, which lets the `.git` file resolve *natively* (no `GIT_*`
overrides). It works for any checkout layout — full clone, main worktree, or a
linked worktree anywhere on disk:

- `.devcontainer/initialize.sh` (wired as `initializeCommand`) runs on the host
  before the build and drops two gitignored artifacts: a symlink
  `.devcontainer/.host-git-common` → the real git common dir, and
  `.devcontainer/.git-plumbing/host-git-common-path` holding that dir's
  absolute path. Both regenerate every `up`, so they never go stale and the
  host tracks nothing. The `.git-plumbing/` directory itself IS tracked
  (anchored by its README) so the Dockerfile's COPY of the directory
  succeeds even when the runtime-written file inside is absent — buildx
  errors on a COPY whose glob matches zero files, so the classic optional-
  COPY trick is not portable, and the tracked directory is the buildx-safe
  workaround. CI's `devcontainer build` never runs `initializeCommand`, so
  the path file is genuinely absent there; the Dockerfile's `[ -s … ]` shell
  test keeps that case a clean no-op.
- `devcontainer.json` binds the symlink (a static, `${localWorkspaceFolder}`-
  relative source — Docker follows it host-side) to a static `/host-git-common`.
- The `Dockerfile` reads `.git-plumbing/host-git-common-path` (it rides in the
  build context) and recreates that exact host-absolute path inside the image
  as a symlink to `/host-git-common`. So the worktree's `.git` file — which
  names the host-absolute path — follows that symlink to the bind-mounted real
  common dir and git resolves with its real contents, no env overrides.
- `workspaceFolder`/`workspaceMount` mount the workspace at its real host path
  so the worktree's own files and the `.git` back-pointer line up verbatim.

The constraint that forces this shape: devcontainer.json `mounts`/`runArgs`/
`build.args` only interpolate `${localEnv}`/`${localWorkspaceFolder}` at parse
time — never a value an `initializeCommand` computes (a child can't set the
CLI's env). A literal bind whose `target=` is the dynamically-discovered
host-absolute path would therefore need a system-wide env var; instead the path
is reproduced *inside the image* as a symlink to a statically-named mount, with
no env var of any kind. Multiple worktrees run concurrently: each carries its
own symlink/path file, bakes its own host-absolute symlink into its own image,
and binds its own `/host-git-common`.

With the above in place git *does* resolve, so `pre-commit install`/`run` work
in a worktree container, as do `./tests/run lint` and `python3 dotfiles_manager.py
check home_source`. `initialize.sh` and `post-create.sh` no longer guard for the
absent-git case — `set -e` plus a real git call fails loudly if a dev shell
can't reach git, which is the correct outcome for a dev-environment bootstrap.
The hooks also still gate every PR in CI.

### Host timezone plumbing

A sibling artifact rides in the same `.devcontainer/.git-plumbing/` directory:
`host-timezone`, holding the host's IANA zone name (e.g. `America/Los_Angeles`).
Without it the container defaults to `Etc/UTC` and timestamps in molecule and
playbook output drift hours off the host's wall clock.

The wiring reuses the host-git-common plumbing's lifecycle one-for-one — same
`initializeCommand` write, same build-context COPY, same `[ -s … ]` shell-guard
absence-tolerance. Only the per-artifact bits differ:

- `initialize.sh` reads `readlink /etc/localtime` (works on macOS and most
  modern Linux distros — both ship `/etc/localtime` as a symlink into a
  zoneinfo db) and strips everything up to and including `zoneinfo/` to get
  the zone name. Falls back to `/etc/timezone` (Debian/Ubuntu) when the
  symlink isn't there. Rejects absolute paths and `..` segments before
  writing, defense-in-depth on a hostile or broken host symlink target.
- The Dockerfile, when the file is non-empty AND the named zoneinfo file
  exists in the image, symlinks `/etc/localtime` to it, writes
  `/etc/timezone`, and appends `TZ=<zone>` to `/etc/environment`. The
  zoneinfo existence check guards against a partial `tzdata` install or an
  unknown zone name; the container falls back to UTC quietly in that case.
- No env vars in `devcontainer.json` — the `/etc/localtime` symlink is what
  libc reads, so Python `datetime`, `date(1)`, Ansible's date facts, and
  anything else that defers to libc local time all pick it up automatically.
  `TZ` in `/etc/environment` covers PAM-managed login shells (the `su -
  testuser` boundary the e2e harnesses cross); non-login `docker exec`
  shells still resolve local time correctly via `/etc/localtime`.

`tzdata` and the zoneinfo db are already in `mcr.microsoft.com/devcontainers/
base:debian`, so no package install. CI's `devcontainer build` runs without
`initializeCommand`, so `host-timezone` is absent there — the `[ -s … ]`
guard makes that path a clean no-op and CI keeps its default UTC.

### Shared git index across stat domains

A consequence of the shared-common-dir design in "Worktree git resolution":
host git and in-container git read and write the **same index file** (it lives
in the common dir both resolve to), but they sit in different stat domains —
the bind mount reports different uid/gid, inode, ctime, and sub-second mtime
for the same files. Under git's default `core.checkStat`, an index written on
one side reads as "everything modified" on the other *without any content
comparison* (`diff-index` flags every tracked file), so checkout-type
operations — rebase, merge, branch switch — refuse with "your local changes
would be overwritten" on a clean tree. Plain commits never hit this (no
checkout involved), which is why the breakage only surfaces on an in-container
rebase/switch, not on signing.

`initialize.sh` therefore sets `core.checkstat = minimal` and
`core.trustctime = false` in the **repo-local** config. That config lives in
the common dir, so one write covers both sides and every worktree. `minimal`
reduces the stat check to whole-second mtime + file size — the two fields the
bind mount preserves — making the index portable in both directions;
`trustctime = false` guards against ctime-only divergence from metadata
changes (chmod/chown) one side doesn't observe. Known trade-off: a same-size
edit landing in the same whole second as the last index refresh can evade stat
detection; git's racy-index protection (entries at least as new as the index
get content-checked) covers the realistic window.

`devcontainer.yml`'s smoke job asserts the setting landed via `git config
--file .git/config` (the `--file` skips repo discovery, which would trip git's
dubious-ownership check since the runner uid differs from the container uid).
That assertion doubles as proof that `devcontainers/ci` **does** run
`initializeCommand` during `up` — distinct from the Dockerfile *build* phase,
which precedes it and therefore can't see the gitignored `.git-plumbing/`
runtime files (why those consumers guard with `[ -s … ]`).

### Signed commits under devcontainer CLI

The repo's branch protection requires signed commits, and the host signs with
**SSH** (`gpg.format = ssh`, `commit.gpgsign = true`, no explicit
`user.signingkey` — `gpg.ssh.defaultKeyCommand` shells out to `ssh-add -L`).
That makes two things load-bearing inside the container: a usable ssh-agent
socket the in-container `git` can reach, and the host's `~/.gitconfig`.
VS Code's Dev Containers extension supplies both automatically — it forwards
the host ssh-agent through the VS Code Server's own SSH tunnel (a per-user
socket published by the server process, *not* Docker Desktop's magic socket
— that mount isn't even present in extension-launched containers) and
copies the host gitconfig between `postCreate` and `postStart`. The
`devcontainer` CLI does neither. The fix is five additive pieces — the first
three for signing itself, the last two for the adjacent SSH operations
(host-key trust on push, allowed-signers trust on verify):

- **SSH agent** — `devcontainer.json` binds Docker Desktop's magic socket
  `/run/host-services/ssh-auth.sock` (Desktop's documented mechanism for
  exposing the host's `ssh-agent` to any container on macOS) and sets
  `SSH_AUTH_SOCK` via `containerEnv`. The macOS launchd path
  (`/var/run/com.apple.launchd.*/Listeners`) is *not* used: it's
  unreachable inside the container and rotates across reboots. Trade-off:
  the mount is Docker-Desktop-specific and would dangle under colima /
  OrbStack / podman. A socat-based engine-agnostic relay is the known
  alternative; not worth the setup until a non-DD engine is on the table.
  Docker Desktop intercepts that path even though it isn't physically on
  the host; on other engines it isn't intercepted *and* doesn't exist, so
  the bind would fail at container start. `initialize.sh` checks
  `docker info` for "Docker Desktop"; if absent it `sudo touch`es a
  placeholder at the magic path so the bind succeeds (agent forwarding
  won't be functional there, which is fine — CI's smoke job just needs
  the container to start).
- **SSH agent socket ownership** — Docker Desktop bind-mounts the magic
  socket root-owned mode 660. The remoteUser is `vscode` (uid 1000), so
  it can't connect to a root-owned socket. `post-start.sh` `chown`s it to
  the current user (vscode has passwordless sudo in the
  `devcontainers/base:debian` image). Has to happen on every container
  start, because the bind-mounted socket is re-created root-owned each
  time. Harmless under VS Code, which uses its own tunneled socket and
  ignores the magic one entirely.
- **`~/.gitconfig`** — `initialize.sh` writes a snapshot to
  `.git-plumbing/host-gitconfig`. `post-start.sh` copies it to
  `$HOME/.gitconfig` *only if that file is missing or empty*.
  `postStartCommand` runs after the Dev Containers extension's own
  gitconfig copy, so the empty-check naturally lets VS Code win when
  it's involved; CI's `devcontainer build` never reaches postStart, so
  the file is absent there and the script is a clean no-op. Same
  lifecycle/buildx-safety story as `host-git-common-path` and
  `host-timezone` — gitignored, regenerated every `up`, anchored by the
  tracked `.git-plumbing/README.md`.
- **`~/.ssh/known_hosts`** — `initialize.sh` snapshots it to
  `.git-plumbing/host-known-hosts`; `post-start.sh` installs it to
  `$HOME/.ssh/known_hosts` under the same missing-or-empty guard. Without
  it, in-container `git push`/`fetch` over the SSH `origin`
  (`git@github.com:…`) fails "Host key verification failed" — the base
  image's `$HOME/.ssh` is empty and SSH refuses unknown fingerprints. The
  ssh-agent forwarding above proves *who* you are; `known_hosts` proves the
  server *is* GitHub, the separate second half SSH needs.
- **`~/.ssh/allowed_signers`** — `initialize.sh` snapshots the file *named
  by* `gpg.ssh.allowedSignersFile` (the setting is authoritative, not a
  hardcoded `~/.ssh` path); `post-start.sh` installs it to
  `$HOME/.ssh/allowed_signers` and repoints the config there. Without it
  `git verify-commit` / `--show-signature` reports `U` ("Unable to open
  allowed keys file…" / "No principal matched") — a good-but-untrusted
  signature — because the copied gitconfig's `allowedSignersFile` names a
  host path not mounted in the container. Signing itself never reads the
  file, which is why commits still sign fine and only verification broke.
  The repoint is keyed on the installed file (not "did we just copy it") so
  it also fixes the VS Code path, which bridges the gitconfig but never the
  file it names.

The two `~/.ssh` installs share an `install_ssh_snapshot` helper in
`post-start.sh` (the missing-or-empty guard + `mkdir`/`chmod 700 ~/.ssh` +
`chmod 644` trio, otherwise duplicated verbatim). Neither snapshot carries
secret material — `known_hosts` is public server fingerprints,
`allowed_signers` is one line of public key plus principal email — so the
gitignored build context (the Dockerfile COPYs the whole `.git-plumbing/`
directory) is an appropriate home, same as `host-gitconfig`.

### Devcontainer lock regeneration

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
PRs for a lock that never silently ages behind a floating tag.

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
tested in `tests/python/test_regenerate_devcontainer_lock.py`; the driver's
subprocess wiring is exercised by the workflow on real Renovate PRs.

`.github/workflows/renovate-devcontainer-lock.yml` runs it: on `pull_request`
touching `.devcontainer/devcontainer.json`, gated to `github.actor ==
'renovate[bot]'`, it installs `@devcontainers/cli`, runs the script, and commits
the regenerated lock back onto the PR branch. The commit is made by the
**`commit-file-via-app` composite action referenced cross-repo from the public
`Syndic/unnatural_designs` repo** (`@main` — that repo has no tags to pin-track,
and the user owns it and keeps it stable). Floating on `@main` means changes to
the action reach this repo without review; the failure mode is a red check on
the next Renovate devcontainer PR, not a silent break. The action's README (in
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
install.sh), CI (`python-version: '3.9'` in `.github/workflows/tests.yml`),
and the devcontainer (`uv venv --python 3.9.6` in `.devcontainer/post-create.sh`,
pinned to the exact CLT patch). Keep all three in step.

The devcontainer provisions Python with **uv**, not the devcontainers `python`
feature. uv fetches prebuilt CPython from python-build-standalone — including
3.9.6 — so the frozen pin costs a download, not a from-source compile (the bulk
of the old startup time; the feature compiled both interpreters every build).
uv is baked into the image in `.devcontainer/Dockerfile`
(`COPY --from=ghcr.io/astral-sh/uv:<pin>`); `post-create.sh` drives it.

`post-create.sh` builds three venvs in parallel: `~/.venv` (the frozen 3.9.6 —
pytest + the default `python3` on PATH), `~/.venv-ansible` (the Ansible dev
stack — `ansible`, `ansible-lint`, `molecule`, the docker driver — all in one
venv so they share the single ansible-core and its bundled collections; a second
collection copy is what produced the duplicate-version warnings, #46/#48), and a
`uv tool` venv for `pre-commit`. The Ansible stack is a plain venv rather than
`uv tool` because only a venv exposes every package's entry points
(`ansible-playbook`, `ansible-galaxy`, `ansible-lint`, `molecule`); `uv tool`
exposes the primary package's scripts only. Their bin dirs are put on PATH via
`remoteEnv` in `devcontainer.json` — keep that layout and `post-create.sh` in
step.

The Ansible-tooling interpreter is `tooling_python` in `post-create.sh` (it just
needs >= 3.10) — not part of the pin. Renovate keeps it current while leaving
`3.9.6` frozen; the wiring is in `renovate.json` (a `customManager` for
`tooling_python`, matching only the annotated assignment so the frozen 3.9.6 in
the same file is never touched, plus a second `customManager` keeping the
molecule CI job's `python-version` in tests.yml in step). The frozen 3.9.6 lives
in plain `uv venv --python 3.9.6` / `uv pip install` lines that no Renovate
manager matches, so it stays put without a disable rule.

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

## Lint

`yamllint` and `ansible-lint` gate every PR via the `lint` job in
`tests.yml` and run locally as pre-commit hooks. Configs:

- `ansible.cfg` (repo root) — shared pins: `inventory`, `roles_path`,
  `stdout_callback`. All invocations of `ansible*` / `ansible-lint` pick
  this up automatically, so devcontainer, CI, and bare-host runs agree.
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
`~/.venv-ansible` uv venv `post-create.sh` builds, alongside ansible itself,
so they share the bundled collections). The pre-commit hooks pin yamllint
and ansible-lint to specific tags; Renovate's pre-commit manager keeps
both `rev:` values current.

Adding a new YAML file or role: it'll get linted automatically. If a
rule flags something genuinely wrong with the *rule* (not the code),
update `.yamllint` / `.ansible-lint` rather than scattering `# noqa`
markers.

## Tests

Required for behavior changes. Three suites: bats (bash), pytest (Python),
and molecule (per-role Ansible scenarios). Lint runs as a fourth suite
(`./tests/run lint`); see the section above.

Run them from the devcontainer (`bats` comes from `.devcontainer/Dockerfile`;
`.devcontainer/post-create.sh` builds the uv venvs holding pytest, pre-commit,
molecule, ansible-lint, and yamllint).

```sh
./tests/run                          # everything (python + bash + lint + molecule)
./tests/run fast                     # python + bash + lint (skip molecule — no docker)
./tests/run python                   # pytest only
./tests/run bash                     # bats only
./tests/run lint                     # yamllint + ansible-lint
./tests/run molecule                 # all molecule roles, serial (needs docker)
./tests/run molecule <role>          # one role's scenarios (used by the CI matrix)
```

`tests/run` imports `announce` / `info` / `warn` / `die` from
`_dotfiles_common` so the bracket-style banners stay consistent with
the bootstrap.

**Multi-suite invocations (`all`, `fast`) run every suite in parallel**,
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

Single-suite invocations (`./tests/run python`, etc.) preserve fail-fast
semantics — no parallelism, no summary, exit code propagates directly.

Two trade-offs the parallel mode pays:

1. **Run-all-then-summarize.** A failing earlier suite no longer aborts
   the run, so the others still run against a tree that may already be
   invalid. The full picture is worth more than the early abort.
2. **Homebrew base image prep is lifted out of the molecule shard** and
   runs serially before the parallel block starts. Parallel `docker build`
   / `docker tag` against the same `:local` tag would race, and the bash
   shards' output would interleave on stdout (we buffer per-suite, but the
   docker daemon writes to its own log streams). The summary's
   `molecule:homebrew` time then reflects test work only, not image prep
   — arguably more honest, but worth knowing when comparing wall-clocks
   against pre-parallel runs.

CI runs all three on Ubuntu as separate `pull_request` jobs. Molecule lives
under `roles/<role>/molecule/<scenario>/` per role; today the dotfiles, apt,
flatpak, and homebrew roles are covered. Most roles have a single `default/`
scenario; **homebrew has three** (`default`, `multi_layer`, `gates`) — see
"Homebrew molecule scenarios" below. The bare `./tests/run` runs everything;
use `./tests/run fast` when you don't have Docker (or don't want to pay the
~5-min molecule cost) and just need the python/bash gates.

**Molecule CI is sharded across roles** via a `strategy.matrix` in
`tests.yml` — one runner per role, all in parallel. The previous single
job was wall-clock-bound by the slowest role (homebrew, which builds a
Linuxbrew base image inline); sharding lets the lighter roles return in
1-2 min while homebrew runs in its own cell. The roles list is duplicated
in two places — `MOLECULE_ROLES` in `tests/run` for local serial runs, and
`matrix.role` in `tests.yml` for CI shard discovery — adding a new molecule-
covered role requires updating both. **`tests/python/test_molecule_role_lists_agree.py`
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

### Homebrew molecule scenarios

Three scenarios under `roles/homebrew/molecule/`, all sharing a single
base image built locally by `./tests/run molecule` from
`roles/homebrew/molecule/Dockerfile` and tagged
`dotfiles-homebrew-molecule:local`. The image bakes Linuxbrew + a
pre-installed `hello` formula; building it cold costs ~5 min, but the
docker layer cache makes rebuilds near-free locally. CI pays the cold-
build cost every run today — a followup will bake-and-publish to ghcr so
CI pulls instead. Each scenario references the tag with
`pre_build_image: true`.

The image deliberately diverges from the apt/dotfiles/flatpak base
(`geerlingguy/docker-debian12-ansible`): the homebrew role has no
`become:` and doesn't manage services, so a plain `debian:bookworm-slim`
with `python3` and a non-root `linuxbrew` user (brew refuses to run as
root on Linux) is enough. Scenarios connect ansible via
`ansible_user: linuxbrew` in `provisioner.inventory.host_vars`.

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
  if that breaks, the assertions in `verify.yml` fail.
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

- **Pull from ghcr** when `MOLECULE_HOMEBREW_IMAGE` is set. CI sets it
  on the homebrew matrix cell to
  `ghcr.io/syndic/dotfiles-homebrew-molecule:latest` (lowercased; ghcr
  requires it). The published image is built + pushed by
  `.github/workflows/publish-molecule-images.yml` on pushes to `main`
  that touch the Dockerfile, **plus a monthly `schedule:` rebuild** that
  bounds base-image staleness so the gates scenario's upgrade path
  doesn't accumulate `brew upgrade` work as the baked formulae drift
  from live upstream.
- **Local `docker build`** otherwise (no env var) or as a fallback when
  the pull fails (registry hiccup, image not yet published, PR that
  changes the Dockerfile and therefore needs the *modified* version
  tested rather than the published one).

The fallback is load-bearing for that last case: a PR editing the
Dockerfile must be tested against its own Dockerfile, not the `:latest`
published from main. The pull is best-effort; failure quietly drops to
build. Don't replace it with a hard pull — that would couple PR CI to
the publish workflow having already shipped, and break Dockerfile-
editing PRs.

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
