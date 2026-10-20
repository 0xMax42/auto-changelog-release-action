"""Generates and optionally commits the unreleased changelog on non-release runs."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from auto_changelog_release_action.changelog_context import augment_context_json
from auto_changelog_release_action.process_utils import run_command, run_git

CHANGELOG_COMMIT_MESSAGE = "chore(changelog): update unreleased changelog"


@dataclass(frozen=True)
class UnreleasedChangelogConfig:
    """Inputs required for the unreleased changelog path."""

    changelog_file: Path
    cliff_config: Path
    git_branch: str
    commit_unreleased_changelog: bool = False
    git_cliff_binary: str = "git-cliff"


@dataclass(frozen=True)
class UnreleasedChangelogResult:
    """Result of the unreleased changelog flow."""

    generated: bool
    committed: bool


def branch_name_from_ref(github_ref: str) -> str:
    """Strip refs/heads/ from a branch ref when present."""

    prefix = "refs/heads/"
    if github_ref.startswith(prefix):
        return github_ref[len(prefix) :]
    return github_ref


def should_generate_unreleased_changelog(changelog_file: Path, git_branch: str) -> bool:
    """Return whether unreleased changelog generation should run."""

    return changelog_file.is_file() or git_branch == "main"


def generate_unreleased_changelog(config: UnreleasedChangelogConfig, *, cwd: Path) -> None:
    """Render the unreleased changelog file from git-cliff context."""

    print(f"📄 Generating {config.changelog_file} using git-cliff...")

    context = run_command(
        [config.git_cliff_binary, "-c", str(config.cliff_config), "--context"],
        cwd=cwd,
    )
    augmented_context = augment_context_json(context.stdout)
    run_command(
        [
            config.git_cliff_binary,
            "-c",
            str(config.cliff_config),
            "--from-context",
            "-",
            "-o",
            str(config.changelog_file),
        ],
        cwd=cwd,
        input_text=augmented_context,
    )

    print(f"✅ {config.changelog_file} generation completed.")


def commit_and_push_changelog(config: UnreleasedChangelogConfig, *, cwd: Path) -> bool:
    """Commit and push the unreleased changelog when it changed."""

    run_git(["add", str(config.changelog_file)], cwd=cwd)

    diff_result = run_git(["diff", "--cached", "--quiet"], cwd=cwd, check=False)
    if diff_result.returncode == 0:
        print("✅ No changes to commit – changelog is up to date.")
        return False
    if diff_result.returncode != 1:
        raise subprocess.CalledProcessError(
            diff_result.returncode,
            diff_result.args,
            output=diff_result.stdout,
            stderr=diff_result.stderr,
        )

    print(f"✍️  Committing updated {config.changelog_file}...")
    run_git(["commit", "-m", CHANGELOG_COMMIT_MESSAGE], cwd=cwd)
    print(f"🚀 Pushing to origin/{config.git_branch}...")
    run_git(["push", "origin", config.git_branch], cwd=cwd)
    return True


def run_unreleased_changelog_flow(
    config: UnreleasedChangelogConfig, *, cwd: Path
) -> UnreleasedChangelogResult:
    """Execute the unreleased changelog path for non-release runs."""

    if not should_generate_unreleased_changelog(config.changelog_file, config.git_branch):
        print(
            f"ℹ️  {config.changelog_file} does not exist and branch is not 'main'. Skipping generation."  # noqa: E501
        )
        return UnreleasedChangelogResult(generated=False, committed=False)

    generate_unreleased_changelog(config, cwd=cwd)
    if not config.commit_unreleased_changelog:
        print("ℹ️  Unreleased changelog commit and push disabled.")
        return UnreleasedChangelogResult(generated=True, committed=False)

    committed = commit_and_push_changelog(config, cwd=cwd)
    return UnreleasedChangelogResult(generated=True, committed=committed)


def config_from_environment() -> UnreleasedChangelogConfig:
    """Build an unreleased changelog configuration from environment variables."""

    github_ref = os.getenv("GITHUB_REF", "")
    return UnreleasedChangelogConfig(
        changelog_file=Path("CHANGELOG.md"),
        cliff_config=Path("cliff.toml"),
        git_branch=branch_name_from_ref(github_ref),
    )
