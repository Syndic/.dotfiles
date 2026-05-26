"""Lock in the shape of roles/homebrew/defaults/main.yml.

The homebrew role gates an optional `brew upgrade` pass on the
`homebrew_upgrade_outdated` variable. The default must stay false so a
plain `ansible-playbook site.yml` run never silently upgrades packages
on a host that didn't opt in (see CLAUDE.md ▸ Conventions). group_vars
should also expose and document the variable so users can grep one file
to find every tunable."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_homebrew_role_defaults_upgrade_outdated_is_false() -> None:
    defaults_text = (REPO_ROOT / "roles" / "homebrew" / "defaults" / "main.yml").read_text()

    assert "homebrew_upgrade_outdated: false" in defaults_text


def test_group_vars_all_documents_homebrew_upgrade_outdated() -> None:
    all_vars_text = (REPO_ROOT / "group_vars" / "all.yml").read_text()

    assert "homebrew_upgrade_outdated: false" in all_vars_text
