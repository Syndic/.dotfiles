"""Lock in the empty-group_sets safety guarantee on every uninstall role.

`lookup('vars', 'group_<set>_<thing>')` raises on missing names, so each
role's resolve-loop output (`<role>_group_layer`) must be initialized to
`[]` before the loop runs — otherwise an empty `group_sets` (zero loop
iterations) leaves the consuming task referencing an undefined variable.

PR #57 added the `Initialize <role>_group_layer` task on the install side
(roles/<role>/tasks/main.yml). The uninstall siblings need the same
guarantee."""

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_tasks(role: str, file_name: str) -> list:
    path = REPO_ROOT / "roles" / role / "tasks" / file_name
    return yaml.safe_load(path.read_text())


def _find_init_index(tasks: list, layer_var: str) -> int:
    """Return the index of the set_fact task that initializes `layer_var`
    to `[]`, or -1 if no such task exists."""
    for i, task in enumerate(tasks):
        set_fact = task.get("ansible.builtin.set_fact") or task.get("set_fact")
        if not set_fact:
            continue
        if "loop" in task:
            continue
        if layer_var not in set_fact:
            continue
        value = set_fact[layer_var]
        if isinstance(value, list) and value == []:
            return i
    return -1


def _find_resolve_index(tasks: list, layer_var: str) -> int:
    """Return the index of the looped set_fact that resolves `layer_var`
    across `group_sets`, or -1."""
    for i, task in enumerate(tasks):
        set_fact = task.get("ansible.builtin.set_fact") or task.get("set_fact")
        if not set_fact or "loop" not in task:
            continue
        if layer_var in set_fact:
            return i
    return -1


def _assert_init_before_resolve(role: str, layer_var: str) -> None:
    tasks = _load_tasks(role, "uninstall.yml")
    init_idx = _find_init_index(tasks, layer_var)
    resolve_idx = _find_resolve_index(tasks, layer_var)

    assert init_idx >= 0, (
        f"{role}/tasks/uninstall.yml is missing an Initialize task that "
        f"sets {layer_var}: [] before the resolve loop runs"
    )
    assert resolve_idx >= 0, (
        f"{role}/tasks/uninstall.yml has no resolve loop for {layer_var}"
    )
    assert init_idx < resolve_idx, (
        f"{role}/tasks/uninstall.yml initializes {layer_var} (idx {init_idx}) "
        f"after the resolve loop (idx {resolve_idx})"
    )


def test_apt_uninstall_initializes_group_layer() -> None:
    _assert_init_before_resolve("apt", "apt_group_layer")


def test_flatpak_uninstall_initializes_group_layer() -> None:
    _assert_init_before_resolve("flatpak", "flatpak_group_layer")


def test_homebrew_uninstall_initializes_group_brewfile_layer() -> None:
    _assert_init_before_resolve("homebrew", "homebrew_group_brewfile_layer")
