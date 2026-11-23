"""`install.sh` is the project's only shell; see CLAUDE.md "The two-language split is intentional".

PENDING_PORTS lists the shell that predates the rule, each entry tagged with the #157 sub-issue
that ports it. A port deletes its own entries; an entry that matches nothing fails, so the list
only shrinks.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterator, List, Set, Tuple

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]

PERMITTED_SHELL_SCRIPTS = {"install.sh"}
# Homebrew ships its installer and uninstaller only as bash scripts.
THIRD_PARTY_SHELL = {
    'phase2.py: ["/bin/bash", "-c", install_script]',
    'uninstall.py: ["/bin/bash", "-c", script, "uninstall.sh", "--force"]',
}
# The user's shell dotfiles, symlinked into $HOME: configuration, not code the project runs.
EXCLUDED_DIRS = ("home_source/",)

SHELL_EXTENSIONS = {".sh", ".bash", ".bats", ".zsh", ".ksh"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "bats"}
ANSIBLE_SHELL_MODULES = {
    prefix + name for prefix in ("", "ansible.builtin.", "ansible.legacy.") for name in ("shell", "raw")
}
# Python calls that hand their argument to /bin/sh.
PYTHON_SHELL_CALLS = {("os", "system"), ("os", "popen"), ("subprocess", "getoutput"), ("subprocess", "getstatusoutput")}
DEVCONTAINER_LIFECYCLE_KEYS = (
    "initializeCommand", "onCreateCommand", "updateContentCommand",
    "postCreateCommand", "postStartCommand", "postAttachCommand",
)
SHELL_OPERATOR = re.compile(r"[&|;<>`\n]|\$\(")

PENDING_PORTS = {
    # #173
    "roles/homebrew/molecule/image-tag.sh: shell script": "#173",
    'tests/run: ["bash", "-c", "yamllint . && ansible-lint"]': "#173",
    'tests/run: ["bash", "-c", f"cd roles/{role} && molecule test -s {scenario.name}"]': "#173",
    # #174
    "roles/homebrew/tasks/uninstall.yml: `ansible.builtin.shell` task "
    "'Uninstall packages listed in each existing Brewfile layer'": "#174",
    # #175
    ".devcontainer/initialize.sh: shell script": "#175",
    ".devcontainer/post-create.sh: shell script": "#175",
    ".devcontainer/post-start.sh: shell script": "#175",
    # #176
    "tests/e2e-linux.sh: shell script": "#176",
    "tests/e2e-roundtrip-linux.sh: shell script": "#176",
    "tests/lib/e2e-common.sh: shell script": "#176",
    # #177 (the initialize and image-tag suites move with their scripts, #175 and #173)
    "tests/bash/test_devcontainer_initialize.bats: shell script": "#177",
    "tests/bash/test_homebrew_image_tag.bats: shell script": "#177",
    "tests/bash/test_install.bats: shell script": "#177",
    "tests/bash/test_uninstall.bats: shell script": "#177",
    # #178
    '.github/workflows/devcontainer.yml: multi-line run: `set -euo pipefail`': "#178",
    '.github/workflows/tests.yml: multi-line run: `uv venv --python 3.9.6 "$RUNNER_TEMP/venv-baseline"`': "#178",
    ".github/workflows/tests.yml: multi-line run: "
    "`uv pip install --system -r lint-requirements.txt -r molecule-requirements.txt \\`": "#178",
    ".github/workflows/tests.yml: multi-line run: `ansible-galaxy collection install -r requirements.yml`": "#178",
    ".github/workflows/tests.yml: multi-line run: `result='${{ needs.molecule.result }}'`": "#178",
}


# --- detectors: each takes a repo-relative path and the file's text, returns findings ---


def shell_script_findings(path: str, text: str) -> List[str]:
    """A shell extension or a shell shebang (direct or through `env`)."""
    if path in PERMITTED_SHELL_SCRIPTS:
        return []
    first = text.split("\n", 1)[0]
    words = first[2:].split() if first.startswith("#!") else []
    if words and PurePosixPath(words[0]).name == "env":
        words = [w for w in words[1:] if not w.startswith("-") and "=" not in w]
    interpreter = PurePosixPath(words[0]).name if words else ""
    if PurePosixPath(path).suffix in SHELL_EXTENSIONS or interpreter in SHELLS:
        return [f"{path}: shell script"]
    return []


def _yaml_nodes(node: yaml.Node) -> Iterator[yaml.Node]:
    yield node
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            yield from _yaml_nodes(key)
            yield from _yaml_nodes(value)
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            yield from _yaml_nodes(item)


def _mapping(node: yaml.MappingNode) -> dict:
    return {k.value: v for k, v in node.value if isinstance(k, yaml.ScalarNode)}


def ansible_shell_findings(path: str, text: str) -> List[str]:
    """A task (a mapping in a list) that calls `shell` or `raw`, short or FQCN."""
    found = []
    for doc in yaml.compose_all(text):
        for node in _yaml_nodes(doc) if doc is not None else ():
            if not isinstance(node, yaml.SequenceNode):
                continue
            for task in (item for item in node.value if isinstance(item, yaml.MappingNode)):
                keys = _mapping(task)
                name = keys["name"].value if isinstance(keys.get("name"), yaml.ScalarNode) else "<unnamed>"
                found += [f"{path}: `{module}` task {name!r}" for module in keys if module in ANSIBLE_SHELL_MODULES]
    return found


def _is_shell_dash_c(node: ast.AST) -> bool:
    if not isinstance(node, (ast.List, ast.Tuple)) or len(node.elts) < 2:
        return False
    shell, flag = node.elts[:2]
    return (
        isinstance(shell, ast.Constant) and isinstance(shell.value, str)
        and PurePosixPath(shell.value).name in SHELLS
        and isinstance(flag, ast.Constant) and isinstance(flag.value, str)
        and re.fullmatch(r"-[a-z]*c[a-z]*", flag.value) is not None
    )


def _is_shell_call(node: ast.AST) -> bool:
    func = node.func if isinstance(node, ast.Call) else None
    return (
        isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
        and (func.value.id, func.attr) in PYTHON_SHELL_CALLS
    )


def python_shell_findings(path: str, text: str) -> List[str]:
    """`shell=True`, an argv list running `<shell> -c`, or a call that always goes through /bin/sh."""
    found = []
    for node in ast.walk(ast.parse(text, filename=path)):
        hits = [kw for kw in getattr(node, "keywords", []) if kw.arg == "shell"
                and isinstance(kw.value, ast.Constant) and kw.value.value is True]
        hits += [node] if _is_shell_dash_c(node) or _is_shell_call(node) else []
        for hit in hits:
            source = " ".join((ast.get_source_segment(text, hit) or "").split())
            found.append(f"{path}: {source}")
    return found


def workflow_run_findings(path: str, text: str) -> List[str]:
    """A `run:` written as a block scalar (`|` or `>`): one command per step instead."""
    found = []
    for doc in yaml.compose_all(text):
        for node in _yaml_nodes(doc) if doc is not None else ():
            run = _mapping(node).get("run") if isinstance(node, yaml.MappingNode) else None
            if isinstance(run, yaml.ScalarNode) and run.style in ("|", ">"):
                first = next((line.strip() for line in run.value.splitlines() if line.strip()), "")
                found.append(f"{path}: multi-line run: `{first}`")
    return found


def _strip_jsonc(text: str) -> str:
    """Drop `//` and `/* */` comments and trailing commas outside strings."""
    out, i, in_string = [], 0, False
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(text[i:i + 2] if ch == "\\" else ch)
            i += 2 if ch == "\\" else 1
            in_string = ch != '"'
        elif ch == '"':
            out.append(ch)
            in_string, i = True, i + 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif text.startswith("/*", i):
            i = text.index("*/", i) + 2
        elif ch == "," and re.match(r"\s*[}\]]", text[i + 1:]):
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def devcontainer_command_findings(path: str, text: str) -> List[str]:
    """A lifecycle command string with a shell operator; a single command or an argv list passes.
    The object form runs each value as its own command, so each is checked the same way."""
    config = json.loads(_strip_jsonc(text))
    found = []
    for key in DEVCONTAINER_LIFECYCLE_KEYS:
        value = config.get(key)
        commands = value.items() if isinstance(value, dict) else [(None, value)]
        for name, command in commands:
            if isinstance(command, str) and SHELL_OPERATOR.search(command):
                label = key if name is None else f"{key}.{name}"
                found.append(f"{path}: {label} {command!r}")
    return found


# --- the live tree ---


def _tracked_files() -> List[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, check=True, capture_output=True, text=True).stdout
    return [p for p in out.split("\0") if p and not p.startswith(EXCLUDED_DIRS) and (REPO / p).is_file()]


def _read(path: str) -> str:
    return (REPO / path).read_text(errors="replace")


def _is_python(path: str) -> bool:
    if path.endswith(".py"):
        return True
    with open(REPO / path, "rb") as f:
        first = f.readline(256)
    return first.startswith(b"#!") and b"python" in first


def _is_ansible_yaml(path: str) -> bool:
    return path in ("site.yml", "uninstall.yml") or (path.startswith("roles/") and path.endswith((".yml", ".yaml")))


def live_findings() -> List[str]:
    found = []
    for path in _tracked_files():
        name = PurePosixPath(path).name
        found += shell_script_findings(path, _read(path))
        if _is_ansible_yaml(path):
            found += ansible_shell_findings(path, _read(path))
        if path.startswith(".github/") and path.endswith((".yml", ".yaml")):
            found += workflow_run_findings(path, _read(path))
        if name in ("devcontainer.json", ".devcontainer.json"):
            found += devcontainer_command_findings(path, _read(path))
        if _is_python(path):
            found += python_shell_findings(path, _read(path))
    return found


def unexpected_and_stale(found: List[str], allowlist: Set[str]) -> Tuple[List[str], List[str]]:
    return sorted(set(found) - allowlist), sorted(allowlist - set(found))


def test_live_tree_has_no_shell_beyond_the_allowlists() -> None:
    unexpected, stale = unexpected_and_stale(live_findings(), set(PENDING_PORTS) | THIRD_PARTY_SHELL)
    assert not unexpected, (
        "Shell outside install.sh; see CLAUDE.md \"The two-language split is intentional\" for where "
        "this logic goes instead:\n" + "\n".join(unexpected)
    )
    assert not stale, "Gone, so delete from PENDING_PORTS / THIRD_PARTY_SHELL:\n" + "\n".join(stale)


def test_new_finding_is_unexpected_and_unmatched_entry_is_stale() -> None:
    assert unexpected_and_stale(["a: shell script", "b: shell script"], {"b: shell script", "c: shell script"}) == (
        ["a: shell script"], ["c: shell script"],
    )


# --- detectors on fixtures ---


@pytest.mark.parametrize("path, text", [
    ("scripts/new.sh", "echo hi\n"),
    ("scripts/new.bash", ""),
    ("tests/x.bats", ""),
    ("bin/tool", "#!/bin/sh\nexit 0\n"),
    ("bin/tool", "#!/usr/bin/env bash\n"),
    ("bin/tool", "#!/usr/bin/env -S bash -eu\n"),
    ("bin/tool", "#!/usr/bin/env zsh\n"),
])
def test_shell_script_is_flagged(path: str, text: str) -> None:
    assert shell_script_findings(path, text) == [f"{path}: shell script"]


@pytest.mark.parametrize("path, text", [
    ("install.sh", "#!/usr/bin/env bash\n"),
    ("bin/tool", "#!/usr/bin/env python3\n"),
    ("bin/tool", "#!/usr/bin/python3 -I\n"),
    ("bin/tool", "no shebang\n"),
    ("docs/bash.md", "# bash\n"),
])
def test_non_shell_file_passes(path: str, text: str) -> None:
    assert shell_script_findings(path, text) == []


def test_ansible_shell_and_raw_tasks_are_flagged_in_any_form_and_nesting() -> None:
    text = (
        "- name: Short\n  shell: echo hi\n"
        "- name: Wrapped\n  block:\n    - name: Fqcn\n      ansible.builtin.shell: |\n        a && b\n"
        "- ansible.legacy.raw: uname\n"
    )
    assert sorted(ansible_shell_findings("roles/x/tasks/main.yml", text)) == [
        "roles/x/tasks/main.yml: `ansible.builtin.shell` task 'Fqcn'",
        "roles/x/tasks/main.yml: `ansible.legacy.raw` task '<unnamed>'",
        "roles/x/tasks/main.yml: `shell` task 'Short'",
    ]


def test_ansible_command_tasks_and_non_task_keys_pass() -> None:
    text = (
        "- name: Argv\n  ansible.builtin.command:\n    argv: [brew, list]\n"
        "  vars:\n    raw: 1\n    shell: zsh\n"
    )
    assert ansible_shell_findings("site.yml", text) == []


@pytest.mark.parametrize("source, expected", [
    ("subprocess.run('a && b', shell=True)", "shell=True"),
    ('subprocess.run(["bash", "-c", "a && b"])', '["bash", "-c", "a && b"]'),
    ('subprocess.run(("/bin/sh", "-ec", cmd))', '("/bin/sh", "-ec", cmd)'),
    ("os.system('ls')", "os.system('ls')"),
    ("subprocess.getoutput('ls')", "subprocess.getoutput('ls')"),
])
def test_python_shell_is_flagged(source: str, expected: str) -> None:
    assert python_shell_findings("x.py", source) == [f"x.py: {expected}"]


@pytest.mark.parametrize("source", [
    "subprocess.run(['ls', '-l'], shell=False)",
    'subprocess.run(["bash", "script.sh"])',
    'note = "shell=True and [\\"bash\\", \\"-c\\"]"',
    'SHELLS = ("bash", "sh")',
])
def test_python_argv_and_strings_pass(source: str) -> None:
    assert python_shell_findings("x.py", source) == []


def test_block_scalar_runs_are_flagged_and_single_line_runs_pass() -> None:
    text = (
        "jobs:\n  a:\n    steps:\n"
        "      - run: pytest -v\n"
        "      - run: |\n          one\n          two\n"
        "      - run: >-\n          folded \\\n          line\n"
        "      - uses: some/action@v1\n        with:\n          args: |\n            not a run\n"
    )
    assert workflow_run_findings("w.yml", text) == [
        "w.yml: multi-line run: `one`",
        "w.yml: multi-line run: `folded \\ line`",
    ]


@pytest.mark.parametrize("command", ["a && b", "a || b", "a; b", "a | b", "a\nb", "a > log", "echo $(date)"])
def test_compound_devcontainer_command_is_flagged(command: str) -> None:
    text = "{\n  // comment\n  \"postCreateCommand\": " + json.dumps(command) + ",\n}\n"
    assert devcontainer_command_findings("d.json", text) == [f"d.json: postCreateCommand {command!r}"]


def test_devcontainer_object_form_is_checked_per_command() -> None:
    text = '{"postStartCommand": {"ok": ["a", "&&"], "bad": "a && b"}}'
    assert devcontainer_command_findings("d.json", text) == ["d.json: postStartCommand.bad 'a && b'"]


def test_single_devcontainer_commands_and_argv_lists_pass() -> None:
    text = (
        '{\n  /* block */ "initializeCommand": ".devcontainer/initialize.sh", // trailing\n'
        '  "postCreateCommand": ["uv", "run", "a && b"],\n'
        '  "mounts": ["source=${localWorkspaceFolder}/x,target=/x;y"]\n}\n'
    )
    assert devcontainer_command_findings("d.json", text) == []
