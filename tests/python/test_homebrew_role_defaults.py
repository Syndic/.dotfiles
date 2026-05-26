"""Lock in the shape of roles/homebrew/defaults/main.yml.

The homebrew role gates an optional `brew upgrade` pass on the
`homebrew_upgrade_outdated` variable. The default must stay TRUE so a
stock install leaves the machine fully up-to-date; the per-run opt-out
is `--no-upgrade` on install.sh / phase2.py, which flips the variable
to false via `-e` (see CLAUDE.md ▸ Conventions). The role-defaults
file is the single source of truth — group_vars deliberately does NOT
also declare the variable, so there's one place to look."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_homebrew_role_defaults_upgrade_outdated_is_true() -> None:
    defaults_text = (REPO_ROOT / "roles" / "homebrew" / "defaults" / "main.yml").read_text()

    assert "homebrew_upgrade_outdated: true" in defaults_text


def test_group_vars_all_does_not_redeclare_homebrew_upgrade_outdated() -> None:
    """One source of truth: the variable lives in roles/homebrew/defaults/main.yml,
    not in group_vars/all.yml. group_vars would override the role default with
    the same value, which is pure noise."""
    all_vars_text = (REPO_ROOT / "group_vars" / "all.yml").read_text()

    assert "homebrew_upgrade_outdated" not in all_vars_text
