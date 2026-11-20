"""Keep tests in the pytest run that matches the code they test.

The baseline run (tests/python/baseline/, plus the plugin's own tests) executes on
the frozen 3.9 so it proves the bootstrap's modules still run there; the
tooling run executes on tooling_python. See CLAUDE.md "Tests"."""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_TESTS = REPO_ROOT / "tests" / "python"
PLUGIN_TESTS = REPO_ROOT / "unnatural-designs-agent-tools" / "tests"

# Every module the bootstrap, uninstall, pre-commit hooks, or host-side plugin
# scripts run as `python3` — on macOS, the frozen 3.9.
BASELINE_MODULES = {p.stem for p in REPO_ROOT.glob("*.py")} | {
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


def test_baseline_modules_are_discovered():
    assert {"phase2", "_dotfiles_common", "uninstall", "dotfiles_manager", "dev_cleanup"} <= BASELINE_MODULES


def test_every_test_file_belongs_to_a_run():
    stray = sorted(
        str(p.relative_to(PYTHON_TESTS))
        for p in PYTHON_TESTS.rglob("test_*.py")
        if p.relative_to(PYTHON_TESTS).parts[0] not in ("baseline", "tooling")
    )
    assert not stray, f"move these into tests/python/baseline/ or tests/python/tooling/: {stray}"


def test_tooling_tests_import_no_baseline_module():
    offenders = {
        str(p.relative_to(PYTHON_TESTS)): sorted(_imported_modules(p) & BASELINE_MODULES)
        for p in sorted((PYTHON_TESTS / "tooling").rglob("*.py"))
    }
    offenders = {name: mods for name, mods in offenders.items() if mods}
    assert not offenders, (
        "these tooling tests import 3.9 baseline modules; move them to "
        f"tests/python/baseline/ so the frozen interpreter runs them: {offenders}"
    )


def test_baseline_tests_each_import_a_baseline_module():
    files = sorted((PYTHON_TESTS / "baseline").rglob("test_*.py")) + sorted(PLUGIN_TESTS.rglob("test_*.py"))
    assert files
    idle = [str(p.relative_to(REPO_ROOT)) for p in files if not _imported_modules(p) & BASELINE_MODULES]
    assert not idle, f"these baseline tests test no 3.9 baseline module; move them to tests/python/tooling/: {idle}"
