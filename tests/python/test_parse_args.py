"""Tests for phase2.parse_args — the --host argument parser."""
import sys
import pytest

import phase2


def test_with_host(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["phase2.py", "--host", "laptop24"])
    args = phase2.parse_args()
    assert args.host == "laptop24"


def test_without_host(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["phase2.py"])
    args = phase2.parse_args()
    assert args.host is None


def test_unknown_arg_exits(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["phase2.py", "--unknown"])
    with pytest.raises(SystemExit) as exc:
        phase2.parse_args()
    assert exc.value.code == 2  # argparse convention for usage errors
