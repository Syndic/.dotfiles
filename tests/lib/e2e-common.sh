# Shared Docker plumbing for the Linux e2e harnesses.
# Sourced by tests/e2e-linux.sh (install-only) and tests/e2e-roundtrip-linux.sh
# (install ↔ uninstall round-trip). Not executable on its own.
#
# Provides:
#   e2e_require_docker
#       Verify the docker CLI and a reachable daemon. Exits 2 if either is
#       missing, with a message pointing at Docker Desktop / Colima.
#
#   e2e_run_in_container REPO_ROOT IMAGE HOST_PROFILE PAYLOAD_FILE [EXTRA_MOUNT ...]
#       Snapshot REPO_ROOT into a tarball, mount it read-only into a fresh
#       container of IMAGE, bootstrap a non-root sudo `testuser`, stage the
#       repo at /srv/source as that user with `git init`+commit, then run
#       PAYLOAD_FILE (a shell script on the host, mounted at /srv/payload.sh)
#       as testuser. The payload runs with these env vars already exported:
#         HOST_PROFILE, COLORTERM, COLUMNS, DOTFILES_REPO=/srv/source
#       Any EXTRA_MOUNT args are passed verbatim as `docker -v` strings
#       (e.g. "/host/path:/container/path:ro").
#
# Quirks preserved from the original tests/e2e-linux.sh — change with care:
#
#   - The repo is extracted as testuser (not root-extract-then-chown) to dodge
#     git >=2.35.2's "dubious ownership" check, which trips on macOS tarballs
#     whose `./` entry carries UID 501.
#
#   - COLORTERM/COLUMNS are re-injected on the `su - testuser -c "..."`
#     command line because login-mode `su` clears the env (only TERM survives
#     per `man su --whitelist-environment`). Without this, phase2.py falls
#     back to 256-color / 80-cols when rendering the splash.

# shellcheck shell=bash

e2e_require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "error: docker not found in PATH. Install Docker Desktop / Colima first." >&2
    exit 2
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "error: docker daemon not reachable. Start Docker Desktop / Colima first." >&2
    exit 2
  fi
}

# Populated by e2e_run_in_container so the caller's EXIT trap can clean up.
e2e_TMP_DIR=""

e2e_run_in_container() {
  local repo_root="$1"
  local image="$2"
  local host_profile="$3"
  local payload_file="$4"
  shift 4
  # Remaining args are extra `docker -v` mount specs (host:container[:opts]).

  e2e_TMP_DIR="$(mktemp -d)"
  local tarball="$e2e_TMP_DIR/dotfiles.tar"
  # --no-xattrs: macOS BSD tar writes com.apple.provenance (and similar
  # Gatekeeper xattrs) into the tarball as PAX headers, which GNU tar inside
  # the Debian container then complains about per-file ("Ignoring unknown
  # extended header keyword 'LIBARCHIVE.xattr.com.apple.provenance'").
  # Cosmetic, but spammy. Skipping the xattrs at write time silences it
  # cleanly; we don't need them in the container either way. Both bsdtar
  # and GNU tar accept --no-xattrs.
  tar --no-xattrs --exclude='./.git' --exclude='./.claude' \
      -cf "$tarball" -C "$repo_root" .

  # The payload runs as `testuser` inside the container (different UID than
  # the host user that created it). `mktemp` creates files mode 0600, so the
  # bind-mounted payload would be unreadable to testuser and `bash /srv/payload.sh`
  # would die with "Permission denied". The payload is just shell commands —
  # nothing secret — so world-readable is fine.
  chmod 0644 "$payload_file"

  local -a docker_args=(
    run --rm
    -v "$tarball:/srv/dotfiles.tar:ro"
    -v "$payload_file:/srv/payload.sh:ro"
    -e HOST_PROFILE="$host_profile"
    -e COLORTERM=truecolor
    -e COLUMNS=160
  )
  local mount
  for mount in "$@"; do
    docker_args+=( -v "$mount" )
  done
  docker_args+=( "$image" bash -euo pipefail -c '
    apt-get update >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      sudo tar git ca-certificates >/dev/null

    # Linuxbrew refuses to run as root, so the payload runs as a non-root
    # user with passwordless sudo.
    useradd -m -s /bin/bash testuser
    echo "testuser ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/testuser
    chmod 0440 /etc/sudoers.d/testuser

    mkdir -p /srv/source
    chown testuser:testuser /srv/source

    # See the file header for why extract+commit must happen as testuser,
    # and why COLORTERM/COLUMNS are re-injected here.
    su - testuser -c "
      set -euo pipefail
      cd /srv/source
      tar -xf /srv/dotfiles.tar
      git init -q -b main
      git -c user.email=e2e@e2e -c user.name=e2e add -A
      git -c user.email=e2e@e2e -c user.name=e2e commit -q -m \"e2e snapshot\"
      export COLORTERM=$COLORTERM COLUMNS=$COLUMNS DOTFILES_REPO=/srv/source HOST_PROFILE=$HOST_PROFILE
      bash /srv/payload.sh
    "
  ' )

  docker "${docker_args[@]}"
}
