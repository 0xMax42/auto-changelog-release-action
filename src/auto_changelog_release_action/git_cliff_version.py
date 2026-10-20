"""Read the git-cliff version pinned for the action and its golden-file tests."""

from __future__ import annotations

import re
from pathlib import Path

VERSION_FILE_NAME = "versions.gitcliff.env"
_VERSION_PATTERN = re.compile(
    r'^GIT_CLIFF_VERSION="v(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)"$',
    re.MULTILINE,
)


def read_git_cliff_version(path: Path) -> str:
    """Read a Renovate-managed version file, failing on missing or invalid pins."""
    match = _VERSION_PATTERN.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"Missing or invalid GIT_CLIFF_VERSION in {path}")
    return match.group("version")
