"""Keep tests in the pytest run that matches the code they test.

The baseline run (tests/python/baseline/) executes on the frozen 3.9 so it
proves the bootstrap's modules still run there; the tooling run (tests/python/tooling/
plus the plugin's own tests, pytest.ini's testpaths) executes on tooling_python. See
CLAUDE.md "Two pytest runs"."""

import ast
import configparser
import glob
import json
import shlex
import subprocess
from pathlib import Path

import yaml
from tests_run import BASELINE_TEST_PATH, PYTHON_SUITES

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_TESTS = REPO_ROOT / "tests" / "python"
PLUGIN_ROOT = REPO_ROOT / "unnatural-designs-agent-tools"
PLUGIN_TESTS = PLUGIN_ROOT / "tests"
BASELINE_TESTS = PYTHON_TESTS / "baseline"

# Every module the bootstrap or uninstall can run on the frozen 3.9 (macOS's /usr/bin/python3).
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


def _named_paths(argv: list) -> list:
    """The repo paths a pytest command line names (the interpreter and options aren't)."""
    return [
        arg
        for arg in argv
        if not arg.startswith("-") and not Path(arg).is_absolute() and (REPO_ROOT / arg.split("::")[0]).exists()
    ]


def _testpaths() -> dict:
    """Each pytest.ini testpaths entry, mapped to what pytest expands it to (glob.iglob, recursive)."""
    ini = configparser.ConfigParser()
    ini.read(REPO_ROOT / "pytest.ini")
    entries = ini["pytest"]["testpaths"].split()
    assert entries
    return {
        entry: [(REPO_ROOT / p).resolve() for p in glob.glob(entry, root_dir=REPO_ROOT, recursive=True)]
        for entry in entries
    }


def test_testpaths_stay_out_of_the_baseline_tests():
    """Bare `pytest` is the tooling run; collecting the baseline tests on tooling_python fails."""
    bad = [entry for entry, paths in _testpaths().items() if any(_overlaps(p, BASELINE_TESTS) for p in paths)]
    assert not bad, f"pytest.ini testpaths (the tooling run) reach tests/python/baseline: {bad}"


def test_testpaths_collect_every_tooling_test():
    paths = [p for expanded in _testpaths().values() for p in expanded]
    files = sorted((PYTHON_TESTS / "tooling").rglob("test_*.py")) + sorted(PLUGIN_TESTS.rglob("test_*.py"))
    assert files
    missed = [str(f.relative_to(REPO_ROOT)) for f in files if not any(_overlaps(f, p) for p in paths)]
    assert not missed, f"pytest.ini testpaths (the tooling run) miss these tests: {missed}"


def test_tooling_commands_take_their_paths_from_testpaths():
    """A path on either tooling command would make it disagree with bare `pytest`."""
    for where, argv in [("tests/run python:tooling", _suite_argv("python:tooling")),
                        ("tests.yml python-tooling job", _ci_pytest_argv("python-tooling"))]:
        paths = _named_paths(argv)
        assert not paths, f"{where} names test paths; put them in pytest.ini's testpaths: {paths}"


def test_baseline_commands_name_only_the_baseline_tests():
    """The baseline run collects tests/python/baseline and nothing else (the plugin included)."""
    assert (REPO_ROOT / BASELINE_TEST_PATH).resolve() == BASELINE_TESTS
    for where, argv in [("tests/run python:baseline", _suite_argv("python:baseline")),
                        ("tests.yml python job", _ci_pytest_argv("python"))]:
        paths = [(REPO_ROOT / p).resolve() for p in _named_paths(argv)]
        assert paths == [BASELINE_TESTS], f"{where} must name exactly {BASELINE_TEST_PATH}: {_named_paths(argv)}"


def _is_baseline_code(rel: Path) -> bool:
    return len(rel.parts) == 1 or rel.parts[:3] == ("tests", "python", "baseline")


def test_pylance_checks_exactly_the_baseline_code_against_python_3_9():
    """pyright (Pylance) applies the first executionEnvironment whose root holds the file."""
    config = json.loads((REPO_ROOT / "pyrightconfig.json").read_text())
    assert "pythonVersion" not in config, "a top-level pythonVersion would pin the tooling code too"
    envs = config["executionEnvironments"]
    files = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.split()
    assert files
    wrong = {}
    for name in files:
        rel = Path(name)
        env = next((e for e in envs if rel.parts[: len(Path(e["root"]).parts)] == Path(e["root"]).parts), {})
        want = "3.9" if _is_baseline_code(rel) else None  # None: the interpreter's, i.e. tooling_python
        if env.get("pythonVersion") != want:
            wrong[name] = env.get("pythonVersion")
    assert not wrong, f"pyrightconfig.json checks these against the wrong Python (want 3.9 only for baseline code): {wrong}"
