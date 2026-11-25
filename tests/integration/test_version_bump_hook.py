from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from auto_changelog_release_action.version_bump_flow import VersionBumpConfig, run_version_bump
from tests.support.git_repo import LocalGitRepo, init_local_git_repo


@pytest.fixture
def bump_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalGitRepo:
    repo = init_local_git_repo(tmp_path)
    repo.write("VERSION", "1.2.3\n")
    repo.write("project.lock", "1.2.3\n")
    repo.write("unrelated.txt", "original\n")
    repo.commit_all("feat: initial version")
    repo.write("feature.txt", "new feature\n")
    repo.commit_all("fix: regression")
    monkeypatch.chdir(repo.root)
    return repo


def config(
    repo: LocalGitRepo, script: str = "", files: str = "", *, patterns: str = "^fix:"
) -> VersionBumpConfig:
    return VersionBumpConfig(
        version_file="VERSION",
        version_regex=r"^([^\n]+)$",
        major_patterns_raw="",
        minor_patterns_raw="",
        patch_patterns_raw=patterns,
        revision_range=f"{repo.rev_parse('HEAD^')}..{repo.rev_parse('HEAD')}",
        allow_non_main_release=False,
        git_ref="refs/heads/main",
        post_version_bump=script,
        version_bump_files=files,
    )


def test_existing_bump_without_hook_only_commits_primary_file(bump_repo: LocalGitRepo) -> None:
    result = run_version_bump(config(bump_repo))
    assert result.version_after == "1.2.4"
    assert bump_repo.run("show", "HEAD:VERSION") == "1.2.4"
    assert bump_repo.run("show", "HEAD:project.lock") == "1.2.3"
    assert bump_repo.head_subject() == "chore(version): bump version to 1.2.4"


def test_hook_synchronizes_files_in_same_commit(
    bump_repo: LocalGitRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RELEASE_PUBLISH_TOKEN", "secret")
    monkeypatch.setenv("UNRELATED_SECRET", "secret")
    script = """
test -z "${RELEASE_PUBLISH_TOKEN+x}"
test -z "${UNRELATED_SECRET+x}"
test "$VERSION_BEFORE" = 1.2.3
test "$VERSION_AFTER" = 1.2.4
test "$VERSION_BUMP" = patch
test "$(cat "$VERSION_FILE")" = "$VERSION_AFTER"
printf '%s\\n' "$VERSION_AFTER" > project.lock
printf '%s\\n' "$VERSION_AFTER" > "extra file"
"""
    result = run_version_bump(config(bump_repo, script, "project.lock\nextra file"))
    assert result.version_after == "1.2.4"
    assert bump_repo.run("show", "HEAD:VERSION") == "1.2.4"
    assert bump_repo.run("show", "HEAD:project.lock") == "1.2.4"
    assert bump_repo.run("show", "HEAD:extra file") == "1.2.4"
    committed_files = bump_repo.run("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
    assert set(committed_files.splitlines()) == {
        "VERSION",
        "project.lock",
        "extra file",
    }
    assert bump_repo.run("status", "--porcelain") == ""


@pytest.mark.parametrize(
    "script",
    [
        "false\ntrue",
        "false | true",
        "printf changed > unrelated.txt",
        "printf changed > undeclared.txt",
        "printf 9.9.9 > VERSION",
        "git add VERSION",
        "rm project.lock",
        "rm project.lock; ln -s unrelated.txt project.lock",
    ],
)
def test_invalid_hook_never_creates_version_commit(bump_repo: LocalGitRepo, script: str) -> None:
    head = bump_repo.rev_parse("HEAD")
    with pytest.raises((RuntimeError, ValueError, subprocess.CalledProcessError)):
        run_version_bump(config(bump_repo, script, "project.lock"))
    assert bump_repo.rev_parse("HEAD") == head
    assert bump_repo.run("tag") == ""


def test_hook_stdin_reader_cannot_consume_following_commands(bump_repo: LocalGitRepo) -> None:
    script = 'cat >/dev/null\ncp "$VERSION_FILE" project.lock'
    result = run_version_bump(config(bump_repo, script, "project.lock"))
    assert result.version_after == "1.2.4"
    assert bump_repo.run("show", "HEAD:project.lock") == "1.2.4"


def test_hook_stdin_reader_cannot_hide_failure(bump_repo: LocalGitRepo) -> None:
    head = bump_repo.rev_parse("HEAD")
    with pytest.raises(subprocess.CalledProcessError) as error:
        run_version_bump(config(bump_repo, "cat >/dev/null\nexit 7"))
    assert error.value.returncode == 7
    assert bump_repo.rev_parse("HEAD") == head


def test_hook_created_commit_is_rejected(bump_repo: LocalGitRepo) -> None:
    with pytest.raises(RuntimeError):
        run_version_bump(config(bump_repo, "git commit --allow-empty -m unexpected"))
    assert bump_repo.head_subject() == "unexpected"
    assert bump_repo.run("tag") == ""


@pytest.mark.parametrize(
    "script",
    [
        'git tag "v$VERSION_AFTER"',
        "git tag -d existing",
        "git tag -f existing HEAD^",
        "git branch unexpected",
        "git update-ref refs/remotes/origin/main HEAD",
        "git update-index --assume-unchanged unrelated.txt",
        "git update-index --skip-worktree unrelated.txt",
    ],
)
def test_hook_git_state_changes_are_rejected(bump_repo: LocalGitRepo, script: str) -> None:
    bump_repo.tag("existing")
    head = bump_repo.rev_parse("HEAD")
    with pytest.raises(RuntimeError):
        run_version_bump(config(bump_repo, script))
    assert bump_repo.rev_parse("HEAD") == head
    assert bump_repo.run("show", "HEAD:VERSION") == "1.2.3"


def test_hook_allows_read_only_git_operations(bump_repo: LocalGitRepo) -> None:
    bump_repo.tag("existing")
    script = """
test "$GIT_OPTIONAL_LOCKS" = 0
git log -1
git describe --tags
git rev-parse HEAD
git status
cp "$VERSION_FILE" project.lock
"""
    result = run_version_bump(config(bump_repo, script, "project.lock"))
    assert result.version_after == "1.2.4"
    assert bump_repo.run("show", "HEAD:project.lock") == "1.2.4"
    assert bump_repo.run("tag") == "existing"


@pytest.mark.parametrize("files", ["../outside", "/tmp/outside", ".git/config"])
def test_invalid_paths_rejected_before_bump(bump_repo: LocalGitRepo, files: str) -> None:
    with pytest.raises(ValueError):
        run_version_bump(config(bump_repo, "true", files))
    assert bump_repo.read("VERSION") == "1.2.3\n"


def test_dirty_worktree_rejected_before_bump(bump_repo: LocalGitRepo) -> None:
    bump_repo.write("unrelated.txt", "local change\n")
    with pytest.raises(RuntimeError):
        run_version_bump(config(bump_repo, "true"))
    assert bump_repo.read("VERSION") == "1.2.3\n"


def test_hook_skipped_when_no_bump_matches(bump_repo: LocalGitRepo) -> None:
    head = bump_repo.rev_parse("HEAD")
    result = run_version_bump(config(bump_repo, "exit 7", patterns="^feat:"))
    assert not result.version_bumped
    assert bump_repo.rev_parse("HEAD") == head
