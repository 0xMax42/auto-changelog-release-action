from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from auto_changelog_release_action import install_git_cliff as installer


def test_install_git_cliff_requires_explicit_version() -> None:
    with pytest.raises(ValueError, match="explicit git-cliff version"):
        installer.install_git_cliff("")


def test_release_url_always_uses_tag() -> None:
    assert installer.resolve_release_url("2.14.2") == (
        "https://api.github.com/repos/orhun/git-cliff/releases/tags/v2.14.2"
    )


def test_install_git_cliff_returns_installed_binary_when_old_one_is_first_in_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    old_binary = old_dir / "git-cliff"
    old_binary.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'git-cliff 2.10.1'\n",
        encoding="utf-8",
    )
    old_binary.chmod(0o755)
    monkeypatch.setenv("PATH", f"{old_dir}{os.pathsep}{os.environ['PATH']}")

    def fake_extract(_archive: Path, destination: Path) -> None:
        binary = destination / "git-cliff"
        binary.write_text(
            "#!/bin/sh\nprintf '%s\\n' 'git-cliff 2.14.2'\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)

    monkeypatch.setattr(
        installer, "fetch_release_info", lambda _version: {"tag_name": "v2.14.2"}
    )
    monkeypatch.setattr(
        installer, "select_asset_url", lambda *_args: "https://example.invalid/git-cliff.tar.gz"
    )
    monkeypatch.setattr(installer, "download_file", lambda *_args: None)
    monkeypatch.setattr(installer, "extract_archive", fake_extract)

    install_dir = tmp_path / "installed"
    executable = installer.install_git_cliff("2.14.2", install_dir=str(install_dir))

    assert executable == (install_dir / "git-cliff").resolve()
    assert installer.get_git_cliff_version(executable) == "2.14.2"
    assert shutil.which("git-cliff") == str(old_binary)


def test_install_git_cliff_uses_existing_binary_without_fetching(
    tmp_path: Path,
    monkeypatch,
) -> None:
    binary_path = tmp_path / "git-cliff"
    binary_path.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'git-cliff 2.10.1'\n",
        encoding="utf-8",
    )
    binary_path.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(
        installer,
        "fetch_release_info",
        lambda _version: (_ for _ in ()).throw(AssertionError("GitHub must not be queried")),
    )

    result = installer.install_git_cliff("2.10.1")

    assert result == binary_path.resolve()
