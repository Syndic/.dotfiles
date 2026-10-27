"""Structural checks on the in-repo agent-tools Claude Code plugin.

The claude_code role registers agent-tools/ as a `directory` marketplace and
enables every plugin its marketplace.json lists, so a malformed manifest or a
skill without frontmatter breaks loading on every host. `claude plugin
validate` isn't available in CI; these checks cover the rules it would."""

import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "agent-tools"
SKILL_DIRS = sorted(p for p in (PLUGIN_ROOT / "skills").iterdir() if p.is_dir())


def _load(name: str) -> dict:
    return json.loads((PLUGIN_ROOT / ".claude-plugin" / name).read_text())


def _frontmatter(path: Path) -> dict:
    """Top-level `key: value` pairs of a SKILL.md frontmatter block (no PyYAML in ~/.venv)."""
    lines = path.read_text().splitlines()
    assert lines and lines[0] == "---", f"{path} has no frontmatter"
    end = lines.index("---", 1)
    top_level = (line for line in lines[1:end] if ":" in line and not line.startswith(" "))
    pairs = (line.split(":", 1) for line in top_level)
    return {k.strip(): v.strip() for k, v in pairs}


def test_marketplace_lists_the_plugin_at_its_own_root() -> None:
    marketplace = _load("marketplace.json")
    assert marketplace["plugins"] == [
        {
            "name": "agent-tools",
            "source": "./",
            "description": marketplace["plugins"][0]["description"],
        }
    ]


def test_marketplace_entry_name_matches_manifest_name() -> None:
    """Claude Code keys enabledPlugins by entry name but prefixes skills with the
    manifest name; the two must agree or `/agent-tools:<skill>` won't resolve."""
    entry_names = {p["name"] for p in _load("marketplace.json")["plugins"]}
    assert entry_names == {_load("plugin.json")["name"]}


def test_role_registers_this_directory() -> None:
    defaults = (REPO_ROOT / "roles" / "claude_code" / "defaults" / "main.yml").read_text()
    assert 'claude_code_marketplace_dir: "{{ playbook_dir }}/agent-tools"' in defaults


def test_plugin_has_skills() -> None:
    assert SKILL_DIRS


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_skill_frontmatter_names_its_directory(skill_dir: Path) -> None:
    meta = _frontmatter(skill_dir / "SKILL.md")
    assert meta.get("name") == skill_dir.name
    assert meta.get("description")
