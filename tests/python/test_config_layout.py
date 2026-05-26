from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_site_targets_all_hosts() -> None:
    site_text = (REPO_ROOT / "site.yml").read_text()

    assert "hosts: all" in site_text


def test_inventory_defines_personal_and_work_machine_groups() -> None:
    inventory_text = (REPO_ROOT / "inventory.yml").read_text()

    assert "personal:" in inventory_text
    assert "work:" in inventory_text


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
    """The role should: (1) concatenate the three layers into
    macos_defaults_resolved, (2) loop osx_defaults over it,
    (3) import geerlingguy.mac.dock behind configure_dock, and
    (4) honor the macos_defaults_extras_script shell escape hatch."""
    tasks = (REPO_ROOT / "roles" / "macos_defaults" / "tasks" / "main.yml").read_text()

    assert "common_macos_defaults" in tasks
    assert "group_purpose_macos_defaults" in tasks
    assert "host_macos_defaults" in tasks
    assert "community.general.osx_defaults" in tasks
    assert "geerlingguy.mac.dock" in tasks
    assert "configure_dock" in tasks
    assert "macos_defaults_extras_script" in tasks


def test_host_brewfiles_live_under_brewfiles_hosts() -> None:
    for host_name in ("laptop24", "mini18", "mini26"):
        host_vars_text = (REPO_ROOT / "host_vars" / f"{host_name}.yml").read_text()

        assert (
            f'host_brewfile: "{{{{ playbook_dir }}}}/brewfiles/hosts/{host_name}.Brewfile"'
            in host_vars_text
        )
