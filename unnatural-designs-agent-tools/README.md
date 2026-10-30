# unnatural-designs-agent-tools

A Claude Code plugin that is also its own one-plugin marketplace. It holds machine-scoped
workflow skills. Everything it needs lives in this folder, so it can move to its own repo
unchanged.

| Path | What's there |
|------|--------------|
| `.claude-plugin/` | `marketplace.json` (one entry, `source: "./"`) and `plugin.json`. |
| `skills/` | One directory per skill; each runs as `/unnatural-designs-agent-tools:<name>`. |
| `scripts/` | Helpers the skills run, as `${CLAUDE_PLUGIN_ROOT}/scripts/...`. |
| `tests/` | pytest suites for `scripts/`. |

## Skills

- **`rebase-branch-on-origin-main`**: rebases the current branch onto `origin/main`, checks
  that commits are still signed, then force-pushes with lease.
- **`dev-cleanup`**: reaps what archived sessions leave behind, across the whole machine. It is
  user-invoked only (`disable-model-invocation`), and has no hooks or schedules.

## dev-cleanup design

`scripts/dev_cleanup.py` runs **on the host** and uses only the Python standard library, so
nothing needs installing. It refuses to run inside a container: there, the host's other
worktrees look missing and would be unregistered as stale. The script has two
subcommands:

- `inventory` prints JSON items, each tagged `auto` (done without asking), `confirm` (ask
  first) or `report` (shown, never acted on).
- `apply --ids` acts on named ids only.

`apply` first recomputes the inventory and acts only on ids still present at an actionable
tier. Worktree, stale-entry, branch and container ids pin the state they were classified in
(the worktree HEAD and the devcontainers running on it, the branch tip, the container run
state), so a change since the report makes the id disappear and the item is skipped rather than
re-guessed. Image ids are content digests and volume ids are names, so for those the recomputed
tier is the check: an image a container picked up since the report is no longer offered. Folder
ids are report-only.
The actions themselves also fail closed:
- `git worktree remove` runs without `--force`, after `apply` re-reads the worktree's status.
  Both count untracked files whatever `status.showUntrackedFiles` says. Git unregisters a
  worktree before deleting it, so a read-only directory can stop it halfway. Only then, once
  git has approved the removal, does `apply` give the leftovers `u+rwx` (symlinks aren't
  followed) and delete them. A removal git refuses leaves the worktree's files and
  permissions as they were.
- A branch is deleted with `git update-ref -d <ref> <expected-tip>`.
- `docker rm -v` and `docker rmi` run without `-f`.
- An image is skipped while any container still uses it.

**Discovery.** The script scans each worktree root: `~/Work/worktrees`, plus `extra_roots`.
Layouts can be `<root>/<repo>/<worktree>` or `<root>/<worktree>`, and hidden repo directories
such as `.dotfiles` are included. It resolves each folder to its main checkout and adds
`extra_repos`. Folders that git doesn't register are reported, never removed: they may hold
the only copy of some work. Only what sits under a worktree root, or is a worktree git lists,
is ever acted on; a container or image whose folder is missing anywhere else (an unmounted
volume, a moved repo) is reported.

**Branches and worktrees.** These repos squash-merge, so `git cherry` and
`git branch --merged` say nothing useful. The ground truth is `gh pr list` (one bulk call per
repo, falling back to per-branch `--head` queries if the bulk call may have been truncated).
Worktree folder names don't match branch names, so matching goes through each worktree's
checked-out branch. Only these are offered:
- a merged PR whose head contains the local tip;
- a detached, clean worktree whose HEAD is on the default branch;
- a local `pr-NNN` copy of a merged or closed PR.

Dirty worktrees (tracked changes or untracked files) and unpushed commits are never offered.
Gitignored files never count as work: `git worktree remove` deletes them with the worktree.
Removing a worktree also deletes its branch. A devcontainer still running on it is handled in
this order: stop it, re-check the worktree (so files it wrote while running or shutting down
count), `git worktree remove`, then `docker rm -v`. If any step fails, the worktree and the
stopped container both stay. A running container never holds back a worktree that is otherwise
offered, because the `devcontainer` CLI leaves containers running after their session ends; the
reason shows how long each has been up, so one still in use (attached in an editor, running
tests) stands out.

A registered worktree whose folder is missing is unregistered one entry at a time
(`git worktree remove` on the missing path, which needs no `--force`), never with a
repo-wide `git worktree prune`. It is auto-tier under a worktree root and confirm-tier
anywhere else.

**Session guard.** One worktree serves many sessions. It is offered only when every Claude
desktop session whose `cwd` is inside it is archived. The skill passes in the session rows,
plus the current session, which the session list omits; the script also protects its own
cwd. A worktree with no known session is "your call". Without a session list, every
worktree is protected.

**Docker.** A devcontainer follows its worktree, matched through the
`devcontainer.local_folder` label:
- worktree gone and container stopped: auto;
- worktree gone and container running: confirm;
- worktree still there: left alone, because removing the container would destroy its
  anonymous volumes. A running one goes with its worktree when that is removed (above).

A `vsc-<basename>-<hash>` image carries no folder label, but its hash is `sha256(<folder
path>)`. So the script hashes candidate paths to prove the folder, and an image it can't
map is reported only. For `devcontainer-base` images (`base_image_pattern`), it keeps every
digest or tag that any checkout's devcontainer setup mentions (everything under
`.devcontainer/`, a root `.devcontainer.json`, and the Dockerfiles and compose builds those
name), any image a container uses, and the newest in each repository. The rest go to the
confirm tier, or are only reported if some named file couldn't be found. Ownerless
anonymous volumes and unreferenced dangling images are auto.

The `docker-in-docker` feature mounts two named volumes per devcontainer,
`dind-var-lib-{docker,containerd}-<devcontainerId>`, which `docker rm -v` leaves behind. They
are only considered once Docker lists them as dangling (no container mounts them):
- mounted by a container this `apply` removed (read from its `Mounts`): auto;
- traced to a worktree that is gone: confirm (reported outside the worktree roots);
- traced to a worktree that still exists: left alone, since its next `devcontainer up`
  reuses them;
- not traceable: confirm.

The trace recomputes the CLI's `devcontainerId` (base-32 `sha256` of the folder and config
file labels as sorted JSON) for each known folder's standard config paths.

Removing a worktree in `apply` exposes its container and image, and removing a container
exposes its docker-in-docker volumes, so `apply` then reaps what became auto (repeating until
nothing new appears) and returns the rest as `follow_up`.

**Never touched:** remote branches, volume contents, `docker system prune` /
`docker builder prune`, image pulls, or sessions. The report still sizes what it leaves
alone: other tools' images and named volumes (docker-in-docker volumes still mounted or
traced to a live worktree among them), the build cache, host caches,
`~/.claude/projects`, Codex worktrees, and `Docker.raw` on disk (measured with `du`, because
the file is sparse).

**Config.** `~/.config/unnatural-designs-agent-tools/dev-cleanup.json` (optional) overrides
any key in `DEFAULT_CONFIG` at the top of the script. Unknown keys and wrongly typed values
are rejected.
