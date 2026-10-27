"""uninstall.build_claude_plugin_action: reverses the claude_code role's two entries."""
from __future__ import annotations

import json
import os
from pathlib import Path

import uninstall


def _seed(path: Path, settings: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings))
    return path


def _installed(root: Path) -> dict:
    return {
        "outputStyle": "Concise",
        "enabledPlugins": {"agent-tools@agent-tools": True, "other@elsewhere": False},
        "extraKnownMarketplaces": {
            "agent-tools": {"source": {"source": "directory", "path": str(root / "agent-tools")}},
            "elsewhere": {"source": {"source": "github", "repo": "o/r"}},
            "local-other": {"source": {"source": "directory", "path": "/opt/other"}},
        },
    }


def test_removes_only_marketplaces_inside_the_managed_root(tmp_path: Path) -> None:
    root = tmp_path / "dotfiles"
    settings = _seed(tmp_path / ".claude" / "settings.json", _installed(root))

    preview, do = uninstall.build_claude_plugin_action(settings, root)
    assert preview == ["  unregister marketplace  agent-tools",
                       "  remove enabledPlugins   agent-tools@agent-tools"]
    do()

    after = json.loads(settings.read_text())
    assert after["outputStyle"] == "Concise"
    assert after["enabledPlugins"] == {"other@elsewhere": False}
    assert set(after["extraKnownMarketplaces"]) == {"elsewhere", "local-other"}
    assert os.stat(settings).st_mode & 0o777 == 0o600


def test_drops_sections_left_empty(tmp_path: Path) -> None:
    root = tmp_path / "dotfiles"
    owned = {k: {n: v for n, v in section.items() if "agent-tools" in n}
             for k, section in _installed(root).items() if isinstance(section, dict)}
    settings = _seed(tmp_path / "settings.json", {"model": "x", **owned})
    uninstall.build_claude_plugin_action(settings, root)[1]()
    assert json.loads(settings.read_text()) == {"model": "x"}


def test_rereads_the_file_before_writing(tmp_path: Path) -> None:
    root = tmp_path / "dotfiles"
    settings = _seed(tmp_path / "settings.json", _installed(root))
    _, do = uninstall.build_claude_plugin_action(settings, root)
    later = _installed(root)
    later["permissions"] = {"allow": ["Bash(ls)"]}
    _seed(settings, later)
    do()
    assert json.loads(settings.read_text())["permissions"] == {"allow": ["Bash(ls)"]}


def test_nothing_to_do_without_owned_entries(tmp_path: Path) -> None:
    settings = _seed(tmp_path / "settings.json", {"enabledPlugins": {"a@b": True}})
    assert uninstall.build_claude_plugin_action(settings, tmp_path / "dotfiles") == ([], None)


def test_missing_symlinked_or_invalid_settings_are_left_alone(tmp_path: Path) -> None:
    root = tmp_path / "dotfiles"
    assert uninstall.build_claude_plugin_action(tmp_path / "absent.json", root) == ([], None)

    target = _seed(tmp_path / "target.json", _installed(root))
    link = tmp_path / "link.json"
    link.symlink_to(target)
    assert uninstall.build_claude_plugin_action(link, root) == ([], None)

    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    preview, do = uninstall.build_claude_plugin_action(broken, root)
    assert do is None and "not valid JSON" in preview[0]
    assert broken.read_text() == "{not json"
