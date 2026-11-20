"""Tests for phase2.resolve_host_profile — the interactive profile picker."""
import io
import sys
import pytest

import phase2


@pytest.fixture
def fake_dotfiles(tmp_path, monkeypatch):
    """Create a tmpdir with three host profiles and point phase2.DOTFILES_DIR
    at it. Returns the path to host_vars/ for additional test setup."""
    host_vars = tmp_path / "host_vars"
    host_vars.mkdir()
    for name in ("stubbed_host_1", "stubbed_host_2", "stubbed_host_3"):
        (host_vars / f"{name}.yml").write_text("")
    monkeypatch.setattr(phase2, "DOTFILES_DIR", tmp_path)
    return host_vars


def feed_tty(monkeypatch, *inputs):
    """Pretend stdin is a tty with the given lines queued up."""
    payload = "\n".join(inputs) + ("\n" if inputs else "")
    stream = io.StringIO(payload)
    stream.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", stream)


def feed_no_tty(monkeypatch):
    """Pretend stdin is not a tty (the curl|bash pipe state)."""
    stream = io.StringIO("")
    stream.isatty = lambda: False
    monkeypatch.setattr(sys, "stdin", stream)


def test_host_arg_short_circuits(fake_dotfiles):
    # A valid --host bypasses the interactive prompt entirely (no tty needed).
    assert phase2.resolve_host_profile("stubbed_host_2") == "stubbed_host_2"


def test_host_arg_unknown_dies_with_available_list(fake_dotfiles, capsys):
    # A typo'd --host must fail loudly: otherwise it reaches
    # `ansible-playbook --limit <typo>` and produces "skipping: no hosts
    # matched" with exit 0, masking a no-op install.
    with pytest.raises(SystemExit) as exc:
        phase2.resolve_host_profile("typo")
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "No host profile named 'typo'" in err
    for name in ("stubbed_host_1", "stubbed_host_2", "stubbed_host_3"):
        assert name in err


def test_host_arg_unknown_with_no_profiles_dies(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(phase2, "DOTFILES_DIR", tmp_path)
    with pytest.raises(SystemExit) as exc:
        phase2.resolve_host_profile("anything")
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "No host profile named 'anything'" in err
    assert "no host_vars/ profiles found" in err


def test_numeric_selection(fake_dotfiles, monkeypatch):
    feed_tty(monkeypatch, "2")
    assert phase2.resolve_host_profile(None) == "stubbed_host_2"


def test_name_selection(fake_dotfiles, monkeypatch):
    feed_tty(monkeypatch, "stubbed_host_3")
    assert phase2.resolve_host_profile(None) == "stubbed_host_3"


def test_typo_then_out_of_range_then_valid(fake_dotfiles, monkeypatch):
    feed_tty(monkeypatch, "nope", "0", "9", "3")
    assert phase2.resolve_host_profile(None) == "stubbed_host_3"


def test_empty_input_reprompts(fake_dotfiles, monkeypatch):
    feed_tty(monkeypatch, "", "  ", "1")
    assert phase2.resolve_host_profile(None) == "stubbed_host_1"


def test_eof_dies(fake_dotfiles, monkeypatch):
    feed_tty(monkeypatch)  # empty stream
    with pytest.raises(SystemExit) as exc:
        phase2.resolve_host_profile(None)
    assert exc.value.code == 1


def test_no_tty_dies_with_helpful_message(fake_dotfiles, monkeypatch, capsys):
    feed_no_tty(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        phase2.resolve_host_profile(None)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "no terminal available" in err
    assert "--host PROFILE" in err


def test_no_profiles_dies(tmp_path, monkeypatch):
    # No host_vars/ at all
    monkeypatch.setattr(phase2, "DOTFILES_DIR", tmp_path)
    with pytest.raises(SystemExit) as exc:
        phase2.resolve_host_profile(None)
    assert exc.value.code == 1


def test_empty_host_vars_dies(tmp_path, monkeypatch):
    # host_vars/ exists but contains nothing valid
    host_vars = tmp_path / "host_vars"
    host_vars.mkdir()
    (host_vars / "README.md").write_text("only junk")
    monkeypatch.setattr(phase2, "DOTFILES_DIR", tmp_path)
    with pytest.raises(SystemExit) as exc:
        phase2.resolve_host_profile(None)
    assert exc.value.code == 1
