"""tests/run: image selection, role resolution, and argv dispatch."""

import sys

import pytest

import tests_run

REPO = "ghcr.io/example/homebrew-molecule"
DIGEST_REF = "repo/name:latest@sha256:0123abcd"


@pytest.fixture(autouse=True)
def _no_image_env(monkeypatch):
    monkeypatch.delenv("MOLECULE_HOMEBREW_IMAGE", raising=False)
    monkeypatch.delenv("MOLECULE_HOMEBREW_IMAGE_REPO", raising=False)


@pytest.fixture
def tag_script(tmp_path, monkeypatch):
    """Point HOMEBREW_IMAGE_DIR at a tmp dir; returns a writer for its image-tag.sh."""
    monkeypatch.setattr(tests_run, "HOMEBREW_IMAGE_DIR", tmp_path)

    def write(body: str) -> None:
        script = tmp_path / "image-tag.sh"
        script.write_text(f"#!/bin/sh\n{body}\n")
        script.chmod(0o755)

    return write


# published_homebrew_image ----------------------------------------------------


def test_published_image_is_none_without_env():
    assert tests_run.published_homebrew_image() is None


def test_full_image_override_wins_over_repo(monkeypatch, tag_script):
    tag_script("exit 1")  # never consulted
    monkeypatch.setenv("MOLECULE_HOMEBREW_IMAGE", f"  {REPO}:sha-abc123 ")
    monkeypatch.setenv("MOLECULE_HOMEBREW_IMAGE_REPO", REPO)
    assert tests_run.published_homebrew_image() == f"{REPO}:sha-abc123"


def test_repo_is_tagged_with_the_tag_script_output(monkeypatch, tag_script):
    tag_script("echo dockerfile-0123456789ab")
    monkeypatch.setenv("MOLECULE_HOMEBREW_IMAGE_REPO", REPO)
    assert tests_run.published_homebrew_image() == f"{REPO}:dockerfile-0123456789ab"


def test_blank_override_falls_through_to_repo(monkeypatch, tag_script):
    tag_script("echo t")
    monkeypatch.setenv("MOLECULE_HOMEBREW_IMAGE", "  ")
    monkeypatch.setenv("MOLECULE_HOMEBREW_IMAGE_REPO", REPO)
    assert tests_run.published_homebrew_image() == f"{REPO}:t"


def test_failing_tag_script_warns_and_builds(monkeypatch, tag_script, capsys):
    tag_script("exit 3")
    monkeypatch.setenv("MOLECULE_HOMEBREW_IMAGE_REPO", REPO)
    assert tests_run.published_homebrew_image() is None
    assert "can't compute the homebrew image tag" in capsys.readouterr().err


def test_missing_tag_script_warns_and_builds(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(tests_run, "HOMEBREW_IMAGE_DIR", tmp_path)
    monkeypatch.setenv("MOLECULE_HOMEBREW_IMAGE_REPO", REPO)
    assert tests_run.published_homebrew_image() is None
    assert "can't compute the homebrew image tag" in capsys.readouterr().err


# molecule_role_images ---------------------------------------------------------


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """A REPO_ROOT whose roles' scenarios use the given image refs."""
    monkeypatch.setattr(tests_run, "REPO_ROOT", tmp_path)

    def scenario(role: str, name: str, *images: str) -> None:
        d = tmp_path / "roles" / role / "molecule" / name
        d.mkdir(parents=True)
        d.joinpath("molecule.yml").write_text(
            "platforms:\n" + "".join(f"  - name: {name}\n    image: {i}\n" for i in images)
        )

    return scenario


def test_role_images_are_the_digest_pinned_refs_deduplicated(fake_repo):
    fake_repo("apt", "default", DIGEST_REF)
    fake_repo("apt", "empty_groups", DIGEST_REF, "other/image:1@sha256:feed")
    assert tests_run.molecule_role_images("apt") == ["other/image:1@sha256:feed", DIGEST_REF]


def test_role_images_skip_local_tags(fake_repo):
    fake_repo("homebrew", "default", "dotfiles-homebrew-molecule:local")
    assert tests_run.molecule_role_images("homebrew") == []


def test_homebrew_images_add_the_published_image(fake_repo, monkeypatch):
    fake_repo("homebrew", "default", "dotfiles-homebrew-molecule:local")
    monkeypatch.setenv("MOLECULE_HOMEBREW_IMAGE", f"{REPO}:t")
    assert tests_run.molecule_role_images("homebrew") == [f"{REPO}:t"]


def test_only_homebrew_gets_the_published_image(fake_repo, monkeypatch):
    fake_repo("apt", "default", DIGEST_REF)
    monkeypatch.setenv("MOLECULE_HOMEBREW_IMAGE", f"{REPO}:t")
    assert tests_run.molecule_role_images("apt") == [DIGEST_REF]


def test_real_scenarios_parse():
    """Every role's real molecule.yml goes through the parser without raising."""
    for role in tests_run.MOLECULE_ROLES:
        assert all("@sha256:" in i for i in tests_run.molecule_role_images(role))


# molecule_roles ---------------------------------------------------------------


def test_molecule_roles_defaults_to_every_role():
    assert tests_run.molecule_roles(None) == tests_run.MOLECULE_ROLES


def test_molecule_roles_narrows_to_a_known_role():
    assert tests_run.molecule_roles("apt") == ["apt"]


def test_molecule_roles_dies_on_an_unknown_role(capsys):
    with pytest.raises(SystemExit) as exc:
        tests_run.molecule_roles("nope")
    assert exc.value.code == 1
    assert "unknown molecule role: nope" in capsys.readouterr().err


# pull_images ------------------------------------------------------------------


def test_pull_images_pulls_each_image_once_and_returns_the_worst_rc(monkeypatch):
    images = {"a": ["x@sha256:1", "y@sha256:2"], "b": ["x@sha256:1"]}
    monkeypatch.setattr(tests_run, "MOLECULE_ROLES", list(images))
    monkeypatch.setattr(tests_run, "molecule_role_images", images.__getitem__)
    pulled = []

    class FakePopen:
        def __init__(self, argv):
            pulled.append(argv)
            self.rc = 2 if argv[-1] == "y@sha256:2" else 0

        def wait(self):
            return self.rc

    monkeypatch.setattr(tests_run.subprocess, "Popen", FakePopen)
    assert tests_run.pull_images(None) == 2
    assert pulled == [["docker", "pull", "-q", "x@sha256:1"], ["docker", "pull", "-q", "y@sha256:2"]]


# main -------------------------------------------------------------------------


@pytest.fixture
def pulls(monkeypatch):
    calls = []
    monkeypatch.setattr(tests_run, "pull_images", lambda role: calls.append(role) or 7)
    return calls


@pytest.mark.parametrize(
    "argv,role",
    [(["pull"], None), (["pull", "apt"], "apt"), (["pull", "apt", "extra"], "apt")],
)
def test_main_dispatches_pull(pulls, argv, role):
    assert tests_run.main(argv) == 7
    assert pulls == [role]


def test_main_python_runs_both_pytest_runs_in_parallel(monkeypatch):
    calls = []
    monkeypatch.setattr(tests_run, "run_parallel", lambda suites: calls.append(suites) or 0)
    assert tests_run.main(["python"]) == 0
    (suites,) = calls
    assert [s.name for s in suites] == ["python:runtime", "python:tooling"]
    # The tooling run must share tests/run's interpreter, which is what can load it.
    assert suites[1].argv[:3] == [sys.executable, "-m", "pytest"]
    caches = [arg for s in suites for arg in s.argv if arg.startswith("cache_dir=")]
    assert len(caches) == len(set(caches)) == 2, "parallel runs would overwrite one cache"


def test_main_rejects_unknown_argv(capsys):
    assert tests_run.main(["nope"]) == 2
    assert capsys.readouterr().err.startswith("usage:")
