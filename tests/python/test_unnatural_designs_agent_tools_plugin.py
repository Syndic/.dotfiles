"""Structural checks on the in-repo unnatural-designs-agent-tools Claude Code plugin.

The claude_code role registers unnatural-designs-agent-tools/ as a `directory` marketplace and
enables every plugin its marketplace.json lists, so a malformed manifest or a
skill without frontmatter breaks loading on every host. `claude plugin
validate` isn't available in CI; these checks cover the rules it would."""

import json
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "unnatural-designs-agent-tools"
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


def test_every_marketplace_entry_is_a_relative_path_plugin_inside_the_folder() -> None:
    """Relative-path entries load in place from a directory marketplace; any other
    source type would be copied to the plugin cache and stop tracking the checkout."""
    for entry in _load("marketplace.json")["plugins"]:
        assert entry["source"].startswith("./"), entry
        manifest = PLUGIN_ROOT / entry["source"] / ".claude-plugin" / "plugin.json"
        assert manifest.is_file(), entry


def test_marketplace_entry_names_match_manifest_names() -> None:
    """Claude Code keys enabledPlugins by entry name but prefixes skills with the
    manifest name; the two must agree or `/<plugin>:<skill>` won't resolve."""
    for entry in _load("marketplace.json")["plugins"]:
        manifest = PLUGIN_ROOT / entry["source"] / ".claude-plugin" / "plugin.json"
        assert json.loads(manifest.read_text())["name"] == entry["name"]


def test_role_default_points_at_a_marketplace_in_this_repo() -> None:
    defaults = (REPO_ROOT / "roles" / "claude_code" / "defaults" / "main.yml").read_text()
    match = re.search(
        r"^claude_code_marketplace_dir:\s*[\"']?\{\{\s*playbook_dir\s*\}\}/([^\"'\s]+)",
        defaults, re.MULTILINE)
    assert match, "claude_code_marketplace_dir should be relative to playbook_dir"
    assert (REPO_ROOT / match.group(1) / ".claude-plugin" / "marketplace.json").is_file()


def test_plugin_has_skills() -> None:
    assert SKILL_DIRS


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_skill_frontmatter_names_its_directory(skill_dir: Path) -> None:
    meta = _frontmatter(skill_dir / "SKILL.md")
    assert meta.get("name") == skill_dir.name
    assert meta.get("description")
