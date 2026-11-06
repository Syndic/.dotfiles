"""tests/run's `image:` parser, which the pin guards in test_config_layout.py share."""

import pytest
from tests_run import image_lines

REF = "repo/name:latest@sha256:0123abcd"


def _parse(tmp_path, text):
    path = tmp_path / "molecule.yml"
    path.write_text(text)
    return list(image_lines(path))


@pytest.mark.parametrize(
    "line",
    [
        f"    image: {REF}",
        f"  - image: {REF}",
        f'    image: "{REF}"',
        f"    image: '{REF}'",
        f"    image: {REF}  # trailing comment",
    ],
)
def test_block_style_forms_parse(tmp_path, line):
    assert [i.ref for i in _parse(tmp_path, f"platforms:\n{line}\n")] == [REF]


def test_reports_line_number_and_previous_line(tmp_path):
    (line,) = _parse(tmp_path, f"platforms:\n  # renovate: x\n  image: {REF}\n")
    assert (line.lineno, line.prev) == (3, "  # renovate: x")


def test_ignores_comments_and_other_image_keys(tmp_path):
    text = "  # Preconfigured molecule image: debian\n  pre_build_image: true\n  image_name: x\n"
    assert _parse(tmp_path, text) == []


@pytest.mark.parametrize(
    "text",
    [
        f"platforms: [{{name: x, image: {REF}}}]\n",
        f"  image:\n    {REF}\n",
        f"  image: &base {REF}\n",
        "  image: *base\n",
        f"  image: \"{REF}'\n",
    ],
)
def test_unsupported_forms_raise(tmp_path, text):
    with pytest.raises(ValueError, match="unsupported `image:` form"):
        _parse(tmp_path, text)
