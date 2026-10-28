"""Tests for scripts/dev_cleanup.py.

Pure classifiers get table tests; git behavior runs against real temp repos;
`gh` and `docker` are faked at their adapter seam."""

import calendar
import copy
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import dev_cleanup as dc  # noqa: E402

SLUG = "o/r"
REMOTE = f"git@github.com:{SLUG}.git"


# --------------------------------------------------------------------------- #
# Pure classification
# --------------------------------------------------------------------------- #


def test_parse_worktrees_reads_every_flag() -> None:
    text = (
        "worktree /m\nHEAD aaa\nbranch refs/heads/main\n\n"
        "worktree /w1\nHEAD bbb\ndetached\nlocked reason\n\n"
        "worktree /w2\nHEAD ccc\nbranch refs/heads/feat/x\nprunable gitdir file points nowhere\n"
    )
    main, w1, w2 = dc.parse_worktrees(text)
    assert (main["path"], main["branch"], main["detached"]) == ("/m", "main", False)
    assert (w1["detached"], w1["locked"], w1["branch"]) == (True, True, None)
    assert (w2["branch"], w2["prunable"]) == ("feat/x", True)


@pytest.mark.parametrize("url,slug", [
    ("git@github.com:Syndic/.dotfiles.git", "Syndic/.dotfiles"),
    ("https://github.com/Syndic/unnatural_designs.git\n", "Syndic/unnatural_designs"),
    ("https://github.com/o/r", "o/r"),
    ("/srv/git/r.git", None),
])
def test_repo_slug(url: str, slug: Optional[str]) -> None:
    assert dc.repo_slug(url) == slug


def pr(number: int, state: str, head: str = "b", oid: str = "x", cross: bool = False) -> dict:
    return {"number": number, "state": state, "headRefName": head, "headRefOid": oid,
            "isCrossRepository": cross, "url": f"https://github.com/{SLUG}/pull/{number}"}


@pytest.mark.parametrize("prs,status,number", [
    (None, "unknown", None),
    ([], "none", None),
    ([pr(1, "MERGED")], "merged", 1),
    ([pr(1, "MERGED"), pr(2, "CLOSED")], "closed", 2),
    ([pr(3, "OPEN"), pr(4, "MERGED")], "open", 3),
    ([pr(5, "MERGED", cross=True)], "none", None),
])
def test_pr_status(prs, status: str, number: Optional[int]) -> None:
    got, chosen = dc.pr_status(prs)
    assert got == status
    assert (chosen or {}).get("number") == number


@pytest.mark.parametrize("status,contained,pr_copy,tier,reason", [
    ("merged", True, False, dc.CONFIRM, "PR #7 is merged"),
    ("merged", False, False, dc.REPORT, "unpushed"),
    ("merged", None, False, dc.REPORT, "could not verify"),
    ("closed", True, False, dc.REPORT, "PR #7 is closed"),
    ("closed", True, True, dc.CONFIRM, "PR #7 is closed"),
    ("open", True, True, dc.REPORT, "PR #7 is open"),
    ("unknown", None, False, dc.REPORT, "could not read PRs"),
])
def test_classify_branch(status: str, contained, pr_copy: bool, tier: str, reason: str) -> None:
    the_pr = None if status == "unknown" else pr(7, status.upper())
    got_tier, got_reason = dc.classify_branch(status, the_pr, contained, pr_copy)
    assert got_tier == tier
    assert reason in got_reason


def test_classify_branch_without_pr() -> None:
    assert dc.classify_branch("none", None, None) == (dc.REPORT, "no PR for this branch")


OK_BRANCH = (dc.CONFIRM, "PR #7 is merged")
REAPABLE = (True, "all 1 session(s) here are archived")


@pytest.mark.parametrize("kwargs,tier,reason", [
    ({}, dc.CONFIRM, "PR #7 is merged"),
    ({"dirty": True}, dc.REPORT, "uncommitted changes"),
    ({"dirty": None}, dc.REPORT, "could not read"),
    ({"locked": True}, dc.REPORT, "locked"),
    ({"branch_verdict": (dc.REPORT, "PR #7 is open")}, dc.REPORT, "PR #7 is open"),
    ({"guard": (False, "no known Claude session")}, dc.REPORT, "no known Claude session"),
    ({"detached": True, "on_default": True}, dc.CONFIRM, "on the default branch"),
    ({"detached": True, "on_default": False}, dc.REPORT, "unpushed"),
    ({"detached": True, "on_default": None}, dc.REPORT, "could not compare"),
    ({"detached": True, "on_default": True, "dirty": True}, dc.REPORT, "uncommitted"),
    ({"running_containers": ["dc-1 (up 3d)"]}, dc.CONFIRM,
     "stops its running devcontainer first: dc-1 (up 3d)"),
    ({"running_containers": ["dc-1"], "dirty": True}, dc.REPORT, "uncommitted"),
    ({"running_containers": ["dc-1"], "branch_verdict": (dc.REPORT, "PR #7 is open")},
     dc.REPORT, "PR #7 is open"),
    ({"running_containers": ["dc-1"], "guard": (False, "a session is active")},
     dc.REPORT, "a session is active"),
])
def test_classify_worktree(kwargs: dict, tier: str, reason: str) -> None:
    args = {"dirty": False, "locked": False, "detached": False, "on_default": None,
            "branch_verdict": OK_BRANCH, "guard": REAPABLE, **kwargs}
    got_tier, got_reason = dc.classify_worktree(**args)
    assert got_tier == tier
    assert reason in got_reason


@pytest.mark.parametrize("exists,state,expected", [
    (True, "running", None),
    (True, "exited", None),
    (False, "exited", dc.AUTO),
    (False, "created", dc.AUTO),
    (False, "running", dc.CONFIRM),
    (False, "paused", dc.CONFIRM),
])
def test_classify_container_follows_its_worktree(exists: bool, state: str, expected) -> None:
    verdict = dc.classify_container(exists, state)
    assert (verdict[0] if verdict else None) == expected


def test_classify_container_outside_the_roots_is_report_only() -> None:
    assert dc.classify_container(False, "exited", in_scope=False)[0] == dc.REPORT


@pytest.mark.parametrize("locked,in_scope,tier", [
    (False, True, dc.AUTO), (False, False, dc.CONFIRM), (True, True, dc.REPORT)])
def test_classify_stale(locked: bool, in_scope: bool, tier: str) -> None:
    assert dc.classify_stale(locked, in_scope)[0] == tier


def sessions(*rows: tuple, available: bool = True) -> dc.SessionIndex:
    return dc.load_sessions({"available": available, "sessions": [
        {"cwd": cwd, "isArchived": archived, "isRunning": running}
        for cwd, archived, running in rows]})


@pytest.mark.parametrize("index,reapable,reason", [
    (sessions(available=False), False, "unavailable"),
    (sessions(("/elsewhere", True, False)), False, "no known Claude session"),
    (sessions(("/w", True, False), ("/w/sub", True, False)), True, "all 2"),
    (sessions(("/w", True, False), ("/w", False, False)), False, "1 of 2"),
    (sessions(("/w", True, True)), False, "1 of 1"),
    (sessions(("/w-other", True, False)), False, "no known"),
])
def test_session_guard(index: dc.SessionIndex, reapable: bool, reason: str) -> None:
    got, why = index.guard("/w")
    assert got is reapable
    assert reason in why


def test_load_sessions_accepts_a_bare_list_and_protects_extra_paths() -> None:
    index = dc.load_sessions([{"cwd": "/w", "isArchived": True}], protect=["/w"])
    assert index.available
    assert index.guard("/w")[0] is False
    assert dc.load_sessions(None).available is False


def test_map_vsc_image_needs_a_hash_proof() -> None:
    folder = "/Users/me/Work/worktrees/repo/happy-cat-1a2b3c"
    repo = f"vsc-happy-cat-1a2b3c-{dc.folder_hash(folder)}"
    assert dc.map_vsc_image(repo, ["/elsewhere/happy-cat-1a2b3c", folder]) == folder
    assert dc.map_vsc_image(repo, ["/elsewhere/happy-cat-1a2b3c"]) is None
    assert dc.map_vsc_image("not-a-vsc-image", [folder]) is None


def test_image_refs_over_match_digests() -> None:
    d1, d2 = "sha256:" + "a" * 64, "sha256:" + "b" * 64
    text = (f"ARG BASE=ghcr.io/x/devcontainer-base@{d2}\n"
            f"FROM ghcr.io/x/devcontainer-base:latest@{d1} AS pinned\n"
            "FROM ${BASE}\nFROM --platform=linux/amd64 debian:stable\n")
    digests, tags = dc.image_refs(text)
    assert digests == {d1, d2}
    assert tags == {"debian:stable"}


def test_image_refs_read_devcontainer_json_and_compose_image_keys() -> None:
    text = ('{\n  "image": "ghcr.io/x/devcontainer-base",\n}\n'
            "services:\n  app:\n    image: redis:7\n")
    assert dc.image_refs(text)[1] == {"ghcr.io/x/devcontainer-base:latest", "redis:7"}


def image(id_: str, created: str, tags=(), digests=(), size: int = 1) -> dict:
    return {"id": id_, "tags": list(tags), "digests": list(digests), "created": created,
            "size": size}


def test_classify_base_images_keeps_referenced_in_use_and_newest() -> None:
    repo = "ghcr.io/x/devcontainer-base"
    images = [
        image("sha256:" + "1" * 64, "2026-01", digests=[f"{repo}@sha256:{'1' * 64}"]),
        image("sha256:" + "2" * 64, "2026-02", digests=[f"{repo}@sha256:{'2' * 64}"]),
        image("sha256:" + "3" * 64, "2026-03", digests=[f"{repo}@sha256:{'3' * 64}"]),
        image("sha256:" + "4" * 64, "2026-04", tags=[f"{repo}:latest"]),
        image("sha256:" + "5" * 64, "2026-05", digests=[f"{repo}@sha256:{'5' * 64}"]),
        image("sha256:" + "9" * 64, "2026-09", tags=["unrelated:latest"]),
    ]
    verdicts = {i["id"][7]: (tier, reason) for i, tier, reason in dc.classify_base_images(
        images, digests={"sha256:" + "2" * 64}, tags={f"{repo}:latest"},
        in_use={"sha256:" + "3" * 64}, pattern=dc.DEFAULT_CONFIG["base_image_pattern"])}
    assert verdicts["1"][0] == dc.CONFIRM
    assert verdicts["2"] == ("keep", "referenced by a checkout's devcontainer config")
    assert verdicts["3"] == ("keep", "used by a container")
    assert verdicts["4"][0] == "keep"
    assert verdicts["5"] == ("keep", f"newest {repo}")
    assert "9" not in verdicts


def test_classify_base_images_reports_when_a_named_file_is_unreadable() -> None:
    repo = "ghcr.io/x/devcontainer-base"
    images = [image("sha256:" + "1" * 64, "2026-01", tags=[f"{repo}:old"]),
              image("sha256:" + "2" * 64, "2026-02", tags=[f"{repo}:new"])]
    verdicts = dc.classify_base_images(images, set(), set(), set(),
                                       dc.DEFAULT_CONFIG["base_image_pattern"], ["../Dockerfile"])
    superseded = [(tier, reason) for i, tier, reason in verdicts if i["created"] == "2026-01"]
    assert superseded[0][0] == dc.REPORT and "could not read ../Dockerfile" in superseded[0][1]


def test_devcontainer_sources_follow_named_files(tmp_path: Path) -> None:
    devc = tmp_path / ".devcontainer"
    devc.mkdir()
    (tmp_path / "Dockerfile.dev").write_text("FROM a\n")
    (devc / "devcontainer.json").write_text(
        '{"build": {"dockerfile": "../Dockerfile.dev"}, "dockerComposeFile": ["compose.yml"]}')
    (devc / "compose.yml").write_text("services:\n  app:\n    build:\n      context: ../svc\n")
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "Dockerfile").write_text("FROM b\n")
    (devc / "link").symlink_to(tmp_path)  # never walked into
    files, unread = dc.devcontainer_sources(str(tmp_path))
    names = {os.path.relpath(f, tmp_path) for f in files}
    assert names == {".devcontainer/devcontainer.json", ".devcontainer/compose.yml",
                     "Dockerfile.dev", "svc/Dockerfile"}
    assert unread == []

    (devc / "devcontainer.json").write_text('{"build": {"dockerfile": "missing.Dockerfile"}}')
    assert dc.devcontainer_sources(str(tmp_path))[1] == [str(devc / "missing.Dockerfile")]


@pytest.mark.parametrize("text,size", [("2.12GB", 2_120_000_000), ("213.1kB", 213_100),
                                       ("0B", 0), ("", 0), ("N/A", 0)])
def test_parse_size(text: str, size: int) -> None:
    assert dc.parse_size(text) == size


def test_parse_labels() -> None:
    assert dc.parse_labels("com.docker.volume.anonymous=,a=b") == {
        "com.docker.volume.anonymous": "", "a": "b"}


def test_main_refuses_to_run_in_a_container(monkeypatch) -> None:
    real = os.path.exists
    monkeypatch.setattr(dc.os.path, "exists", lambda p: p == "/.dockerenv" or real(p))
    with pytest.raises(SystemExit):
        dc.main(["inventory", "--no-fetch"])


# --------------------------------------------------------------------------- #
# Fakes and real-git fixtures
# --------------------------------------------------------------------------- #


class FakeGitHub:
    def __init__(self, prs: Optional[List[dict]] = None, fail: bool = False) -> None:
        self.prs = prs or []
        self.fail = fail

    def list_prs(self, slug: str) -> Optional[List[dict]]:
        return None if self.fail or slug != SLUG else copy.deepcopy(self.prs)

    def prs_for_head(self, slug: str, branch: str) -> Optional[List[dict]]:
        return [p for p in self.prs if p["headRefName"] == branch]


class FakeDocker:
    """In-memory docker: `command` mutates state the way the real CLI would."""

    def __init__(self, containers=(), images=(), volumes=(), available: bool = True,
                 failing: Sequence[str] = ()) -> None:
        self._containers = [dict(c) for c in containers]
        self.failing = set(failing)
        self._images = [dict(i) for i in images]
        self._volumes = [dict(v) for v in volumes]
        self._available = available
        self.calls: List[tuple] = []

    def available(self) -> bool:
        return self._available

    def containers(self):
        return copy.deepcopy(self._containers)

    def images(self):
        return copy.deepcopy(self._images)

    def volumes(self):
        return copy.deepcopy(self._volumes)

    def sizes(self) -> Dict[str, int]:
        return {}

    def build_cache_bytes(self) -> Optional[int]:
        return None

    def command(self, *args: str) -> dc.Result:
        self.calls.append(args)
        if args[0] in self.failing:
            return dc.Result(1, "", f"{args[0]} refused")
        if args[0] == "stop":
            for c in self._containers:
                if c["id"] == args[1]:
                    c["state"] = "exited"
        elif args[:2] == ("rm", "-v"):
            self._containers = [c for c in self._containers if c["id"] != args[2]]
        elif args[0] == "ps":
            image_id = args[-1].split("=", 1)[1]
            users = [c["id"] for c in self._containers if c["image_id"] == image_id]
            return dc.Result(0, "\n".join(users))
        elif args[0] == "rmi":
            self._images = [i for i in self._images if i["id"] != args[1]]
        elif args[:2] == ("volume", "rm"):
            self._volumes = [v for v in self._volumes if v["name"] != args[2]]
        return dc.Result(0, "")


def git(cwd, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


@dataclass
class Repo:
    main: Path
    root: Path
    tmp: Path

    def commit(self, where: Path, name: str) -> str:
        (where / name).write_text(name)
        git(where, "add", name)
        git(where, "commit", "-qm", name)
        return git(where, "rev-parse", "HEAD")

    def worktree(self, name: str, branch: Optional[str] = None) -> Path:
        path = self.root / "r" / name
        if branch:
            git(self.main, "worktree", "add", "-q", "-b", branch, str(path), "origin/main")
        else:
            git(self.main, "worktree", "add", "-q", "--detach", str(path), "origin/main")
        return path

    def head(self, where: Path) -> str:
        return git(where, "rev-parse", "HEAD")


@pytest.fixture(autouse=True)
def isolated_git(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = T\n\temail = t@example.com\n[commit]\n\tgpgsign = false\n"
                      "[init]\n\tdefaultBranch = main\n[gc]\n\tauto = 0\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    tmp = Path(os.path.realpath(tmp_path))
    origin, main, root = tmp / "origin.git", tmp / "checkouts" / "r", tmp / "worktrees"
    git(tmp, "init", "-q", "--bare", str(origin))
    main.mkdir(parents=True)
    (root / "r").mkdir(parents=True)
    git(main, "init", "-q")
    # The remote URL must parse as a GitHub slug; insteadOf points it at the bare repo.
    git(main, "config", f"url.{origin}.insteadOf", REMOTE)
    git(main, "remote", "add", "origin", REMOTE)
    r = Repo(main, root, tmp)
    r.commit(main, "init")
    git(main, "push", "-q", "-u", "origin", "main")
    git(main, "remote", "set-head", "origin", "main")
    return r


def context(repo: Repo, index: Optional[dc.SessionIndex] = None, github=None,
            docker=None) -> dc.Context:
    config = dict(dc.DEFAULT_CONFIG, worktree_roots=[str(repo.root)], extra_roots=[],
                  extra_repos=[str(repo.main)],
                  codex_worktrees=str(repo.tmp / "codex"), claude_projects=str(repo.tmp / "cp"),
                  host_caches=[], docker_raw=str(repo.tmp / "Docker.raw"))
    return dc.Context(config=config, sessions=index or sessions(available=False),
                      github=github or FakeGitHub(), docker=docker or FakeDocker(available=False),
                      fetch=False, du=lambda _: None)


def items(ctx: dc.Context) -> Dict[str, dict]:
    return {i["id"]: i for i in dc.build_inventory(ctx)["items"]}


def only(found: Dict[str, dict], kind: str, **match) -> dict:
    hits = [i for i in found.values() if i["kind"] == kind
            and all(i["details"].get(k) == v or i.get(k) == v for k, v in match.items())]
    assert len(hits) == 1, hits
    return hits[0]


# --------------------------------------------------------------------------- #
# Git behavior against real repos
# --------------------------------------------------------------------------- #


def test_merged_clean_worktree_with_archived_sessions_is_removed_with_its_branch(repo) -> None:
    wt = repo.worktree("happy-cat-1a2b3c", branch="claude/feature")
    tip = repo.commit(wt, "work")
    git(wt, "push", "-q", "origin", "claude/feature")
    github = FakeGitHub([pr(7, "MERGED", "claude/feature", tip)])
    ctx = context(repo, sessions((str(wt), True, False)), github)

    item = only(items(ctx), "worktree", path=str(wt))
    assert item["tier"] == dc.CONFIRM
    result = dc.apply(ctx, [item["id"]])

    assert [d["id"] for d in result["done"]] == [item["id"]]
    assert not wt.exists()
    assert "claude/feature" not in git(repo.main, "branch", "--format=%(refname:short)")
    assert git(repo.main, "ls-remote", "origin", "claude/feature")  # remote untouched


def test_dirty_worktree_is_report_only_and_apply_refuses_it(repo) -> None:
    wt = repo.worktree("dirty-dog-000000", branch="claude/dirty")
    tip = repo.commit(wt, "work")
    (wt / "scratch.txt").write_text("unsaved")
    ctx = context(repo, sessions((str(wt), True, False)),
                  FakeGitHub([pr(8, "MERGED", "claude/dirty", tip)]))

    item = only(items(ctx), "worktree", path=str(wt))
    assert (item["tier"], item["reason"]) == (dc.REPORT, "uncommitted changes")
    result = dc.apply(ctx, [item["id"]])
    assert result["done"] == [] and "no longer eligible" in result["skipped"][0]["reason"]
    assert wt.exists()


def test_commits_after_the_merged_pr_head_are_unpushed(repo) -> None:
    wt = repo.worktree("eager-elk-111111", branch="claude/more")
    merged = repo.commit(wt, "work")
    repo.commit(wt, "after-merge")
    ctx = context(repo, sessions((str(wt), True, False)),
                  FakeGitHub([pr(9, "MERGED", "claude/more", merged)]))
    item = only(items(ctx), "worktree", path=str(wt))
    assert item["tier"] == dc.REPORT and "unpushed" in item["reason"]


def test_state_change_between_report_and_apply_is_skipped(repo) -> None:
    git(repo.main, "branch", "claude/old")
    tip = repo.head(repo.main)
    ctx = context(repo, github=FakeGitHub([pr(10, "MERGED", "claude/old", tip)]))
    item = only(items(ctx), "branch", branch="claude/old")
    assert item["tier"] == dc.CONFIRM

    git(repo.main, "switch", "-q", "claude/old")
    repo.commit(repo.main, "new-local-work")
    git(repo.main, "switch", "-q", "main")
    result = dc.apply(ctx, [item["id"]])

    assert result["done"] == []
    assert "state changed" in result["skipped"][0]["reason"]
    assert "claude/old" in git(repo.main, "branch", "--format=%(refname:short)")


def test_delete_branch_refuses_a_moved_tip(repo) -> None:
    git(repo.main, "branch", "claude/racy")
    stale = repo.head(repo.main)
    git(repo.main, "switch", "-q", "claude/racy")
    repo.commit(repo.main, "raced")
    git(repo.main, "switch", "-q", "main")
    ok, _ = dc.delete_branch(str(repo.main), "claude/racy", stale)
    assert not ok
    assert "claude/racy" in git(repo.main, "branch", "--format=%(refname:short)")


def test_detached_worktrees_on_and_off_the_default_branch(repo) -> None:
    on_main = repo.worktree("calm-cow-222222")
    off_main = repo.worktree("wild-wolf-333333")
    repo.commit(off_main, "local-only")
    found = items(context(repo, sessions((str(on_main), True, False),
                                         (str(off_main), True, False))))
    assert only(found, "worktree", path=str(on_main))["tier"] == dc.CONFIRM
    assert "unpushed" in only(found, "worktree", path=str(off_main))["reason"]


def test_worktrees_are_protected_without_a_session_list(repo) -> None:
    wt = repo.worktree("calm-cow-222222")
    item = only(items(context(repo)), "worktree", path=str(wt))
    assert item["tier"] == dc.REPORT and "unavailable" in item["reason"]


def test_worktree_with_no_known_session_is_your_call(repo) -> None:
    wt = repo.worktree("calm-cow-222222")
    item = only(items(context(repo, sessions(("/elsewhere", True, False)))), "worktree",
                path=str(wt))
    assert item["tier"] == dc.REPORT and "no known Claude session" in item["reason"]


@pytest.mark.parametrize("state,tier", [("CLOSED", dc.CONFIRM), ("MERGED", dc.CONFIRM),
                                        ("OPEN", dc.REPORT)])
def test_pr_copies_are_looked_up_by_number(repo, state: str, tier: str) -> None:
    git(repo.main, "branch", "pr-42")
    tip = repo.head(repo.main)
    github = FakeGitHub([pr(42, state, "someone/feature", tip)])
    assert only(items(context(repo, github=github)), "branch", branch="pr-42")["tier"] == tier


def test_github_failure_offers_nothing(repo) -> None:
    git(repo.main, "branch", "claude/whatever")
    item = only(items(context(repo, github=FakeGitHub(fail=True))), "branch",
                branch="claude/whatever")
    assert item["tier"] == dc.REPORT and "could not read PRs" in item["reason"]


def test_branches_checked_out_or_default_are_never_listed(repo) -> None:
    repo.worktree("busy-bee-444444", branch="claude/live")
    found = items(context(repo))
    branches = {i["details"]["branch"] for i in found.values() if i["kind"] == "branch"}
    assert branches.isdisjoint({"main", "claude/live"})


def test_unregistered_folder_under_a_root_is_reported(repo) -> None:
    stray = repo.root / "r" / "romantic-meninsky-0607c9"
    stray.mkdir()
    (stray / "notes.txt").write_text("only copy")
    item = only(items(context(repo)), "folder", path=str(stray))
    assert item["tier"] == dc.REPORT and "only copy" in item["reason"]


def test_hidden_repo_dirs_under_a_root_are_discovered(repo) -> None:
    hidden = repo.root / ".r"
    hidden.mkdir()
    path = hidden / "quiet-quail-555555"
    git(repo.main, "worktree", "add", "-q", "--detach", str(path), "origin/main")
    found = items(context(repo, sessions((str(path), True, False))))
    assert only(found, "worktree", path=str(path))["tier"] == dc.CONFIRM


def test_missing_worktree_folder_is_unregistered_then_its_branch_is_deletable(repo) -> None:
    wt = repo.worktree("gone-goat-666666", branch="claude/gone")
    other = repo.worktree("lost-lynx-777777")
    tip = repo.head(wt)
    subprocess.run(["rm", "-rf", str(wt), str(other)], check=True)
    ctx = context(repo, github=FakeGitHub([pr(11, "MERGED", "claude/gone", tip)]))
    found = items(ctx)
    stale = only(found, "worktree-stale", path=str(wt))
    branch = only(found, "branch", branch="claude/gone")
    assert stale["id"] == f"worktree-stale:{wt}@{tip}"
    assert stale["tier"] == dc.AUTO and branch["tier"] == dc.CONFIRM

    result = dc.apply(ctx, [branch["id"], stale["id"]])
    assert {d["id"] for d in result["done"]} == {stale["id"], branch["id"]}
    listing = git(repo.main, "worktree", "list")
    assert "gone-goat" not in listing and "lost-lynx" in listing  # only the named entry


def test_stale_entry_outside_the_roots_needs_confirming(repo) -> None:
    path = repo.tmp / "external" / "ejected-emu-888888"
    git(repo.main, "worktree", "add", "-q", "--detach", str(path), "origin/main")
    subprocess.run(["rm", "-rf", str(path)], check=True)
    item = only(items(context(repo)), "worktree-stale", path=str(path))
    assert item["tier"] == dc.CONFIRM and "outside the worktree roots" in item["reason"]


def test_stale_entry_whose_folder_reappears_is_skipped(repo) -> None:
    wt = repo.worktree("back-bear-999999")
    item = {"id": "x", "kind": "worktree-stale", "path": str(wt), "tier": dc.AUTO,
            "details": {"repo": str(repo.main)}}
    assert dc.apply_item(context(repo), item) == (False, "folder exists again")
    assert wt.exists() and "back-bear" in git(repo.main, "worktree", "list")


def test_gitignored_files_never_protect_a_worktree(repo) -> None:
    (repo.main / ".git" / "info" / "exclude").write_text(".env\n")
    ignored = repo.worktree("keen-kiwi-121212")
    (ignored / ".env").write_text("TOKEN=x")
    untracked = repo.worktree("cool-crab-131313")
    (untracked / "notes.txt").write_text("mine")
    ctx = context(repo, sessions((str(ignored), True, False), (str(untracked), True, False)))
    found = items(ctx)
    assert only(found, "worktree", path=str(untracked))["tier"] == dc.REPORT
    item = only(found, "worktree", path=str(ignored))
    assert item["tier"] == dc.CONFIRM

    result = dc.apply(ctx, [item["id"]])
    assert [d["id"] for d in result["done"]] == [item["id"]] and not ignored.exists()


def test_untracked_files_count_whatever_status_show_untracked_files_says(
        repo, monkeypatch) -> None:
    git(repo.main, "config", "status.showUntrackedFiles", "no")
    wt = repo.worktree("keen-kiwi-121212")
    (wt / "u.txt").write_text("mine")
    ctx = context(repo, sessions((str(wt), True, False)))
    item = only(items(ctx), "worktree", path=str(wt))
    assert item["tier"] == dc.REPORT and "uncommitted" in item["reason"]

    # Even past a stale "clean" re-check, git's own removal check still counts them.
    monkeypatch.setattr(dc, "worktree_dirty", lambda path: False)
    ok, why = dc.apply_item(ctx, {**item, "tier": dc.CONFIRM})
    assert not ok and "untracked" in why and (wt / "u.txt").exists()


def test_read_only_ignored_directories_do_not_strand_a_removal(repo) -> None:
    (repo.main / ".git" / "info" / "exclude").write_text("cache/\n")
    wt = repo.worktree("cool-crab-131313")
    (wt / "cache" / "ro").mkdir(parents=True)
    (wt / "cache" / "ro" / "f").write_text("")
    outside = repo.tmp / "outside-ro"
    outside.mkdir()
    (wt / "cache" / "link").symlink_to(outside)
    for folder in (wt / "cache" / "ro", outside):
        folder.chmod(0o555)
    try:
        ctx = context(repo, sessions((str(wt), True, False)))
        item = only(items(ctx), "worktree", path=str(wt))
        result = dc.apply(ctx, [item["id"]])
        assert [d["id"] for d in result["done"]] == [item["id"]] and not wt.exists()
        assert outside.stat().st_mode & 0o777 == 0o555  # the symlink wasn't followed
    finally:
        outside.chmod(0o755)


def test_apply_fails_closed_when_worktree_status_fails(repo, tmp_path) -> None:
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    item = {"id": "x", "kind": "worktree", "path": str(not_a_repo), "tier": dc.CONFIRM,
            "details": {"repo": str(repo.main), "branch": None, "head": ""}}
    assert dc.apply_item(context(repo), item) == (False, "could not read worktree status")
    assert not_a_repo.exists()


# --------------------------------------------------------------------------- #
# Docker behavior through the fake adapter
# --------------------------------------------------------------------------- #


def container(cid: str, folder: str, state: str, image_id: str = "sha256:img",
              started_at: str = "") -> dict:
    return {"id": cid, "name": cid, "state": state, "image_id": image_id,
            "labels": {dc.FOLDER_LABEL: folder}, "volumes": [], "started_at": started_at}


@pytest.mark.parametrize("started_at,shown", [
    ("2026-10-24T12:00:00.123456789Z", "up 3d"),
    ("2026-10-27T07:30:00Z", "up 4h"),
    ("", "up for an unknown time"),
    ("garbage", "up for an unknown time"),
])
def test_uptime(started_at: str, shown: str) -> None:
    now = calendar.timegm((2026, 10, 27, 12, 0, 0))
    assert dc.uptime({"started_at": started_at}, now) == shown


def test_containers_follow_their_worktree(repo, tmp_path) -> None:
    live = repo.worktree("busy-bee-444444", branch="claude/live")
    gone = str(repo.root / "r" / "eloquent-shannon-7eb6c5")
    docker = FakeDocker(containers=[container("c-live", str(live), "exited"),
                                    container("c-stopped", gone, "exited"),
                                    container("c-running", gone, "running")])
    found = items(context(repo, docker=docker))
    tiers = {i["details"]["container"]: i["tier"] for i in found.values()
             if i["kind"] == "container"}
    assert tiers == {"c-stopped": dc.AUTO, "c-running": dc.CONFIRM}


def test_containers_and_images_outside_the_roots_are_report_only(repo) -> None:
    gone = str(repo.tmp / "external-drive" / "project")
    tag = f"vsc-project-{dc.folder_hash(gone)}:latest"
    docker = FakeDocker(images=[image("sha256:v", "2026", tags=[tag])],
                        containers=[container("c", gone, "exited", image_id="sha256:v")])
    found = items(context(repo, docker=docker))
    assert found["container:c:exited"]["tier"] == dc.REPORT
    assert found["image:sha256:v"]["tier"] == dc.REPORT


def test_a_running_devcontainer_is_stopped_before_its_worktree_goes(repo) -> None:
    wt = repo.worktree("calm-cow-222222")

    class Recording(FakeDocker):
        def command(self, *args: str) -> dc.Result:
            if args[0] == "stop":
                assert wt.exists(), "worktree removed before its devcontainer stopped"
            if args[0] == "rm":
                assert not wt.exists(), "devcontainer removed before its worktree"
            return super().command(*args)

    docker = Recording(containers=[container("c", str(wt), "running")])
    ctx = context(repo, sessions((str(wt), True, False)), docker=docker)
    item = only(items(ctx), "worktree", path=str(wt))
    assert item["tier"] == dc.CONFIRM
    assert "stops its running devcontainer first: c (up " in item["reason"]
    assert item["id"].endswith("+containers:c")

    result = dc.apply(ctx, [item["id"]])
    assert [d["id"] for d in result["done"]] == [item["id"]]
    assert "removed devcontainer c" in result["done"][0]["result"]
    assert docker.calls[0] == ("stop", "c") and ("rm", "-v", "c") in docker.calls
    assert not wt.exists() and docker.containers() == []


@pytest.mark.parametrize("on_stop,reason", [
    # The container writes an untracked file as it shuts down: the re-check must see it.
    (lambda wt: (wt / "late.txt").write_text("mine"), "uncommitted changes"),
    # git refuses after the stop: the container must not be removed yet.
    (lambda wt: git(wt, "worktree", "lock", str(wt)), "locked"),
])
def test_a_worktree_kept_after_its_devcontainer_stops_keeps_the_container(
        repo, on_stop, reason: str) -> None:
    wt = repo.worktree("calm-cow-222222")

    class StopHook(FakeDocker):
        def command(self, *args: str) -> dc.Result:
            result = super().command(*args)
            if args[0] == "stop":
                on_stop(wt)
            return result

    docker = StopHook(containers=[container("c", str(wt), "running")])
    ctx = context(repo, sessions((str(wt), True, False)), docker=docker)
    result = dc.apply(ctx, [only(items(ctx), "worktree", path=str(wt))["id"]])
    assert result["done"] == []
    skipped = result["skipped"][0]["reason"]
    assert reason in skipped and "stopped, not removed: c" in skipped
    assert wt.exists() and ("rm", "-v", "c") not in docker.calls


def test_a_devcontainer_started_after_the_report_voids_the_worktree_id(repo) -> None:
    wt = repo.worktree("calm-cow-222222")
    docker = FakeDocker()
    ctx = context(repo, sessions((str(wt), True, False)), docker=docker)
    old_id = only(items(ctx), "worktree", path=str(wt))["id"]
    docker._containers.append(container("c", str(wt), "running"))
    result = dc.apply(ctx, [old_id])
    assert result["done"] == [] and "state changed" in result["skipped"][0]["reason"]
    assert wt.exists() and docker.calls == []


def test_a_devcontainer_that_will_not_stop_keeps_its_worktree(repo) -> None:
    wt = repo.worktree("calm-cow-222222")
    docker = FakeDocker(containers=[container("c", str(wt), "running")], failing=["stop"])
    ctx = context(repo, sessions((str(wt), True, False)), docker=docker)
    result = dc.apply(ctx, [only(items(ctx), "worktree", path=str(wt))["id"]])
    assert result["done"] == []
    assert result["skipped"][0]["reason"] == "kept worktree; docker stop c failed: stop refused"
    assert wt.exists() and "calm-cow" in git(repo.main, "worktree", "list")


def test_apply_stops_only_confirmed_running_containers(repo) -> None:
    gone = str(repo.root / "r" / "eloquent-shannon-7eb6c5")
    docker = FakeDocker(containers=[container("c-stopped", gone, "exited"),
                                    container("c-running", gone, "running")])
    ctx = context(repo, docker=docker)
    result = dc.apply(ctx, [i for i in items(ctx) if i.startswith("container:")])
    assert len(result["done"]) == 2
    assert ("stop", "c-running") in docker.calls and ("stop", "c-stopped") not in docker.calls
    assert ("rm", "-v", "c-stopped") in docker.calls


def test_vsc_images_map_by_hash_and_fail_closed(repo) -> None:
    gone = str(repo.root / "r" / "review-318-8a45c8")
    mapped = f"vsc-review-318-8a45c8-{dc.folder_hash(gone)}"
    unmapped = f"vsc-mystery-{'0' * 64}"
    docker = FakeDocker(images=[image("sha256:m", "2026", tags=[f"{mapped}:latest"]),
                                image("sha256:u", "2026", tags=[f"{unmapped}:latest"])])
    found = items(context(repo, docker=docker))
    assert found["image:sha256:m"]["tier"] == dc.CONFIRM
    assert found["image:sha256:u"]["tier"] == dc.REPORT


def test_base_images_referenced_by_a_checkout_dockerfile_are_kept(repo) -> None:
    keep, old, new = ("sha256:" + c * 64 for c in "abc")
    base = "ghcr.io/x/devcontainer-base"
    (repo.main / ".devcontainer").mkdir()
    (repo.main / ".devcontainer" / "Dockerfile").write_text(f"FROM {base}:latest@{keep}\n")
    docker = FakeDocker(images=[image(keep, "2026-01", digests=[f"{base}@{keep}"]),
                                image(old, "2026-02", digests=[f"{base}@{old}"]),
                                image(new, "2026-03", digests=[f"{base}@{new}"])])
    found = items(context(repo, docker=docker))
    assert found[f"image:{old}"]["tier"] == dc.CONFIRM
    assert f"image:{keep}" not in found and f"image:{new}" not in found


def test_base_images_named_by_devcontainer_json_are_kept(repo) -> None:
    keep, new = ("sha256:" + c * 64 for c in "ab")
    base = "ghcr.io/x/devcontainer-base"
    (repo.main / ".devcontainer").mkdir()
    (repo.main / ".devcontainer" / "devcontainer.json").write_text(
        f'{{"image": "{base}@{keep}"}}')
    docker = FakeDocker(images=[image(keep, "2026-01", digests=[f"{base}@{keep}"]),
                                image(new, "2026-02", digests=[f"{base}@{new}"])])
    assert not any(k.startswith("image:") for k in items(context(repo, docker=docker)))


def test_ownerless_anonymous_volumes_are_auto(repo) -> None:
    docker = FakeDocker(volumes=[
        {"name": "a" * 64, "anonymous": True, "dangling": True},
        {"name": "b" * 64, "anonymous": True, "dangling": False},
        {"name": "ud-cache", "anonymous": False, "dangling": True},
    ])
    found = items(context(repo, docker=docker))
    assert found[f"volume:{'a' * 64}"]["tier"] == dc.AUTO
    assert not any(k.startswith("volume:") and k != f"volume:{'a' * 64}" for k in found)


def test_apply_refuses_an_image_a_container_still_uses(repo) -> None:
    gone = str(repo.root / "r" / "review-318-8a45c8")
    tag = f"vsc-review-318-8a45c8-{dc.folder_hash(gone)}:latest"
    docker = FakeDocker(images=[image("sha256:m", "2026", tags=[tag])],
                        containers=[container("c", gone, "running", image_id="sha256:m")])
    ctx = context(repo, docker=docker)
    result = dc.apply(ctx, ["image:sha256:m"])
    assert result["done"] == [] and "still uses" in result["skipped"][0]["reason"]


def test_removing_a_worktree_reaps_its_stopped_container_and_offers_its_image(repo) -> None:
    wt = repo.worktree("calm-cow-222222")
    tag = f"vsc-calm-cow-222222-{dc.folder_hash(str(wt))}:latest"
    docker = FakeDocker(images=[image("sha256:v", "2026", tags=[tag])],
                        containers=[container("c", str(wt), "exited", image_id="sha256:v")])
    ctx = context(repo, sessions((str(wt), True, False)), docker=docker)
    found = items(ctx)
    assert not any(k.startswith(("container:", "image:")) for k in found)

    result = dc.apply(ctx, [only(found, "worktree", path=str(wt))["id"]])
    assert ("rm", "-v", "c") in docker.calls
    assert [i["id"] for i in result["follow_up"]] == ["image:sha256:v"]


def test_apply_measures_only_docker_raw(repo) -> None:
    (repo.root / "r" / "stray-folder").mkdir()
    measured: List[str] = []
    ctx = context(repo)
    ctx.du = lambda path: measured.append(path)
    dc.apply(ctx, ["branch:/nowhere:x@0"])
    assert measured == [str(repo.tmp / "Docker.raw")]


def test_unknown_ids_are_skipped(repo) -> None:
    result = dc.apply(context(repo), ["branch:/nowhere:x@0"])
    assert result["done"] == [] and "gone" in result["skipped"][0]["reason"]


def test_config_file_overrides_defaults(tmp_path) -> None:
    path = tmp_path / "dev-cleanup.json"
    path.write_text('{"extra_roots": ["~/elsewhere"]}')
    config = dc.load_config(str(path))
    assert config["extra_roots"] == ["~/elsewhere"]
    assert config["worktree_roots"] == dc.DEFAULT_CONFIG["worktree_roots"]
    with pytest.raises(SystemExit):
        dc.load_config(str(tmp_path / "missing.json"))


@pytest.mark.parametrize("body,message", [
    ('{"worktree_roots": "~/code"}', "must be a list of strings"),
    ('{"docker_raw": ["a"]}', "must be a string"),
    ('{"worktree_root": ["~/code"]}', "unknown key"),
    ('["~/code"]', "expected a JSON object"),
])
def test_config_file_is_validated(tmp_path, body: str, message: str) -> None:
    path = tmp_path / "dev-cleanup.json"
    path.write_text(body)
    with pytest.raises(SystemExit, match=message):
        dc.load_config(str(path))
