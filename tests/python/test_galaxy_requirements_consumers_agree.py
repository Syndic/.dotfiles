"""Guard the Galaxy-collection sourcing invariant.

Collections reach an environment from requirements files, never from the
`ansible` package's bundle — two roots on the resolution path produce
duplicate-version warnings. That invariant has three moving parts, each
in a different file and language:

  1. The requirements files themselves (`requirements*.yml` at the repo
     root) — ground truth for what gets installed.
  2. `.devcontainer/post-create.sh` — installs both, runtime + dev.
  3. `.github/workflows/tests.yml` — the molecule job installs both.

Plus the scoping asymmetry: `phase2.py` installs the runtime file only,
so a user's machine never downloads molecule's docker-driver collections.

Plain string parsing — `~/.venv` carries pytest + pytest-cov only; no
PyYAML. See test_molecule_role_lists_agree.py for the same precedent."""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

POST_CREATE = REPO_ROOT / ".devcontainer" / "post-create.sh"
TESTS_YML = REPO_ROOT / ".github" / "workflows" / "tests.yml"
PHASE2 = REPO_ROOT / "phase2.py"

# `ansible` as a whole pip requirement, not the `ansible-core` / `ansible-lint`
# prefixes. The negative lookahead is what separates them.
BUNDLE_RE = re.compile(r"(?<![-\w])ansible(?![-\w])")


def _requirements_files() -> set:
    """Root-level `requirements*.yml` filenames."""
    return {p.name for p in REPO_ROOT.glob("requirements*.yml")}


def _installed_by(path: Path) -> set:
    """Requirements filenames the file passes to `ansible-galaxy ... -r`."""
    return set(
        re.findall(
            r"collection[\"']?,?\s+[\"']?install.*?(requirements[-\w]*\.yml)",
            path.read_text(),
        )
    )


def _pip_install_lines(path: Path) -> list:
    """Lines that install Python packages (pip or uv pip), minus comments.

    Backslash continuations are folded first — post-create.sh wraps its
    package list onto the next line, which would otherwise hide every
    package name from the `pip install` match."""
    text = re.sub(r"\\\n\s*", " ", path.read_text())
    return [
        line
        for line in text.splitlines()
        if "pip install" in line and not line.lstrip().startswith("#")
    ]


def _collection_entries(path: Path) -> list:
    """(name, pinned) for every collection entry in a requirements file.

    Plain parse — the pytest venv has no PyYAML. Splitting on each
    `- name:` list item scopes any following `version:` to that entry, so
    the one-collection-per-item layout is the only assumption."""
    blocks = re.split(r"\n\s*-\s+name:", path.read_text())
    entries = []
    for block in blocks[1:]:  # blocks[0] is the header/preamble
        name = block.splitlines()[0].strip().strip("\"'")
        pinned = bool(re.search(r"\n\s*version:\s*\S", block))
        entries.append((name, pinned))
    return entries


def test_repo_declares_a_runtime_and_a_dev_requirements_file() -> None:
    assert _requirements_files() == {"requirements.yml", "requirements-dev.yml"}


def test_every_collection_is_version_pinned() -> None:
    # The repo pins every dependency it can and lets Renovate bump it (see
    # CLAUDE.md "Dependency updates"). An unpinned collection makes a fresh
    # install non-reproducible and can break bootstrap on an upstream release
    # with no repo change — guard against one slipping back in.
    for name in _requirements_files():
        entries = _collection_entries(REPO_ROOT / name)
        assert entries, f"{name}: no collection entries parsed"
        unpinned = [coll for coll, pinned in entries if not pinned]
        assert not unpinned, f"{name}: collections missing a version pin: {unpinned}"


def test_post_create_installs_every_requirements_file() -> None:
    missing = _requirements_files() - _installed_by(POST_CREATE)
    assert not missing, (
        f".devcontainer/post-create.sh does not ansible-galaxy install: "
        f"{sorted(missing)}"
    )


def test_molecule_ci_installs_every_requirements_file() -> None:
    missing = _requirements_files() - _installed_by(TESTS_YML)
    assert not missing, (
        f".github/workflows/tests.yml does not ansible-galaxy install: "
        f"{sorted(missing)}"
    )


def test_phase2_installs_only_the_runtime_requirements_file() -> None:
    # The scoping decision: dev-only collections (molecule's docker driver)
    # must not land on a user's machine during a normal bootstrap.
    # phase2 builds the path from a variable, so match filenames anywhere
    # in the source rather than on the ansible-galaxy invocation.
    named = set(re.findall(r"requirements[-\w]*\.yml", PHASE2.read_text()))
    assert named == {"requirements.yml"}, (
        f"phase2.py should reference only requirements.yml, found: "
        f"{sorted(named)}"
    )


def test_no_consumer_installs_the_full_ansible_bundle() -> None:
    # The regression this whole file exists for: `ansible` ships ~100
    # collections in its own site-packages, which then shadow-or-duplicate
    # whatever ansible-galaxy puts in ~/.ansible/collections.
    for path in (POST_CREATE, TESTS_YML):
        for line in _pip_install_lines(path):
            assert not BUNDLE_RE.search(line), (
                f"{path.relative_to(REPO_ROOT)} installs the full `ansible` "
                f"bundle; use `ansible-core` and declare collections in a "
                f"requirements file:\n  {line.strip()}"
            )
