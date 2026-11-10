# Devcontainer host-plumbing artifacts

Host state that `../initialize.sh` writes on every `devcontainer up`, for the
shared base image's plumbing to apply in-container. The files are gitignored;
this README keeps the directory in git. See "Devcontainer host plumbing" in the
repo's `CLAUDE.md`.

- `host-git-common-path` — absolute path of the host's git common directory.
  The plumbing recreates that path in-container as a symlink to the
  `/host-git-common` bind, so a worktree's `.git` file resolves natively.
- `host-timezone` — the host's IANA zone name (e.g. `America/Los_Angeles`).
  The plumbing points `/etc/localtime` at it. Empty keeps the container's
  default.
- `host-gitconfig` — snapshot of the host's `~/.gitconfig`. The plumbing
  installs it at `postStart`, only when `~/.gitconfig` is empty (the
  `devcontainer` CLI path; VS Code's Dev Containers extension copies it for
  itself).
- `empty-allowed-signers` — written only when the host has no readable
  `gpg.ssh.allowedSignersFile`, so the `.host-allowed-signers` bind has a
  target.

The host's `known_hosts` and allowed-signers file are not copied here: they
are bind-mounted through the `../.host-known-hosts` and
`../.host-allowed-signers` symlinks.
