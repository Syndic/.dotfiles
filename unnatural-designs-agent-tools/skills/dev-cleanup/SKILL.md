---
name: dev-cleanup
description: Reap worktrees, merged branches, devcontainer containers and images, superseded devcontainer-base images, and ownerless anonymous Docker volumes left behind by archived Claude Code sessions, machine-wide. Reports first and asks per tier before deleting anything.
disable-model-invocation: true
---

Clean up after archived Claude Code sessions on this machine. The script does all
discovery and every deletion; your job is to feed it the session list, present
its report, collect the user's choices, and pass back exactly the ids they chose.

Script: `${CLAUDE_PLUGIN_ROOT}/scripts/dev_cleanup.py` (Python standard library;
run it with `python3` on the host, never inside a container — it refuses).

## 1. Collect sessions (the session guard)

A worktree is offered for removal only when every Claude desktop session that
used it is archived. Only you can read sessions:

1. Call `mcp__ccd_session_mgmt__list_sessions` with `include_archived: true` and
   `limit: 1000`. If the result count equals the limit, the list may be
   truncated: treat sessions as unavailable (step 3).
2. Write the rows to a temp file as `{"available": true, "sessions": [...rows]}`,
   or pass the tool's saved result file directly if the output overflowed (a bare
   JSON array is accepted). Add a row for **this** session — the list omits it:
   `{"cwd": "<your cwd>", "isArchived": false, "isRunning": true}`.
3. If the tool isn't available (for example in the CLI), don't fabricate rows:
   omit `--sessions`. Every worktree is then protected and the rest still runs.

Never archive, unarchive, delete, or otherwise manage sessions.

## 2. Inventory

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dev_cleanup.py" inventory --sessions <file>
```

It runs `git fetch --prune` in each discovered repo (an auto-tier step), then
prints JSON: `items` (each with `id`, `kind`, `tier`, `title`, `reason`,
`size_bytes`, `age_days`), `summary` (sizes of things it never touches), and
`notes`.

## 3. Present one report

Group by tier, and within a tier by kind. Show sizes in human units, and ages in days.

- **Auto — runs without asking**: `tier: auto` (stale worktree entries, stopped
  containers whose worktree is gone, dangling images, ownerless anonymous volumes).
- **Needs your OK**: `tier: confirm`, one group per kind (worktrees — each also
  deletes its branch, and stops any devcontainer its `reason` names — show each
  one's uptime from the reason, since a recently started one may still be in use;
  branches; containers; images). Number the items.
- **Your call — never touched**: `tier: report`, with each `reason` and age
  (closed/no-PR/open/dirty/unpushed branches and worktrees, worktrees holding
  gitignored files, unregistered folders, Codex
  worktrees, unmapped images, anything outside the worktree roots).
- **Space**: from `summary` — `docker_raw_bytes`, `build_cache_bytes` (self-capped
  by Docker's GC; not pruned here), `untouched_docker`, `host_caches`,
  `claude_projects_bytes` (transcripts back archived-session restore),
  `codex_worktrees`, `base_images_kept`.

Then ask once per confirm group: all, none, or all except the numbers the user
lists. Don't ask about the auto tier.

## 4. Apply

Pass every auto id plus the confirmed ids, verbatim:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dev_cleanup.py" apply --sessions <file> --ids <id> ...
```

`apply` recomputes the inventory and acts only on ids still present at an
actionable tier; anything that changed since the report is skipped. Report `done`, every
`skipped` entry with its reason, and Docker.raw before → `docker_raw_bytes_after`.

If `follow_up` is non-empty (removing a worktree exposed its devcontainer image or
a running container), present those items the same way, ask, and run `apply` again
with the chosen ids.

## Never

Touch remote branches; read or write volume contents; run `docker system prune`,
`docker builder prune`, or `docker pull`; force any removal (`-f`/`--force`);
pass an id the user didn't confirm (apart from auto-tier ids); or manage sessions.
