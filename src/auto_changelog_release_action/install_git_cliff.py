"""Downloads, extracts, and installs the git-cliff binary for the current runner."""

from __future__ import annotations

import json
import lzma
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_ARCH_OS = "x86_64-unknown-linux-gnu"
DEFAULT_INSTALL_DIR = "/usr/local/bin"
REPO = "orhun/git-cliff"
VERSION_PATTERN = re.compile(r"^git-cliff\s+(\S+)$")


def resolve_release_url(version: str) -> str:
    """Build the GitHub API URL for the requested git-cliff version."""

    return f"https://api.github.com/repos/{REPO}/releases/tags/v{version}"


def fetch_release_info(version: str) -> dict[str, object]:
    """Fetch git-cliff release metadata from the GitHub API."""

    api_url = resolve_release_url(version)
    print(f"🔍 Fetching release info ({api_url})…")
    with urllib.request.urlopen(api_url) as response:
        return json.loads(response.read().decode("utf-8"))


def select_asset_url(release_info: dict[str, object], arch_os: str) -> str:
    """Select the first archive asset matching the requested runner architecture."""

    assets = release_info.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError(f"❌ Matching asset not found for architecture {arch_os}")

    for asset in assets:
        if not isinstance(asset, dict):
            continue
        url = asset.get("browser_download_url")
        if not isinstance(url, str):
            continue
        if arch_os not in url:
            continue
        if url.endswith((".tar.gz", ".tgz", ".tar.xz", ".zip")):
            return url
    raise RuntimeError(f"❌ Matching asset not found for architecture {arch_os}")


def download_file(url: str, target_path: Path) -> None:
    """Download a file to disk."""

    with urllib.request.urlopen(url) as response, open(target_path, "wb") as handle:
        shutil.copyfileobj(response, handle)


def get_git_cliff_version(binary_path: str | Path) -> str:
    """Return the version reported by a git-cliff binary."""

    completed = subprocess.run(
        [str(binary_path), "--version"],
        check=True,
        text=True,
        capture_output=True,
    )
    match = VERSION_PATTERN.fullmatch(completed.stdout.strip())
    if match is None:
        raise RuntimeError(f"❌ Unexpected git-cliff version output: {completed.stdout!r}")
    return match.group(1)


def extract_archive(archive_path: Path, destination: Path) -> None:
    """Extract a supported release archive into a directory."""

    if archive_path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(destination)
        return
    if archive_path.name.endswith(".tar.xz"):
        with (
            lzma.open(archive_path, "rb") as compressed,
            tarfile.open(
                fileobj=compressed,
                mode="r:",
            ) as archive,
        ):
            archive.extractall(destination)
        return
    if archive_path.name.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(destination)
        return
    raise RuntimeError(f"❌ Unknown archive format: {archive_path.name}")


def find_executable(root: Path, name: str) -> Path:
    """Find an executable file by name inside an extracted archive."""

    for path in root.rglob(name):
        if path.is_file() and os.access(path, os.X_OK):
            return path
    raise RuntimeError("❌ Binary not found")


def install_binary(source_path: Path, install_dir: Path) -> None:
    """Install the git-cliff binary directly or via sudo when needed."""

    target_path = install_dir / "git-cliff"
    parent_dir = install_dir if install_dir.exists() else install_dir.parent

    if os.access(parent_dir, os.W_OK):
        install_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        target_path.chmod(target_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return

    if shutil.which("sudo"):
        subprocess.run(["sudo", "mkdir", "-p", str(install_dir)], check=True)
        subprocess.run(["sudo", "install", "-m755", str(source_path), str(target_path)], check=True)
        return

    raise RuntimeError(f"❌ Cannot write to {install_dir} and sudo is not available")


def install_git_cliff(
    version: str,
    *,
    arch_os: str = DEFAULT_ARCH_OS,
    install_dir: str = DEFAULT_INSTALL_DIR,
) -> Path:
    """Return the executable path for the requested git-cliff version."""

    if not version:
        raise ValueError("An explicit git-cliff version is required")

    existing_binary = shutil.which("git-cliff")
    if existing_binary:
        existing_version = get_git_cliff_version(existing_binary)
        if existing_version == version:
            print(f"✅ Using existing git-cliff {existing_version} at {existing_binary}")
            return Path(existing_binary).resolve()

    release_info = fetch_release_info(version)
    resolved_version = str(release_info["tag_name"])
    asset_url = select_asset_url(release_info, arch_os)
    asset_name = asset_url.rsplit("/", 1)[-1]

    print(f"📦 Downloading git-cliff {resolved_version} ({asset_name}) …")
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        archive_path = temp_dir / asset_name
        download_file(asset_url, archive_path)
        extract_archive(archive_path, temp_dir)
        binary_path = find_executable(temp_dir, "git-cliff")
        install_binary(binary_path, Path(install_dir))

    installed_binary = Path(install_dir) / "git-cliff"
    installed_version = get_git_cliff_version(installed_binary)
    if installed_version != version:
        raise RuntimeError(f"Expected git-cliff {version}, got {installed_version}")
    print(f"✅ git-cliff {installed_version} installed in {install_dir}")
    return installed_binary.resolve()
