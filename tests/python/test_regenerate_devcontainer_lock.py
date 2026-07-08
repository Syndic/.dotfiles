"""Tests for regenerate_devcontainer_lock.py.

The pure functions carry all the logic; tests focus there, plus the offline
--verify-refs driver mode (no CLI/network). The upgrade+reconcile driver's
subprocess wiring is exercised end-to-end by the renovate-devcontainer-lock
workflow on a real Renovate PR — mocking the CLI here would be low-value.
"""
import json
import textwrap
from pathlib import Path

from regenerate_devcontainer_lock import (
    REGEN_COMMAND,
    config_feature_refs,
    diff_refs,
    main,
    parse_features,
    reconcile,
    render_ref_mismatch,
    serialize,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEVCONTAINER = REPO_ROOT / ".devcontainer"
COMMITTED_LOCK = DEVCONTAINER / "devcontainer-lock.json"
COMMITTED_CONFIG = DEVCONTAINER / "devcontainer.json"


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


class TestConfigFeatureRefs:
    def test_line_comments_stripped(self):
        text = textwrap.dedent("""\
            {
              // a leading comment
              "features": {
                "ghcr.io/x:1.0.0": {},  // trailing tag comment
                "ghcr.io/y:2.0.0": {}
              }
            }
        """)
        assert config_feature_refs(text) == {"ghcr.io/x:1.0.0", "ghcr.io/y:2.0.0"}

    def test_block_comments_stripped(self):
        text = '{"features": {/* block */ "ghcr.io/x:1.0.0": {}}}'
        assert config_feature_refs(text) == {"ghcr.io/x:1.0.0"}

    def test_double_slash_inside_string_is_not_a_comment(self):
        # A `//` inside a string value must survive — only real comments go.
        text = textwrap.dedent("""\
            {
              "features": {"ghcr.io/x:1.0.0": {"onCreate": "echo https://ok"}}
            }
        """)
        assert config_feature_refs(text) == {"ghcr.io/x:1.0.0"}

    def test_trailing_comma_tolerated(self):
        text = '{"features": {"ghcr.io/x:1.0.0": {},}}'
        assert config_feature_refs(text) == {"ghcr.io/x:1.0.0"}

    def test_absent_features_is_empty(self):
        assert config_feature_refs('{"name": "x"}') == set()

    def test_matches_committed_devcontainer_json(self):
        # Integration guard: the real config's feature refs equal the real lock's
        # keys, so the shipped pair is in sync (what --verify-refs asserts).
        config_refs = config_feature_refs(COMMITTED_CONFIG.read_text(encoding="utf-8"))
        lock_refs = set(parse_features(COMMITTED_LOCK.read_text(encoding="utf-8")))
        assert config_refs == lock_refs
        assert "ghcr.io/devcontainers/features/docker-in-docker:4.0.0" in config_refs


class TestDiffRefs:
    def test_in_sync(self):
        assert diff_refs({"a", "b"}, {"a", "b"}) == ([], [])

    def test_only_in_config(self):
        assert diff_refs({"a", "b"}, {"a"}) == (["b"], [])

    def test_only_in_lock(self):
        assert diff_refs({"a"}, {"a", "b"}) == ([], ["b"])

    def test_both_directions_sorted(self):
        # A tag bump shows as one ref on each side (old key vs new key).
        only_config, only_lock = diff_refs({"git:1.3.8", "z:1"}, {"git:1.3.7", "z:1"})
        assert only_config == ["git:1.3.8"]
        assert only_lock == ["git:1.3.7"]


class TestRenderRefMismatch:
    def test_includes_regen_command_and_refs(self):
        msg = render_ref_mismatch(["git:1.3.8"], ["git:1.3.7"])
        assert REGEN_COMMAND in msg
        assert "git:1.3.8" in msg
        assert "git:1.3.7" in msg


class TestVerifyRefsMain:
    """End-to-end of the offline --verify-refs mode (no CLI/network)."""

    @staticmethod
    def _workspace(tmp_path, config_refs, lock_refs):
        dc = tmp_path / ".devcontainer"
        dc.mkdir()
        features = {ref: {} for ref in config_refs}
        (dc / "devcontainer.json").write_text(
            json.dumps({"features": features}), encoding="utf-8"
        )
        lock_features = {r: {"version": "1.0.0"} for r in lock_refs}
        (dc / "devcontainer-lock.json").write_text(serialize(lock_features), encoding="utf-8")
        return tmp_path

    def test_in_sync_returns_zero(self, tmp_path):
        ws = self._workspace(tmp_path, {"ghcr.io/x:1.0.0"}, {"ghcr.io/x:1.0.0"})
        assert main(["--workspace-folder", str(ws), "--verify-refs"]) == 0

    def test_out_of_sync_returns_one_and_prints_command(self, tmp_path, capsys):
        ws = self._workspace(tmp_path, {"ghcr.io/x:2.0.0"}, {"ghcr.io/x:1.0.0"})
        assert main(["--workspace-folder", str(ws), "--verify-refs"]) == 1
        err = capsys.readouterr().err
        assert REGEN_COMMAND in err
        assert "ghcr.io/x:2.0.0" in err and "ghcr.io/x:1.0.0" in err
