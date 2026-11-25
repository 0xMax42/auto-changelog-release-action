"""Detects semantic version bumps from commit messages and updates the version file."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from auto_changelog_release_action.process_utils import run_git_stdout
from auto_changelog_release_action.version_bump_hook import prepare_hook, run_hook
from auto_changelog_release_action.versioning import (
    bump_version,
    detect_bump,
    parse_patterns,
    replace_version,
)

ZERO_SHA = "0" * 40


@dataclass(frozen=True)
class VersionBumpConfig:
    """Inputs required to decide and apply a version bump."""

    version_file: str
    version_regex: str
    major_patterns_raw: str
    minor_patterns_raw: str
    patch_patterns_raw: str
    revision_range: str
    allow_non_main_release: bool
    git_ref: str
    post_version_bump: str = ""
    version_bump_files: str = ""


@dataclass(frozen=True)
class VersionBumpResult:
    """Result of a version bump attempt."""

    version_bumped: bool
    version_after: str | None = None


def run_git(args: list[str]) -> str:
    """Run git and return stripped stdout."""

    return run_git_stdout(args)


def resolve_revision_selector(revision_range: str) -> str:
    """Normalize a revision selector so push events with no before SHA remain usable."""

    if ".." not in revision_range:
        return revision_range

    commit_before, commit_after = revision_range.split("..", maxsplit=1)
    if commit_before and commit_before != ZERO_SHA:
        return revision_range
    if not commit_after:
        return ""

    try:
        parent = run_git(["rev-parse", f"{commit_after}^"])
    except subprocess.CalledProcessError:
        return commit_after

    if not parent:
        return commit_after
    return f"{parent}..{commit_after}"


def get_commit_messages(revision_range: str) -> list[str]:
    """Return commit messages from the configured revision range."""

    revision_selector = resolve_revision_selector(revision_range)
    if not revision_selector:
        return []

    output = run_git(["log", "--format=%B%x00", revision_selector])
    return [message.strip() for message in output.split("\x00") if message.strip()]


def run_version_bump(config: VersionBumpConfig) -> VersionBumpResult:
    """Detect and commit a version bump when the configured patterns match."""

    if (not config.allow_non_main_release) and (config.git_ref != "refs/heads/main"):
        print(
            "🚫 Not on 'main' branch and non-main releases are disabled – skipping version check."
        )
        return VersionBumpResult(version_bumped=False)

    messages = get_commit_messages(config.revision_range)
    if not messages:
        return VersionBumpResult(version_bumped=False)

    bump = detect_bump(
        messages,
        major_patterns=parse_patterns(config.major_patterns_raw),
        minor_patterns=parse_patterns(config.minor_patterns_raw),
        patch_patterns=parse_patterns(config.patch_patterns_raw),
    )
    if bump is None:
        return VersionBumpResult(version_bumped=False)

    path = Path(config.version_file)
    content = path.read_text(encoding="utf-8")
    match = re.search(config.version_regex, content, flags=re.MULTILINE)
    if not match:
        raise RuntimeError("Version regex did not match")

    old_version = match.group(1) if match.lastindex else match.group(0)
    new_version = bump_version(old_version, bump)
    if old_version == new_version:
        return VersionBumpResult(version_bumped=False)

    hook = None
    if config.post_version_bump.strip():
        hook = prepare_hook(config.version_file, config.version_bump_files)
    elif config.version_bump_files.strip():
        raise ValueError("version_bump_files requires post_version_bump")

    path.write_text(
        replace_version(content, config.version_regex, new_version),
        encoding="utf-8",
    )
    if hook is None:
        run_git(["add", str(path)])
    else:
        run_hook(
            hook,
            config.post_version_bump,
            version_before=old_version,
            version_after=new_version,
            bump=bump,
            version_regex=config.version_regex,
        )
        run_git(["--literal-pathspecs", "add", "--", *hook.files])
    run_git(
        [
            "commit",
            "-m",
            f"chore(version): bump version to {new_version}",
            "-m",
            "Automated version bump based on commit message patterns.",
        ]
    )
    print(f"Version bumped: {old_version} → {new_version}")
    return VersionBumpResult(version_bumped=True, version_after=new_version)
