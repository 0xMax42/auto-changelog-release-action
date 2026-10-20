"""Regression tests for the cached upstream git-cliff test dependency."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from scripts import ensure_git_cliff as installer


def _release_archive(payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo(f"git-cliff-{installer.GIT_CLIFF_VERSION}/git-cliff")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    return buffer.getvalue()


def test_ensure_git_cliff_reuses_valid_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binary = tmp_path / "git-cliff"
    binary.write_bytes(b"cached")
    monkeypatch.setattr(installer, "GIT_CLIFF_BINARY", binary)
    monkeypatch.setattr(installer, "_version_matches", lambda candidate: candidate == binary)

    def unexpected_download(*args: object, **kwargs: object) -> None:
        raise AssertionError("A valid cache must not trigger a download")

    monkeypatch.setattr(installer.urllib.request, "urlopen", unexpected_download)
    assert installer.ensure_git_cliff() == binary


def test_ensure_git_cliff_replaces_invalid_cache_and_reuses_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binary = tmp_path / "cache" / "git-cliff"
    binary.parent.mkdir()
    binary.write_bytes(b"outdated")
    monkeypatch.setattr(installer, "GIT_CLIFF_BINARY", binary)
    monkeypatch.setattr(
        installer,
        "_version_matches",
        lambda candidate: candidate.is_file() and candidate.read_bytes() == b"upstream",
    )

    archive = _release_archive(b"upstream")
    requests: list[str] = []

    def fake_download(url: str, *, timeout: int) -> io.BytesIO:
        assert timeout == 60
        requests.append(url)
        return io.BytesIO(archive)

    monkeypatch.setattr(installer.urllib.request, "urlopen", fake_download)

    assert installer.ensure_git_cliff() == binary
    assert binary.read_bytes() == b"upstream"
    assert installer.ensure_git_cliff() == binary
    assert requests == [installer.ARCHIVE_URL]
