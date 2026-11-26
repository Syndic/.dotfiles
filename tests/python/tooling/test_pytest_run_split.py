"""Keep tests in the pytest run that matches the code they test.

The baseline run (tests/python/baseline/) executes on the frozen 3.9 so it
proves the bootstrap's modules still run there; the tooling run (tests/python/tooling/
plus the plugin's own tests) executes on tooling_python. See CLAUDE.md "Two pytest runs"."""

import ast
import configparser
import shlex
from pathlib import Path

import yaml
from tests_run import PYTHON_SUITES, TOOLING_TEST_PATHS

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_TESTS = REPO_ROOT / "tests" / "python"
PLUGIN_ROOT = REPO_ROOT / "unnatural-designs-agent-tools"
PLUGIN_TESTS = PLUGIN_ROOT / "tests"

# Every module the bootstrap, uninstall, or pre-commit hooks run as `python3` —
# on macOS, the frozen 3.9.
BASELINE_MODULES = {p.stem for p in REPO_ROOT.glob("*.py")}


def _imported_modules(path: Path) -> set:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


def _overlaps(path: Path, other: Path) -> bool:
    return path == other or path in other.parents or other in path.parents


def test_baseline_modules_are_discovered():
    assert {"phase2", "_dotfiles_common", "uninstall", "dotfiles_manager"} <= BASELINE_MODULES


def test_every_test_file_belongs_to_a_run():
    stray = sorted(
        str(p.relative_to(PYTHON_TESTS))
        for p in PYTHON_TESTS.rglob("test_*.py")
        if p.relative_to(PYTHON_TESTS).parts[0] not in ("baseline", "tooling")
    )
    assert not stray, f"move these into tests/python/baseline/ or tests/python/tooling/: {stray}"


def test_tooling_tests_import_no_baseline_module():
    files = sorted((PYTHON_TESTS / "tooling").rglob("*.py")) + sorted(PLUGIN_TESTS.rglob("*.py"))
    offenders = {
        str(p.relative_to(REPO_ROOT)): sorted(_imported_modules(p) & BASELINE_MODULES) for p in files
    }
    offenders = {name: mods for name, mods in offenders.items() if mods}
    assert not offenders, (
        "these tooling tests import 3.9 baseline modules; move them to "
        f"tests/python/baseline/ so the frozen interpreter runs them: {offenders}"
    )


def test_baseline_tests_each_import_a_baseline_module():
    files = sorted((PYTHON_TESTS / "baseline").rglob("test_*.py"))
    assert files
    idle = [str(p.relative_to(REPO_ROOT)) for p in files if not _imported_modules(p) & BASELINE_MODULES]
    assert not idle, f"these baseline tests test no 3.9 baseline module; move them to tests/python/tooling/: {idle}"


def _ci_pytest_argv(job: str) -> list:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text())
    runs = [step["run"] for step in workflow["jobs"][job]["steps"] if "run" in step]
    pytest_runs = [shlex.split(run) for run in runs if run.lstrip().startswith("pytest")]
    assert len(pytest_runs) == 1, f"expected one pytest step in the {job} job"
    return pytest_runs[0]


def _suite_argv(name: str) -> list:
    (suite,) = [s for s in PYTHON_SUITES if s.name == name]
    return suite.argv


def test_plugin_is_outside_the_baseline_run():
    """The plugin's scripts target the tooling Python, so the frozen 3.9 must not collect them."""
    ini = configparser.ConfigParser()
    ini.read(REPO_ROOT / "pytest.ini")
    entries = ini["pytest"]["testpaths"].split()
    assert entries
    # pytest expands globs in testpaths, so match them against the tree as it does.
    testpaths = [p.resolve() for entry in entries for p in REPO_ROOT.glob(entry)]
    bad = [str(p.relative_to(REPO_ROOT)) for p in testpaths if _overlaps(p, PLUGIN_ROOT)]
    assert not bad, f"pytest.ini testpaths (the baseline run) reach the plugin: {bad}"


def test_baseline_run_takes_its_paths_only_from_testpaths():
    """A path on either baseline command would bypass the testpaths check above."""
    for where, argv in [("tests/run python:baseline", _suite_argv("python:baseline")),
                        ("tests.yml python job", _ci_pytest_argv("python"))]:
        paths = [arg for arg in argv if (REPO_ROOT / arg.split("::")[0]).exists()]
        assert not paths, f"{where} names test paths; put them in pytest.ini's testpaths: {paths}"


def test_tooling_run_covers_the_plugin_tests_locally_and_in_ci():
    assert {"tests/python/tooling", "unnatural-designs-agent-tools/tests"} <= set(TOOLING_TEST_PATHS)
    tail = len(TOOLING_TEST_PATHS)
    assert _suite_argv("python:tooling")[-tail:] == TOOLING_TEST_PATHS
    assert _ci_pytest_argv("python-tooling")[-tail:] == TOOLING_TEST_PATHS
