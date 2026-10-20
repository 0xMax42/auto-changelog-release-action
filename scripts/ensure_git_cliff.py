"""Cache the official git-cliff binary for the golden-file tests."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

GIT_CLIFF_VERSION = "2.14.2"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
GIT_CLIFF_BINARY = (
    PROJECT_ROOT / ".cache" / "tools" / "git-cliff" / GIT_CLIFF_VERSION / "git-cliff"
)
ARCHIVE_URL = (
    f"https://github.com/orhun/git-cliff/releases/download/v{GIT_CLIFF_VERSION}/"
    f"git-cliff-{GIT_CLIFF_VERSION}-x86_64-unknown-linux-gnu.tar.gz"
)


def _version_matches(binary: Path) -> bool:
    if not binary.is_file():
        return False
    try:
        result = subprocess.run(
            [str(binary), "--version"], check=True, capture_output=True, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return result.stdout.strip() == f"git-cliff {GIT_CLIFF_VERSION}"


def ensure_git_cliff() -> Path:
    """Reuse the cached binary or download the upstream Linux x86_64 release."""
    if _version_matches(GIT_CLIFF_BINARY):
        print(f"Using cached git-cliff {GIT_CLIFF_VERSION}: {GIT_CLIFF_BINARY}")
        return GIT_CLIFF_BINARY

    if sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("Golden tests require the Linux x86_64 git-cliff release")

    GIT_CLIFF_BINARY.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".git-cliff-", dir=GIT_CLIFF_BINARY.parent) as d:
        temporary = Path(d)
        archive_path = temporary / "git-cliff.tar.gz"
        print(f"Downloading git-cliff {GIT_CLIFF_VERSION} from {ARCHIVE_URL}")
        with urllib.request.urlopen(ARCHIVE_URL, timeout=60) as response:
            with archive_path.open("wb") as archive_file:
                shutil.copyfileobj(response, archive_file)

        with tarfile.open(archive_path, mode="r:gz") as archive:
            binaries = [
                member
                for member in archive.getmembers()
                if member.isfile() and Path(member.name).name == "git-cliff"
            ]
            if len(binaries) != 1:
                raise RuntimeError("Expected exactly one git-cliff binary in release archive")
            source = archive.extractfile(binaries[0])
            if source is None:
                raise RuntimeError("Could not read git-cliff from release archive")
            candidate = temporary / "git-cliff"
            with source, candidate.open("wb") as output:
                shutil.copyfileobj(source, output)

        candidate.chmod(0o755)
        if not _version_matches(candidate):
            raise RuntimeError("Downloaded git-cliff failed its version check")
        candidate.replace(GIT_CLIFF_BINARY)

    print(f"Cached git-cliff {GIT_CLIFF_VERSION}: {GIT_CLIFF_BINARY}")
    return GIT_CLIFF_BINARY


if __name__ == "__main__":
    try:
        ensure_git_cliff()
    except (OSError, RuntimeError, tarfile.TarError) as error:
        sys.exit(f"Could not prepare git-cliff {GIT_CLIFF_VERSION}: {error}")
