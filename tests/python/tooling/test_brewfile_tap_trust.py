"""Every third-party tap is trusted on its own `tap` line.

Homebrew refuses to load formulae and casks from an untrusted non-official tap,
and `brew bundle install` applies a Brewfile's `trusted:` options before loading
anything. See CLAUDE.md ▸ Conventions ("Third-party taps are trusted in the
Brewfile").
"""
import re
from pathlib import Path
from typing import List, Set

REPO = Path(__file__).resolve().parents[3]
BREWFILES = REPO / "brewfiles"
TAP_LINE = re.compile(r'^\s*tap\s+"(?P<tap>[^"]+)"(?P<opts>[^#\n]*)', re.MULTILINE)
QUALIFIED_ENTRY = re.compile(r'^\s*(?:brew|cask)\s+"(?P<tap>[^"/]+/[^"/]+)/[^"]+"', re.MULTILINE)
TRUSTED_TRUE = re.compile(r",\s*trusted:\s*true\b")


def official(tap: str) -> bool:
    return tap.lower().startswith("homebrew/")


def problems(text: str) -> List[str]:
    """Why a Brewfile's text would hit Homebrew's untrusted-tap refusal."""
    found: List[str] = []
    declared: Set[str] = set()
    for m in TAP_LINE.finditer(text):
        tap = m.group("tap").lower()
        declared.add(tap)
        if not official(tap) and not TRUSTED_TRUE.search(m.group("opts")):
            found.append(f'tap "{m.group("tap")}" needs `, trusted: true`')
    for m in QUALIFIED_ENTRY.finditer(text):
        tap = m.group("tap").lower()
        if not official(tap) and tap not in declared:
            found.append(f'entry from {m.group("tap")} needs a `tap "{m.group("tap")}", trusted: true` line')
    return found


def test_trusted_third_party_tap_passes() -> None:
    text = 'tap "x/y", trusted: true\nbrew "x/y/a"\ncask "x/y/b", greedy: true\n'
    assert problems(text) == []


def test_untrusted_third_party_tap_fails() -> None:
    assert problems('tap "x/y"\nbrew "x/y/a"\n') == ['tap "x/y" needs `, trusted: true`']


def test_trust_only_in_a_comment_fails() -> None:
    assert problems('tap "x/y" # trusted: true\n') == ['tap "x/y" needs `, trusted: true`']


def test_entry_from_undeclared_tap_fails() -> None:
    # brew would auto-tap x/y untrusted, then refuse to load the formula.
    assert problems('brew "x/y/a"\n') == ['entry from x/y needs a `tap "x/y", trusted: true` line']


def test_official_taps_and_core_names_need_nothing() -> None:
    assert problems('tap "homebrew/cask-fonts"\nbrew "homebrew/core/jq"\nbrew "jq"\ncask "font-x"\n') == []


def test_repo_brewfiles_trust_their_third_party_taps() -> None:
    brewfiles = sorted(BREWFILES.rglob("*.Brewfile"))
    assert brewfiles
    found = [f"{p.relative_to(REPO)}: {msg}" for p in brewfiles for msg in problems(p.read_text())]
    assert not found, "\n".join(found)
