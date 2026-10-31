import json
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_site_targets_all_hosts() -> None:
    site_text = (REPO_ROOT / "site.yml").read_text()

    assert "hosts: all" in site_text


def test_inventory_defines_personal_and_work_machine_groups() -> None:
    inventory_text = (REPO_ROOT / "inventory.yml").read_text()

    assert "personal:" in inventory_text
    assert "work:" in inventory_text


def test_inventory_defines_macos_and_linux_os_groups() -> None:
    """The `os` group set partitions hosts by OS. macOS hosts (laptop24,
    mini18, mini26) live in `macos`; Linux hosts (devbox) live in `linux`.
    Each host is in exactly one group per set — purpose AND os."""
    inventory_text = (REPO_ROOT / "inventory.yml").read_text()

    assert "macos:" in inventory_text
    assert "linux:" in inventory_text


def test_group_sets_declares_both_purpose_and_os() -> None:
    """group_sets is the authoritative list of active group sets, iterated
    by every role's `lookup('vars', 'group_<set>_<thing>')` indirection.
    Order matters for concatenation (purpose contribution before os)."""
    all_vars_text = (REPO_ROOT / "group_vars" / "all.yml").read_text()

    assert "group_sets:" in all_vars_text
    # Ordering: purpose before os in the list.
    purpose_idx = all_vars_text.find("- purpose")
    os_idx = all_vars_text.find("- os")
    assert 0 < purpose_idx < os_idx, "group_sets should list purpose before os"


def test_os_group_vars_define_their_layered_contributions() -> None:
    """The `lookup('vars', name)`-based indirection raises on missing
    vars (intentionally, to catch typos). Each group_vars/<group>.yml
    must declare every layered var that a role running on hosts in that
    group might consume. macos hosts run homebrew + macos_defaults;
    linux hosts run homebrew + apt + flatpak."""
    macos_text = (REPO_ROOT / "group_vars" / "macos.yml").read_text()
    linux_text = (REPO_ROOT / "group_vars" / "linux.yml").read_text()

    # macos.yml: brewfile (path) + macos_defaults vars (lists).
    assert "group_os_brewfile:" in macos_text
    assert "brewfiles/groups/macos.Brewfile" in macos_text
    assert "group_os_macos_defaults: []" in macos_text
    assert "group_os_dockitems_persist: []" in macos_text
    assert "group_os_dockitems_remove: []" in macos_text

    # linux.yml: brewfile (empty path — filtered by stat step) + apt/flatpak.
    assert 'group_os_brewfile: ""' in linux_text
    assert "group_os_apt: []" in linux_text
    assert "group_os_flatpak: []" in linux_text


def test_macos_brewfile_layer_carries_dockutil() -> None:
    """dockutil is macOS-only at the formula level (depends_on :macos).
    It lives in the os-set's macos Brewfile so it can't accidentally
    leak into a Linuxbrew install path."""
    brewfile = (REPO_ROOT / "brewfiles" / "groups" / "macos.Brewfile").read_text()

    assert 'brew "dockutil"' in brewfile


def test_roles_use_lookup_vars_indirection_over_group_sets() -> None:
    """Each role that consumes layered vars should iterate `group_sets`
    via `lookup('vars', ...)` rather than hardcoding `group_purpose_*`.
    Lock in that the indirection is actually in place — a regression
    that hardcodes `group_purpose_<thing>` would still work today (since
    purpose is in group_sets) but would silently drop contributions from
    any future set."""
    for role, layered_var in (
        ("apt", "apt"),
        ("flatpak", "flatpak"),
        ("homebrew", "brewfile"),
        ("macos_defaults", "macos_defaults"),
    ):
        tasks = (REPO_ROOT / "roles" / role / "tasks" / "main.yml").read_text()
        assert "group_sets" in tasks, f"{role} doesn't iterate group_sets"
        assert f"'group_' ~ item ~ '_{layered_var}'" in tasks, (
            f"{role} doesn't lookup group_<set>_{layered_var}"
        )
        assert f"group_purpose_{layered_var}" not in tasks, (
            f"{role} still hardcodes group_purpose_{layered_var}"
        )


def test_brewfile_layering_is_split_across_common_group_and_host_vars() -> None:
    """All-hosts gets common_brewfile; each purpose group gets its own
    group_purpose_brewfile (the set-qualified name; see group_vars/all.yml
    for the naming convention). Scope is encoded as a prefix so vars at the
    same scope sort together alphabetically."""
    all_vars_text = (REPO_ROOT / "group_vars" / "all.yml").read_text()
    personal_vars_text = (REPO_ROOT / "group_vars" / "personal.yml").read_text()
    work_vars_text = (REPO_ROOT / "group_vars" / "work.yml").read_text()

    assert 'common_brewfile: "{{ playbook_dir }}/brewfiles/common.Brewfile"' in all_vars_text
    assert (
        'group_purpose_brewfile: "{{ playbook_dir }}/brewfiles/groups/personal.Brewfile"'
        in personal_vars_text
    )
    assert (
        'group_purpose_brewfile: "{{ playbook_dir }}/brewfiles/groups/work.Brewfile"'
        in work_vars_text
    )


def test_macos_defaults_layering_uses_same_prefix_convention() -> None:
    """The macos_defaults role concatenates common + group_purpose + host
    layers for both osx_defaults entries and Dock items. Lock in that each
    scope is seeded as an empty list at the right scope, so an opt-in
    host can just append without first having to define the layer."""
    all_vars_text = (REPO_ROOT / "group_vars" / "all.yml").read_text()
    personal_vars_text = (REPO_ROOT / "group_vars" / "personal.yml").read_text()
    work_vars_text = (REPO_ROOT / "group_vars" / "work.yml").read_text()

    for name in ("common_macos_defaults", "common_dockitems_persist", "common_dockitems_remove"):
        assert f"{name}: []" in all_vars_text, name
    for name in (
        "group_purpose_macos_defaults",
        "group_purpose_dockitems_persist",
        "group_purpose_dockitems_remove",
    ):
        assert f"{name}: []" in personal_vars_text, name
        assert f"{name}: []" in work_vars_text, name


def test_macos_defaults_role_wires_layered_lists_and_dock() -> None:
    """The role should: (1) compose the three layered sources (common +
    group-set indirection + host) into macos_defaults_resolved, (2) loop
    osx_defaults over it, (3) import geerlingguy.mac.dock behind
    macos_defaults_configure_dock, and (4) honor the
    macos_defaults_extras_script shell escape hatch."""
    tasks = (REPO_ROOT / "roles" / "macos_defaults" / "tasks" / "main.yml").read_text()

    assert "common_macos_defaults" in tasks
    assert "macos_defaults_group_layer" in tasks
    assert "host_macos_defaults" in tasks
    assert "community.general.osx_defaults" in tasks
    assert "geerlingguy.mac.dock" in tasks
    assert "macos_defaults_configure_dock" in tasks
    assert "macos_defaults_extras_script" in tasks


def _renovate_config() -> dict:
    """renovate.json is consumed only by Mend-hosted Renovate, so nothing
    else in CI would catch a syntax error — the first symptom would be
    silently stalled dependency updates. Parsing it here is the gate."""
    return json.loads((REPO_ROOT / "renovate.json").read_text())


_CATCH_ALL_GROUP = "all non-major dependencies"


def _matches_minor_or_patch(rule: dict) -> bool:
    """No `matchUpdateTypes` means the rule matches every update type."""
    types = rule.get("matchUpdateTypes")
    return types is None or bool({"minor", "patch"} & set(types))


def _catch_all_index(rules: list) -> int:
    """The minor/patch catch-all, keyed on its groupName: the base-image digest
    rule shares that groupName but matches only digests."""
    matches = [
        i
        for i, r in enumerate(rules)
        if r.get("groupName") == _CATCH_ALL_GROUP and _matches_minor_or_patch(r)
    ]
    assert len(matches) == 1, f"expected exactly one minor/patch catch-all, found {len(matches)}"
    return matches[0]


# `uses: owner/repo[/path]@<40-hex sha> # v<major>.<minor>.<patch>`. The version
# comment is what Renovate reads to compute the next update, so all three
# components are required — see the assertion's docstring.
_PINNED_USES_RE = re.compile(
    r"uses:\s+(?P<action>[\w.-]+/[\w./-]+)@(?P<ref>\S+)(?:\s+#\s*(?P<version>\S+))?"
)
_FULL_SEMVER_RE = re.compile(r"^v?\d+\.\d+\.\d+$")

# The one `uses:` that floats by design; renovate.json carries the matching
# `pinDigests: false` carve-out. See CLAUDE.md "Devcontainer lock regeneration".
_UNPINNED_ACTION_ALLOWLIST = {"Syndic/unnatural_designs/.github/actions/commit-file-via-app"}


def test_workflow_actions_are_sha_pinned_to_full_semver() -> None:
    """Every `uses:` must be a 40-hex commit SHA with a full three-component
    version comment.

    The SHA is what Actions resolves — a tag is mutable, a commit is not.
    The comment must carry all three components because a bare-major comment
    (`# v7`) tracks the floating `v7` tag: every `v7.x` release then moves the
    SHA under a fixed version string, which Renovate reports as a `digest`
    update and which renovate.json's catch-all deliberately does not batch.
    Routine upgrades would arrive wearing a supply-chain signal's clothing.

    This can't self-heal — under `helpers:pinGitHubActionDigestsToSemver`'s
    versioning regex, minor and patch are optional, so `v7` and `v7.0.0`
    compare equal and Renovate never offers the rewrite. A hand-written `@v7`
    stays wrong until a human notices, which is why this is a test."""
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows, "no workflows found — did the path move?"

    problems = []
    seen = 0
    for workflow in workflows:
        for lineno, line in enumerate(workflow.read_text().splitlines(), start=1):
            match = _PINNED_USES_RE.search(line)
            if not match:
                continue
            seen += 1
            action, ref, version = match.group("action", "ref", "version")
            if action in _UNPINNED_ACTION_ALLOWLIST:
                continue
            where = f"{workflow.name}:{lineno} {action}"
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                problems.append(f"{where} is not pinned to a 40-hex SHA (got @{ref})")
            elif version is None:
                problems.append(f"{where} has no `# <version>` comment")
            elif not _FULL_SEMVER_RE.match(version):
                problems.append(f"{where} comment `# {version}` is not full semver (want vX.Y.Z)")

    assert not problems, "\n".join(problems)
    assert seen >= len(workflows), "regex matched suspiciously few `uses:` lines"


def test_renovate_pins_action_digests_to_semver() -> None:
    """The preset is what keeps the version comments accurate through
    updates. Without it the pins are still valid but go stale silently."""
    assert "helpers:pinGitHubActionDigestsToSemver" in _renovate_config()["extends"]


def test_renovate_exempts_the_floating_cross_repo_action() -> None:
    """The allowlisted `@main` action needs a matching carve-out, or the
    preset's `pinDigests: true` would SHA-pin it and quietly reverse a
    documented decision. (Renovate does pin branch refs, not just tags — it
    routes them to the github-digest datasource.)"""
    rules = _renovate_config()["packageRules"]
    carve_outs = [rule for rule in rules if rule.get("pinDigests") is False]

    assert len(carve_outs) == 1, "expected exactly one pinDigests carve-out"
    patterns = set(carve_outs[0]["matchPackageNames"])
    # Renovate's github-actions manager strips the subpath: an action at
    # `owner/repo/some/path@ref` gets packageName `owner/repo`. Match on that.
    for allowed in _UNPINNED_ACTION_ALLOWLIST:
        owner_repo = "/".join(allowed.split("/")[:2])
        assert owner_repo in patterns, f"carve-out {patterns} doesn't cover {owner_repo}"


def test_renovate_batches_non_major_updates_in_one_group() -> None:
    """The catch-all that collapses routine minor/patch bumps into a single
    PR. See CLAUDE.md "Dependency updates" for why the axis is update type, and
    why digest is excluded from the catch-all by default (a moving digest on an
    immutable version tag is a re-tag — a supply-chain signal that deserves
    its own PR)."""
    rules = _renovate_config()["packageRules"]
    catch_all = rules[_catch_all_index(rules)]

    assert sorted(catch_all.get("matchUpdateTypes", [])) == ["minor", "patch"]


def test_renovate_batches_floating_base_image_digests() -> None:
    """The three base images pinned to a floating tag + digest (see CLAUDE.md
    "Base image pins") get their digest updates funneled into the same batch
    as routine bumps — on a floating tag a moving digest IS the update
    mechanism, so a solo PR per digest would be noise. The rule must share the
    catch-all's groupName and be scoped to digest updates on exactly those
    packages, so an immutable-tag image elsewhere still gets the default
    solo-PR treatment."""
    rules = _renovate_config()["packageRules"]
    digest_rules = [
        rule
        for rule in rules
        if rule.get("matchUpdateTypes") == ["digest"]
        and rule.get("groupName") == _CATCH_ALL_GROUP
    ]

    assert len(digest_rules) == 1, "expected exactly one base-image digest-batching rule"
    assert digest_rules[0]["matchDatasources"] == ["docker"]
    assert set(digest_rules[0]["matchPackageNames"]) == {
        "geerlingguy/docker-debian12-ansible",
        "mcr.microsoft.com/devcontainers/base",
        "debian",
    }


def test_renovate_custom_manager_tracks_molecule_images() -> None:
    """molecule.yml is parsed by no built-in Renovate manager, so without a
    customManager the pinned digests would never refresh and the scenarios
    would silently rot on a fixed image. Assert the manager exists and its
    matchStrings capture the four groups Renovate needs to resolve and rewrite
    a digest: datasource, depName, currentValue (the tag), currentDigest.

    Also assert versioningTemplate is `docker`. A customManager with no
    versioning capture group and no versioningTemplate defaults to
    `semver-coerced` (per Renovate's regex-manager docs), and the `latest`
    tag can't be coerced to semver — which silently suppresses the digest
    update while the dashboard still lists the dependency as detected. That
    failure shipped in #106 and was caught by the #107 canary; this assertion
    is the regression guard."""
    managers = _renovate_config()["customManagers"]
    molecule_mgrs = [
        m for m in managers if any("molecule" in p for p in m.get("managerFilePatterns", []))
    ]

    assert len(molecule_mgrs) == 1, "expected one molecule.yml customManager"
    manager = molecule_mgrs[0]
    match_string = manager["matchStrings"][0]
    for group in ("?<datasource>", "?<depName>", "?<currentValue>", "?<currentDigest>"):
        assert group in match_string, f"matchStrings missing capture group {group}"
    # No `versioning` capture group in the regex, so the template is the only
    # source — it must be set, and to docker. The customManager default is
    # `semver-coerced`, which is the wrong scheme for a docker image tag (a bare
    # `latest` is not a semver version). See CLAUDE.md "Base image pins".
    assert "?<versioning>" not in match_string, (
        "unexpected versioning capture group — the assertion below assumes the template is authoritative"
    )
    assert manager.get("versioningTemplate") == "docker", (
        "molecule customManager must set versioningTemplate=docker; the customManager "
        "default semver-coerced is the wrong scheme for a docker image tag"
    )


def _molecule_image_lines():
    """Yield (relpath, lineno, prev_line, image_ref) for every `image:` line in
    the molecule scenarios. Shared by the digest-pin and index-digest guards."""
    for scenario in sorted((REPO_ROOT / "roles").glob("*/molecule/*/molecule.yml")):
        lines = scenario.read_text().splitlines()
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("image:"):
                image = stripped[len("image:") :].strip()
                prev = lines[lineno - 2] if lineno >= 2 else ""
                yield scenario.relative_to(REPO_ROOT), lineno, prev, image


def test_molecule_base_images_are_digest_pinned() -> None:
    """Every registry-pulled molecule image must carry a @sha256 digest, and
    every digest-pinned line must sit under a `# renovate:` annotation the
    customManager keys on (an unannotated pin would freeze forever). The
    homebrew scenarios are exempt — they reference a locally-built
    `:local` tag, not a registry image."""
    rows = list(_molecule_image_lines())
    assert rows, "no molecule image lines found — did the layout move?"

    problems = []
    for rel, lineno, prev, image in rows:
        if image.endswith(":local"):
            continue  # locally-built homebrew base, not registry-pulled
        if "@sha256:" not in image:
            problems.append(f"{rel}:{lineno} registry image not digest-pinned: {image}")
        elif "# renovate:" not in prev:
            problems.append(f"{rel}:{lineno} digest pin lacks a preceding `# renovate:` annotation")

    assert not problems, "\n".join(problems)


def test_molecule_platform_names_are_unique_across_scenarios() -> None:
    """tests/run runs scenarios concurrently, and a platform `name:` is the
    docker container name — two scenarios sharing one would collide. See
    CLAUDE.md "Tests"."""
    owners: dict = {}
    for scenario in sorted((REPO_ROOT / "roles").glob("*/molecule/*/molecule.yml")):
        text = scenario.read_text()
        block = re.search(r"^platforms:\n((?:[ #].*\n|\n)*)", text, re.MULTILINE)
        rel = scenario.relative_to(REPO_ROOT)
        assert block, f"{rel} has no platforms: block"
        names = re.findall(
            r"^  - name: [\"']?([^\"'\s]+)", block.group(1), re.MULTILINE
        )
        # A layout the regex doesn't recognise must fail, not silently pass.
        assert names, f"{rel}: no `  - name:` platform entries recognised"
        for name in names:
            owners.setdefault(name, []).append(str(rel))
    dupes = {n: paths for n, paths in owners.items() if len(paths) > 1}
    assert not dupes, f"platform names shared across scenarios: {dupes}"


def test_ci_pulls_the_homebrew_image_tag_the_publish_workflow_pushes() -> None:
    """tests/run pulls MOLECULE_HOMEBREW_IMAGE_REPO at image-tag.sh's tag, so
    the publish workflow must push that repo under that tag. See CLAUDE.md
    "Homebrew molecule scenarios"."""
    workflows = REPO_ROOT / ".github" / "workflows"
    tests_yml = (workflows / "tests.yml").read_text()
    publish = (workflows / "publish-molecule-images.yml").read_text()

    repo = re.search(r"MOLECULE_HOMEBREW_IMAGE_REPO:\s*(\S+)", tests_yml)
    assert repo, "tests.yml no longer sets MOLECULE_HOMEBREW_IMAGE_REPO"
    repo = repo.group(1)
    # tests/run appends the tag; one here would produce `repo:tag:tag`.
    assert ":" not in repo.rsplit("/", 1)[-1], f"repo carries a tag: {repo}"

    images = re.search(r"images:[ \t]*(.+)$", publish, re.MULTILINE)
    assert images, "publish workflow has no metadata-action `images:`"
    owner = repo.split("/")[1]
    published = images.group(1).strip().replace("${{ steps.owner.outputs.value }}", owner)
    assert published == repo

    assert "roles/homebrew/molecule/image-tag.sh" in publish
    assert "type=raw,value=${{ steps.image-tag.outputs.value }}" in publish


def test_molecule_ci_prepulls_images_before_the_installs() -> None:
    """The background pull only saves time if it starts before the pip
    install it overlaps. See CLAUDE.md "Tests"."""
    tests_yml = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text()
    pull = tests_yml.find("- run: ./tests/run pull ${{ matrix.role }}")
    install = tests_yml.find("- run: pip install -r molecule-requirements.txt")
    assert pull != -1, "molecule job no longer pre-pulls images"
    assert install != -1, "molecule job's pip install step moved"
    assert pull < install
    pull_line = tests_yml[pull:].splitlines()[0]
    assert pull_line.rstrip().endswith("&"), "pre-pull must run in the background"


# Manifest media types: a multi-platform *index* (manifest list) vs a
# single-arch *child* image manifest.
_INDEX_MEDIA_TYPES = frozenset(
    {
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    }
)
_CHILD_MEDIA_TYPES = frozenset(
    {
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    }
)


def _docker_hub_manifest_media_type(repo: str, digest: str) -> str:
    """Return the manifest media type a Docker Hub digest points at, via an
    anonymous pull token. Raises on any network/registry error — the caller
    turns that into a skip so offline runs don't fail."""
    import json
    import urllib.request

    accept = ", ".join(_INDEX_MEDIA_TYPES | _CHILD_MEDIA_TYPES)
    token_url = (
        "https://auth.docker.io/token"
        f"?service=registry.docker.io&scope=repository:{repo}:pull"
    )
    token = json.load(urllib.request.urlopen(token_url, timeout=10))["token"]
    req = urllib.request.Request(
        f"https://registry-1.docker.io/v2/{repo}/manifests/{digest}",
        headers={"Authorization": f"Bearer {token}", "Accept": accept},
        method="HEAD",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.headers["Content-Type"]


def test_molecule_images_pin_index_not_child_digest() -> None:
    """Each molecule pin must be a multi-platform *index* digest, not a
    single-arch *child*.

    Renovate perpetuates whichever kind the pin already is: its docker
    datasource reads the current digest's architecture, and if it finds one
    (a child) it re-pins the same-arch child on every future bump; if it finds
    none (an index) it tracks the index. So a child pin silently locks the
    scenarios to one architecture forever — an amd64 child fails
    `exec format error` on an arm64 host with no emulation (e.g. a dev's
    Apple-Silicon devcontainer). A plain "is it @sha256-pinned?" check passes
    a child digest, which is exactly how the #107 canary degraded these pins;
    this classifies the digest against the registry to catch it.

    Network-dependent by necessity (the kind can't be told from the digest
    string), so it skips cleanly offline; CI has network and enforces it."""
    import pytest

    checked = 0
    for rel, lineno, _prev, image in _molecule_image_lines():
        if "@sha256:" not in image:
            continue  # :local or unpinned — covered by the digest-pin test
        ref, digest = image.split("@", 1)
        repo = ref.rsplit(":", 1)[0]  # strip the tag, keep owner/name
        try:
            media_type = _docker_hub_manifest_media_type(repo, digest)
        except Exception as err:  # noqa: BLE001 — any failure means "can't verify now"
            pytest.skip(f"registry unreachable ({err!r}); skipping index-digest check")
        assert media_type in _INDEX_MEDIA_TYPES, (
            f"{rel}:{lineno} pins a {'child' if media_type in _CHILD_MEDIA_TYPES else 'non-index'} "
            f"digest ({media_type}); molecule pins must be the multi-platform index digest so "
            f"Renovate keeps tracking the index and each host selects its own arch"
        )
        checked += 1

    assert checked, "no digest-pinned molecule images were checked — did the layout move?"


def _is_carve_out(rule: dict) -> bool:
    """A grouping rule the catch-all would overwrite if it came first."""
    if rule.get("groupName") in (None, _CATCH_ALL_GROUP):
        return False
    return _matches_minor_or_patch(rule)


def _misordered_carve_outs(rules: list) -> list:
    """Carve-outs placed ahead of the catch-all."""
    catch_all = _catch_all_index(rules)
    return [r["groupName"] for r in rules[:catch_all] if _is_carve_out(r)]


def test_renovate_carve_outs_follow_the_catch_all() -> None:
    """Last matching rule wins, so a carve-out ahead of the catch-all is
    overwritten by it and its updates go silently back into the batch. See
    CLAUDE.md "Dependency updates"."""
    misordered = _misordered_carve_outs(_renovate_config()["packageRules"])

    assert misordered == [], (
        f"{misordered} sit ahead of the catch-all, which overrides them for minor/patch "
        "updates. Move a carve-out after it. A rule that should group only majors and "
        "leave minor/patch to the batch says so with `matchUpdateTypes: [\"major\"]`."
    )


def test_renovate_carves_python_minors_out_of_the_batch() -> None:
    """A Python minor can outrun the pinned tooling; see CLAUDE.md
    "Dependency updates"."""
    rules = [
        r
        for r in _renovate_config()["packageRules"]
        if r.get("groupName") == "Python language version"
    ]

    assert len(rules) == 1
    assert rules[0]["matchDepNames"] == ["python"]
    assert rules[0]["matchUpdateTypes"] == ["minor"], "patches stay in the batch"


def test_renovate_carves_pre_1_0_minors_out_of_the_batch() -> None:
    """Under 0.x semver the minor is the breaking bump; see CLAUDE.md
    "Dependency updates". The regex must catch both a bare docker tag (uv)
    and a `v`-prefixed action tag, and nothing at 1.0 or above."""
    rules = [
        r
        for r in _renovate_config()["packageRules"]
        if r.get("groupName") == "pre-1.0 minor updates"
    ]

    assert len(rules) == 1
    assert rules[0]["matchUpdateTypes"] == ["minor"], "patches stay in the batch"
    pattern = rules[0]["matchCurrentVersion"]
    assert pattern.startswith("/") and pattern.endswith("/"), "Renovate regex form is /…/"
    regex = re.compile(pattern[1:-1])
    for version in ("0.13.6", "v0.3.1900000450"):
        assert regex.search(version), f"{pattern} misses {version}"
    for version in ("1.0.0", "v10.2.0", "20.1.0"):
        assert not regex.search(version), f"{pattern} wrongly matches {version}"


def _precommit_hooks() -> dict:
    """{hook id: (repo, hook body)} by plain parse — ~/.venv has no PyYAML."""
    text = (REPO_ROOT / ".pre-commit-config.yaml").read_text()
    hooks = {}
    for repo_block in re.split(r"^  - repo: ", text, flags=re.MULTILINE)[1:]:
        repo = repo_block.splitlines()[0].strip()
        for hook in re.split(r"^      - id: ", repo_block, flags=re.MULTILINE)[1:]:
            hooks[hook.splitlines()[0].strip()] = (repo, hook)
    return hooks


def test_precommit_lint_hooks_run_the_pinned_venv_tools() -> None:
    """A remote `repo:` + `rev:` hook builds its own env, pinned apart from
    lint-requirements.txt (and with ansible-core unpinned), so local and CI
    lint drift. Every tool lint-requirements.txt pins must run as a local
    `language: system` hook instead. See CLAUDE.md "Lint"."""
    lint_reqs = (REPO_ROOT / "lint-requirements.txt").read_text()
    tools = re.findall(r"^([\w.-]+)==", lint_reqs, flags=re.MULTILINE)
    assert tools, "no pins parsed from lint-requirements.txt"

    hooks = _precommit_hooks()
    for tool in tools:
        assert tool in hooks, f"no pre-commit hook for {tool}"
        repo, body = hooks[tool]
        assert repo == "local", f"{tool} hook comes from {repo}, not the venv"
        assert re.search(r"^\s+language: system$", body, re.MULTILINE), (
            f"{tool} hook must be `language: system`"
        )


_CATCH_ALL_RULE = {"matchUpdateTypes": ["minor", "patch"], "groupName": _CATCH_ALL_GROUP}
_LATE_MINOR = {"matchUpdateTypes": ["minor"], "groupName": "late"}


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        pytest.param(
            [{"matchUpdateTypes": ["minor"], "groupName": "early"}, _CATCH_ALL_RULE],
            ["early"],
            id="minor-ahead",
        ),
        pytest.param(
            [{"matchDepNames": ["x"], "groupName": "untyped"}, _CATCH_ALL_RULE],
            ["untyped"],
            id="untyped-ahead",
        ),
        pytest.param(
            [{"matchUpdateTypes": ["major"], "groupName": "majors"}, _CATCH_ALL_RULE, _LATE_MINOR],
            [],
            id="major-only-ahead-is-fine",
        ),
        pytest.param(
            [
                {"matchUpdateTypes": ["digest"], "groupName": _CATCH_ALL_GROUP},
                _CATCH_ALL_RULE,
                _LATE_MINOR,
            ],
            [],
            id="joining-the-batch-is-not-a-carve-out",
        ),
        pytest.param(
            [_CATCH_ALL_RULE, {"matchManagers": ["x"], "pinDigests": False}],
            [],
            id="no-carve-out",
        ),
        pytest.param(
            [{"matchUpdateTypes": ["patch", "minor"], "groupName": _CATCH_ALL_GROUP}, _LATE_MINOR],
            [],
            id="catch-all-types-in-any-order",
        ),
        pytest.param(
            [_CATCH_ALL_RULE, {"matchUpdateTypes": ["minor", "patch"], "groupName": "late"}],
            [],
            id="minor-and-patch-carve-out-is-not-a-catch-all",
        ),
    ],
)
def test_misordered_carve_outs(rules: list, expected: list) -> None:
    assert _misordered_carve_outs(rules) == expected


def test_misordered_carve_outs_requires_a_catch_all() -> None:
    with pytest.raises(AssertionError):
        _misordered_carve_outs([_LATE_MINOR])


def test_renovate_catch_all_does_not_group_majors() -> None:
    """Majors must fall through to their own branch so a breaking bump is
    never buried in a batch of routine ones."""
    rules = _renovate_config()["packageRules"]

    for rule in rules:
        assert "major" not in rule.get("matchUpdateTypes", []), (
            f"rule {rule.get('groupName') or rule.get('description')!r} groups major updates"
        )


def test_host_brewfiles_live_under_brewfiles_hosts() -> None:
    for host_name in ("laptop24", "mini18", "mini26"):
        host_vars_text = (REPO_ROOT / "host_vars" / f"{host_name}.yml").read_text()

        assert (
            f'host_brewfile: "{{{{ playbook_dir }}}}/brewfiles/hosts/{host_name}.Brewfile"'
            in host_vars_text
        )


def test_homebrew_image_tag_covers_everything_the_build_reads() -> None:
    """image-tag.sh hashes only the Dockerfile, so the build must read
    nothing else from its context — a COPY'd file edited in a PR would
    otherwise keep main's tag and test main's image."""
    dockerfile = REPO_ROOT / "roles" / "homebrew" / "molecule" / "Dockerfile"
    reads = [
        line
        for line in dockerfile.read_text().splitlines()
        if re.match(r"\s*(COPY|ADD)\b", line, re.IGNORECASE)
    ]
    assert not reads, f"extend image-tag.sh to hash these inputs too: {reads}"
