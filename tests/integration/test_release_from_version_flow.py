from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import textwrap
import threading
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from auto_changelog_release_action import action_runtime
from auto_changelog_release_action.release_flow import ReleaseConfig, run_release_flow
from auto_changelog_release_action.runtime_host import RuntimeHost
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


class ReleaseRequestRecorder:
    def __init__(self, status_code: int = 201) -> None:
        self.status_code = status_code
        self.requests: list[dict[str, object]] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._build_handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _build_handler(self):
        recorder = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                content_length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(content_length).decode("utf-8")
                recorder.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers.items()),
                        "body": json.loads(body),
                    }
                )
                self.send_response(recorder.status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": true}')

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                return

        return Handler

    @property
    def api_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> ReleaseRequestRecorder:
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def run_release_from_version(
    repo_root: Path,
    *,
    version_after: str,
    api_url: str,
    fake_output: str,
    github_ref: str = "refs/heads/main",
) -> str:
    action_root = Path(__file__).resolve().parents[2]
    bin_dir = repo_root.parent / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    write_fake_git_cliff(bin_dir)

    original_path = os.environ.get("PATH", "")
    original_output = os.environ.get("FAKE_GIT_CLIFF_OUTPUT")
    os.environ["PATH"] = f"{bin_dir}:{original_path}"
    os.environ["FAKE_GIT_CLIFF_OUTPUT"] = fake_output

    config = ReleaseConfig(
        changelog_file=repo_root / "CHANGELOG.md",
        cliff_config=repo_root / "cliff.toml",
        version=version_after,
        git_branch=github_ref.removeprefix("refs/heads/"),
        api_url=api_url,
        repository_owner="actions",
        repository_name="auto-changelog-release-action",
        publish_token="test-token",
    )

    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            run_release_flow(config, cwd=repo_root)
    finally:
        os.environ["PATH"] = original_path
        if original_output is None:
            os.environ.pop("FAKE_GIT_CLIFF_OUTPUT", None)
        else:
            os.environ["FAKE_GIT_CLIFF_OUTPUT"] = original_output

    return buffer.getvalue()


def run_action_runtime_from_environment(
    repo_root: Path,
    *,
    github_api_url: str,
    github_server_url: str,
    before_sha: str,
    head_sha: str,
    fake_output: str,
    monkeypatch,
) -> str:
    action_root = Path(__file__).resolve().parents[2]
    bin_dir = repo_root.parent / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    write_fake_git_cliff(bin_dir)

    github_output = repo_root.parent / "github_output.txt"
    github_env = repo_root.parent / "github_env.txt"
    github_output.write_text("", encoding="utf-8")
    github_env.write_text("", encoding="utf-8")

    monkeypatch.chdir(repo_root)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_GIT_CLIFF_OUTPUT", fake_output)
    monkeypatch.setenv("GITHUB_ACTION_PATH", str(action_root))
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    monkeypatch.setenv("AUTHOR_NAME", "Integration Test Bot")
    monkeypatch.setenv("AUTHOR_EMAIL", "integration@example.invalid")
    monkeypatch.setenv("ALLOW_NON_MAIN_RELEASE", "false")
    monkeypatch.setenv("VERSION_FILE", "VERSION")
    monkeypatch.setenv("VERSION_REGEX", "^(.*)$")
    monkeypatch.setenv("MAJOR_PATTERNS", "")
    monkeypatch.setenv("MINOR_PATTERNS", "")
    monkeypatch.setenv("PATCH_PATTERNS", "")
    monkeypatch.setenv("RANGE", f"{before_sha}..{head_sha}")
    monkeypatch.setenv("GITHUB_EVENT_BEFORE", before_sha)
    monkeypatch.setenv("GITHUB_SHA", head_sha)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_API_URL", github_api_url)
    monkeypatch.setenv("GITHUB_SERVER_URL", github_server_url)
    monkeypatch.setenv("GITHUB_REPOSITORY", "actions/auto-changelog-release-action")
    monkeypatch.setenv("RELEASE_PUBLISH_TOKEN", "test-token")
    monkeypatch.delenv("GITEA_API_URL", raising=False)
    monkeypatch.delenv("GITEA_SERVER_URL", raising=False)
    monkeypatch.delenv("GITEA_REPOSITORY", raising=False)
    monkeypatch.delenv("GITEA_REF", raising=False)
    monkeypatch.setattr(action_runtime, "install_git_cliff", lambda *_args, **_kwargs: "git-cliff")
    monkeypatch.setattr(action_runtime, "configure_git_author", lambda *_args: None)

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        config = action_runtime.config_from_environment()
        action_runtime.run_action_runtime(config)

    return buffer.getvalue()


def run_action_runtime_from_gitea_runner_environment(
    repo_root: Path,
    *,
    gitea_api_url: str,
    gitea_server_url: str,
    before_sha: str,
    head_sha: str,
    fake_output: str,
    monkeypatch,
) -> tuple[str, action_runtime.ActionRuntimeConfig]:
    action_root = Path(__file__).resolve().parents[2]
    bin_dir = repo_root.parent / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    write_fake_git_cliff(bin_dir)

    github_output = repo_root.parent / "github_output.txt"
    github_env = repo_root.parent / "github_env.txt"
    github_output.write_text("", encoding="utf-8")
    github_env.write_text("", encoding="utf-8")

    monkeypatch.chdir(repo_root)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_GIT_CLIFF_OUTPUT", fake_output)
    monkeypatch.setenv("GITHUB_ACTION_PATH", str(action_root))
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    monkeypatch.setenv("AUTHOR_NAME", "Integration Test Bot")
    monkeypatch.setenv("AUTHOR_EMAIL", "integration@example.invalid")
    monkeypatch.setenv("ALLOW_NON_MAIN_RELEASE", "false")
    monkeypatch.setenv("VERSION_FILE", "VERSION")
    monkeypatch.setenv("VERSION_REGEX", "^(.*)$")
    monkeypatch.setenv("MAJOR_PATTERNS", "")
    monkeypatch.setenv("MINOR_PATTERNS", "")
    monkeypatch.setenv("PATCH_PATTERNS", "")
    monkeypatch.setenv("RANGE", f"{before_sha}..{head_sha}")
    monkeypatch.setenv("GITHUB_EVENT_BEFORE", before_sha)
    monkeypatch.setenv("GITHUB_SHA", head_sha)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_REPOSITORY", "actions/auto-changelog-release-action")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITEA_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_API_URL", gitea_api_url)
    monkeypatch.setenv("GITEA_API_URL", gitea_api_url)
    monkeypatch.setenv("GITHUB_SERVER_URL", gitea_server_url)
    monkeypatch.setenv("RELEASE_PUBLISH_TOKEN", "test-token")
    monkeypatch.delenv("GITEA_SERVER_URL", raising=False)
    monkeypatch.delenv("GITEA_REPOSITORY", raising=False)
    monkeypatch.delenv("GITEA_REF", raising=False)
    monkeypatch.setattr(action_runtime, "install_git_cliff", lambda *_args, **_kwargs: "git-cliff")
    monkeypatch.setattr(action_runtime, "configure_git_author", lambda *_args: None)

    config = action_runtime.config_from_environment()
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        action_runtime.run_action_runtime(config)

    return buffer.getvalue(), config


def remote_branch_head(remote_root: Path, branch: str) -> str:
    completed = subprocess.run(
        ["git", "--git-dir", str(remote_root), "rev-parse", f"refs/heads/{branch}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def remote_tag_exists(remote_root: Path, tag_name: str) -> bool:
    completed = subprocess.run(
        ["git", "--git-dir", str(remote_root), "show-ref", "--tags", tag_name],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def test_release_from_version_generates_tags_pushes_and_publishes(tmp_path: Path) -> None:
    repo = init_local_git_repo(tmp_path)
    remote_root = init_local_bare_remote(tmp_path)
    repo.add_remote("origin", str(remote_root))
    repo.write("cliff.toml", "test\n")
    repo.commit_all("chore: initial import")
    repo.push("origin", "main", set_upstream=True)

    changelog_output = (
        "# Changelog\n\n"
        "## [1.2.3] (https://example.invalid/compare/v1.2.2..v1.2.3) - 2026-05-10\n"
        "- Added feature\n\n"
        "## [1.2.2] - 2026-05-01\n"
        "- Previous release\n"
    )

    with ReleaseRequestRecorder() as recorder:
        stdout = run_release_from_version(
            repo.root,
            version_after="1.2.3",
            api_url=recorder.api_url,
            fake_output=changelog_output,
        )

    assert "Workflow finished successfully" in stdout
    assert repo.read("CHANGELOG.md") == changelog_output
    assert repo.head_subject() == "chore(changelog): update changelog for v1.2.3"
    assert (
        repo.run("for-each-ref", "refs/tags/v1.2.3", "--format=%(subject)")
        == "[1.2.3] - 2026-05-10 - Added feature"
    )
    assert remote_branch_head(remote_root, "main") == repo.rev_parse("HEAD")
    assert remote_tag_exists(remote_root, "v1.2.3") is True
    assert len(recorder.requests) == 1
    payload = recorder.requests[0]["body"]
    assert recorder.requests[0]["path"] == "/repos/actions/auto-changelog-release-action/releases"
    assert payload == {
        "tag_name": "v1.2.3",
        "target_commitish": "main",
        "name": "Release v1.2.3",
        "body": "- Added feature\n\n",
        "draft": False,
        "prerelease": False,
    }


def test_release_from_version_marks_configured_prereleases(tmp_path: Path) -> None:
    repo = init_local_git_repo(tmp_path)
    remote_root = init_local_bare_remote(tmp_path)
    repo.add_remote("origin", str(remote_root))
    repo.write("cliff.toml", "test\n")
    repo.commit_all("chore: initial import")
    repo.push("origin", "main", set_upstream=True)

    changelog_output = (
        "# Changelog\n\n## [1.2.3-pre.1] (pre-release) - 2026-05-10\n- Preview feature\n"
    )

    with ReleaseRequestRecorder() as recorder:
        stdout = run_release_from_version(
            repo.root,
            version_after="1.2.3-pre.1",
            api_url=recorder.api_url,
            fake_output=changelog_output,
        )

    assert "Detected configured pre-release label" in stdout
    payload = recorder.requests[0]["body"]
    assert payload["tag_name"] == "v1.2.3-pre.1"
    assert payload["prerelease"] is True


def test_action_runtime_github_host_path_publishes_release(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo = init_local_git_repo(tmp_path)
    remote_root = init_local_bare_remote(tmp_path)
    repo.add_remote("origin", str(remote_root))
    repo.write("VERSION", "1.2.2\n")
    repo.write("CHANGELOG.md", "# Changelog\n")
    repo.commit_all("chore: initial import")
    repo.push("origin", "main", set_upstream=True)

    before_sha = repo.rev_parse("HEAD")
    repo.write("VERSION", "1.2.3\n")
    repo.commit_all("docs: prepare github runtime release")
    head_sha = repo.rev_parse("HEAD")

    changelog_output = (
        "# Changelog\n\n"
        "## [1.2.3] (https://github.example.invalid/actions/auto-changelog-release-action/compare/v1.2.2...v1.2.3) - 2026-05-10\n"
        "- Added feature\n\n"
        "## [1.2.2] - 2026-05-01\n"
        "- Previous release\n"
    )

    with ReleaseRequestRecorder() as recorder:
        stdout = run_action_runtime_from_environment(
            repo.root,
            github_api_url=recorder.api_url,
            github_server_url="https://github.example.invalid",
            before_sha=before_sha,
            head_sha=head_sha,
            fake_output=changelog_output,
            monkeypatch=monkeypatch,
        )

    assert "Workflow finished successfully" in stdout
    assert repo.read("CHANGELOG.md") == changelog_output
    assert repo.head_subject() == "chore(changelog): update changelog for v1.2.3"
    assert remote_branch_head(remote_root, "main") == repo.rev_parse("HEAD")
    assert remote_tag_exists(remote_root, "v1.2.3") is True
    github_output = (repo.root.parent / "github_output.txt").read_text(encoding="utf-8")
    github_env = (repo.root.parent / "github_env.txt").read_text(encoding="utf-8")
    assert "release_created=true" in github_output
    assert "release_prerelease=false" in github_output
    assert "release_tag=v1.2.3" in github_output
    assert "RELEASE_CREATED=true" in github_env
    assert "RELEASE_PRERELEASE=false" in github_env
    assert "RELEASE_TAG=v1.2.3" in github_env
    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert request["path"] == "/repos/actions/auto-changelog-release-action/releases"
    assert request["headers"]["Authorization"] == "token test-token"
    assert request["body"] == {
        "tag_name": "v1.2.3",
        "target_commitish": "main",
        "name": "Release v1.2.3",
        "body": "- Added feature\n\n",
        "draft": False,
        "prerelease": False,
    }


def test_action_runtime_gitea_mixed_runner_env_publishes_release(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo = init_local_git_repo(tmp_path)
    remote_root = init_local_bare_remote(tmp_path)
    repo.add_remote("origin", str(remote_root))
    repo.write("VERSION", "1.2.2\n")
    repo.write("CHANGELOG.md", "# Changelog\n")
    repo.commit_all("chore: initial import")
    repo.push("origin", "main", set_upstream=True)

    before_sha = repo.rev_parse("HEAD")
    repo.write("VERSION", "1.2.3\n")
    repo.commit_all("fix: prepare gitea runtime release")
    head_sha = repo.rev_parse("HEAD")

    changelog_output = (
        "# Changelog\n\n"
        "## [1.2.3] (https://git.example.invalid/actions/auto-changelog-release-action/compare/v1.2.2..v1.2.3) - 2026-05-10\n"
        "- Added feature\n\n"
        "## [1.2.2] - 2026-05-01\n"
        "- Previous release\n"
    )

    with ReleaseRequestRecorder() as recorder:
        stdout, config = run_action_runtime_from_gitea_runner_environment(
            repo.root,
            gitea_api_url=f"{recorder.api_url}/api/v1",
            gitea_server_url="https://git.example.invalid",
            before_sha=before_sha,
            head_sha=head_sha,
            fake_output=changelog_output,
            monkeypatch=monkeypatch,
        )

    assert config.host is RuntimeHost.GITEA
    assert config.api_url.endswith("/api/v1")
    assert config.server_url == "https://git.example.invalid"
    assert repo.read("cliff.toml").startswith("# git-cliff ~ default configuration file\n")
    assert "[remote.gitea]" in repo.read("cliff.toml")
    assert "/compare/{{ previous.version }}..{{ version }}" in repo.read("cliff.toml")
    assert 'replace = "https://git.example.invalid"' in repo.read("cliff.toml")
    assert "Workflow finished successfully" in stdout
    assert repo.read("CHANGELOG.md") == changelog_output
    assert repo.head_subject() == "chore(changelog): update changelog for v1.2.3"
    assert remote_branch_head(remote_root, "main") == repo.rev_parse("HEAD")
    assert remote_tag_exists(remote_root, "v1.2.3") is True
    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert request["path"] == "/api/v1/repos/actions/auto-changelog-release-action/releases"
    assert request["headers"]["Authorization"] == "token test-token"
    assert request["body"] == {
        "tag_name": "v1.2.3",
        "target_commitish": "main",
        "name": "Release v1.2.3",
        "body": "- Added feature\n\n",
        "draft": False,
        "prerelease": False,
    }
