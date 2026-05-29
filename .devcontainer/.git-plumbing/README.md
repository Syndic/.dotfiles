# Devcontainer git plumbing

Holds host-generated artifacts that bridge the host's git layout into the
devcontainer image. Currently one file:

- `host-git-common-path` — gitignored, written on every `devcontainer up` by
  `../initialize.sh`. Contains the absolute path of the host's git common
  directory (`git rev-parse --git-common-dir`). The Dockerfile reads it at
  build time and recreates that same host-absolute path inside the image as
  a symlink to `/host-git-common`, so a worktree's `.git` file resolves
  natively in-container. See `../initialize.sh` and `../Dockerfile` for the
  full mechanism, and the "Worktree git resolution" section in the repo's
  `CLAUDE.md` for the why.

This directory exists in git (via this README) so the Dockerfile's
`COPY .devcontainer/.git-plumbing/ …` step always finds a source — buildx
errors on a COPY whose glob matches zero files, and CI's `devcontainer
build` doesn't run `initializeCommand`, so the path file is absent there.
The tracked README makes the COPY a guaranteed no-op in that case while
keeping the runtime-generated path file out of the index.
