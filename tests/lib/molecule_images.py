"""The one parser for molecule scenarios' `image:` lines, shared by
tests/run (pre-pull) and the pytest pin guards so they can't disagree.

Runs under the frozen 3.9 (pytest) as well as tests/run's interpreter.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, NamedTuple

# Block style only: `image: ref` / `- image: ref`, optionally quoted, optional trailing comment.
_IMAGE_LINE = re.compile(r"""^\s*(?:-\s+)?image:\s*(["']?)([^"'\s#]+)\1\s*(?:#.*)?$""")
_IMAGE_KEY = re.compile(r"\bimage\s*:")


class ImageLine(NamedTuple):
    lineno: int
    prev: str
    ref: str


def image_lines(path: Path) -> Iterator[ImageLine]:
    """Yield every `image:` in a molecule.yml. Raises ValueError on an `image:`
    key in any other form (flow style, anchor/alias, value on the next line),
    so a new form fails loudly instead of being skipped."""
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#") or not _IMAGE_KEY.search(line):
            continue
        m = _IMAGE_LINE.match(line)
        if not m or m.group(2)[0] in "*&":
            raise ValueError(f"{path}:{i + 1}: unsupported `image:` form: {line.strip()}")
        yield ImageLine(i + 1, lines[i - 1] if i else "", m.group(2))
