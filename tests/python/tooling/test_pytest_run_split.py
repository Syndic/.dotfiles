"""Keep tests in the pytest run that matches the code they test.

The runtime run (tests/python/runtime/, plus the plugin's own tests) executes on
the frozen 3.9 so it proves the bootstrap's modules still run there; the
tooling run executes on tooling_python. See CLAUDE.md "Tests"."""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_TESTS = REPO_ROOT / "tests" / "python"
PLUGIN_TESTS = REPO_ROOT / "unnatural-designs-agent-tools" / "tests"

# Every module the bootstrap, uninstall, pre-commit hooks, or host-side plugin
# scripts run as `python3` — on macOS, the frozen 3.9.
RUNTIME_MODULES = {p.stem for p in REPO_ROOT.glob("*.py")} | {
    p.stem for p in (REPO_ROOT / "unnatural-designs-agent-tools" / "scripts").glob("*.py")
}


def _imported_modules(path: Path) -> set:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


def test_runtime_modules_are_discovered():
    assert {"phase2", "_dotfiles_common", "uninstall", "dotfiles_manager", "dev_cleanup"} <= RUNTIME_MODULES


def test_every_test_file_belongs_to_a_run():
    stray = sorted(
        str(p.relative_to(PYTHON_TESTS))
        for p in PYTHON_TESTS.rglob("test_*.py")
        if p.relative_to(PYTHON_TESTS).parts[0] not in ("runtime", "tooling")
    )
    assert not stray, f"move these into tests/python/runtime/ or tests/python/tooling/: {stray}"


def test_tooling_tests_import_no_runtime_module():
    offenders = {
        str(p.relative_to(PYTHON_TESTS)): sorted(_imported_modules(p) & RUNTIME_MODULES)
        for p in sorted((PYTHON_TESTS / "tooling").rglob("*.py"))
    }
    offenders = {name: mods for name, mods in offenders.items() if mods}
    assert not offenders, (
        "these tooling tests import 3.9 runtime modules; move them to "
        f"tests/python/runtime/ so the frozen interpreter runs them: {offenders}"
    )


def test_runtime_tests_each_import_a_runtime_module():
    files = sorted((PYTHON_TESTS / "runtime").rglob("test_*.py")) + sorted(PLUGIN_TESTS.rglob("test_*.py"))
    assert files
    idle = [str(p.relative_to(REPO_ROOT)) for p in files if not _imported_modules(p) & RUNTIME_MODULES]
    assert not idle, f"these runtime tests test no 3.9 runtime module; move them to tests/python/tooling/: {idle}"
