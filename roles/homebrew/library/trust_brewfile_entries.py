#!/usr/bin/python
"""Trust a Brewfile's third-party formulae and casks, plus their third-party
dependencies, before `brew bundle` loads them.

See CLAUDE.md "Third-party Brewfile entries are trusted by the role".
"""
from __future__ import annotations

import os
import re
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Set, Tuple

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = r"""
module: trust_brewfile_entries
short_description: Trust a Brewfile's third-party entries and their dependencies.
options:
  brewfile:
    description: Path to the Brewfile on the target.
    type: path
    required: true
"""

RETURN = r"""
tapped:
  description: Taps this run added.
  type: list
  elements: str
trusted:
  description: Entries this run newly trusted, as kind (formula, cask or any) and name.
  type: list
  elements: dict
"""

TAP_LINE = re.compile(r'^\s*tap\s+"(?P<tap>[^"]+)"(?:\s*,\s*"(?P<remote>[^"]+)")?')
ENTRY_LINE = re.compile(r'^\s*(?P<kind>brew|cask)\s+"(?P<name>[^"/]+/[^"/]+/[^"]+)"')
QUALIFIED = re.compile(r"^[^/\s]+/[^/\s]+/[^/\s]+$")
# A cask's dependencies can be formulae or casks; `brew` resolves which.
ANY = "any"

Brew = Callable[[List[str]], str]


def tap_of(name: str) -> str:
    return "/".join(name.split("/")[:2])


def is_official(name: str) -> bool:
    return name.lower().startswith("homebrew/")


def trust_brewfile(text: str, brew: Brew) -> Dict[str, list]:
    """Tap and trust what `text` (a Brewfile) needs; return what was newly done.

    `brew` runs one brew command (argv without the `brew`) and returns its stdout,
    raising or exiting on failure."""
    taps_checked: Set[str] = set()
    tapped: List[str] = []
    trusted: List[Dict[str, str]] = []

    # `brew trust` and `brew deps` both need the tap on disk.
    def ensure_tapped(tap: str, remote: Optional[str] = None) -> None:
        key = tap.lower()
        if is_official(key) or key in taps_checked:
            return
        taps_checked.add(key)
        if os.path.isdir(brew(["--repository", tap]).strip()):
            return
        brew(["tap", tap] + ([remote] if remote else []))
        tapped.append(tap)

    queue: Deque[Tuple[str, str]] = deque()
    for line in text.splitlines():
        tap = TAP_LINE.match(line)
        if tap:
            ensure_tapped(tap["tap"], tap["remote"])
            continue
        entry = ENTRY_LINE.match(line)
        if entry and not is_official(entry["name"]):
            queue.append(("formula" if entry["kind"] == "brew" else "cask", entry["name"]))

    # Keyed by kind too: a formula and a cask can share a token in one tap.
    seen: Set[Tuple[str, str]] = set()
    while queue:
        kind, name = queue.popleft()
        if (kind, name.lower()) in seen:
            continue
        seen.add((kind, name.lower()))
        ensure_tapped(tap_of(name))
        flag = [] if kind == ANY else ["--" + kind]
        if re.search(r"^Trusted ", brew(["trust"] + flag + [name]), re.MULTILINE):
            trusted.append({"kind": kind, "name": name})
        dep_kind = "formula" if kind == "formula" else ANY
        # No --full-name: it loads each dependency, which an untrusted one refuses.
        for dep in brew(["deps", "--direct", "--include-build"] + flag + [name]).split():
            if QUALIFIED.match(dep) and not is_official(dep):
                queue.append((dep_kind, dep))
    return {"tapped": tapped, "trusted": trusted}


def main() -> None:
    module = AnsibleModule(argument_spec={"brewfile": {"type": "path", "required": True}})

    def brew(args: List[str]) -> str:
        rc, out, err = module.run_command(["brew"] + args)
        if rc != 0:
            module.fail_json(msg="brew " + " ".join(args) + " failed", rc=rc, stdout=out, stderr=err)
        return out

    with open(module.params["brewfile"], encoding="utf-8") as f:
        result = trust_brewfile(f.read(), brew)
    module.exit_json(changed=bool(result["tapped"] or result["trusted"]), **result)


if __name__ == "__main__":
    main()
