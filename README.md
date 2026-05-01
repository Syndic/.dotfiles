# dotfiles

Joshua Yanchar's (macOS) dotfiles, managed with Ansible.

## Install

```bash
curl -fsSL https://install.yanch.ar | bash -s -- --host <profile>
```

Should work on a brand new mac, or one that has had this run before.

## Wait, what does it do?

The bootstrap shim will:

1. Install Xcode Command Line Tools (needed for `git` and `python3`).
2. Clone this repo to `~/.dotfiles`.
3. Hand off to `phase2.py`, which installs Homebrew + Ansible and runs the playbook.

## How the short URL works

`https://install.yanch.ar` is a Cloudflare redirect to the raw `install.sh` on GitHub's `main`
branch. `curl -fsSL` follows the redirect (`-L`) and pipes the final response body to `bash`.
Nothing on the install URL needs to be updated when `install.sh` changes - the redirect always
resolves to whatever is on `main`.

### Cloudflare setup

In the Cloudflare dashboard for `yanch.ar`:

1. **DNS** → add a proxied (orange-cloud) record so the hostname resolves through Cloudflare. A
   `CNAME` for `install` pointing to `yanch.ar` (or any placeholder — Cloudflare answers before
   origin) works; the record just needs to exist and be proxied.
2. **Rules → Redirect Rules** → create a single-redirect rule:
   - **When incoming requests match**: `Hostname equals install.yanch.ar`
   - **Then**:
     - Type: **Static**
     - URL: `https://raw.githubusercontent.com/Syndic/.dotfiles/refs/heads/main/install.sh`
     - Status code: 301
     - Preserve query string: off
3. Test:
   ```bash
   curl -sSI https://install.yanch.ar          # should show 302 + Location header
   curl -fsSL https://install.yanch.ar | head  # should show install.sh contents
   ```
