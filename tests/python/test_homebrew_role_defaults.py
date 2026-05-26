"""Lock in the shape of roles/homebrew/defaults/main.yml.

The homebrew role gates an optional `brew upgrade` pass on the
`homebrew_upgrade_outdated` variable. The default must stay TRUE so a
stock install leaves the machine fully up-to-date; the per-run opt-out
is `--no-upgrade` on install.sh / phase2.py, which flips the variable
to false via `-e` (see CLAUDE.md ▸ Conventions). group_vars also
exposes and documents the variable so users can grep one file to find
every tunable."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_homebrew_role_defaults_upgrade_outdated_is_true() -> None:
    defaults_text = (REPO_ROOT / "roles" / "homebrew" / "defaults" / "main.yml").read_text()

    assert "homebrew_upgrade_outdated: true" in defaults_text


def test_group_vars_all_documents_homebrew_upgrade_outdated() -> None:
    all_vars_text = (REPO_ROOT / "group_vars" / "all.yml").read_text()

    assert "homebrew_upgrade_outdated: true" in all_vars_text
