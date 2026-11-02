"""Make `import phase2` work when pytest runs from the repo root."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "lib"))  # molecule_images, shared with tests/run
