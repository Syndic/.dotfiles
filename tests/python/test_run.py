"""Tests for phase2.run — the subprocess wrapper that pins check=True and
forwards kwargs. Uses true/false/echo, which exist on both macOS and the
Ubuntu CI runner."""
import subprocess

import pytest

import phase2


def test_run_returns_completed_process_on_success():
    result = phase2.run(["true"])
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0


def test_run_raises_on_nonzero_exit():
    with pytest.raises(subprocess.CalledProcessError):
        phase2.run(["false"])


def test_run_forwards_kwargs_to_subprocess():
    result = phase2.run(["echo", "hello"], capture_output=True, text=True)
    assert result.stdout == "hello\n"
