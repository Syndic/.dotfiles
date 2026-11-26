"""`install.sh` is the project's only shell; see CLAUDE.md "The two-language split is intentional"."""
from __future__ import annotations

import ast
import json
import re
import shlex
import subprocess
from collections import Counter
from collections.abc import Iterator, Sequence
from pathlib import Path, PurePosixPath

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]

EXCLUDED_DIRS = ("home_source/",)

SHELL_EXTENSIONS = {".sh", ".bash", ".bats", ".zsh", ".ksh"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "bats"}
_ANSIBLE_PREFIXES = ("", "ansible.builtin.", "ansible.legacy.")
ANSIBLE_SHELL_MODULES = {prefix + name for prefix in _ANSIBLE_PREFIXES for name in ("shell", "raw", "script")}
ANSIBLE_COMMAND_MODULES = {prefix + "command" for prefix in _ANSIBLE_PREFIXES}
# Python calls that hand their argument to a shell.
PYTHON_SHELL_CALLS = {
    ("os", "system"), ("os", "popen"), ("subprocess", "getoutput"), ("subprocess", "getstatusoutput"),
    ("asyncio", "create_subprocess_shell"),
}
_PYTHON_SHELL_ATTRS = {attr for _, attr in PYTHON_SHELL_CALLS}
DEVCONTAINER_LIFECYCLE_KEYS = (
    "initializeCommand", "onCreateCommand", "updateContentCommand",
    "postCreateCommand", "postStartCommand", "postAttachCommand",
)

# Each entry in either allowlist admits one occurrence.
# Shell that stays; the value says why.
PERMANENT_SHELL = {
    "install.sh: shell script": "phase 1 runs before Python is usable",
    'phase2.py: ["/bin/bash", "-c", install_script]': "Homebrew ships its installer only as a bash script",
    'uninstall.py: ["/bin/bash", "-c", script, "uninstall.sh", "--force"]':
        "Homebrew ships its uninstaller only as a bash script",
}
# Shell that predates the rule; the value is the #157 sub-issue that ports it.
PENDING_PORTS = {
    "roles/homebrew/molecule/image-tag.sh: shell script": "#173",
    'tests/run: ["bash", "-c", "yamllint . && ansible-lint"]': "#173",
    'tests/run: ["bash", "-c", f"cd roles/{role} && molecule test -s {scenario.name}"]': "#173",
    "roles/homebrew/tasks/uninstall.yml: `ansible.builtin.shell` task "
    "'Uninstall packages listed in each existing Brewfile layer'": "#174",
    ".devcontainer/initialize.sh: shell script": "#175",
    ".devcontainer/post-create.sh: shell script": "#175",
    ".devcontainer/post-start.sh: shell script": "#175",
    "tests/e2e-linux.sh: shell script": "#176",
    "tests/e2e-roundtrip-linux.sh: shell script": "#176",
    "tests/lib/e2e-common.sh: shell script": "#176",
    "tests/bash/test_devcontainer_initialize.bats: shell script": "#175",
    "tests/bash/test_homebrew_image_tag.bats: shell script": "#173",
    "tests/bash/test_install.bats: shell script": "#177",
    "tests/bash/test_uninstall.bats: shell script": "#177",
    ".github/workflows/tests.yml: compound run: `sudo apt-get update && sudo apt-get install -y bats`": "#177",
    ".github/workflows/publish-molecule-images.yml: compound run: "
    "`echo \"value=$(echo '${{ github.repository_owner }}' | tr '[:upper:]' '[:lower:]')\" >> \"$GITHUB_OUTPUT\"`":
        "#178",
    ".github/workflows/publish-molecule-images.yml: compound run: "
    '`echo "value=$(roles/homebrew/molecule/image-tag.sh)" >> "$GITHUB_OUTPUT"`': "#178",
    '.github/workflows/tests.yml: compound run: `./tests/run pull ${{ matrix.role }} > "$RUNNER_TEMP/pull.log" 2>&1 &`':
        "#178",
    ".github/workflows/devcontainer.yml: multi-line run: `set -euo pipefail`": "#178",
    '.github/workflows/tests.yml: multi-line run: `uv venv --python 3.9.6 "$RUNNER_TEMP/venv-baseline"`': "#178",
    ".github/workflows/tests.yml: multi-line run: "
    "`uv pip install --system -r lint-requirements.txt -r molecule-requirements.txt \\`": "#178",
    ".github/workflows/tests.yml: multi-line run: `ansible-galaxy collection install -r requirements.yml`": "#178",
    ".github/workflows/tests.yml: multi-line run: `result='${{ needs.molecule.result }}'`": "#178",
}


# --- shared helpers ---


def _skip_env(words: Sequence[str | None]) -> int:
    """Index of the command after a leading `env` and its flags and NAME=value assignments."""
    if not words or words[0] is None or PurePosixPath(words[0]).name != "env":
        return 0
    i = 1
    while i < len(words) and words[i] is not None and (words[i].startswith("-") or "=" in words[i]):
        i += 1
    return i


def runs_shell_dash_c(words: Sequence[str | None]) -> bool:
    """An argv that runs `<shell> … -c`, directly or through `env`. None marks a non-literal word."""
    i = _skip_env(words)
    if i >= len(words) or words[i] is None or PurePosixPath(words[i]).name not in SHELLS:
        return False
    i += 1
    while i < len(words) and words[i] and words[i][0] in "-+":
        if re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", words[i]):
            return True
        i += 2 if words[i] in ("-o", "+o", "-O", "+O") else 1  # these take an argument
    return False


_EXPRESSION = re.compile(r"\$\{\{.*?\}\}")


def _has_substitution(command: str) -> bool:
    """`$(` or a backtick outside single quotes, where the shell would run it."""
    quote = None
    for i, ch in enumerate(command):
        if quote == "'":
            quote = None if ch == "'" else quote
        elif ch in "'\"" and quote is None:
            quote = ch
        elif ch == '"' and quote == '"':
            quote = None
        elif ch == "`" or command.startswith("$(", i):
            return True
    return False


def is_compound(command: str) -> bool:
    """More than one command, as a shell would run the string. `${{ }}` expressions are ignored."""
    command = _EXPRESSION.sub("x", command)
    if "\n" in command.strip() or _has_substitution(command):
        return True
    # Non-POSIX mode keeps quotes on tokens, so a quoted `'|'` is never read as an operator.
    lexer = shlex.shlex(command, posix=False, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:  # unbalanced quotes: no way to tell, so make someone look
        return True
    operators = set("&|;()")  # not `<` or `>`: a redirect leaves it one command
    return any(t and set(t) <= operators for t in tokens)


# --- detectors: each takes a repo-relative path and the file's text, returns findings ---


def _interpreter(text: str) -> str:
    """The shebang's interpreter, looking through `env`; empty without a shebang."""
    first = text.split("\n", 1)[0]
    words = first[2:].split() if first.startswith("#!") else []
    words = words[_skip_env(words):]
    return PurePosixPath(words[0]).name if words else ""


def shell_script_findings(path: str, text: str) -> list[str]:
    """A shell extension or a shell shebang (direct or through `env`)."""
    if PurePosixPath(path).suffix in SHELL_EXTENSIONS or _interpreter(text) in SHELLS:
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


def _yaml_nodes_in(text: str) -> Iterator[yaml.Node]:
    for doc in yaml.compose_all(text):
        if doc is not None:
            yield from _yaml_nodes(doc)


def _mapping(node: yaml.MappingNode) -> dict:
    return {k.value: v for k, v in node.value if isinstance(k, yaml.ScalarNode)}


def _command_words(module_value: yaml.Node, args: yaml.Node | None) -> list[str | None]:
    """The argv a `command` task runs: free-form, `cmd`, or `argv`, under the module or `args`."""
    if isinstance(module_value, yaml.ScalarNode) and module_value.value:
        return module_value.value.split()
    for node in (module_value, args):
        params = _mapping(node) if isinstance(node, yaml.MappingNode) else {}
        if isinstance(params.get("argv"), yaml.SequenceNode):
            return [w.value if isinstance(w, yaml.ScalarNode) else None for w in params["argv"].value]
        if isinstance(params.get("cmd"), yaml.ScalarNode):
            return params["cmd"].value.split()
    return []


def ansible_shell_findings(path: str, text: str) -> list[str]:
    """A task (a mapping in a list) that calls `shell`, `raw` or `script`, short or FQCN, or a
    `command` task that runs `<shell> -c`."""
    found = []
    for node in _yaml_nodes_in(text):
        if not isinstance(node, yaml.SequenceNode):
            continue
        for task in (item for item in node.value if isinstance(item, yaml.MappingNode)):
            keys = _mapping(task)
            name = keys["name"].value if isinstance(keys.get("name"), yaml.ScalarNode) else "<unnamed>"
            for module, value in keys.items():
                if module in ANSIBLE_SHELL_MODULES:
                    found.append(f"{path}: `{module}` task {name!r}")
                elif module in ANSIBLE_COMMAND_MODULES and runs_shell_dash_c(_command_words(value, keys.get("args"))):
                    found.append(f"{path}: `{module}` task {name!r} runs a shell")
    return found


def _literal(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def python_shell_findings(path: str, text: str) -> list[str]:
    """`shell=True`, an argv list running `<shell> -c`, or a call (or from-import) of a function
    that always goes through a shell."""
    tree = ast.parse(text, filename=path)
    modules = {}  # local name -> module it binds
    hits: list[ast.AST] = []
    calls = []  # `name.attr(...)` calls, resolved once every import is known
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                modules[alias.asname or top] = alias.name if alias.asname else top
        elif isinstance(node, ast.ImportFrom):
            if any((node.module, a.name) in PYTHON_SHELL_CALLS for a in node.names):
                hits.append(node)
        elif isinstance(node, ast.keyword):
            if node.arg == "shell" and isinstance(node.value, ast.Constant) and node.value.value is True:
                hits.append(node)
        elif isinstance(node, (ast.List, ast.Tuple)):
            if runs_shell_dash_c([_literal(e) for e in node.elts]):
                hits.append(node)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and isinstance(node.func.value, ast.Name) and node.func.attr in _PYTHON_SHELL_ATTRS):
            calls.append(node)
    hits += [c for c in calls if (modules.get(c.func.value.id), c.func.attr) in PYTHON_SHELL_CALLS]
    return [f"{path}: {' '.join((ast.get_source_segment(text, hit) or '').split())}" for hit in hits]


def workflow_run_findings(path: str, text: str) -> list[str]:
    """A `run:` that isn't one command: a block scalar (`|` or `>`), or a line chaining commands."""
    found = []
    for node in _yaml_nodes_in(text):
        run = _mapping(node).get("run") if isinstance(node, yaml.MappingNode) else None
        if not isinstance(run, yaml.ScalarNode):
            continue
        if run.style in ("|", ">"):
            first = next((line.strip() for line in run.value.splitlines() if line.strip()), "")
            found.append(f"{path}: multi-line run: `{first}`")
        elif is_compound(run.value):
            found.append(f"{path}: compound run: `{run.value}`")
    return found


_JSON_STRING = r'"(?:\\.|[^"\\])*"'


def _strip_jsonc(text: str) -> str:
    """Drop comments, then trailing commas, both outside strings."""
    text = re.sub(rf"({_JSON_STRING})|//[^\n]*|/\*.*?\*/", r"\1", text, flags=re.DOTALL)
    return re.sub(rf"({_JSON_STRING})|,(?=\s*[}}\]])", r"\1", text)


def devcontainer_command_findings(path: str, text: str) -> list[str]:
    """A lifecycle command string a shell would read as more than one command; a single command or
    an argv list passes. The object form runs each value as its own command."""
    config = json.loads(_strip_jsonc(text))
    found = []
    for key in DEVCONTAINER_LIFECYCLE_KEYS:
        value = config.get(key)
        commands = value.items() if isinstance(value, dict) else [(None, value)]
        for name, command in commands:
            if isinstance(command, str) and is_compound(command):
                label = key if name is None else f"{key}.{name}"
                found.append(f"{path}: {label} {command!r}")
    return found


# --- the live tree ---


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, check=True, capture_output=True, text=True).stdout
    return [p for p in out.split("\0") if p and not p.startswith(EXCLUDED_DIRS) and (REPO / p).is_file()]


def live_findings() -> list[str]:
    found = []
    for path in _tracked_files():
        text = (REPO / path).read_text(errors="replace")
        found += shell_script_findings(path, text)
        if path.endswith((".yml", ".yaml")):
            if path.startswith(".github/"):
                found += workflow_run_findings(path, text)
            else:  # every other YAML, so a new playbook is scanned without being listed here
                found += ansible_shell_findings(path, text)
        if PurePosixPath(path).name in ("devcontainer.json", ".devcontainer.json"):
            found += devcontainer_command_findings(path, text)
        if path.endswith(".py") or _interpreter(text).startswith("python"):
            found += python_shell_findings(path, text)
    return found


def unexpected_and_stale(found: Sequence[str], allowlist: Sequence[str]) -> tuple[list[str], list[str]]:
    """Compared as multisets, so an entry admits exactly one occurrence."""
    found_count, allowed_count = Counter(found), Counter(allowlist)
    return sorted((found_count - allowed_count).elements()), sorted((allowed_count - found_count).elements())


def test_live_tree_has_no_shell_beyond_the_allowlists() -> None:
    allowlist = {**PERMANENT_SHELL, **PENDING_PORTS}
    unexpected, stale = unexpected_and_stale(live_findings(), list(allowlist))
    assert not unexpected, (
        "Shell outside install.sh; see CLAUDE.md \"The two-language split is intentional\" for where "
        "this logic goes instead:\n" + "\n".join(unexpected)
    )
    assert not stale, "Gone, so delete from PERMANENT_SHELL / PENDING_PORTS:\n" + "\n".join(
        f"{entry} ({allowlist[entry]})" for entry in stale
    )


def test_allowlist_entry_admits_one_occurrence_and_unmatched_entry_is_stale() -> None:
    found = ["a: shell script", "b: shell script", "b: shell script"]
    assert unexpected_and_stale(found, ["b: shell script", "c: shell script"]) == (
        ["a: shell script", "b: shell script"], ["c: shell script"],
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
    ("install.sh", "#!/usr/bin/env bash\n"),
])
def test_shell_script_is_flagged(path: str, text: str) -> None:
    assert shell_script_findings(path, text) == [f"{path}: shell script"]


@pytest.mark.parametrize("path, text", [
    ("bin/tool", "#!/usr/bin/env python3\n"),
    ("bin/tool", "#!/usr/bin/python3 -I\n"),
    ("bin/tool", "no shebang\n"),
    ("docs/bash.md", "# bash\n"),
])
def test_non_shell_file_passes(path: str, text: str) -> None:
    assert shell_script_findings(path, text) == []


def test_ansible_shell_raw_and_script_tasks_are_flagged_in_any_form_and_nesting() -> None:
    text = (
        "- name: Short\n  shell: echo hi\n"
        "- name: Wrapped\n  block:\n    - name: Fqcn\n      ansible.builtin.shell: |\n        a && b\n"
        "- ansible.legacy.raw: uname\n"
        "- name: Local script\n  ansible.builtin.script: files/setup.sh\n"
    )
    assert sorted(ansible_shell_findings("roles/x/tasks/main.yml", text)) == [
        "roles/x/tasks/main.yml: `ansible.builtin.script` task 'Local script'",
        "roles/x/tasks/main.yml: `ansible.builtin.shell` task 'Fqcn'",
        "roles/x/tasks/main.yml: `ansible.legacy.raw` task '<unnamed>'",
        "roles/x/tasks/main.yml: `shell` task 'Short'",
    ]


@pytest.mark.parametrize("task", [
    "ansible.builtin.command: bash -c 'a && b'",
    "command:\n    argv: [/bin/sh, -ec, 'a && b']",
    "ansible.builtin.command:\n    cmd: env FOO=1 bash -c 'a'",
    "ansible.legacy.command:\n  args:\n    argv: [bash, -o, pipefail, -c, a]",
])
def test_ansible_command_running_a_shell_is_flagged(task: str) -> None:
    findings = ansible_shell_findings("site.yml", f"- name: T\n  {task}\n")
    assert len(findings) == 1 and findings[0].endswith("task 'T' runs a shell")


def test_ansible_argv_commands_and_non_task_keys_pass() -> None:
    text = (
        "- name: Argv\n  ansible.builtin.command:\n    argv: [brew, list]\n"
        "  vars:\n    raw: 1\n    shell: zsh\n"
        "- name: Script arg\n  command: bash setup.sh -c\n"
    )
    assert ansible_shell_findings("site.yml", text) == []


@pytest.mark.parametrize("source, expected", [
    ("subprocess.run('a && b', shell=True)", "shell=True"),
    ('subprocess.run(["bash", "-c", "a && b"])', '["bash", "-c", "a && b"]'),
    ('subprocess.run(("/bin/sh", "-ec", cmd))', '("/bin/sh", "-ec", cmd)'),
    ('subprocess.run(["/usr/bin/env", "bash", "-c", "a"])', '["/usr/bin/env", "bash", "-c", "a"]'),
    ('subprocess.run(["bash", "-e", "-c", "a"])', '["bash", "-e", "-c", "a"]'),
    ("import os\nos.system('ls')", "os.system('ls')"),
    ("import subprocess as sp\nsp.getoutput('ls')", "sp.getoutput('ls')"),
    ("import asyncio\nasyncio.create_subprocess_shell('ls')", "asyncio.create_subprocess_shell('ls')"),
    ("from os import system", "from os import system"),
])
def test_python_shell_is_flagged(source: str, expected: str) -> None:
    assert python_shell_findings("x.py", source) == [f"x.py: {expected}"]


@pytest.mark.parametrize("source", [
    "subprocess.run(['ls', '-l'], shell=False)",
    'subprocess.run(["bash", "script.sh", "-c"])',
    'note = "shell=True and [\\"bash\\", \\"-c\\"]"',
    'SHELLS = ("bash", "sh")',
    "import platform\nplatform.system()",
    "from os import path",
])
def test_python_argv_and_strings_pass(source: str) -> None:
    assert python_shell_findings("x.py", source) == []


def test_multi_line_and_compound_runs_are_flagged() -> None:
    text = (
        "jobs:\n  a:\n    steps:\n"
        "      - run: |\n          one\n          two\n"
        "      - run: >-\n          folded \\\n          line\n"
        "      - run: a && b\n"
        '      - run: "a\\nb"\n'
        "      - run: ./tests/run pull x > log 2>&1 &\n"
        '      - run: echo "v=$(date)" >> "$GITHUB_OUTPUT"\n'
    )
    assert workflow_run_findings("w.yml", text) == [
        "w.yml: multi-line run: `one`",
        "w.yml: multi-line run: `folded \\ line`",
        "w.yml: compound run: `a && b`",
        "w.yml: compound run: `a\nb`",
        "w.yml: compound run: `./tests/run pull x > log 2>&1 &`",
        'w.yml: compound run: `echo "v=$(date)" >> "$GITHUB_OUTPUT"`',
    ]


def test_single_command_runs_pass() -> None:
    text = (
        "jobs:\n  a:\n    steps:\n"
        "      - run: pytest -v\n"
        "      - run: ./tests/run molecule ${{ matrix.role || 'all' }}\n"
        "      - run: echo \"value=x\" >> \"$GITHUB_OUTPUT\"\n"
        "      - run: grep -E 'a|b;c' file\n"
        "      - run: tr '|' ','\n"
        "      - run: echo \";\"\n"
        "      - run: echo '$(x)' '`y`'\n"
        "      - uses: some/action@v1\n        with:\n          args: |\n            not a run\n"
    )
    assert workflow_run_findings("w.yml", text) == []


@pytest.mark.parametrize("command", ["a && b", "a || b", "a; b", "a | b", "a\nb", "echo $(date)", "a &"])
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
        '  "mounts": ["source=${localWorkspaceFolder}/x,target=/x;y", "a // not a comment",],\n'
        '  "postAttachCommand": "tool > log 2>&1",\n'
        '  "postStartCommand": "tool", // a comment after the trailing comma\n'
        "}\n"
    )
    assert devcontainer_command_findings("d.json", text) == []
