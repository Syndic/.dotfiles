# dotfiles

Joshua Yanchar's dotfiles, managed with Ansible. Supports macOS and
Debian/Ubuntu Linux.

## Install

```bash
curl -fsSL https://install.yanch.ar | bash -s -- --host PROFILE
```

Replace `PROFILE` with one of the host profiles in [`host_vars/`](host_vars).
Works on a fresh machine or one that's been bootstrapped before — re-runs
are idempotent.

If you leave off `--host`, you'll be prompted to pick a profile
interactively (assuming you have a terminal).

## What it does

The bootstrap shim:

1. Installs platform-specific phase-2 prereqs:
   - **macOS**: Xcode Command Line Tools (needed for `git` and `python3`).
   - **Debian/Ubuntu**: `git`, `python3`, `curl`, `ca-certificates`, plus
     Homebrew's Linux build deps.
2. Clones this repo to `~/.dotfiles`.
3. Hands off to `phase2.py`, which installs Homebrew (Linuxbrew on Linux),
   installs Ansible via brew, and runs the playbook against the selected
   host profile.

The Ansible playbook is what actually configures the machine —
brew/apt/flatpak package installs, dotfile symlinks, macOS preferences,
certs, SSH config. The bash + Python layers are just bootstrap; most
behavior lives in the roles under [`roles/`](roles).

If you're modifying this code, see [CLAUDE.md](CLAUDE.md) for the
invariants that matter (two-language split, sudo flow, output buffering,
package-layering naming convention, etc.) before touching anything
load-bearing.

## Where things live

| Path | What's there |
|------|--------------|
| `install.sh`, `phase2.py` | The two-phase bootstrap. |
| `site.yml`, `inventory.yml` | Ansible entry point + host inventory. |
| `group_vars/`, `host_vars/` | Variable scopes for the playbook. |
| `roles/` | Roles that do the work: `homebrew`, `apt`, `flatpak`, `dotfiles`, `certs`, `ssh`, `macos_defaults`. |
| `brewfiles/` | Layered Homebrew package lists — `common.Brewfile` + `groups/<group>.Brewfile` + `hosts/<host>.Brewfile`. Used on both macOS and Linuxbrew (casks silently skip on Linux). |
| `home_source/common/`, `home_source/hosts/<host>/` | Source tree the `dotfiles` role symlinks into `$HOME`. Host files override common files at the same path. |
| `tests/` | bats + pytest unit suites, plus `tests/e2e-linux.sh` for full end-to-end runs in a fresh Debian container. |
| `.devcontainer/` | Debian devcontainer with ansible / ansible-lint / pytest / pre-commit pre-installed. |

## Common tasks

### Add or change a dotfile

Drop the file under `home_source/common/<path>` (mirroring its location
under `$HOME`). For host-specific overrides, use
`home_source/hosts/<host>/<path>`. Then re-run the install command — the
`dotfiles` role builds the effective tree (host files override common at
the same path), backs up any conflicting file in `$HOME` to
`<name>.backup-N`, and replaces it with a symlink into the repo. Use
`dotfiles_excludes` in host_vars to drop a common-only path on a
specific host without needing a placeholder file.

### Add a package

| Goal | Where it goes |
|------|---------------|
| Cross-platform CLI tool via Homebrew (works on macOS and Linuxbrew) | `brewfiles/common.Brewfile` |
| Group-scoped (personal vs work) | `brewfiles/groups/<group>.Brewfile` |
| Host-specific | `brewfiles/hosts/<host>.Brewfile` |
| macOS-only GUI app | `cask "..."` line in any Brewfile (silently skipped on Linux) |
| Linux-only system package | `common_apt` in `group_vars/all.yml`, `group_purpose_apt` in `group_vars/<group>.yml`, or `host_apt` in `host_vars/<host>.yml` |
| Linux GUI app via Flatpak | `common_flatpak` / `group_purpose_flatpak` / `host_flatpak` — same three-layer shape as apt |

Full variable-naming convention is in [`group_vars/all.yml`](group_vars/all.yml).

### Add a new host

1. Add `host_vars/<hostname>.yml`. For a macOS host: set `host_brewfile`
   pointing at the host's Brewfile. For a Linux host: also set `host_apt:
   [...]` and `host_flatpak: [...]` if the host needs anything beyond the
   common/group layers.
2. Add `brewfiles/hosts/<hostname>.Brewfile`.
3. List the hostname under one purpose group in `inventory.yml`
   (`personal` or `work`).
4. Run the install command above with `--host <hostname>` on the target
   machine.

## Tests

```bash
brew bundle --file=tests/Brewfile   # one-time: bats-core + pytest + pre-commit
./tests/run                         # both suites
./tests/run python                  # pytest only
./tests/run bash                    # bats only
pre-commit install                  # optional: install repo hooks
pre-commit run --all-files          # run hooks manually
```

The end-to-end Linux test runs the full `install.sh` → `phase2.py` →
playbook chain inside a fresh Debian container as a non-root sudo user.
It's slow (real Homebrew install + real `brew install ansible` + full
playbook), so it's never wired to push/PR — run it manually when you want
a real-Linux smoke test:

```bash
./tests/e2e-linux.sh                # local (requires Docker)
```

The same script runs in CI via the `workflow_dispatch` job at
[`.github/workflows/e2e-linux.yml`](.github/workflows/e2e-linux.yml) —
trigger it from the Actions tab.

## Dev environment

A Debian-based devcontainer is set up in [`.devcontainer/`](.devcontainer)
with Python 3.9.6 (matching the macOS CLT pin), the latest Python (for
ansible/ansible-lint), bats, pytest, and pre-commit pre-installed. Open
in VS Code with "Reopen in Container", or drive it from the CLI:

```bash
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . ansible-lint
```

## How the short URL works

`https://install.yanch.ar` is a Cloudflare redirect to the raw
`install.sh` on GitHub's `main` branch. `curl -fsSL` follows the redirect
(`-L`) and pipes the final response body to `bash`. Nothing on the
install URL needs to be updated when `install.sh` changes — the redirect
always resolves to whatever is on `main`.

### Cloudflare setup

In the Cloudflare dashboard for `yanch.ar`:

1. **DNS** → add a proxied (orange-cloud) record so the hostname resolves
   through Cloudflare. A `CNAME` for `install` pointing to `yanch.ar` (or
   any placeholder — Cloudflare answers before origin) works; the record
   just needs to exist and be proxied.
2. **Rules → Redirect Rules** → create a single-redirect rule:
   - **When incoming requests match**: `Hostname equals install.yanch.ar`
   - **Then**:
     - Type: **Static**
     - URL: `https://raw.githubusercontent.com/Syndic/.dotfiles/refs/heads/main/install.sh`
     - Status code: 301
     - Preserve query string: off
3. Test:
   ```bash
   curl -sSI https://install.yanch.ar          # should show 301 + Location header
   curl -fsSL https://install.yanch.ar | head  # should show install.sh contents
   ```
