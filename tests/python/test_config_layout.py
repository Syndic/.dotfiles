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
    """All-hosts gets brewfile_common; each purpose group gets its own
    group_purpose_brewfile (the set-qualified name; see group_vars/all.yml
    for the naming convention)."""
    all_vars_text = (REPO_ROOT / "group_vars" / "all.yml").read_text()
    personal_vars_text = (REPO_ROOT / "group_vars" / "personal.yml").read_text()
    work_vars_text = (REPO_ROOT / "group_vars" / "work.yml").read_text()

    assert 'brewfile_common: "{{ playbook_dir }}/brewfiles/common.Brewfile"' in all_vars_text
    assert (
        'group_purpose_brewfile: "{{ playbook_dir }}/brewfiles/groups/personal.Brewfile"'
        in personal_vars_text
    )
    assert (
        'group_purpose_brewfile: "{{ playbook_dir }}/brewfiles/groups/work.Brewfile"'
        in work_vars_text
    )


def test_host_brewfiles_live_under_brewfiles_hosts() -> None:
    for host_name in ("laptop24", "mini18", "mini26"):
        host_vars_text = (REPO_ROOT / "host_vars" / f"{host_name}.yml").read_text()

        assert (
            f'brewfile_host: "{{{{ playbook_dir }}}}/brewfiles/hosts/{host_name}.Brewfile"'
            in host_vars_text
        )
