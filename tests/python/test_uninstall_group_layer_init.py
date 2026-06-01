"""Lock in the empty-group_sets safety guarantee on every uninstall role.

`lookup('vars', 'group_<set>_<thing>')` raises on missing names, so each
role's resolve-loop output (`<role>_group_layer`) must be initialized to
`[]` before the loop runs — otherwise an empty `group_sets` (zero loop
iterations) leaves the consuming task referencing an undefined variable.

PR #57 added the `Initialize <role>_group_layer` task on the install side
(roles/<role>/tasks/main.yml). The uninstall siblings need the same
guarantee.

Asserted via line-matching rather than YAML parsing so the pytest venv
doesn't need PyYAML (the test venv ships pytest + pytest-cov only —
see .devcontainer/post-create.sh). Matches the precedent set by
test_homebrew_role_defaults.py."""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _find_line(lines: list, pattern: str) -> int:
    """Return the 1-based line number of the first line matching `pattern`,
    or -1 if no match."""
    regex = re.compile(pattern)
    for i, line in enumerate(lines, start=1):
        if regex.search(line):
            return i
    return -1


def _assert_init_before_resolve(role: str, layer_var: str) -> None:
    path = REPO_ROOT / "roles" / role / "tasks" / "uninstall.yml"
    lines = path.read_text().splitlines()

    # `<var>: []` on its own line — the Initialize set_fact body.
    init_line = _find_line(lines, rf"^\s+{re.escape(layer_var)}:\s*\[\s*\]\s*$")
    # `loop: "{{ group_sets }}"` — the hallmark of the resolve loop, with
    # tolerant whitespace inside the Jinja braces.
    resolve_line = _find_line(lines, r'loop:\s*"\{\{\s*group_sets\s*\}\}"')

    assert init_line >= 0, (
        f"{path.relative_to(REPO_ROOT)} is missing an Initialize task that "
        f"sets {layer_var}: [] before the resolve loop runs"
    )
    assert resolve_line >= 0, (
        f"{path.relative_to(REPO_ROOT)} has no `loop: \"{{{{ group_sets }}}}\"` "
        f"resolve loop"
    )
    assert init_line < resolve_line, (
        f"{path.relative_to(REPO_ROOT)} initializes {layer_var} on line "
        f"{init_line}, after the resolve loop on line {resolve_line}"
    )


def test_apt_uninstall_initializes_group_layer() -> None:
    _assert_init_before_resolve("apt", "apt_group_layer")


def test_flatpak_uninstall_initializes_group_layer() -> None:
    _assert_init_before_resolve("flatpak", "flatpak_group_layer")


def test_homebrew_uninstall_initializes_group_brewfile_layer() -> None:
    _assert_init_before_resolve("homebrew", "homebrew_group_brewfile_layer")
