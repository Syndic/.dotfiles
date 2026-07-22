import json
import re
from pathlib import Path


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
    """The catch-all that collapses routine bumps into a single PR. See
    CLAUDE.md "Dependency updates" for why the axis is update type rather
    than manager, and why pin/digest are excluded (a digest-only change is
    a re-tag — a supply-chain signal that deserves its own PR)."""
    rules = _renovate_config()["packageRules"]
    catch_all = [rule for rule in rules if rule.get("groupName") == "all non-major dependencies"]

    assert len(catch_all) == 1, "expected exactly one non-major catch-all rule"
    assert catch_all[0]["matchUpdateTypes"] == ["minor", "patch"]


def test_renovate_catch_all_rule_sorts_last() -> None:
    """Renovate merges matching packageRules in order, last writer wins.
    A groupName set by a later rule would beat the catch-all and split the
    batch back out, so the catch-all has to be the final entry."""
    rules = _renovate_config()["packageRules"]

    assert rules[-1].get("groupName") == "all non-major dependencies", (
        "the non-major catch-all must be the last packageRules entry"
    )


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
