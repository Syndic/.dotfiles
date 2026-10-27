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
worktrees look missing, and a `git worktree prune` would unregister them. The script has two
subcommands:

- `inventory` prints JSON items, each tagged `auto` (done without asking), `confirm` (ask
  first) or `report` (shown, never acted on).
- `apply --ids` acts on named ids only.

`apply` first recomputes the inventory, and every id embeds the state it was classified in:
the worktree HEAD, the branch tip, the container run state. So a predicate that changed
since the report makes the id disappear, and the item is skipped rather than re-guessed.
The actions themselves also fail closed:
- `git worktree remove` runs without `--force`.
- A branch is deleted with `git update-ref -d <ref> <expected-tip>`.
- `docker rm -v` and `docker rmi` run without `-f`.
- An image is skipped while any container still uses it.

**Discovery.** The script scans each worktree root: `~/Work/worktrees`, plus `extra_roots`.
Layouts can be `<root>/<repo>/<worktree>` or `<root>/<worktree>`, and hidden repo directories
such as `.dotfiles` are included. It resolves each folder to its main checkout and adds
`extra_repos`. Folders that git doesn't register are reported, never removed: they may hold
the only copy of some work.

**Branches and worktrees.** These repos squash-merge, so `git cherry` and
`git branch --merged` say nothing useful. The ground truth is `gh pr list` (one bulk call per
repo, falling back to per-branch `--head` queries if the bulk call may have been truncated).
Worktree folder names don't match branch names, so matching goes through each worktree's
checked-out branch. Only these are offered:
- a merged PR whose head contains the local tip;
- a detached, clean worktree whose HEAD is on the default branch;
- a local `pr-NNN` copy of a merged or closed PR.

Dirty worktrees and unpushed commits are never offered. Removing a worktree also deletes
its branch.

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
  anonymous volumes.

A `vsc-<basename>-<hash>` image carries no folder label, but its hash is `sha256(<folder
path>)`. So the script hashes candidate paths to prove the folder, and an image it can't
map is reported only. For `devcontainer-base` images (`base_image_pattern`), it keeps every
digest or tag any checkout's `.devcontainer/Dockerfile` mentions, any image a container
uses, and the newest in each repository. The rest go to the confirm tier. Ownerless
anonymous volumes and unreferenced dangling images are auto. Removing a worktree in `apply`
exposes its container and image, so `apply` then reaps what became auto and returns the
rest as `follow_up`.

**Never touched:** remote branches, volume contents, `docker system prune` /
`docker builder prune`, image pulls, or sessions. The report still sizes what it leaves
alone: other tools' images and named volumes, the build cache, host caches,
`~/.claude/projects`, Codex worktrees, and `Docker.raw` on disk (measured with `du`, because
the file is sparse).

**Config.** `~/.config/unnatural-designs-agent-tools/dev-cleanup.json` (optional) overrides any key in
`DEFAULT_CONFIG` at the top of the script.
