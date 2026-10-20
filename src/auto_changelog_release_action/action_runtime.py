"""Orchestrates the full composite-action pipeline from inputs to release output."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from auto_changelog_release_action.actions_io import append_kv
from auto_changelog_release_action.cliff_config import DEFAULT_CLIFF_CONFIG, ensure_cliff_config
from auto_changelog_release_action.git_cliff_version import (
    VERSION_FILE_NAME,
    read_git_cliff_version,
)
from auto_changelog_release_action.git_setup import configure_git_author
from auto_changelog_release_action.install_git_cliff import install_git_cliff
from auto_changelog_release_action.release_flow import (
    ReleaseConfig,
    run_release_flow,
)
from auto_changelog_release_action.repository import split_repository_slug
from auto_changelog_release_action.runtime_host import RuntimeHost, resolve_runtime_host
from auto_changelog_release_action.unreleased_changelog import (
    UnreleasedChangelogConfig,
    run_unreleased_changelog_flow,
)
from auto_changelog_release_action.version_bump_flow import VersionBumpConfig, run_version_bump
from auto_changelog_release_action.version_change_flow import (
    VersionChangeConfig,
    run_version_change_detection,
)
from auto_changelog_release_action.versioning import default_version_regex_for_file


@dataclass(frozen=True)
class ActionRuntimeConfig:
    """Resolved inputs, GitHub context, and tokens for one action run."""

    action_path: Path
    host: RuntimeHost
    api_url: str
    server_url: str
    repository: str
    git_ref: str
    github_output: str
    github_env: str
    author_name: str
    author_email: str
    allow_non_main_release: bool
    version_file: str
    version_regex: str
    major_patterns: str
    minor_patterns: str
    patch_patterns: str
    git_cliff_offline: bool
    revision_range: str
    github_event_before: str
    github_sha: str
    release_publish_token: str
    trigger_release_workflows: bool = False
    commit_unreleased_changelog: bool = False


def bool_string(value: bool) -> str:
    """Convert a boolean to the lowercase string form used by Actions files."""

    return "true" if value else "false"


def write_version_bump_outputs(
    config: ActionRuntimeConfig,
    *,
    version_bumped: bool,
    version_after: str | None,
) -> None:
    """Persist version bump results to both Actions output channels."""

    append_kv(config.github_output, "version_bumped", bool_string(version_bumped))
    append_kv(config.github_env, "VERSION_BUMPED", bool_string(version_bumped))
    if version_after is not None:
        append_kv(config.github_output, "version_after", version_after)
        append_kv(config.github_env, "VERSION_AFTER", version_after)


def write_version_change_outputs(
    config: ActionRuntimeConfig,
    *,
    version_changed: bool,
    version_before: str | None,
    version_after: str | None,
) -> None:
    """Persist version change results to both Actions output channels."""

    append_kv(config.github_output, "version_changed", bool_string(version_changed))
    append_kv(config.github_env, "VERSION_CHANGED", bool_string(version_changed))
    if version_before is not None:
        append_kv(config.github_output, "version_before", version_before)
        append_kv(config.github_env, "VERSION_BEFORE", version_before)
    if version_after is not None:
        append_kv(config.github_output, "version_after", version_after)
        append_kv(config.github_env, "VERSION_AFTER", version_after)


def write_release_outputs(
    config: ActionRuntimeConfig,
    *,
    release_created: bool,
    release_prerelease: bool,
    release_tag: str | None,
) -> None:
    """Persist release publication results to both Actions output channels."""

    append_kv(config.github_output, "release_created", bool_string(release_created))
    append_kv(config.github_env, "RELEASE_CREATED", bool_string(release_created))
    append_kv(config.github_output, "release_prerelease", bool_string(release_prerelease))
    append_kv(config.github_env, "RELEASE_PRERELEASE", bool_string(release_prerelease))
    append_kv(config.github_output, "release_tag", release_tag or "")
    append_kv(config.github_env, "RELEASE_TAG", release_tag or "")


def config_from_environment() -> ActionRuntimeConfig:
    """Build the runtime configuration from process environment variables."""

    resolved_runtime = resolve_runtime_host(
        api_url=os.environ.get("GITHUB_API_URL") or os.environ.get("GITEA_API_URL", ""),
        server_url=os.environ.get("GITHUB_SERVER_URL") or os.environ.get("GITEA_SERVER_URL", ""),
        repository=os.environ.get("GITHUB_REPOSITORY") or os.environ.get("GITEA_REPOSITORY", ""),
        ref=os.environ.get("GITHUB_REF") or os.environ.get("GITEA_REF", ""),
    )

    return ActionRuntimeConfig(
        action_path=Path(os.environ["GITHUB_ACTION_PATH"]),
        host=resolved_runtime.host,
        api_url=resolved_runtime.api_url,
        server_url=resolved_runtime.server_url,
        repository=resolved_runtime.repository,
        git_ref=resolved_runtime.ref,
        github_output=os.environ.get("GITHUB_OUTPUT", ""),
        github_env=os.environ.get("GITHUB_ENV", ""),
        author_name=os.environ.get("AUTHOR_NAME", ""),
        author_email=os.environ.get("AUTHOR_EMAIL", ""),
        allow_non_main_release=os.environ.get("ALLOW_NON_MAIN_RELEASE", "false").lower() == "true",
        version_file=os.environ.get("VERSION_FILE", "VERSION"),
        version_regex=os.environ.get("VERSION_REGEX", ""),
        major_patterns=os.environ.get("MAJOR_PATTERNS", ""),
        minor_patterns=os.environ.get("MINOR_PATTERNS", ""),
        patch_patterns=os.environ.get("PATCH_PATTERNS", ""),
        git_cliff_offline=os.environ.get("GIT_CLIFF_OFFLINE", "true").lower() == "true",
        revision_range=os.environ["RANGE"],
        github_event_before=os.environ.get("GITHUB_EVENT_BEFORE", ""),
        github_sha=os.environ.get("GITHUB_SHA", ""),
        release_publish_token=os.environ.get("RELEASE_PUBLISH_TOKEN", ""),
        trigger_release_workflows=(
            os.environ.get("TRIGGER_RELEASE_WORKFLOWS", "false").lower() == "true"
        ),
        commit_unreleased_changelog=(
            os.environ.get("COMMIT_UNRELEASED_CHANGELOG", "false").lower() == "true"
        ),
    )


def run_action_runtime(config: ActionRuntimeConfig) -> None:
    """Execute the full action pipeline for the current repository state."""

    configure_git_author(config.author_name, config.author_email)
    resolved_version_regex = config.version_regex or default_version_regex_for_file(
        config.version_file
    )

    bump_result = run_version_bump(
        VersionBumpConfig(
            version_file=config.version_file,
            version_regex=resolved_version_regex,
            major_patterns_raw=config.major_patterns,
            minor_patterns_raw=config.minor_patterns,
            patch_patterns_raw=config.patch_patterns,
            revision_range=config.revision_range,
            allow_non_main_release=config.allow_non_main_release,
            git_ref=config.git_ref,
        )
    )
    write_version_bump_outputs(
        config,
        version_bumped=bump_result.version_bumped,
        version_after=bump_result.version_after,
    )

    if bump_result.version_bumped:
        version_changed = True
        version_before = None
        version_after = bump_result.version_after
        print("Version was bumped in previous step.")
    else:
        detect_result = run_version_change_detection(
            VersionChangeConfig(
                git_ref=config.git_ref,
                commit_before=config.github_event_before,
                commit_after=config.github_sha,
                allow_non_main_release=config.allow_non_main_release,
                version_file=config.version_file,
                version_regex=resolved_version_regex,
            )
        )
        version_changed = detect_result.version_changed
        version_before = detect_result.version_before
        version_after = detect_result.version_after

    write_version_change_outputs(
        config,
        version_changed=version_changed,
        version_before=version_before,
        version_after=version_after,
    )

    cliff_path = Path(DEFAULT_CLIFF_CONFIG)
    ensure_cliff_config(
        cliff_path,
        templates_root=config.action_path,
        host=config.host,
        repository=config.repository,
        server_url=config.server_url,
    )
    git_cliff_binary = install_git_cliff(
        read_git_cliff_version(config.action_path / VERSION_FILE_NAME)
    )

    previous_git_cliff_offline = os.environ.get("GIT_CLIFF_OFFLINE")
    os.environ["GIT_CLIFF_OFFLINE"] = bool_string(config.git_cliff_offline)
    try:
        if version_changed:
            if not version_after:
                raise RuntimeError("VERSION_AFTER is required for release publishing")
            if not config.release_publish_token:
                raise RuntimeError("Release publishing requires the explicit token input.")
            owner, repo = split_repository_slug(config.repository)
            release_result = run_release_flow(
                ReleaseConfig(
                    changelog_file=Path("CHANGELOG.md"),
                    cliff_config=Path(DEFAULT_CLIFF_CONFIG),
                    version=version_after,
                    git_branch=config.git_ref.removeprefix("refs/heads/"),
                    api_url=config.api_url,
                    repository_owner=owner,
                    repository_name=repo,
                    publish_token=config.release_publish_token,
                    host=config.host,
                    trigger_release_workflows=config.trigger_release_workflows,
                    git_cliff_binary=str(git_cliff_binary),
                ),
                cwd=Path.cwd(),
            )
            write_release_outputs(
                config,
                release_created=release_result.release_created,
                release_prerelease=release_result.release_prerelease,
                release_tag=release_result.release_tag,
            )
            return

        run_unreleased_changelog_flow(
            UnreleasedChangelogConfig(
                changelog_file=Path("CHANGELOG.md"),
                cliff_config=Path(DEFAULT_CLIFF_CONFIG),
                git_branch=config.git_ref.removeprefix("refs/heads/"),
                commit_unreleased_changelog=config.commit_unreleased_changelog,
                git_cliff_binary=str(git_cliff_binary),
            ),
            cwd=Path.cwd(),
        )
        write_release_outputs(
            config,
            release_created=False,
            release_prerelease=False,
            release_tag=None,
        )
    finally:
        if previous_git_cliff_offline is None:
            os.environ.pop("GIT_CLIFF_OFFLINE", None)
        else:
            os.environ["GIT_CLIFF_OFFLINE"] = previous_git_cliff_offline
