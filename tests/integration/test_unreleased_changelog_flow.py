from __future__ import annotations

import io
import os
import stat
import subprocess
import textwrap
from contextlib import redirect_stdout
from pathlib import Path

from auto_changelog_release_action.unreleased_changelog import (
    UnreleasedChangelogConfig,
    run_unreleased_changelog_flow,
)
from tests.support.git_repo import init_local_bare_remote, init_local_git_repo


def write_fake_git_cliff(bin_dir: Path) -> None:
    script_path = bin_dir / "git-cliff"
    script_path.write_text(
        textwrap.dedent(
            """
            #!/usr/bin/env bash
            set -euo pipefail

            if printf '%s\n' "$@" | grep -qx -- '--context'; then
                printf '%s' '[{"version": null, "commits": []}]'
                exit 0
            fi

            if printf '%s\n' "$@" | grep -qx -- '--from-context'; then
                output_path=''
                while [[ $# -gt 0 ]]; do
                    if [[ "$1" == '-o' ]]; then
                        output_path="$2"
                        shift 2
                        continue
                    fi
                    shift
                done

                cat >/dev/null
                printf '%s' "${FAKE_GIT_CLIFF_OUTPUT:-# Changelog\n}" >"${output_path}"
                exit 0
            fi

            echo "unexpected args: $*" >&2
            exit 1
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)


def run_unreleased_changelog(
    repo_root: Path,
    *,
    github_ref: str,
    fake_output: str | None = None,
    commit_unreleased_changelog: bool = False,
) -> str:
    action_root = Path(__file__).resolve().parents[2]
    bin_dir = repo_root.parent / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    write_fake_git_cliff(bin_dir)

    original_path = os.environ.get("PATH", "")
    original_output = os.environ.get("FAKE_GIT_CLIFF_OUTPUT")
    os.environ["PATH"] = f"{bin_dir}:{original_path}"
    if fake_output is not None:
        os.environ["FAKE_GIT_CLIFF_OUTPUT"] = fake_output
    else:
        os.environ.pop("FAKE_GIT_CLIFF_OUTPUT", None)

    config = UnreleasedChangelogConfig(
        changelog_file=repo_root / "CHANGELOG.md",
        cliff_config=repo_root / "cliff.toml",
        git_branch=github_ref.removeprefix("refs/heads/"),
        commit_unreleased_changelog=commit_unreleased_changelog,
    )

    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            run_unreleased_changelog_flow(config, cwd=repo_root)
    finally:
        os.environ["PATH"] = original_path
        if original_output is None:
            os.environ.pop("FAKE_GIT_CLIFF_OUTPUT", None)
        else:
            os.environ["FAKE_GIT_CLIFF_OUTPUT"] = original_output

    return buffer.getvalue()


def remote_branch_head(remote_root: Path, branch: str) -> str:
    completed = subprocess.run(
        ["git", "--git-dir", str(remote_root), "rev-parse", f"refs/heads/{branch}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_unreleased_changelog_skips_when_missing_off_main_branch(tmp_path: Path) -> None:
    repo = init_local_git_repo(tmp_path, default_branch="v1/main")
    remote_root = init_local_bare_remote(tmp_path)
    repo.add_remote("origin", str(remote_root))
    repo.write("cliff.toml", "test\n")
    repo.commit_all("chore: initial import")
    repo.push("origin", "v1/main", set_upstream=True)

    repo.checkout("v1/refactor/skip-changelog", create=True)
    repo.run("push", "-u", "origin", "v1/refactor/skip-changelog")
    before_head = repo.rev_parse("HEAD")

    stdout = run_unreleased_changelog(
        repo.root,
        github_ref="refs/heads/v1/refactor/skip-changelog",
    )

    assert "Skipping generation" in stdout
    assert not (repo.root / "CHANGELOG.md").exists()
    assert repo.rev_parse("HEAD") == before_head
    assert remote_branch_head(remote_root, "v1/refactor/skip-changelog") == before_head


def test_unreleased_changelog_generates_without_committing_by_default(tmp_path: Path) -> None:
    repo = init_local_git_repo(tmp_path)
    remote_root = init_local_bare_remote(tmp_path)
    repo.add_remote("origin", str(remote_root))
    repo.write("cliff.toml", "test\n")
    repo.commit_all("chore: initial import")
    repo.push("origin", "main", set_upstream=True)
    before_head = repo.rev_parse("HEAD")

    stdout = run_unreleased_changelog(
        repo.root,
        github_ref="refs/heads/main",
        fake_output="# Changelog\n\nGenerated unreleased entry\n",
    )

    assert "Generating" in stdout
    assert "commit and push disabled" in stdout
    assert repo.read("CHANGELOG.md") == "# Changelog\n\nGenerated unreleased entry\n"
    assert repo.rev_parse("HEAD") == before_head
    assert remote_branch_head(remote_root, "main") == before_head


def test_unreleased_changelog_generates_commits_and_pushes(tmp_path: Path) -> None:
    repo = init_local_git_repo(tmp_path)
    remote_root = init_local_bare_remote(tmp_path)
    repo.add_remote("origin", str(remote_root))
    repo.write("cliff.toml", "test\n")
    repo.commit_all("chore: initial import")
    repo.push("origin", "main", set_upstream=True)

    stdout = run_unreleased_changelog(
        repo.root,
        github_ref="refs/heads/main",
        fake_output="# Changelog\n\nGenerated unreleased entry\n",
        commit_unreleased_changelog=True,
    )

    assert "Generating" in stdout
    assert "CHANGELOG.md" in stdout
    assert repo.read("CHANGELOG.md") == "# Changelog\n\nGenerated unreleased entry\n"
    assert repo.head_subject() == "chore(changelog): update unreleased changelog"
    assert remote_branch_head(remote_root, "main") == repo.rev_parse("HEAD")
