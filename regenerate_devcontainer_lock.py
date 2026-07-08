#!/usr/bin/env python3
"""Regenerate .devcontainer/devcontainer-lock.json after a Renovate feature bump.

Renovate rewrites a feature's version tag in devcontainer.json but never updates
the lock (Mend-hosted Renovate can't run postUpgradeTasks). This script closes
that gap: it re-resolves the current config with the devcontainer CLI and rewrites
only the entries whose reference actually changed, leaving unchanged references at
their committed digest. See CLAUDE.md "Devcontainer lock regeneration" for the full
mechanism (why upgrade+reconcile rather than a plain build, the pinning policy, and
the signed-commit workflow that runs this in CI).

The pure functions (parse_features, reconcile, serialize, config_feature_refs) hold
all the logic so the test suite can exercise them without the CLI. The driver has two
modes: the default upgrade+reconcile (a thin shell around `devcontainer upgrade
--dry-run` plus file I/O), and an offline `--verify-refs` consistency check — used by
the pre-commit hook — that compares the lock's feature keys against devcontainer.json
without the CLI or network.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Paths relative to the workspace folder (the devcontainer CLI's defaults).
DEFAULT_LOCK_RELPATH = ".devcontainer/devcontainer-lock.json"
DEFAULT_CONFIG_RELPATH = ".devcontainer/devcontainer.json"

# The command a stale-lock failure tells the user to run (copy/paste-ready).
REGEN_COMMAND = "python3 regenerate_devcontainer_lock.py"


# ── Pure functions (the part the tests exercise) ──────────────────────────────


def parse_features(text: str) -> dict:
    """Return the `features` map from devcontainer-lock JSON text.

    Empty/whitespace text and a JSON object without a `features` key both yield
    {}, so a missing or first-time lock needs no special-casing by the caller.
    """
    text = text.strip()
    if not text:
        return {}
    return json.loads(text).get("features", {})


def reconcile(committed: dict, resolved: dict) -> dict:
    """Merge a freshly-resolved features map against the committed one.

    For each reference in `resolved` (fresh `devcontainer upgrade` output): keep
    the committed entry verbatim when that exact reference key is already locked,
    else adopt the fresh entry. References absent from `resolved` are dropped.

    The tag is part of the reference key, so a Renovate version bump is a key
    swap — the new reference is absent from `committed` (which still holds the old
    key) and gets adopted, while an *unchanged* reference shares its key and keeps
    its committed digest (so a floating tag can't silently flap the lock).
    """
    return {
        ref: committed[ref] if ref in committed else entry
        for ref, entry in resolved.items()
    }


def serialize(features: dict) -> str:
    """Render a features map exactly as the devcontainer CLI writes its lock.

    `json.dumps(indent=2)` + trailing newline reproduces the CLI's output
    byte-for-byte, so a regenerated lock diffs cleanly against a CLI-written one.
    """
    return json.dumps({"features": features}, indent=2) + "\n"


def _strip_jsonc(text: str) -> str:
    """Strip `//` and `/* */` comments from JSONC, preserving string literals."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:  # keep the escaped char verbatim
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] != "\n":
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def config_feature_refs(text: str) -> set:
    """Return the set of feature reference strings from a devcontainer.json.

    Tolerates JSONC (comments + trailing commas); an absent or empty `features`
    block yields an empty set. Only the reference keys matter — feature options
    aren't recorded in the lock, so they're irrelevant to the consistency check.
    """
    stripped = re.sub(r",(\s*[}\]])", r"\1", _strip_jsonc(text))  # drop trailing commas
    return set(json.loads(stripped).get("features", {}).keys())


def diff_refs(config_refs: set, lock_refs: set) -> tuple[list[str], list[str]]:
    """Return (only-in-config, only-in-lock) as sorted lists — empty ⇒ in sync."""
    return sorted(config_refs - lock_refs), sorted(lock_refs - config_refs)


def render_ref_mismatch(only_in_config: list[str], only_in_lock: list[str]) -> str:
    """Build the stale-lock failure message, ending with the regeneration command."""
    lines = ["devcontainer-lock.json is out of sync with devcontainer.json:"]
    for ref in only_in_config:
        lines.append(f"  + {ref}  (referenced in devcontainer.json, missing from the lock)")
    for ref in only_in_lock:
        lines.append(f"  - {ref}  (in the lock, no longer referenced in devcontainer.json)")
    lines += ["", "Regenerate the lock with:", f"    {REGEN_COMMAND}"]
    return "\n".join(lines)


# ── I/O driver ────────────────────────────────────────────────────────────────


def _resolve_features(workspace_folder: str) -> dict:
    """Fresh-resolve every feature via `devcontainer upgrade --dry-run`.

    stdout (the regenerated lock JSON) is captured for parsing; stderr streams to
    the caller's log. A non-zero exit (e.g. a bumped tag that doesn't exist)
    raises CalledProcessError, failing the run loudly.
    """
    result = subprocess.run(
        ["devcontainer", "upgrade", "--workspace-folder", workspace_folder, "--dry-run"],
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    )
    return parse_features(result.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-folder",
        default=".",
        help="Workspace folder passed to the devcontainer CLI (default: cwd).",
    )
    parser.add_argument(
        "--lock-path",
        default=None,
        help=f"Lock file to write (default: <workspace-folder>/{DEFAULT_LOCK_RELPATH}).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the lock would change; do not write it.",
    )
    parser.add_argument(
        "--verify-refs",
        action="store_true",
        help="Offline: fail if the lock's feature keys don't match devcontainer.json "
        "(no CLI/network). Used by the pre-commit hook.",
    )
    args = parser.parse_args(argv)

    lock_path = (
        Path(args.lock_path)
        if args.lock_path
        else Path(args.workspace_folder) / DEFAULT_LOCK_RELPATH
    )

    if args.verify_refs:
        config_path = Path(args.workspace_folder) / DEFAULT_CONFIG_RELPATH
        config_refs = config_feature_refs(config_path.read_text(encoding="utf-8"))
        lock_text = lock_path.read_text(encoding="utf-8") if lock_path.exists() else ""
        only_config, only_lock = diff_refs(config_refs, set(parse_features(lock_text)))
        if not only_config and not only_lock:
            print(f"{lock_path}: feature references in sync.")
            return 0
        print(render_ref_mismatch(only_config, only_lock), file=sys.stderr)
        return 1

    resolved = _resolve_features(args.workspace_folder)
    current_text = lock_path.read_text(encoding="utf-8") if lock_path.exists() else ""
    new_text = serialize(reconcile(parse_features(current_text), resolved))

    if new_text == current_text:
        print(f"{lock_path}: already up to date.")
        return 0

    if args.check:
        print(
            f"{lock_path}: OUT OF DATE — run regenerate_devcontainer_lock.py to update.",
            file=sys.stderr,
        )
        return 1

    lock_path.write_text(new_text, encoding="utf-8")
    print(f"{lock_path}: regenerated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
