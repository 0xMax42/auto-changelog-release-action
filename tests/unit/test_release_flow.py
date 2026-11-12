from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest

from auto_changelog_release_action.release_flow import (
    ReleaseConfig,
    create_release,
    extract_release_notes,
    is_configured_prerelease_version,
    release_api_body,
)
from auto_changelog_release_action.runtime_host import RuntimeHost


def test_extract_release_notes_matches_current_heading_behavior() -> None:
    changelog_text = (
        "# Changelog\n\n"
        "## [1.2.3] (https://example.invalid/compare/v1.2.2..v1.2.3) - 2026-05-10\n"
        "- Added feature\n\n"
        "## [1.2.2] - 2026-05-01\n"
        "- Previous release\n"
    )

    notes = extract_release_notes(changelog_text, "1.2.3")

    assert notes == "[1.2.3] - 2026-05-10\n- Added feature\n\n"


def test_release_api_body_skips_heading_line() -> None:
    notes = "[1.2.3]\n- Added feature\n\n"

    assert release_api_body(notes) == "- Added feature\n\n"


def test_is_configured_prerelease_version_uses_allowed_labels_only() -> None:
    assert is_configured_prerelease_version("1.2.3-pre.1") is True
    assert is_configured_prerelease_version("1.2.3-alpha.2") is True
    assert is_configured_prerelease_version("1.2.3-beta") is True
    assert is_configured_prerelease_version("1.2.3-miktex.26.2") is False
    assert is_configured_prerelease_version("1.2.3") is False


def test_create_release_requires_explicit_publish_token(tmp_path: Path) -> None:
    config = ReleaseConfig(
        changelog_file=tmp_path / "CHANGELOG.md",
        cliff_config=tmp_path / "cliff.toml",
        version="1.2.3",
        git_branch="main",
        api_url="https://api.github.com",
        repository_owner="actions",
        repository_name="auto-changelog-release-action",
        publish_token="",
    )

    try:
        create_release(config, "[1.2.3]\n- Added feature\n", prerelease=False)
    except RuntimeError as error:
        assert str(error) == "Release publishing requires the explicit token input."
    else:
        raise AssertionError("expected explicit token error")


def test_create_release_requires_api_url(tmp_path: Path) -> None:
    config = ReleaseConfig(
        changelog_file=tmp_path / "CHANGELOG.md",
        cliff_config=tmp_path / "cliff.toml",
        version="1.2.3",
        git_branch="main",
        api_url="",
        repository_owner="actions",
        repository_name="auto-changelog-release-action",
        publish_token="test-token",
    )

    try:
        create_release(config, "[1.2.3]\n- Added feature\n", prerelease=False)
    except RuntimeError as error:
        assert str(error) == "Release API URL is not set"
    else:
        raise AssertionError("expected missing api url error")


@pytest.mark.parametrize(
    ("host", "trigger_release_workflows", "includes_trigger_workflows"),
    [
        (RuntimeHost.GITEA, True, True),
        (RuntimeHost.GITEA, False, False),
        (RuntimeHost.GITHUB, True, False),
    ],
)
def test_create_release_uses_host_aware_payload_and_normalized_endpoint(
    monkeypatch,
    tmp_path: Path,
    host: RuntimeHost,
    trigger_release_workflows: bool,
    includes_trigger_workflows: bool,
) -> None:
    config = ReleaseConfig(
        changelog_file=tmp_path / "CHANGELOG.md",
        cliff_config=tmp_path / "cliff.toml",
        version="1.2.3",
        git_branch="main",
        api_url="https://api.example.invalid/",
        repository_owner="actions",
        repository_name="auto-changelog-release-action",
        publish_token="test-token",
        host=host,
        trigger_release_workflows=trigger_release_workflows,
    )
    captured: dict[str, Any] = {}

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def getcode(self) -> int:
            return 201

        def read(self) -> bytes:
            return b'{"ok": true}'

    def fake_urlopen(request):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["content_type"] = request.get_header("Content-type")
        captured["method"] = request.get_method()
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    created = create_release(config, "[1.2.3]\n- Added feature\n", prerelease=False)

    assert created is True

    expected_payload = {
        "tag_name": "v1.2.3",
        "target_commitish": "main",
        "name": "Release v1.2.3",
        "body": "- Added feature\n",
        "draft": False,
        "prerelease": False,
    }
    if includes_trigger_workflows:
        expected_payload["trigger_workflows"] = True

    assert captured == {
        "url": "https://api.example.invalid/repos/actions/auto-changelog-release-action/releases",
        "authorization": "token test-token",
        "content_type": "application/json",
        "method": "POST",
        "payload": expected_payload,
    }


def test_create_release_returns_false_when_release_already_exists(
    monkeypatch, tmp_path: Path
) -> None:
    config = ReleaseConfig(
        changelog_file=tmp_path / "CHANGELOG.md",
        cliff_config=tmp_path / "cliff.toml",
        version="1.2.3",
        git_branch="main",
        api_url="https://api.example.invalid",
        repository_owner="actions",
        repository_name="auto-changelog-release-action",
        publish_token="test-token",
    )

    def fake_urlopen(_request):
        raise HTTPError(
            url="https://api.example.invalid/repos/actions/auto-changelog-release-action/releases",
            code=409,
            msg="Conflict",
            hdrs=None,
            fp=io.BytesIO(b'{"message": "release exists"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    created = create_release(config, "[1.2.3]\n- Added feature\n", prerelease=False)

    assert created is False


@pytest.mark.parametrize(
    ("host", "existing_tag", "expected_calls", "expected_result"),
    [
        (RuntimeHost.GITHUB, "v1.2.3", ["POST", "GET"], False),
        (RuntimeHost.GITHUB, "v9.9.9", ["POST", "GET"], None),
        (RuntimeHost.GITHUB, None, ["POST", "GET"], None),
        (RuntimeHost.GITEA, "v1.2.3", ["POST"], None),
    ],
)
def test_create_release_handles_github_422_only_for_existing_tag(
    monkeypatch,
    tmp_path: Path,
    host: RuntimeHost,
    existing_tag: str | None,
    expected_calls: list[str],
    expected_result: bool | None,
) -> None:
    config = ReleaseConfig(
        changelog_file=tmp_path / "CHANGELOG.md",
        cliff_config=tmp_path / "cliff.toml",
        version="1.2.3",
        git_branch="main",
        api_url="https://api.example.invalid",
        repository_owner="actions",
        repository_name="auto-changelog-release-action",
        publish_token="test-token",
        host=host,
    )
    calls: list[str] = []

    def fake_urlopen(request):
        calls.append(request.get_method())
        if request.get_method() == "POST":
            raise HTTPError(
                url=request.full_url,
                code=422,
                msg="Validation Failed",
                hdrs=None,
                fp=io.BytesIO(b'{"message": "Validation Failed"}'),
            )
        assert request.full_url.endswith("/releases/tags/v1.2.3")
        assert request.get_header("Authorization") == "token test-token"
        if existing_tag is None:
            raise HTTPError(
                url=request.full_url,
                code=404,
                msg="Not Found",
                hdrs=None,
                fp=io.BytesIO(b'{"message": "Not Found"}'),
            )
        return io.BytesIO(json.dumps({"tag_name": existing_tag}).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    if expected_result is None:
        with pytest.raises(RuntimeError, match="Giving up"):
            create_release(config, "[1.2.3]\n- Added feature\n", prerelease=False, max_attempts=1)
    else:
        assert (
            create_release(config, "[1.2.3]\n- Added feature\n", prerelease=False, max_attempts=1)
            is expected_result
        )

    assert calls == expected_calls
