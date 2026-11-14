"""Every third-party tap in a Brewfile has a fully qualified entry from it.

The homebrew role trusts only qualified `brew`/`cask` entries and their
dependencies, so a tap with none is either unused or used only through
unqualified names the role won't trust. See CLAUDE.md ▸ Conventions
("Third-party Brewfile entries are trusted by the role").
"""
import re
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parents[3]
BREWFILES = REPO / "brewfiles"
TAP_LINE = re.compile(r'^\s*tap\s+"(?P<tap>[^"]+)"', re.MULTILINE)
QUALIFIED_ENTRY = re.compile(r'^\s*(?:brew|cask)\s+"(?P<tap>[^"/]+/[^"/]+)/[^"]+"', re.MULTILINE)


def unused_taps(text: str) -> List[str]:
    used = {m.group("tap").lower() for m in QUALIFIED_ENTRY.finditer(text)}
    return [
        m.group("tap") for m in TAP_LINE.finditer(text)
        if not m.group("tap").lower().startswith("homebrew/") and m.group("tap").lower() not in used
    ]


def test_tap_with_a_qualified_entry_is_used() -> None:
    text = 'tap "acme/tap", "https://example.invalid/acme.git"\nbrew "Acme/Tap/tool"\n'
    assert unused_taps(text) == []


def test_tap_with_only_unqualified_or_commented_entries_is_unused() -> None:
    assert unused_taps('tap "acme/tap"\nbrew "tool"\n# brew "acme/tap/x"\n') == ["acme/tap"]


def test_a_qualified_cask_counts() -> None:
    assert unused_taps('tap "acme/tap"\ncask "acme/tap/app"\n') == []


def test_official_taps_are_exempt() -> None:
    assert unused_taps('tap "homebrew/cask-fonts"\ncask "font-x"\n') == []


def test_repo_brewfiles_use_every_third_party_tap() -> None:
    brewfiles = sorted(BREWFILES.rglob("*.Brewfile"))
    assert brewfiles
    found = [f"{p.relative_to(REPO)}: tap {tap!r} has no qualified brew/cask entry"
             for p in brewfiles for tap in unused_taps(p.read_text())]
    assert not found, "\n".join(found)
