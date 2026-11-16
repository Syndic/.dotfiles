"""roles/homebrew/library/trust_brewfile_entries.py against a fake `brew`.

See CLAUDE.md "Third-party Brewfile entries are trusted by the role".
"""
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional

import pytest

MODULE = Path(__file__).resolve().parents[3] / "roles/homebrew/library/trust_brewfile_entries.py"
_spec = importlib.util.spec_from_file_location("trust_brewfile_entries", MODULE)
trust = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trust)


class BrewFailed(Exception):
    pass


class FakeBrew:
    """Records calls; `--repository` maps into `taps_dir`, `deps` answers from `deps`."""

    def __init__(self, taps_dir: Path, deps: Optional[Dict[str, List[str]]] = None,
                 tapped: List[str] = (), fail_deps_for: Optional[str] = None) -> None:
        self.taps_dir = taps_dir
        self.deps = deps or {}
        self.fail_deps_for = fail_deps_for
        self.calls: List[List[str]] = []
        self.trust_store = set()
        for tap in tapped:
            (taps_dir / tap).mkdir(parents=True)

    def __call__(self, args: List[str]) -> str:
        self.calls.append(args)
        cmd, name = args[0], args[-1]
        if cmd == "--repository":
            return f"{self.taps_dir / name}\n"
        if cmd == "tap":
            (self.taps_dir / args[1]).mkdir(parents=True, exist_ok=True)
        elif cmd == "trust":
            key = tuple(args[1:])
            if key in self.trust_store:
                return f"Already trusted formula: {name}\n"
            self.trust_store.add(key)
            return f"Trusted formula: {name}\n"
        elif cmd == "deps":
            if name == self.fail_deps_for:
                raise BrewFailed(args)
            return "".join(f"{dep}\n" for dep in self.deps.get(name, []))
        return ""

    def calls_to(self, *cmds: str) -> List[List[str]]:
        return [c for c in self.calls if c[0] in cmds]


def test_trusts_qualified_third_party_entries_by_type_and_nothing_else(tmp_path):
    brew = FakeBrew(tmp_path, tapped=["acme/tap"])
    text = "\n".join([
        'tap "acme/tap"',
        'brew "jq"',
        'brew "acme/tap/tool"',
        '# brew "acme/tap/commented"',
        'cask "acme/tap/app", greedy: true',
        'brew "homebrew/core/wget"',
        'cask "firefox"',
    ])
    result = trust.trust_brewfile(text, brew)
    assert brew.calls_to("trust") == [
        ["trust", "--formula", "acme/tap/tool"], ["trust", "--cask", "acme/tap/app"]]
    assert brew.calls_to("tap") == []
    assert result == {"tapped": [], "trusted": [
        {"kind": "formula", "name": "acme/tap/tool"}, {"kind": "cask", "name": "acme/tap/app"}]}


def test_walks_third_party_dependencies_across_taps_skipping_core_ones(tmp_path):
    brew = FakeBrew(tmp_path, tapped=["acme/tap"], deps={
        "acme/tap/meta": ["kubectl", "acme/tap/cli", "other/tap/lib", "homebrew/core/curl"],
        "acme/tap/cli": ["acme/tap/meta"],
        "acme/tap/app": ["acme/tap/helper"],
    })
    text = 'tap "acme/tap"\nbrew "acme/tap/meta"\ncask "acme/tap/app"\n'
    result = trust.trust_brewfile(text, brew)
    assert brew.calls_to("trust") == [
        ["trust", "--formula", "acme/tap/meta"],
        ["trust", "--cask", "acme/tap/app"],
        ["trust", "--formula", "acme/tap/cli"],
        ["trust", "--formula", "other/tap/lib"],
        ["trust", "acme/tap/helper"],
    ]
    assert result["tapped"] == ["other/tap"]
    assert ["deps", "--direct", "--include-build", "--formula", "acme/tap/meta"] in brew.calls


def test_taps_a_missing_tap_with_the_brewfiles_remote_before_trusting_from_it(tmp_path):
    brew = FakeBrew(tmp_path)
    text = 'tap "acme/tap", "https://example.invalid/acme.git"\nbrew "acme/tap/tool"\n'
    result = trust.trust_brewfile(text, brew)
    assert brew.calls_to("tap", "trust") == [
        ["tap", "acme/tap", "https://example.invalid/acme.git"],
        ["trust", "--formula", "acme/tap/tool"],
    ]
    assert result["tapped"] == ["acme/tap"]


def test_a_second_run_taps_and_trusts_nothing_new(tmp_path):
    brew = FakeBrew(tmp_path, deps={"acme/tap/tool": ["acme/tap/lib"]})
    text = 'tap "acme/tap"\nbrew "acme/tap/tool"\n'
    first = trust.trust_brewfile(text, brew)
    assert {"kind": "formula", "name": "acme/tap/lib"} in first["trusted"]
    assert trust.trust_brewfile(text, brew) == {"tapped": [], "trusted": []}


def test_a_failing_brew_deps_fails_the_run(tmp_path):
    brew = FakeBrew(tmp_path, tapped=["acme/tap"], fail_deps_for="acme/tap/tool")
    with pytest.raises(BrewFailed):
        trust.trust_brewfile('brew "acme/tap/tool"\n', brew)


def test_a_brewfile_with_no_third_party_entries_calls_no_brew(tmp_path):
    brew = FakeBrew(tmp_path)
    text = 'brew "jq"\ncask "firefox"\ntap "homebrew/cask-fonts"\n'
    assert trust.trust_brewfile(text, brew) == {"tapped": [], "trusted": []}
    assert brew.calls == []


def test_a_formula_and_a_cask_sharing_a_token_are_both_trusted(tmp_path):
    brew = FakeBrew(tmp_path, tapped=["acme/tap"])
    trust.trust_brewfile('brew "acme/tap/foo"\ncask "acme/tap/foo"\n', brew)
    assert brew.calls_to("trust") == [
        ["trust", "--formula", "acme/tap/foo"], ["trust", "--cask", "acme/tap/foo"]]


def test_each_tap_is_looked_up_once_per_run(tmp_path):
    brew = FakeBrew(tmp_path, tapped=["acme/tap"], deps={"acme/tap/a": ["acme/tap/c"]})
    trust.trust_brewfile('tap "acme/tap"\nbrew "acme/tap/a"\nbrew "acme/tap/b"\n', brew)
    assert brew.calls.count(["--repository", "acme/tap"]) == 1
