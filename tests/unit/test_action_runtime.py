from __future__ import annotations

from pathlib import Path

import pytest

from auto_changelog_release_action import action_runtime
from auto_changelog_release_action.git_cliff_version import VERSION_FILE_NAME
from auto_changelog_release_action.release_flow import ReleaseFlowResult
from auto_changelog_release_action.runtime_host import RuntimeHost
from auto_changelog_release_action.version_bump_flow import VersionBumpResult
from auto_changelog_release_action.version_change_flow import VersionChangeResult
from auto_changelog_release_action.versioning import default_version_regex_for_file


@pytest.fixture(autouse=True)
def pinned_git_cliff_version(tmp_path: Path) -> None:
    """Provide the action's version pin for runtime tests."""
    (tmp_path / VERSION_FILE_NAME).write_text(
        'GIT_CLIFF_VERSION="v2.14.2"\n', encoding="utf-8"
    )


def clear_runtime_environment(monkeypatch) -> None:
    """Remove host-related environment variables so tests are hermetic in CI."""

    for name in (
        "GITHUB_API_URL",
        "GITEA_API_URL",
        "GITHUB_SERVER_URL",
        "GITEA_SERVER_URL",
        "GITHUB_REPOSITORY",
        "GITEA_REPOSITORY",
        "GITHUB_REF",
        "GITEA_REF",
        "TRIGGER_RELEASE_WORKFLOWS",
        "COMMIT_UNRELEASED_CHANGELOG",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("pattern_kind", ("major", "minor", "patch"))
@pytest.mark.parametrize(
    ("version_file", "version_regex", "file_contents"),
    [
        ("VERSION", "", "0.0.0\n"),
        (
            "pyproject.toml",
            r'^version\s*=\s*"([^"]+)"',
            '[tool.poetry]\nversion = "0.0.0"\n',
        ),
    ],
)
def test_run_action_runtime_skips_zero_version_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pattern_kind: str,
    version_file: str,
    version_regex: str,
    file_contents: str,
) -> None:
    (tmp_path / version_file).write_text(file_contents, encoding="utf-8")
    github_output = tmp_path / "github_output.txt"
    github_env = tmp_path / "github_env.txt"
    config = action_runtime.ActionRuntimeConfig(
        action_path=tmp_path,
        host=RuntimeHost.GITEA,
        api_url="https://git.example.invalid/api/v1",
        server_url="https://git.example.invalid",
        repository="owner/repo",
        git_ref="refs/heads/main",
        github_output=str(github_output),
        github_env=str(github_env),
        author_name="CI Bot",
        author_email="ci@example.invalid",
        allow_non_main_release=False,
        version_file=version_file,
        version_regex=version_regex,
        major_patterns=".*" if pattern_kind == "major" else "",
        minor_patterns=".*" if pattern_kind == "minor" else "",
        patch_patterns=".*" if pattern_kind == "patch" else "",
        git_cliff_offline=True,
        revision_range="before..after",
        github_event_before="before",
        github_sha="after",
        release_publish_token="token",
        commit_unreleased_changelog=True,
    )
    monkeypatch.chdir(tmp_path)

    def unexpected(*_args, **_kwargs) -> None:
        raise AssertionError("The 0.0.0 guard must skip the release pipeline")

    for name in (
        "configure_git_author",
        "run_version_bump",
        "run_version_change_detection",
        "ensure_cliff_config",
        "install_git_cliff",
        "run_release_flow",
        "run_unreleased_changelog_flow",
    ):
        monkeypatch.setattr(action_runtime, name, unexpected)

    action_runtime.run_action_runtime(config)

    assert github_output.read_text(encoding="utf-8") == (
        "version_bumped=false\n"
        "version_changed=false\n"
        "release_created=false\n"
        "release_prerelease=false\n"
        "release_tag=\n"
    )
    assert github_env.read_text(encoding="utf-8") == (
        "VERSION_BUMPED=false\n"
        "VERSION_CHANGED=false\n"
        "RELEASE_CREATED=false\n"
        "RELEASE_PRERELEASE=false\n"
        "RELEASE_TAG=\n"
    )
    assert (tmp_path / version_file).read_text(encoding="utf-8") == file_contents
    assert not (tmp_path / "cliff.toml").exists()
    assert not (tmp_path / "CHANGELOG.md").exists()


def test_run_action_runtime_allows_manual_first_release_from_zero_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The working version is no longer 0.0.0 even though the previous commit was.
    (tmp_path / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    config = action_runtime.ActionRuntimeConfig(
        action_path=tmp_path,
        host=RuntimeHost.GITEA,
        api_url="https://git.example.invalid/api/v1",
        server_url="https://git.example.invalid",
        repository="owner/repo",
        git_ref="refs/heads/main",
        github_output="",
        github_env="",
        author_name="CI Bot",
        author_email="ci@example.invalid",
        allow_non_main_release=False,
        version_file="VERSION",
        version_regex="",
        major_patterns="",
        minor_patterns="",
        patch_patterns="^fix:",
        git_cliff_offline=True,
        revision_range="before..after",
        github_event_before="before",
        github_sha="after",
        release_publish_token="token",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(action_runtime, "configure_git_author", lambda *_args: None)
    observed: dict[str, str] = {}

    def fake_bump(bump_config) -> VersionBumpResult:
        assert bump_config.patch_patterns_raw == "^fix:"
        return VersionBumpResult(version_bumped=False)

    def fake_change(change_config) -> VersionChangeResult:
        assert change_config.version_file == "VERSION"
        return VersionChangeResult(
            version_changed=True, version_before="0.0.0", version_after="0.1.0"
        )

    def fake_release(release_config, *, cwd: Path) -> ReleaseFlowResult:
        observed["version"] = release_config.version
        observed["binary"] = release_config.git_cliff_binary
        assert cwd == tmp_path
        return ReleaseFlowResult(
            release_created=True, release_prerelease=False, release_tag="v0.1.0"
        )

    monkeypatch.setattr(action_runtime, "run_version_bump", fake_bump)
    monkeypatch.setattr(action_runtime, "run_version_change_detection", fake_change)
    monkeypatch.setattr(action_runtime, "ensure_cliff_config", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        action_runtime, "install_git_cliff", lambda _version: Path("/opt/bin/git-cliff")
    )
    monkeypatch.setattr(action_runtime, "run_release_flow", fake_release)

    action_runtime.run_action_runtime(config)

    assert observed == {"version": "0.1.0", "binary": "/opt/bin/git-cliff"}


def test_run_action_runtime_uses_api_url_for_release_requests(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    action_root = tmp_path / "action"
    action_root.mkdir()
    (action_root / VERSION_FILE_NAME).write_text(
        'GIT_CLIFF_VERSION="v2.15.0"\n', encoding="utf-8"
    )
    (tmp_path / "cliff.toml").write_text(
        '# CLIFF_VERSION=99.99.99\n', encoding="utf-8"
    )

    config = action_runtime.ActionRuntimeConfig(
        action_path=action_root,
        host=RuntimeHost.GITEA,
        api_url="https://api.example.invalid",
        server_url="https://example.invalid",
        repository="owner/repo",
        git_ref="refs/heads/main",
        github_output="",
        github_env="",
        author_name="CI Bot",
        author_email="ci@example.invalid",
        allow_non_main_release=False,
        version_file="VERSION",
        version_regex="^(.*)$",
        major_patterns="",
        minor_patterns="",
        patch_patterns="",
        git_cliff_offline=False,
        revision_range="before..after",
        github_event_before="before",
        github_sha="after",
        release_publish_token="token",
        trigger_release_workflows=True,
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(action_runtime, "configure_git_author", lambda *_args: None)
    monkeypatch.setattr(
        action_runtime,
        "run_version_bump",
        lambda _config: VersionBumpResult(version_bumped=False),
    )
    monkeypatch.setattr(
        action_runtime,
        "run_version_change_detection",
        lambda _config: VersionChangeResult(
            version_changed=True,
            version_before="0.0.1",
            version_after="0.0.2",
        ),
    )
    monkeypatch.setattr(
        action_runtime, "write_version_bump_outputs", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        action_runtime,
        "write_version_change_outputs",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(action_runtime, "ensure_cliff_config", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        action_runtime,
        "install_git_cliff",
        lambda version: captured.__setitem__("cliff_version", version)
        or Path("/opt/git-cliff/bin/git-cliff"),
    )

    def fake_run_release_flow(release_config, *, cwd: Path) -> ReleaseFlowResult:
        captured["api_url"] = release_config.api_url
        captured["git_cliff_binary"] = release_config.git_cliff_binary
        captured["host"] = release_config.host
        captured["trigger_release_workflows"] = release_config.trigger_release_workflows
        captured["cwd"] = cwd
        return ReleaseFlowResult(
            release_created=True,
            release_prerelease=False,
            release_tag="v0.0.2",
        )

    monkeypatch.setattr(action_runtime, "run_release_flow", fake_run_release_flow)
    monkeypatch.setattr(
        action_runtime,
        "run_unreleased_changelog_flow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected path")),
    )

    action_runtime.run_action_runtime(config)

    assert captured == {
        "api_url": "https://api.example.invalid",
        "cliff_version": "2.15.0",
        "git_cliff_binary": "/opt/git-cliff/bin/git-cliff",
        "host": RuntimeHost.GITEA,
        "trigger_release_workflows": True,
        "cwd": tmp_path,
    }


def test_run_action_runtime_writes_release_outputs(monkeypatch, tmp_path: Path) -> None:
    github_output = tmp_path / "github_output.txt"
    github_env = tmp_path / "github_env.txt"

    config = action_runtime.ActionRuntimeConfig(
        action_path=tmp_path,
        host=RuntimeHost.GITHUB,
        api_url="https://api.github.com",
        server_url="https://github.com",
        repository="owner/repo",
        git_ref="refs/heads/main",
        github_output=str(github_output),
        github_env=str(github_env),
        author_name="CI Bot",
        author_email="ci@example.invalid",
        allow_non_main_release=False,
        version_file="VERSION",
        version_regex="^(.*)$",
        major_patterns="",
        minor_patterns="",
        patch_patterns="",
        git_cliff_offline=False,
        revision_range="before..after",
        github_event_before="before",
        github_sha="after",
        release_publish_token="token",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(action_runtime, "configure_git_author", lambda *_args: None)
    monkeypatch.setattr(
        action_runtime,
        "run_version_bump",
        lambda _config: VersionBumpResult(version_bumped=False),
    )
    monkeypatch.setattr(
        action_runtime,
        "run_version_change_detection",
        lambda _config: VersionChangeResult(
            version_changed=True,
            version_before="0.0.1",
            version_after="0.0.2",
        ),
    )
    monkeypatch.setattr(action_runtime, "ensure_cliff_config", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        action_runtime, "install_git_cliff", lambda *_args, **_kwargs: "git-cliff 2.10.1"
    )
    monkeypatch.setattr(
        action_runtime,
        "run_release_flow",
        lambda *_args, **_kwargs: ReleaseFlowResult(
            release_created=True,
            release_prerelease=True,
            release_tag="v0.0.2",
        ),
    )
    monkeypatch.setattr(
        action_runtime,
        "run_unreleased_changelog_flow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected path")),
    )

    action_runtime.run_action_runtime(config)

    assert github_output.read_text(encoding="utf-8") == (
        "version_bumped=false\n"
        "version_changed=true\n"
        "version_before=0.0.1\n"
        "version_after=0.0.2\n"
        "release_created=true\n"
        "release_prerelease=true\n"
        "release_tag=v0.0.2\n"
    )
    assert github_env.read_text(encoding="utf-8") == (
        "VERSION_BUMPED=false\n"
        "VERSION_CHANGED=true\n"
        "VERSION_BEFORE=0.0.1\n"
        "VERSION_AFTER=0.0.2\n"
        "RELEASE_CREATED=true\n"
        "RELEASE_PRERELEASE=true\n"
        "RELEASE_TAG=v0.0.2\n"
    )


def test_run_action_runtime_uses_default_version_regex_when_input_is_blank(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    config = action_runtime.ActionRuntimeConfig(
        action_path=tmp_path,
        host=RuntimeHost.GITEA,
        api_url="https://git.0xmax42.io/api/v1",
        server_url="https://example.invalid",
        repository="owner/repo",
        git_ref="refs/heads/main",
        github_output="",
        github_env="",
        author_name="CI Bot",
        author_email="ci@example.invalid",
        allow_non_main_release=False,
        version_file="VERSION",
        version_regex="",
        major_patterns="",
        minor_patterns="",
        patch_patterns="",
        git_cliff_offline=False,
        revision_range="before..after",
        github_event_before="before",
        github_sha="after",
        release_publish_token="",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(action_runtime, "configure_git_author", lambda *_args: None)

    def fake_run_version_bump(bump_config):
        captured["bump_version_regex"] = bump_config.version_regex
        return VersionBumpResult(version_bumped=False)

    def fake_run_version_change_detection(change_config):
        captured["change_version_regex"] = change_config.version_regex
        return VersionChangeResult(version_changed=False)

    monkeypatch.setattr(action_runtime, "run_version_bump", fake_run_version_bump)
    monkeypatch.setattr(
        action_runtime,
        "run_version_change_detection",
        fake_run_version_change_detection,
    )
    monkeypatch.setattr(
        action_runtime, "write_version_bump_outputs", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        action_runtime,
        "write_version_change_outputs",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(action_runtime, "ensure_cliff_config", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        action_runtime, "install_git_cliff", lambda *_args, **_kwargs: "git-cliff 2.10.1"
    )
    monkeypatch.setattr(
        action_runtime,
        "run_unreleased_changelog_flow",
        lambda *_args, **_kwargs: None,
    )

    action_runtime.run_action_runtime(config)

    expected_regex = default_version_regex_for_file("VERSION")
    assert captured == {
        "bump_version_regex": expected_regex,
        "change_version_regex": expected_regex,
    }


def test_config_from_environment_resolves_gitea_from_api_url(monkeypatch, tmp_path: Path) -> None:
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTION_PATH", str(tmp_path))
    monkeypatch.setenv("RANGE", "before..after")
    monkeypatch.setenv("GITEA_API_URL", "https://git.example.invalid/api/v1/")
    monkeypatch.setenv("GITHUB_REPOSITORY", "actions/auto-changelog-release-action")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")

    config = action_runtime.config_from_environment()

    assert config.host is RuntimeHost.GITEA
    assert config.api_url == "https://git.example.invalid/api/v1"
    assert config.server_url == "https://git.example.invalid"
    assert config.repository == "actions/auto-changelog-release-action"
    assert config.git_ref == "refs/heads/main"


def test_config_from_environment_prefers_gitea_host_on_mixed_runner_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTION_PATH", str(tmp_path))
    monkeypatch.setenv("RANGE", "before..after")
    monkeypatch.setenv("GITEA_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITEA_API_URL", "https://git.example.invalid/api/v1")
    monkeypatch.setenv("GITHUB_API_URL", "https://git.example.invalid/api/v1")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://git.example.invalid")
    monkeypatch.setenv("GITHUB_REPOSITORY", "actions/auto-changelog-release-action")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")

    config = action_runtime.config_from_environment()

    assert config.host is RuntimeHost.GITEA
    assert config.api_url == "https://git.example.invalid/api/v1"
    assert config.server_url == "https://git.example.invalid"
    assert config.repository == "actions/auto-changelog-release-action"
    assert config.git_ref == "refs/heads/main"


def test_config_from_environment_does_not_use_fixed_gitea_url_defaults(
    monkeypatch, tmp_path: Path
) -> None:
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTION_PATH", str(tmp_path))
    monkeypatch.setenv("RANGE", "before..after")

    config = action_runtime.config_from_environment()

    assert config.host is RuntimeHost.GITEA
    assert config.api_url == ""
    assert config.server_url == ""


def test_config_from_environment_resolves_github_from_server_url(
    monkeypatch, tmp_path: Path
) -> None:
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTION_PATH", str(tmp_path))
    monkeypatch.setenv("RANGE", "before..after")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com/")
    monkeypatch.setenv("GITHUB_REPOSITORY", "actions/auto-changelog-release-action")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")

    config = action_runtime.config_from_environment()

    assert config.host is RuntimeHost.GITHUB
    assert config.api_url == "https://api.github.com"
    assert config.server_url == "https://github.com"
    assert config.repository == "actions/auto-changelog-release-action"
    assert config.git_ref == "refs/heads/main"


def test_config_from_environment_reads_git_cliff_offline(monkeypatch, tmp_path: Path) -> None:
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTION_PATH", str(tmp_path))
    monkeypatch.setenv("RANGE", "before..after")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "actions/auto-changelog-release-action")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GIT_CLIFF_OFFLINE", "true")

    config = action_runtime.config_from_environment()

    assert config.git_cliff_offline is True


def test_config_from_environment_defaults_unreleased_changelog_commit_to_false(
    monkeypatch, tmp_path: Path
) -> None:
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTION_PATH", str(tmp_path))
    monkeypatch.setenv("RANGE", "before..after")

    config = action_runtime.config_from_environment()

    assert config.commit_unreleased_changelog is False


def test_config_from_environment_allows_unreleased_changelog_commits(
    monkeypatch, tmp_path: Path
) -> None:
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTION_PATH", str(tmp_path))
    monkeypatch.setenv("RANGE", "before..after")
    monkeypatch.setenv("COMMIT_UNRELEASED_CHANGELOG", "true")

    config = action_runtime.config_from_environment()

    assert config.commit_unreleased_changelog is True


def test_config_from_environment_reads_trigger_release_workflows(
    monkeypatch, tmp_path: Path
) -> None:
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTION_PATH", str(tmp_path))
    monkeypatch.setenv("RANGE", "before..after")
    monkeypatch.setenv("TRIGGER_RELEASE_WORKFLOWS", "true")

    config = action_runtime.config_from_environment()

    assert config.trigger_release_workflows is True


def test_config_from_environment_defaults_git_cliff_offline_to_true(
    monkeypatch, tmp_path: Path
) -> None:
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTION_PATH", str(tmp_path))
    monkeypatch.setenv("RANGE", "before..after")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "actions/auto-changelog-release-action")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.delenv("GIT_CLIFF_OFFLINE", raising=False)

    config = action_runtime.config_from_environment()

    assert config.git_cliff_offline is True


def test_run_action_runtime_sets_git_cliff_offline_env(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str | bool | None] = {}
    config = action_runtime.ActionRuntimeConfig(
        action_path=tmp_path,
        host=RuntimeHost.GITEA,
        api_url="https://git.0xmax42.io/api/v1",
        server_url="https://example.invalid",
        repository="owner/repo",
        git_ref="refs/heads/main",
        github_output="",
        github_env="",
        author_name="CI Bot",
        author_email="ci@example.invalid",
        allow_non_main_release=False,
        version_file="VERSION",
        version_regex="^(.*)$",
        major_patterns="",
        minor_patterns="",
        patch_patterns="",
        git_cliff_offline=True,
        revision_range="before..after",
        github_event_before="before",
        github_sha="after",
        release_publish_token="",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(action_runtime, "configure_git_author", lambda *_args: None)
    monkeypatch.setattr(
        action_runtime,
        "run_version_bump",
        lambda _config: VersionBumpResult(version_bumped=False),
    )
    monkeypatch.setattr(
        action_runtime,
        "run_version_change_detection",
        lambda _config: VersionChangeResult(version_changed=False),
    )
    monkeypatch.setattr(
        action_runtime, "write_version_bump_outputs", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        action_runtime,
        "write_version_change_outputs",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(action_runtime, "ensure_cliff_config", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(action_runtime, "install_git_cliff", lambda *_args, **_kwargs: "2.10.1")

    def fake_run_unreleased_changelog_flow(unreleased_config, *, cwd: Path) -> None:
        captured["offline"] = action_runtime.os.environ.get("GIT_CLIFF_OFFLINE")
        captured["commit_unreleased_changelog"] = unreleased_config.commit_unreleased_changelog

    monkeypatch.setattr(
        action_runtime,
        "run_unreleased_changelog_flow",
        fake_run_unreleased_changelog_flow,
    )

    action_runtime.run_action_runtime(config)

    assert captured == {"offline": "true", "commit_unreleased_changelog": False}
    assert action_runtime.os.environ.get("GIT_CLIFF_OFFLINE") is None


def test_run_action_runtime_requires_explicit_release_token(monkeypatch, tmp_path: Path) -> None:
    config = action_runtime.ActionRuntimeConfig(
        action_path=tmp_path,
        host=RuntimeHost.GITHUB,
        api_url="https://api.github.com",
        server_url="https://github.com",
        repository="owner/repo",
        git_ref="refs/heads/main",
        github_output="",
        github_env="",
        author_name="CI Bot",
        author_email="ci@example.invalid",
        allow_non_main_release=False,
        version_file="VERSION",
        version_regex="^(.*)$",
        major_patterns="",
        minor_patterns="",
        patch_patterns="",
        git_cliff_offline=False,
        revision_range="before..after",
        github_event_before="before",
        github_sha="after",
        release_publish_token="",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(action_runtime, "configure_git_author", lambda *_args: None)
    monkeypatch.setattr(
        action_runtime,
        "run_version_bump",
        lambda _config: VersionBumpResult(version_bumped=False),
    )
    monkeypatch.setattr(
        action_runtime,
        "run_version_change_detection",
        lambda _config: VersionChangeResult(
            version_changed=True,
            version_before="0.0.1",
            version_after="0.0.2",
        ),
    )
    monkeypatch.setattr(
        action_runtime, "write_version_bump_outputs", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        action_runtime,
        "write_version_change_outputs",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(action_runtime, "ensure_cliff_config", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        action_runtime, "install_git_cliff", lambda *_args, **_kwargs: "git-cliff 2.10.1"
    )

    try:
        action_runtime.run_action_runtime(config)
    except RuntimeError as error:
        assert str(error) == "Release publishing requires the explicit token input."
    else:
        raise AssertionError("expected explicit token error")