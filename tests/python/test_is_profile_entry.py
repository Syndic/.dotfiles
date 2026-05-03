"""Tests for phase2.is_profile_entry — the filter that decides whether a
host_vars/ entry is a real Ansible host profile or junk."""
import os
import pytest

import phase2


@pytest.fixture
def host_vars(tmp_path):
    """A synthetic host_vars/ dir with a mix of valid entries and junk."""
    root = tmp_path / "host_vars"
    root.mkdir()

    # valid entries — should be kept
    (root / "laptop24.yml").write_text("")
    (root / "mini18.yaml").write_text("")
    (root / "mini26").mkdir()
    (root / "mini26" / "general.yml").write_text("")

    # junk — should be filtered
    (root / ".DS_Store").write_bytes(b"\x00")
    (root / ".gitkeep").write_text("")
    (root / "README.md").write_text("# notes")
    (root / "laptop24.yml.bak").write_text("")
    (root / "scratch.txt").write_text("")
    os.symlink("/nonexistent/target", root / "broken-symlink")

    return root


@pytest.mark.parametrize("name,expected", [
    # valid
    ("laptop24.yml", True),
    ("mini18.yaml", True),
    ("mini26", True),
    # junk
    (".DS_Store", False),
    (".gitkeep", False),
    ("README.md", False),
    ("laptop24.yml.bak", False),
    ("scratch.txt", False),
    ("broken-symlink", False),
])
def test_is_profile_entry(host_vars, name, expected):
    assert phase2.is_profile_entry(host_vars / name) is expected


def test_filtered_list_is_just_real_profiles(host_vars):
    profiles = sorted(
        p.stem if p.is_file() else p.name
        for p in host_vars.iterdir()
        if phase2.is_profile_entry(p)
    )
    assert profiles == ["laptop24", "mini18", "mini26"]
