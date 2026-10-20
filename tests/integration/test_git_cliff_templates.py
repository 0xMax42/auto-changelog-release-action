"""Check real git-cliff rendering against automatically discovered golden files."""

from __future__ import annotations

import json
import os
import runpy
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from auto_changelog_release_action import release_flow
from auto_changelog_release_action.cliff_config import ensure_cliff_config
from auto_changelog_release_action.release_flow import ReleaseConfig, generate_release_changelog
from auto_changelog_release_action.runtime_host import RuntimeHost
from auto_changelog_release_action.unreleased_changelog import (
    UnreleasedChangelogConfig,
    generate_unreleased_changelog,
)
from scripts.ensure_git_cliff import GIT_CLIFF_BINARY, GIT_CLIFF_VERSION
from tests.support.git_cliff_fixture import GitCliffFixture

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES_ROOT = Path(__file__).resolve().parent / "git_cliff_cases"
FIXED_GIT_CLIFF_TIME = "2026-01-15 18:00:00"
SERVER_URLS = {
    RuntimeHost.GITEA: "https://git.example.invalid",
    RuntimeHost.GITHUB: "https://github.com",
}


def _discover_cases() -> list[Path]:
    cases = sorted(path for path in CASES_ROOT.iterdir() if path.is_dir())
    if not cases:
        raise RuntimeError(f"No git-cliff test cases found in {CASES_ROOT}")
    return cases


def _frozen_git_cliff_bin(tmp_path: Path, executable: str) -> Path:
    """Wrap only git-cliff subprocesses in faketime, not Python or Git."""
    faketime = shutil.which("faketime")
    if faketime is None:
        pytest.fail("faketime is required for git-cliff golden tests")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "git-cliff"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(faketime)} -f {shlex.quote(FIXED_GIT_CLIFF_TIME)} "
        f'{shlex.quote(executable)} "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    # Exercise the wrapper directly; an invalid shebang can otherwise be skipped by PATH lookup.
    subprocess.run([str(wrapper), "--version"], check=True, capture_output=True, text=True)
    return bin_dir


@pytest.mark.integration
@pytest.mark.parametrize("case_dir", _discover_cases(), ids=lambda path: path.name)
def test_git_cliff_template(
    case_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = GIT_CLIFF_BINARY
    if not executable.is_file():
        pytest.fail("Cached git-cliff is missing; run `poetry run task ensure-git-cliff`")
    version = subprocess.run(
        [executable, "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert version == f"git-cliff {GIT_CLIFF_VERSION}"

    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    build = runpy.run_path(str(case_dir / "build.py"))["build"]
    fixture = GitCliffFixture(tmp_path / "repo")
    build(fixture)

    host = RuntimeHost(case["host"])
    cliff_config = fixture.root / "cliff.toml"
    ensure_cliff_config(
        cliff_config,
        templates_root=PROJECT_ROOT,
        host=host,
        repository="example/changelog-fixture",
        server_url=SERVER_URLS[host],
    )
    changelog = fixture.root / "CHANGELOG.md"

    # augment_context_json uses Git subprocesses without an explicit cwd.
    wrapped_bin = _frozen_git_cliff_bin(tmp_path, str(executable))
    with monkeypatch.context() as context:
        context.chdir(fixture.root)
        context.setenv("PATH", f"{wrapped_bin}{os.pathsep}{os.environ.get('PATH', '')}")
        context.setenv("GIT_CLIFF_OFFLINE", "true")
        context.setenv("TZ", "UTC")
        context.setattr(release_flow, "release_timestamp", lambda: 1768500000)
        if case["mode"] == "release":
            # The action renders the changelog before committing it and creating its tag.
            target_tag = f"v{case['version']}"
            assert fixture.git("tag", "--list", target_tag) == "", (
                f"Release fixture must not create its target tag {target_tag}"
            )
            generate_release_changelog(
                ReleaseConfig(
                    changelog_file=changelog,
                    cliff_config=cliff_config,
                    version=case["version"],
                    git_branch="main",
                    api_url="",
                    repository_owner="example",
                    repository_name="changelog-fixture",
                    publish_token="",
                    host=host,
                ),
                cwd=fixture.root,
            )
        elif case["mode"] == "unreleased":
            generate_unreleased_changelog(
                UnreleasedChangelogConfig(
                    changelog_file=changelog,
                    cliff_config=cliff_config,
                    git_branch="main",
                ),
                cwd=fixture.root,
            )
        else:
            pytest.fail(f"Unsupported case mode: {case['mode']}")

    actual = changelog.read_text(encoding="utf-8")
    golden = case_dir / "expected.md"
    if os.getenv("UPDATE_GIT_CLIFF_GOLDENS") == "1":
        golden.write_text(actual, encoding="utf-8")
    else:
        assert actual == golden.read_text(encoding="utf-8")
