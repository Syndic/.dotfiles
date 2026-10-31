"""Every cask a Linux host can install must ship Linux builds.

Most casks are macOS-only, so they belong in brewfiles/groups/macos.Brewfile or
a macOS host's Brewfile. Every other layer reaches Linux hosts too, so each
cask there is checked against Homebrew's cask API.
"""
import json
import re
import urllib.request
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pytest

REPO = Path(__file__).resolve().parents[2]
BREWFILES = REPO / "brewfiles"
CASK_LINE = re.compile(r'^\s*cask\s+"(?P<name>[^"]+)"', re.MULTILINE)
LINUX_BUILDS = ("x86_64_linux", "arm64_linux")


def casks(text: str) -> List[str]:
    return CASK_LINE.findall(text)


def group_hosts(inventory: str, group: str) -> Set[str]:
    """Hosts listed under `<group>: hosts:` in inventory.yml, without a YAML parser."""
    hosts: Set[str] = set()
    lines = inventory.splitlines()
    for i, line in enumerate(lines):
        if line.strip() != f"{group}:" or i + 1 >= len(lines) or lines[i + 1].strip() != "hosts:":
            continue
        indent = len(lines[i + 1]) - len(lines[i + 1].lstrip())
        for host in lines[i + 2:]:
            if host.strip() and len(host) - len(host.lstrip()) <= indent:
                break
            m = re.match(r"\s*([\w.-]+):\s*$", host)
            if m and len(host) - len(host.lstrip()) == indent + 2:
                hosts.add(m.group(1))
    return hosts


def linux_reachable_brewfiles() -> List[Path]:
    macos_hosts = group_hosts((REPO / "inventory.yml").read_text(), "macos")
    mac_only = {BREWFILES / "groups" / "macos.Brewfile"}
    mac_only |= {BREWFILES / "hosts" / f"{h}.Brewfile" for h in macos_hosts}
    return [p for p in sorted(BREWFILES.rglob("*.Brewfile")) if p not in mac_only]


def missing_linux_builds(cask: dict) -> Tuple[str, ...]:
    """Linux platforms the cask's API record has no build for."""
    variations: Dict[str, object] = cask.get("variations") or {}
    return tuple(p for p in LINUX_BUILDS if p not in variations)


def fetch_cask(name: str) -> dict:
    url = f"https://formulae.brew.sh/api/cask/{name}.json"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.load(resp)


def test_casks_are_read_from_brewfile_lines() -> None:
    text = 'tap "x/y"\n# cask "commented"\ncask "a"\n  cask "b", greedy: true\nbrew "c"\n'
    assert casks(text) == ["a", "b"]


def test_group_hosts_reads_one_group() -> None:
    inventory = (
        "all:\n  children:\n    macos:\n      hosts:\n        mac1:\n        mac2:\n"
        "          ansible_host: localhost\n    linux:\n      hosts:\n        box:\n"
    )
    assert group_hosts(inventory, "macos") == {"mac1", "mac2"}
    assert group_hosts(inventory, "linux") == {"box"}


def test_the_real_inventory_has_macos_hosts() -> None:
    assert group_hosts((REPO / "inventory.yml").read_text(), "macos")


@pytest.mark.parametrize("record,missing", [
    ({"variations": {"x86_64_linux": {}, "arm64_linux": {}, "sonoma": {}}}, ()),
    ({"variations": {"x86_64_linux": {}}}, ("arm64_linux",)),
    ({"variations": {}, "depends_on": {"macos": {">=": ["13"]}}}, LINUX_BUILDS),
])
def test_missing_linux_builds(record: dict, missing: Tuple[str, ...]) -> None:
    assert missing_linux_builds(record) == missing


def test_linux_reachable_casks_ship_linux_builds() -> None:
    """Network-dependent, so it skips offline; CI has network and enforces it."""
    found = [(p.relative_to(REPO), name) for p in linux_reachable_brewfiles()
             for name in casks(p.read_text())]
    if not found:
        pytest.skip("no casks in Brewfiles that reach Linux hosts")
    for rel, name in found:
        try:
            record = fetch_cask(name)
        except Exception as err:  # noqa: BLE001 — any failure means "can't verify now"
            pytest.skip(f"Homebrew API unreachable ({err!r}); skipping Linux-build check")
        missing = missing_linux_builds(record)
        assert not missing, (
            f"{rel}: cask {name!r} has no {', '.join(missing)} build, so a Linux host "
            f"can't install it; move it to brewfiles/groups/macos.Brewfile"
        )
