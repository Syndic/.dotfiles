"""Load tests/run (no .py suffix, so not importable by name) as `tests_run`."""
import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

TESTS_RUN = Path(__file__).resolve().parents[2] / "run"

_loader = SourceFileLoader("tests_run", str(TESTS_RUN))
tests_run = importlib.util.module_from_spec(importlib.util.spec_from_loader("tests_run", _loader))
# Registered before exec: @dataclass resolves its module via sys.modules.
sys.modules["tests_run"] = tests_run
_loader.exec_module(tests_run)
