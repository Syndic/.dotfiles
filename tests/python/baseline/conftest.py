"""Make `import phase2` work when pytest runs from the repo root, and refuse to
run on anything but 3.9 (see CLAUDE.md "Two pytest runs")."""
import sys
from pathlib import Path

if sys.version_info[:2] != (3, 9):
    raise RuntimeError(
        f"the baseline run must execute on Python 3.9, got {sys.version.split()[0]} "
        f"({sys.executable}); is ~/.venv-baseline missing? Rebuild the devcontainer."
    )

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
