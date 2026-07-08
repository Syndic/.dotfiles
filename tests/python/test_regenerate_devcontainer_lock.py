"""Tests for regenerate_devcontainer_lock.py.

The pure functions (parse_features, reconcile, serialize) carry all the logic;
tests focus there. The driver's subprocess wiring is exercised end-to-end by the
renovate-devcontainer-lock workflow on a real Renovate PR — mocking the CLI here
would be low-value.
"""
from pathlib import Path

import pytest

from regenerate_devcontainer_lock import parse_features, reconcile, serialize

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_LOCK = REPO_ROOT / ".devcontainer" / "devcontainer-lock.json"


def _entry(version, digest):
    """A lock entry shaped like the CLI writes (resolved == integrity sha256)."""
    return {
        "version": version,
        "resolved": f"ghcr.io/devcontainers/features/x@sha256:{digest}",
        "integrity": f"sha256:{digest}",
    }


class TestParseFeatures:
    def test_empty_string(self):
        assert parse_features("") == {}

    def test_whitespace_only(self):
        assert parse_features("   \n  ") == {}

    def test_object_without_features_key(self):
        assert parse_features('{"other": 1}') == {}

    def test_normal_lock(self):
        text = '{"features": {"ghcr.io/x:1": {"version": "1.0.0"}}}'
        assert parse_features(text) == {"ghcr.io/x:1": {"version": "1.0.0"}}


class TestReconcile:
    def test_empty_committed_adopts_all_resolved(self):
        # First-time lock (nothing committed): every resolved entry is adopted.
        resolved = {"a:1": _entry("1.0.0", "aaa"), "b:2": _entry("2.0.0", "bbb")}
        assert reconcile({}, resolved) == resolved

    def test_unchanged_reference_keeps_committed_digest(self):
        # Same key in both, but resolved re-resolved to a newer digest. We must
        # keep the committed one — this is the trigger-B (floating-tag) no-flap
        # guarantee.
        committed = {"git:1": _entry("1.3.5", "old")}
        resolved = {"git:1": _entry("1.3.7", "new")}
        assert reconcile(committed, resolved) == {"git:1": _entry("1.3.5", "old")}

    def test_changed_reference_swaps_key(self):
        # The headline case: a version bump is a key swap. The old key is dropped
        # (absent from resolved) and the new key adopted from resolved; unrelated
        # references keep their committed digest.
        committed = {
            "docker-in-docker:3": _entry("3.0.1", "d3"),
            "git:1": _entry("1.3.7", "g"),
        }
        resolved = {
            "docker-in-docker:4": _entry("4.0.0", "d4"),
            "git:1": _entry("1.3.7", "g-newer"),
        }
        result = reconcile(committed, resolved)
        assert "docker-in-docker:3" not in result
        assert result["docker-in-docker:4"] == _entry("4.0.0", "d4")
        assert result["git:1"] == _entry("1.3.7", "g")  # committed, not g-newer

    def test_added_reference_is_adopted(self):
        committed = {"a:1": _entry("1.0.0", "a")}
        resolved = {"a:1": _entry("1.0.0", "a"), "b:1": _entry("1.0.0", "b")}
        assert reconcile(committed, resolved) == resolved

    def test_removed_reference_is_dropped(self):
        # A reference deleted from devcontainer.json is absent from resolved, so
        # iterating resolved drops it.
        committed = {"a:1": _entry("1.0.0", "a"), "b:1": _entry("1.0.0", "b")}
        resolved = {"a:1": _entry("1.0.0", "a")}
        assert reconcile(committed, resolved) == {"a:1": _entry("1.0.0", "a")}

    def test_result_follows_resolved_key_order(self):
        # Output order matches resolved (which follows devcontainer.json order), so
        # the serialized lock is deterministic.
        committed = {"b:1": _entry("1.0.0", "b")}
        resolved = {"a:1": _entry("1.0.0", "a"), "b:1": _entry("1.0.0", "b")}
        assert list(reconcile(committed, resolved)) == ["a:1", "b:1"]


class TestSerialize:
    def test_round_trips_through_parse(self):
        features = {"a:1": _entry("1.0.0", "aaa")}
        assert parse_features(serialize(features)) == features

    def test_two_space_indent_and_trailing_newline(self):
        out = serialize({"a:1": {"version": "1.0.0"}})
        assert out.startswith('{\n  "features": {\n')
        assert out.endswith("}\n")

    def test_committed_lock_is_byte_identical_round_trip(self):
        # Guards both our serializer and that the shipped lock stays in the CLI's
        # canonical format — a hand-edit that reformats it would fail here.
        raw = COMMITTED_LOCK.read_text(encoding="utf-8")
        assert serialize(parse_features(raw)) == raw
