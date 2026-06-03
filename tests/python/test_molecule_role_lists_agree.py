"""Guard against drift between the three sources of "which roles have
molecule scenarios":

  1. The filesystem — `roles/<role>/molecule/` directories. This is the
     ground truth: if a role has scenarios on disk, both consumers below
     must cover it.
  2. `MOLECULE_ROLES` in `tests/run` — drives the local serial run.
  3. `matrix.role` in `.github/workflows/tests.yml` — drives CI shards.

The two consumers read independently (one bash array, one workflow YAML)
so a new role added to disk + one list but not the other would silently
ship — local would run it, CI wouldn't (or vice versa). This test catches
that the moment it happens.

Plain string parsing — `~/.venv` carries pytest + pytest-cov only; no
PyYAML. See test_uninstall_group_layer_init.py for the same precedent."""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _roles_on_disk() -> set:
    """Set of role names that have a `roles/<role>/molecule/` directory."""
    molecule_dirs = (REPO_ROOT / "roles").glob("*/molecule")
    return {p.parent.name for p in molecule_dirs if p.is_dir()}


def _roles_in_tests_run() -> set:
    """Set of role names declared in `MOLECULE_ROLES = [...]` in tests/run.

    Matches the Python list literal — tolerates single or double quotes
    and surrounding whitespace."""
    text = (REPO_ROOT / "tests" / "run").read_text()
    match = re.search(
        r"^MOLECULE_ROLES\s*=\s*\[([^\]]+)\]", text, re.MULTILINE
    )
    assert match, "MOLECULE_ROLES = [...] declaration not found in tests/run"
    return {
        item.strip().strip("\"'")
        for item in match.group(1).split(",")
        if item.strip()
    }


def _roles_in_ci_matrix() -> set:
    """Set of role names in the `matrix.role: [...]` axis of tests.yml.

    Parsed via regex rather than YAML so this test stays stdlib-only
    (the pytest venv doesn't carry PyYAML)."""
    text = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text()
    # Match `role: [a, b, c]` under the matrix: block. The leading indent
    # disambiguates from any other `role:` key elsewhere in the file.
    match = re.search(r"^\s+role:\s*\[([^\]]+)\]", text, re.MULTILINE)
    assert match, "matrix.role list not found in .github/workflows/tests.yml"
    return {name.strip() for name in match.group(1).split(",")}


def test_tests_run_lists_every_role_with_molecule_scenarios() -> None:
    on_disk = _roles_on_disk()
    in_tests_run = _roles_in_tests_run()
    missing = on_disk - in_tests_run
    extra = in_tests_run - on_disk
    assert not missing, (
        f"tests/run MOLECULE_ROLES is missing roles that have "
        f"molecule scenarios on disk: {sorted(missing)}"
    )
    assert not extra, (
        f"tests/run MOLECULE_ROLES lists roles with no molecule/ dir "
        f"on disk: {sorted(extra)}"
    )


def test_ci_matrix_lists_every_role_with_molecule_scenarios() -> None:
    on_disk = _roles_on_disk()
    in_matrix = _roles_in_ci_matrix()
    missing = on_disk - in_matrix
    extra = in_matrix - on_disk
    assert not missing, (
        f"tests.yml molecule matrix.role is missing roles that have "
        f"molecule scenarios on disk: {sorted(missing)}"
    )
    assert not extra, (
        f"tests.yml molecule matrix.role lists roles with no molecule/ "
        f"dir on disk: {sorted(extra)}"
    )


def test_tests_run_and_ci_matrix_agree() -> None:
    # Implied by the two checks above, but called out explicitly so the
    # failure message names the right asymmetry when only this one breaks
    # (e.g. someone adds a role to tests/run + disk but not the matrix).
    assert _roles_in_tests_run() == _roles_in_ci_matrix()
