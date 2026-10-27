#!/usr/bin/env python3
"""Inventory and reap the cruft archived Claude Code sessions leave behind.

`inventory` prints a JSON report of every candidate, each tagged with a tier:
`auto` (safe without asking), `confirm` (ask first), or `report` (shown, never
acted on). `apply --ids` recomputes the inventory and acts only on the named
ids that are still present and actionable. Ids embed the state they were
classified in (a branch tip, a container's run state), so anything that changed
since the report no longer matches and is skipped. Standard library only,
because it runs on the host.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

AUTO, CONFIRM, REPORT = "auto", "confirm", "report"
ACTIONABLE = (AUTO, CONFIRM)
# apply executes in this order: a worktree must be gone before its branch,
# a container before its image.
KIND_ORDER = ["worktree-prune", "container", "worktree", "branch", "image", "volume"]

DEFAULT_CONFIG: Dict[str, object] = {
    "worktree_roots": ["~/Work/worktrees"],
    "extra_roots": [],
    "extra_repos": [],
    "codex_worktrees": "~/.codex/worktrees",
    "claude_projects": "~/.claude/projects",
    "host_caches": ["~/.cache/bazel", "~/go/pkg/mod", "~/.cache/uv"],
    "docker_raw": "~/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw",
    "base_image_pattern": r"(^|/)[^/]*devcontainer-base$",
}
DEFAULT_CONFIG_PATH = "~/.config/unnatural-designs-agent-tools/dev-cleanup.json"
ANON_VOLUME_LABEL = "com.docker.volume.anonymous"
FOLDER_LABEL = "devcontainer.local_folder"
VSC_IMAGE = re.compile(r"vsc-(?P<base>.+)-(?P<hash>[0-9a-f]{64})")
GITHUB_SLUG = re.compile(r"github\.com[:/](?P<slug>[^/]+/[^/]+?)(?:\.git)?/?$")
PR_COPY = re.compile(r"pr-(?P<number>\d+)")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
FROM_LINE = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?(?P<ref>\S+)",
                       re.IGNORECASE | re.MULTILINE)
PR_FIELDS = "number,state,headRefName,headRefOid,isCrossRepository,url"
PR_LIMIT = 1000


# --------------------------------------------------------------------------- #
# Process adapter
# --------------------------------------------------------------------------- #


@dataclass
class Result:
    rc: int
    out: str
    err: str = ""

    @property
    def ok(self) -> bool:
        return self.rc == 0


Runner = Callable[[Sequence[str]], Result]


def run(argv: Sequence[str], timeout: int = 300) -> Result:
    try:
        proc = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        return Result(127, "", str(exc))
    except subprocess.TimeoutExpired:
        return Result(124, "", f"timed out after {timeout}s: {' '.join(argv)}")
    return Result(proc.returncode, proc.stdout, proc.stderr)


def git(repo: str, *args: str) -> Result:
    return run(["git", "-C", repo, *args])


class GitHub:
    """`gh` behind a seam so tests can fake it."""

    def __init__(self, runner: Runner = run) -> None:
        self._run = runner

    def _prs(self, *args: str) -> Optional[List[dict]]:
        res = self._run(["gh", "pr", "list", *args, "--state", "all", "--json", PR_FIELDS])
        if not res.ok:
            return None
        try:
            return json.loads(res.out)
        except ValueError:
            return None

    def list_prs(self, slug: str) -> Optional[List[dict]]:
        return self._prs("-R", slug, "--limit", str(PR_LIMIT))

    def prs_for_head(self, slug: str, branch: str) -> Optional[List[dict]]:
        return self._prs("-R", slug, "--head", branch)


class Docker:
    """`docker` behind a seam so tests can fake it."""

    def __init__(self, runner: Runner = run) -> None:
        self._run = runner

    def _json_lines(self, *args: str) -> Optional[List[dict]]:
        res = self._run(["docker", *args])
        if not res.ok:
            return None
        return [json.loads(line) for line in res.out.splitlines() if line.strip()]

    def available(self) -> bool:
        return self._run(["docker", "info", "--format", "{{.ServerVersion}}"]).ok

    def containers(self) -> Optional[List[dict]]:
        ids = self._run(["docker", "ps", "-aq", "--no-trunc"])
        if not ids.ok:
            return None
        if not ids.out.split():
            return []
        res = self._run(["docker", "inspect", *ids.out.split()])
        if not res.ok:
            return None
        return [
            {
                "id": c["Id"],
                "name": c["Name"].lstrip("/"),
                "state": c["State"]["Status"],
                "image_id": c["Image"],
                "labels": c["Config"].get("Labels") or {},
                "volumes": [m["Name"] for m in c.get("Mounts", []) if m.get("Type") == "volume"],
            }
            for c in json.loads(res.out)
        ]

    def images(self) -> Optional[List[dict]]:
        ids = self._run(["docker", "image", "ls", "-aq", "--no-trunc"])
        if not ids.ok:
            return None
        unique = sorted(set(ids.out.split()))
        if not unique:
            return []
        res = self._run(["docker", "image", "inspect", *unique])
        if not res.ok:
            return None
        return [
            {
                "id": i["Id"],
                "tags": [t for t in i.get("RepoTags") or [] if t != "<none>:<none>"],
                "digests": [d for d in i.get("RepoDigests") or [] if d != "<none>@<none>"],
                "created": i.get("Created", ""),
                "size": int(i.get("Size") or 0),
            }
            for i in json.loads(res.out)
        ]

    def volumes(self) -> Optional[List[dict]]:
        """Every volume, with whether docker considers it dangling (no container refs)."""
        everything = self._json_lines("volume", "ls", "--format", "{{json .}}")
        dangling = self._run(["docker", "volume", "ls", "-q", "-f", "dangling=true"])
        if everything is None or not dangling.ok:
            return None
        loose = set(dangling.out.split())
        return [
            {
                "name": v["Name"],
                "anonymous": ANON_VOLUME_LABEL in parse_labels(v.get("Labels", "")),
                "dangling": v["Name"] in loose,
            }
            for v in everything
        ]

    def sizes(self) -> Dict[str, int]:
        """Image ids and volume names → bytes, as `docker system df -v` shows them."""
        res = self._run(["docker", "system", "df", "-v", "--format", "json"])
        try:
            data = json.loads(res.out) if res.ok else {}
        except ValueError:
            data = {}
        sizes = {v["Name"]: parse_size(v.get("Size", "")) for v in data.get("Volumes") or []}
        sizes.update({i["ID"]: parse_size(i.get("Size", "")) for i in data.get("Images") or []})
        return sizes

    def build_cache_bytes(self) -> Optional[int]:
        rows = self._json_lines("system", "df", "--format", "{{json .}}")
        for row in rows or []:
            if row.get("Type") == "Build Cache":
                return parse_size(row.get("Size", ""))
        return None

    def command(self, *args: str) -> Result:
        return self._run(["docker", *args])


def parse_labels(text: str) -> Dict[str, str]:
    """`docker volume ls` renders labels as `k=v,k2=v2`."""
    pairs = (part.split("=", 1) for part in text.split(",") if part)
    return {kv[0]: (kv[1] if len(kv) > 1 else "") for kv in pairs}


_UNITS = {"B": 1, "KB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12, "PB": 10**15}


def parse_size(text: str) -> int:
    """Docker's human sizes are decimal (`2.12GB`, `213.1kB`)."""
    m = re.match(r"\s*([\d.]+)\s*([kKMGTP]?B)", text or "")
    return int(float(m.group(1)) * _UNITS[m.group(2).upper()]) if m else 0


def du_bytes(path: str) -> Optional[int]:
    """Allocated size, so sparse files like Docker.raw report what they really use."""
    if not os.path.exists(path):
        return None
    res = run(["du", "-sk", path], timeout=900)
    try:
        return int(res.out.split()[0]) * 1024
    except (IndexError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Pure classification
# --------------------------------------------------------------------------- #


@dataclass
class Item:
    id: str
    kind: str
    tier: str
    title: str
    reason: str
    path: Optional[str] = None
    size_bytes: Optional[int] = None
    age_days: Optional[int] = None
    details: Dict[str, object] = field(default_factory=dict)


@dataclass
class Session:
    cwd: str
    archived: bool
    running: bool


@dataclass
class SessionIndex:
    available: bool
    sessions: List[Session]

    def guard(self, path: str) -> Tuple[bool, str]:
        """(reapable, reason): reapable only when every session in `path` is archived."""
        if not self.available:
            return False, "session list unavailable, so every worktree is protected"
        matched = [s for s in self.sessions if is_within(s.cwd, path)]
        if not matched:
            return False, "no known Claude session used this worktree"
        live = [s for s in matched if s.running or not s.archived]
        if live:
            return False, f"{len(live)} of {len(matched)} session(s) here are not archived"
        return True, f"all {len(matched)} session(s) here are archived"


def is_within(child: str, parent: str) -> bool:
    child, parent = os.path.realpath(child), os.path.realpath(parent)
    return child == parent or child.startswith(parent.rstrip("/") + "/")


def load_sessions(data: Optional[object], protect: Iterable[str] = ()) -> SessionIndex:
    """Sessions JSON from the skill: `{"available": bool, "sessions": [rows]}` or a bare list.

    `protect` paths are added as live sessions (the caller's own cwd, which the
    session list omits)."""
    if data is None:
        return SessionIndex(False, [])
    if isinstance(data, list):
        data = {"available": True, "sessions": data}
    if not isinstance(data, dict) or not data.get("available", False):
        return SessionIndex(False, [])
    sessions = [
        Session(str(row["cwd"]), bool(row.get("isArchived")), bool(row.get("isRunning")))
        for row in data.get("sessions") or []
        if row.get("cwd")
    ]
    sessions += [Session(p, archived=False, running=True) for p in protect]
    return SessionIndex(True, sessions)


def parse_worktrees(porcelain: str) -> List[Dict[str, object]]:
    """`git worktree list --porcelain` blocks → dicts."""
    entries: List[Dict[str, object]] = []
    for block in porcelain.strip().split("\n\n"):
        entry: Dict[str, object] = {"branch": None, "detached": False, "locked": False,
                                    "prunable": False, "bare": False}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            if key == "worktree":
                entry["path"] = value
            elif key == "HEAD":
                entry["head"] = value
            elif key == "branch":
                entry["branch"] = value[len("refs/heads/"):]
            elif key in ("detached", "locked", "prunable", "bare"):
                entry[key] = True
        if "path" in entry:
            entries.append(entry)
    return entries


def repo_slug(url: str) -> Optional[str]:
    m = GITHUB_SLUG.search(url.strip())
    return m.group("slug") if m else None


def pr_status(prs: Optional[List[dict]]) -> Tuple[str, Optional[dict]]:
    """Ground truth for one head branch: any open PR wins, else the newest PR's state."""
    if prs is None:
        return "unknown", None
    prs = [p for p in prs if not p.get("isCrossRepository")]
    if not prs:
        return "none", None
    open_prs = [p for p in prs if p["state"] == "OPEN"]
    newest = max(open_prs or prs, key=lambda p: p["number"])
    return newest["state"].lower(), newest


def classify_branch(status: str, pr: Optional[dict], contained: Optional[bool],
                    pr_copy: bool = False) -> Tuple[str, str]:
    """Tier for deleting a local branch (or a worktree's branch).

    Offered only when its PR is merged — or, for a local `pr-NNN` copy, merged or
    closed — and the local tip is already inside that PR's head, so nothing
    local-only is lost."""
    if status == "unknown":
        return REPORT, "could not read PRs from GitHub"
    if status == "none" or pr is None:
        return REPORT, "no PR for this branch"
    label = f"PR #{pr['number']}"
    deletable = ("merged", "closed") if pr_copy else ("merged",)
    if status not in deletable:
        return REPORT, f"{label} is {status}"
    if contained is None:
        return REPORT, f"could not verify the local tip is part of {label}"
    if not contained:
        return REPORT, f"local commits not in {label} (unpushed)"
    return CONFIRM, f"{label} is {status}"


def classify_worktree(*, dirty: Optional[bool], locked: bool, detached: bool,
                      on_default: Optional[bool], branch_verdict: Tuple[str, str],
                      guard: Tuple[bool, str]) -> Tuple[str, str]:
    if locked:
        return REPORT, "worktree is locked"
    if dirty is None:
        return REPORT, "could not read worktree status"
    if dirty:
        return REPORT, "uncommitted changes"
    if detached:
        if on_default is None:
            return REPORT, "detached HEAD; could not compare with the default branch"
        if not on_default:
            return REPORT, "detached HEAD not on the default branch (unpushed)"
        verdict = "detached, clean, on the default branch"
    else:
        tier, verdict = branch_verdict
        if tier != CONFIRM:
            return REPORT, verdict
    reapable, why = guard
    if not reapable:
        return REPORT, f"{verdict}, but {why}"
    return CONFIRM, f"{verdict}; {why}"


def classify_container(folder_exists: bool, state: str) -> Optional[Tuple[str, str]]:
    """A devcontainer follows its worktree; None means leave it alone (and its volumes)."""
    if folder_exists:
        return None
    if state in ("exited", "created", "dead"):
        return AUTO, "worktree is gone; container is stopped"
    return CONFIRM, f"worktree is gone; container is {state}"


def folder_hash(path: str) -> str:
    """The devcontainer CLI names images `vsc-<basename>-<sha256(folder path)>`."""
    return hashlib.sha256(path.encode()).hexdigest()


def map_vsc_image(repo: str, candidates: Iterable[str]) -> Optional[str]:
    """The folder a `vsc-*` image was built for, proven by its hash; None if unproven."""
    m = VSC_IMAGE.fullmatch(repo)
    if not m:
        return None
    for path in candidates:
        if folder_hash(path) == m.group("hash"):
            return path
    return None


def dockerfile_refs(text: str) -> Tuple[Set[str], Set[str]]:
    """(digests, tag refs) a Dockerfile could pull: every sha256 anywhere, plus
    digest-less FROM refs. Over-matching only keeps more images."""
    tags = {
        m.group("ref") for m in FROM_LINE.finditer(text)
        if "@" not in m.group("ref") and "$" not in m.group("ref")
    }
    return set(DIGEST.findall(text)), tags


def image_repos(image: dict) -> Set[str]:
    tagged = {t.rsplit(":", 1)[0] for t in image["tags"]}
    return tagged | {d.split("@", 1)[0] for d in image["digests"]}


def classify_base_images(images: List[dict], digests: Set[str], tags: Set[str],
                         in_use: Set[str], pattern: str) -> List[Tuple[dict, str, str]]:
    """Per devcontainer-base repository: keep every referenced or in-use image and the
    newest; the rest are confirm-tier. Returns (image, tier-or-'keep', reason)."""
    family = re.compile(pattern)
    by_repo: Dict[str, List[dict]] = {}
    for image in images:
        for repo in image_repos(image):
            if family.search(repo):
                by_repo.setdefault(repo, []).append(image)
    verdicts: Dict[str, Tuple[dict, str, str]] = {}
    for repo, members in sorted(by_repo.items()):
        newest = max(members, key=lambda i: i["created"])["id"]
        for image in members:
            image_digests = {d.split("@", 1)[1] for d in image["digests"]} | {image["id"]}
            if image_digests & digests or set(image["tags"]) & tags:
                verdict = ("keep", "referenced by a checkout's .devcontainer/Dockerfile")
            elif image["id"] in in_use:
                verdict = ("keep", "used by a container")
            elif image["id"] == newest:
                verdict = ("keep", f"newest {repo}")
            else:
                verdict = (CONFIRM, f"superseded {repo}, referenced by no checkout")
            previous = verdicts.get(image["id"])
            if previous is None or previous[1] != "keep":
                verdicts[image["id"]] = (image, *verdict)
    return list(verdicts.values())


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def expand(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def subdirs(path: str) -> List[str]:
    try:
        return sorted(e.path for e in os.scandir(path) if e.is_dir(follow_symlinks=False))
    except OSError:
        return []


def candidate_folders(roots: Iterable[str]) -> List[str]:
    """Folders a worktree root holds: `<root>/<repo>/<worktree>` (hidden repos included),
    or `<root>/<worktree>` when the child is itself a checkout."""
    found: List[str] = []
    for root in roots:
        for child in subdirs(root):
            if os.path.lexists(os.path.join(child, ".git")):
                found.append(child)
            else:
                found.extend(subdirs(child))
    return found


def main_checkout(folder: str) -> Optional[str]:
    res = git(folder, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not res.ok:
        return None
    common = res.out.strip()
    return os.path.dirname(common) if os.path.basename(common) == ".git" else None


def commit_age_days(repo: str, rev: str, now: float) -> Optional[int]:
    res = git(repo, "log", "-1", "--format=%ct", rev)
    try:
        return int((now - int(res.out.strip())) // 86400)
    except ValueError:
        return None


def contained_in(repo: str, tip: str, head_oid: str) -> Optional[bool]:
    if tip == head_oid:
        return True
    res = git(repo, "merge-base", "--is-ancestor", tip, head_oid)
    return {0: True, 1: False}.get(res.rc)


def default_branch(repo: str) -> Optional[str]:
    res = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if res.ok:
        return res.out.strip()
    has_main = git(repo, "rev-parse", "--verify", "-q", "refs/remotes/origin/main").ok
    return "origin/main" if has_main else None


class PrIndex:
    """One bulk `gh pr list` per repo, with per-branch queries if it may be truncated."""

    def __init__(self, github: GitHub, slug: Optional[str]) -> None:
        self._github, self._slug = github, slug
        self._all = github.list_prs(slug) if slug else None
        self._truncated = self._all is not None and len(self._all) >= PR_LIMIT

    def for_head(self, branch: str) -> Optional[List[dict]]:
        if self._slug is None or self._all is None:
            return None
        if self._truncated:
            return self._github.prs_for_head(self._slug, branch)
        return [p for p in self._all if p["headRefName"] == branch]

    def by_number(self, number: int) -> Optional[List[dict]]:
        if self._all is None:
            return None
        hits = [p for p in self._all if p["number"] == number]
        return hits if hits or not self._truncated else None


@dataclass
class Context:
    config: Dict[str, object]
    sessions: SessionIndex
    github: GitHub
    docker: Docker
    fetch: bool = True
    now: float = field(default_factory=time.time)
    du: Callable[[str], Optional[int]] = du_bytes


def branch_verdict(repo: str, prs: PrIndex, name: str, tip: str) -> Tuple[str, str, Optional[int]]:
    copy = PR_COPY.fullmatch(name)
    status, pr = pr_status(prs.by_number(int(copy.group("number"))) if copy else prs.for_head(name))
    contained = contained_in(repo, tip, pr["headRefOid"]) if pr else None
    tier, reason = classify_branch(status, pr, contained, pr_copy=bool(copy))
    return tier, reason, pr["number"] if pr else None


def inventory_repo(ctx: Context, repo: str, roots: List[str], items: List[Item],
                   notes: List[str]) -> List[str]:
    """Worktree + branch items for one main checkout. Returns the worktree paths git knows."""
    if ctx.fetch:
        res = git(repo, "fetch", "--prune", "--quiet", "origin")
        notes.append(f"git fetch --prune {repo}: {'ok' if res.ok else res.err.strip()}")
    listing = git(repo, "worktree", "list", "--porcelain")
    if not listing.ok:
        notes.append(f"git worktree list failed in {repo}: {listing.err.strip()}")
        return []
    entries = parse_worktrees(listing.out)
    url = git(repo, "config", "--get", "remote.origin.url").out
    prs = PrIndex(ctx.github, repo_slug(url))
    base = default_branch(repo)
    codex = expand(str(ctx.config["codex_worktrees"]))

    if any(e["prunable"] for e in entries):
        stale = [str(e["path"]) for e in entries if e["prunable"]]
        items.append(Item(f"worktree-prune:{repo}", "worktree-prune", AUTO,
                          f"git worktree prune in {repo}",
                          f"{len(stale)} worktree entr(ies) point at missing folders",
                          path=repo, details={"stale": stale}))

    checked_out = {e["branch"] for e in entries if e["branch"] and not e["prunable"]}
    for entry in entries:
        path, head = str(entry["path"]), str(entry.get("head", ""))
        if entry["prunable"] or entry["bare"] or os.path.realpath(path) == os.path.realpath(repo):
            continue
        under_root = any(is_within(path, r) for r in roots)
        age = commit_age_days(path, "HEAD", ctx.now)
        if not under_root:
            where = "Codex worktree" if is_within(path, codex) else "outside the worktree roots"
            items.append(Item(f"worktree:{path}@{head}", "worktree", REPORT, path,
                              where, path=path, age_days=age))
            continue
        status = git(path, "status", "--porcelain")
        dirty = bool(status.out.strip()) if status.ok else None
        on_default = contained_in(path, head, base) if base else None
        branch = entry["branch"]
        verdict = branch_verdict(repo, prs, str(branch), head)[:2] if branch else (REPORT, "")
        tier, reason = classify_worktree(
            dirty=dirty, locked=bool(entry["locked"]), detached=bool(entry["detached"]),
            on_default=on_default, branch_verdict=verdict, guard=ctx.sessions.guard(path))
        title = f"{path} ({branch or 'detached'})"
        items.append(Item(f"worktree:{path}@{head}", "worktree", tier, title, reason, path=path,
                          age_days=age, details={"repo": repo, "branch": branch, "head": head}))

    refs = git(repo, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads")
    base_name = base.split("/", 1)[1] if base else None
    for line in refs.out.splitlines():
        name, _, tip = line.partition(" ")
        if name in checked_out or name == base_name:
            continue
        tier, reason, number = branch_verdict(repo, prs, name, tip)
        items.append(Item(f"branch:{repo}:{name}@{tip}", "branch", tier, f"{name} in {repo}",
                          reason, path=repo, age_days=commit_age_days(repo, tip, ctx.now),
                          details={"repo": repo, "branch": name, "tip": tip, "pr": number}))
    return [str(e["path"]) for e in entries]


def inventory_docker(ctx: Context, known_paths: Set[str], roots: List[str], checkouts: List[str],
                     items: List[Item], summary: Dict[str, object]) -> None:
    docker = ctx.docker
    if not docker.available():
        summary["docker"] = "unavailable"
        return
    containers, images, volumes = docker.containers(), docker.images(), docker.volumes()
    if containers is None or images is None or volumes is None:
        summary["docker"] = "could not list containers, images, or volumes"
        return
    sizes = docker.sizes()
    for image in images:
        image["size"] = sizes.get(image["id"], image["size"])
    claimed_images: Set[str] = set()
    claimed_volumes: Set[str] = set()

    for c in containers:
        folder = c["labels"].get(FOLDER_LABEL)
        if not folder:
            continue
        known_paths.add(folder)
        verdict = classify_container(os.path.exists(folder), c["state"])
        if verdict is None:
            continue
        items.append(Item(f"container:{c['id']}:{c['state']}", "container", verdict[0],
                          f"{c['name']} ({folder})", verdict[1], path=folder,
                          details={"container": c["id"], "image": c["image_id"],
                                   "anonymous_volumes": c["volumes"]}))

    in_use = {c["image_id"] for c in containers}
    # Folders a vsc-* image might have been built for: everything known, its
    # siblings, and the same basename under any parent a worktree could live in.
    parents = {os.path.dirname(p) for p in known_paths} | set(roots)
    parents.update(d for r in roots for d in subdirs(r))
    guesses = set(known_paths)
    for parent in parents:
        guesses.update(subdirs(parent))
    for image in images:
        tag = next((t for t in image["tags"] if VSC_IMAGE.fullmatch(t.rsplit(":", 1)[0])), None)
        if tag is None:
            continue
        claimed_images.add(image["id"])
        repo = tag.rsplit(":", 1)[0]
        base = VSC_IMAGE.fullmatch(repo).group("base")  # type: ignore[union-attr]
        folder = map_vsc_image(repo, guesses | {os.path.join(p, base) for p in parents})
        if folder is None:
            items.append(Item(f"image:{image['id']}", "image", REPORT, tag,
                              "could not prove which folder this image was built for",
                              size_bytes=image["size"]))
        elif not os.path.exists(folder):
            items.append(Item(f"image:{image['id']}", "image", CONFIRM, tag,
                              f"worktree {folder} is gone", path=folder,
                              size_bytes=image["size"]))

    digests: Set[str] = set()
    tags: Set[str] = set()
    for checkout in checkouts:
        try:
            text = Path(checkout, ".devcontainer", "Dockerfile").read_text()
        except OSError:
            continue
        d, t = dockerfile_refs(text)
        digests |= d
        tags |= t
    kept = []
    for image, tier, reason in classify_base_images(images, digests, tags, in_use,
                                                    str(ctx.config["base_image_pattern"])):
        claimed_images.add(image["id"])
        label = (image["tags"] or image["digests"] or [image["id"]])[0]
        if tier == "keep":
            kept.append(f"{label}: {reason}")
            continue
        items.append(Item(f"image:{image['id']}", "image", tier, label, reason,
                          size_bytes=image["size"], details={"created": image["created"]}))
    summary["base_images_kept"] = kept

    for image in images:
        if not image["tags"] and not image["digests"] and image["id"] not in in_use:
            claimed_images.add(image["id"])
            items.append(Item(f"image:{image['id']}", "image", AUTO, image["id"][:19],
                              "dangling image, used by no container", size_bytes=image["size"]))

    for v in volumes:
        if v["anonymous"] and v["dangling"]:
            claimed_volumes.add(v["name"])
            items.append(Item(f"volume:{v['name']}", "volume", AUTO, v["name"][:12],
                              "anonymous volume no container references",
                              size_bytes=sizes.get(v["name"])))

    other_images = [i for i in images if i["id"] not in claimed_images]
    other_volumes = [v for v in volumes if v["name"] not in claimed_volumes]
    summary["untouched_docker"] = {
        "images_bytes": sum(i["size"] for i in other_images),
        "images": sorted({(i["tags"] or i["digests"] or [i["id"]])[0] for i in other_images}),
        "volumes_bytes": sum(sizes.get(v["name"], 0) for v in other_volumes),
        "volumes": sorted(v["name"] for v in other_volumes),
    }
    summary["build_cache_bytes"] = docker.build_cache_bytes()


def build_inventory(ctx: Context) -> Dict[str, object]:
    cfg = ctx.config
    roots = [expand(str(r)) for r in list(cfg["worktree_roots"]) + list(cfg["extra_roots"])]
    items: List[Item] = []
    notes: List[str] = []
    summary: Dict[str, object] = {"sessions_available": ctx.sessions.available}

    owners = {folder: main_checkout(folder) for folder in candidate_folders(roots)}
    loose = [folder for folder, main in owners.items() if main is None]
    repos = sorted({main for main in owners.values() if main is not None}
                   | {expand(str(r)) for r in cfg["extra_repos"]})
    known: Set[str] = set(repos)
    for repo in repos:
        known.update(inventory_repo(ctx, repo, roots, items, notes))
    listed = {os.path.realpath(k) for k in known}
    for folder in loose:
        items.append(Item(f"folder:{folder}", "folder", REPORT, folder,
                          "not a registered git worktree; it may hold the only copy of work",
                          path=folder, size_bytes=ctx.du(folder),
                          age_days=int((ctx.now - os.path.getmtime(folder)) // 86400)))
    for folder, main in owners.items():
        if main is not None and os.path.realpath(folder) not in listed:
            items.append(Item(f"folder:{folder}", "folder", REPORT, folder,
                              "git doesn't list this folder as a worktree", path=folder))
    known.update(loose)

    checkouts = sorted(p for p in known if os.path.isdir(p))
    inventory_docker(ctx, known, roots, checkouts, items, summary)

    codex = expand(str(cfg["codex_worktrees"]))
    summary["codex_worktrees"] = {"count": len(candidate_folders([codex])), "bytes": ctx.du(codex)}
    summary["claude_projects_bytes"] = ctx.du(expand(str(cfg["claude_projects"])))
    summary["host_caches"] = {expand(str(p)): ctx.du(expand(str(p))) for p in cfg["host_caches"]}
    summary["docker_raw_bytes"] = ctx.du(expand(str(cfg["docker_raw"])))
    return {"version": 1, "generated_at": int(ctx.now), "items": [asdict(i) for i in items],
            "summary": summary, "notes": notes}


# --------------------------------------------------------------------------- #
# Apply
# --------------------------------------------------------------------------- #


def checked_out_branches(repo: str) -> Optional[Set[str]]:
    res = git(repo, "worktree", "list", "--porcelain")
    if not res.ok:
        return None
    return {str(e["branch"]) for e in parse_worktrees(res.out) if e["branch"] and not e["prunable"]}


def delete_branch(repo: str, branch: str, tip: str) -> Tuple[bool, str]:
    live = checked_out_branches(repo)
    if live is None or branch in live:
        return False, "branch is checked out in a worktree"
    # Old-value form: refuses if the branch moved since it was classified.
    res = git(repo, "update-ref", "-d", f"refs/heads/{branch}", tip)
    if not res.ok:
        return False, res.err.strip() or "update-ref refused"
    git(repo, "config", "--remove-section", f"branch.{branch}")
    return True, f"deleted branch {branch} (was {tip[:12]})"


def apply_item(ctx: Context, item: Dict[str, object]) -> Tuple[bool, str]:
    kind, details = item["kind"], item["details"]
    assert isinstance(details, dict)
    if kind == "worktree-prune":
        res = git(str(item["path"]), "worktree", "prune")
        return res.ok, "pruned stale worktree entries" if res.ok else res.err.strip()
    if kind == "worktree":
        path, repo = str(item["path"]), str(details["repo"])
        if git(path, "status", "--porcelain").out.strip():
            return False, "worktree has uncommitted changes"
        # No --force: git itself refuses a dirty or locked worktree.
        res = git(repo, "worktree", "remove", path)
        if not res.ok:
            return False, res.err.strip()
        if details.get("branch"):
            ok, msg = delete_branch(repo, str(details["branch"]), str(details["head"]))
            return True, f"removed worktree; {msg if ok else 'kept branch: ' + msg}"
        return True, "removed worktree"
    if kind == "branch":
        return delete_branch(str(details["repo"]), str(details["branch"]), str(details["tip"]))
    if kind == "container":
        cid = str(details["container"])
        if item["tier"] == CONFIRM:
            res = ctx.docker.command("stop", cid)
            if not res.ok:
                return False, res.err.strip()
        # -v takes the container's anonymous volumes with it; named volumes stay.
        res = ctx.docker.command("rm", "-v", cid)
        return res.ok, "removed container and its anonymous volumes" if res.ok else res.err.strip()
    if kind == "image":
        image = str(item["id"]).split(":", 1)[1]
        users = ctx.docker.command("ps", "-aq", "--filter", f"ancestor={image}")
        if not users.ok or users.out.strip():
            return False, "a container still uses this image"
        res = ctx.docker.command("rmi", image)
        return res.ok, "removed image" if res.ok else res.err.strip()
    if kind == "volume":
        res = ctx.docker.command("volume", "rm", str(item["id"]).split(":", 1)[1])
        return res.ok, "removed volume" if res.ok else res.err.strip()
    return False, f"unknown kind {kind}"


def record(done: List[Dict[str, str]], skipped: List[Dict[str, str]], item: Dict[str, object],
           ok: bool, msg: str) -> None:
    if ok:
        done.append({"id": str(item["id"]), "result": msg})
    else:
        skipped.append({"id": str(item["id"]), "reason": msg})


def apply(ctx: Context, ids: Sequence[str]) -> Dict[str, object]:
    """Recompute, then act on each requested id still present at an actionable tier."""
    fresh = {i["id"]: i for i in build_inventory(ctx)["items"]}
    done: List[Dict[str, str]] = []
    skipped: List[Dict[str, str]] = []
    queue = []
    for item_id in dict.fromkeys(ids):
        item = fresh.get(item_id)
        if item is None:
            skipped.append({"id": item_id, "reason": "state changed since the report, or gone"})
        elif item["tier"] not in ACTIONABLE:
            skipped.append({"id": item_id, "reason": f"no longer eligible: {item['reason']}"})
        else:
            queue.append(item)
    queue.sort(key=lambda i: KIND_ORDER.index(str(i["kind"])))
    for item in queue:
        ok, msg = apply_item(ctx, item)
        record(done, skipped, item, ok, msg)

    # Removing a worktree orphans its devcontainer: reap what is now auto-tier and
    # hand back anything that now needs confirming.
    follow_up: List[Dict[str, object]] = []
    if any(i["kind"] == "worktree" for i in queue):
        handled = {d["id"] for d in done} | {s["id"] for s in skipped}
        ctx.fetch = False
        for item in build_inventory(ctx)["items"]:
            if item["id"] in handled or item["kind"] not in ("container", "image", "volume"):
                continue
            if item["tier"] == AUTO:
                record(done, skipped, item, *apply_item(ctx, item))
            elif item["tier"] == CONFIRM:
                follow_up.append(item)
    return {"done": done, "skipped": skipped, "follow_up": follow_up,
            "docker_raw_bytes_after": ctx.du(expand(str(ctx.config["docker_raw"])))}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def load_config(path: Optional[str]) -> Dict[str, object]:
    config = dict(DEFAULT_CONFIG)
    target = expand(path or DEFAULT_CONFIG_PATH)
    if os.path.exists(target):
        with open(target) as fh:
            config.update(json.load(fh))
    elif path:
        raise SystemExit(f"config file not found: {target}")
    return config


def read_json_arg(value: Optional[str]) -> Optional[object]:
    if value is None:
        return None
    if value == "-":
        return json.load(sys.stdin)
    with open(value) as fh:
        return json.load(fh)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inventory", "apply"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--sessions", help="sessions JSON file from the skill, or - for stdin; "
                                            "omitted means unavailable (all worktrees protected)")
        cmd.add_argument("--config", help=f"config JSON (default {DEFAULT_CONFIG_PATH})")
        cmd.add_argument("--no-fetch", action="store_true", help="skip git fetch --prune")
        if name == "apply":
            cmd.add_argument("--ids", nargs="+", required=True, help="item ids from inventory")
    args = parser.parse_args(argv)
    if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
        # In a container, host worktrees look missing; worktree prune would drop them.
        parser.error("run this on the host, not inside a container")
    ctx = Context(config=load_config(args.config),
                  sessions=load_sessions(read_json_arg(args.sessions), protect=[os.getcwd()]),
                  github=GitHub(), docker=Docker(), fetch=not args.no_fetch)
    result = build_inventory(ctx) if args.command == "inventory" else apply(ctx, args.ids)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
