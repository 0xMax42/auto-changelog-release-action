from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.support.git_repo import (
    init_local_bare_remote,
    init_local_git_repo,
)

pytestmark = pytest.mark.podman


def podman_or_skip() -> str:
    if os.getenv("RUN_PODMAN_TESTS") != "1":
        pytest.skip("Set RUN_PODMAN_TESTS=1 to enable Podman-based smoke tests.")

    podman = shutil.which("podman")
    if podman is None:
        pytest.skip("Podman is not available in PATH.")

    return podman


def run_podman_script(
    podman: str,
    *,
    action_root: Path,
    fixtures_root: Path,
    image: str,
    script: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            podman,
            "run",
            "--rm",
            "-v",
            f"{action_root}:/action:ro",
            "-v",
            f"{fixtures_root}:/fixtures",
            image,
            "bash",
            "-lc",
            script,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def remote_branch_subject(remote_root: Path, branch: str) -> str:
    completed = subprocess.run(
        ["git", "--git-dir", str(remote_root), "log", "-1", "--pretty=%s", branch],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_action_runtime_smoke_in_podman(tmp_path: Path) -> None:
    podman = podman_or_skip()

    repo = init_local_git_repo(tmp_path)
    remote_root = init_local_bare_remote(tmp_path)
    repo.write("VERSION", "1.2.3\n")
    repo.write("CHANGELOG.md", "# Changelog\n")
    repo.commit_all("feat: initial import")
    repo.write("README.md", "runtime smoke\n")
    repo.commit_all("docs: add runtime smoke marker")

    before_sha = repo.rev_parse("HEAD~1")
    head_sha = repo.rev_parse("HEAD")
    action_root = Path(__file__).resolve().parents[2]
    image = os.getenv("PODMAN_TEST_IMAGE", "docker.io/library/ubuntu:24.04")

    container_script = textwrap.dedent(
        f"""
        set -euo pipefail
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y git ca-certificates
        git config --global --add safe.directory /fixtures/repo
        cd /fixtures/repo
        git remote add origin /fixtures/origin.git
        bash /action/scripts/install-python.sh
        : >/tmp/github_output
        : >/tmp/github_env
        export GITHUB_ACTION_PATH=/action
        export GITHUB_OUTPUT=/tmp/github_output
        export GITHUB_ENV=/tmp/github_env
        export AUTHOR_NAME='Podman Test Bot'
        export AUTHOR_EMAIL='podman@example.invalid'
        export ALLOW_NON_MAIN_RELEASE=false
        export VERSION_FILE=VERSION
        export VERSION_REGEX='^(.*)$'
        export MAJOR_PATTERNS=''
        export MINOR_PATTERNS=''
        export PATCH_PATTERNS=''
        export RANGE='{before_sha}..{head_sha}'
        export GITHUB_EVENT_BEFORE='{before_sha}'
        export GITHUB_SHA='{head_sha}'
        export GITHUB_REF='refs/heads/main'
        export GITHUB_SERVER_URL='https://example.invalid'
        export GITHUB_REPOSITORY='example/project'
        export RELEASE_PUBLISH_TOKEN=''
        export GIT_CLIFF_OFFLINE=true
        export COMMIT_UNRELEASED_CHANGELOG=true
        PYTHONPATH="/action/src${{PYTHONPATH:+:${{PYTHONPATH}}}}" python3 -m auto_changelog_release_action
        git log -1 --pretty=%s > /fixtures/head_subject.txt
        git status --short > /fixtures/status.txt
        cp CHANGELOG.md /fixtures/generated_CHANGELOG.md
        cp /tmp/github_output /fixtures/github_output.txt
        cp /tmp/github_env /fixtures/github_env.txt
        """
    ).strip()

    run_podman_script(
        podman,
        action_root=action_root,
        fixtures_root=tmp_path,
        image=image,
        script=container_script,
    )

    assert (tmp_path / "head_subject.txt").read_text(encoding="utf-8").strip() == (
        "chore(changelog): update unreleased changelog"
    )
    assert (tmp_path / "status.txt").read_text(encoding="utf-8").strip() == "?? cliff.toml"

    github_output = (tmp_path / "github_output.txt").read_text(encoding="utf-8")
    github_env = (tmp_path / "github_env.txt").read_text(encoding="utf-8")
    changelog = (tmp_path / "generated_CHANGELOG.md").read_text(encoding="utf-8")

    assert "version_bumped=false" in github_output
    assert "version_changed=false" in github_output
    assert "release_created=false" in github_output
    assert "release_prerelease=false" in github_output
    assert "release_tag=" in github_output
    assert "VERSION_BUMPED=false" in github_env
    assert "VERSION_CHANGED=false" in github_env
    assert "RELEASE_CREATED=false" in github_env
    assert "RELEASE_PRERELEASE=false" in github_env
    assert "RELEASE_TAG=" in github_env
    assert "All notable changes to this project will be documented in this file." in changelog
    assert remote_branch_subject(remote_root, "main") == (
        "chore(changelog): update unreleased changelog"
    )
