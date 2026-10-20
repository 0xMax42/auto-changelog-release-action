"""Builds the release changelog, pushes tags, and creates the remote release."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from auto_changelog_release_action.changelog_context import (
    augment_context_json,
    ensure_target_release_entry,
)
from auto_changelog_release_action.process_utils import run_command, run_git, run_git_stdout
from auto_changelog_release_action.runtime_host import RuntimeHost
from auto_changelog_release_action.versioning import PRE_RELEASE_LABELS, parse_version

RELEASE_COMMIT_MESSAGE_TEMPLATE = "chore(changelog): update changelog for v{version}"


@dataclass(frozen=True)
class ReleaseConfig:
    """Inputs required for publishing a release."""

    changelog_file: Path
    cliff_config: Path
    version: str
    git_branch: str
    api_url: str
    repository_owner: str
    repository_name: str
    publish_token: str
    host: RuntimeHost = RuntimeHost("github")
    trigger_release_workflows: bool = False
    git_cliff_binary: str = "git-cliff"


@dataclass(frozen=True)
class ReleaseFlowResult:
    """Result values exposed by the release publishing flow."""

    release_created: bool
    release_prerelease: bool
    release_tag: str


def is_configured_prerelease_version(version: str) -> bool:
    """Return whether a version should be published as a prerelease."""

    try:
        parsed = parse_version(version)
    except ValueError:
        return False

    return bool(parsed.label and parsed.label in PRE_RELEASE_LABELS and parsed.suffix)


def release_timestamp() -> int:
    """Return the timestamp for a release missing from the git-cliff context."""
    return int(time.time())


def generate_release_changelog(config: ReleaseConfig, *, cwd: Path) -> None:
    """Render the release changelog for the target tag."""

    tag_name = f"v{config.version}"
    print(f"📄 Generating changelog for tag {tag_name}")

    context = run_command(
        [config.git_cliff_binary, "-c", str(config.cliff_config), "-t", tag_name, "--context"],
        cwd=cwd,
    )
    augmented_context = augment_context_json(context.stdout)
    if not any(
        entry.get("version") == tag_name
        for entry in json.loads(augmented_context)
        if isinstance(entry, dict)
    ):
        augmented_context = ensure_target_release_entry(
            augmented_context,
            tag=tag_name,
            commit_id=run_git_stdout(["rev-parse", "HEAD"], cwd=cwd),
            timestamp=release_timestamp(),
            repository=str(cwd),
        )
    run_command(
        [
            config.git_cliff_binary,
            "-c",
            str(config.cliff_config),
            "-t",
            tag_name,
            "--from-context",
            "-",
            "-o",
            str(config.changelog_file),
        ],
        cwd=cwd,
        input_text=augmented_context,
    )


def extract_release_notes(changelog_text: str, version: str) -> str:
    """Extract the changelog section belonging to one release version."""

    heading_pattern = re.compile(rf"^## \[{re.escape(version)}\]")
    notes: list[str] = []
    collecting = False

    for line in changelog_text.splitlines():
        if heading_pattern.match(line):
            collecting = True
            heading = re.sub(r"^## ", "", line)
            heading = re.sub(r"\s*\(.*\)", "", heading)
            notes.append(heading)
            continue

        if collecting and re.match(r"^## \[", line):
            break

        if collecting:
            notes.append(line)

    if not notes:
        return ""
    return "\n".join(notes) + "\n"


def release_api_body(release_notes: str) -> str:
    """Drop the section heading before sending release notes to the API."""

    lines = release_notes.splitlines(keepends=True)
    return "".join(lines[1:])


def commit_release_changelog(config: ReleaseConfig, *, cwd: Path) -> bool:
    """Commit and push CHANGELOG.md if the release render changed it."""

    run_git(["add", str(config.changelog_file)], cwd=cwd)

    diff_result = run_git(["diff", "--cached", "--quiet"], cwd=cwd, check=False)
    if diff_result.returncode == 0:
        print("✅ No changes to commit")
        return False
    if diff_result.returncode != 1:
        raise RuntimeError(diff_result.stderr or diff_result.stdout or "git diff failed")

    print("📝 Committing updated changelog")
    run_git(
        ["commit", "-m", RELEASE_COMMIT_MESSAGE_TEMPLATE.format(version=config.version)],
        cwd=cwd,
    )
    run_git(["push", "origin", config.git_branch], cwd=cwd)
    return True


def tag_exists(tag_name: str, *, cwd: Path) -> bool:
    """Return whether the release tag already exists locally."""

    result = run_git(["rev-parse", tag_name], cwd=cwd, check=False)
    return result.returncode == 0


def create_release_tag(config: ReleaseConfig, release_notes: str, *, cwd: Path) -> bool:
    """Create and push the annotated release tag when it is still missing."""

    tag_name = f"v{config.version}"
    if tag_exists(tag_name, cwd=cwd):
        print(f"🔁 Tag {tag_name} already exists, skipping.")
        return False

    print(f"🏷️  Creating annotated tag {tag_name}")
    timestamp = int(time.time())
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = f"@{timestamp}"
    env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"]

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(release_notes)
            temp_path = Path(handle.name)

        run_git(
            ["tag", "-a", tag_name, "-F", str(temp_path), "--cleanup=verbatim"],
            cwd=cwd,
            env=env,
        )
        run_git(["push", "origin", tag_name], cwd=cwd)
        return True
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def create_release(
    config: ReleaseConfig,
    release_notes: str,
    *,
    prerelease: bool,
    max_attempts: int = 3,
    delay_seconds: int = 5,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bool:
    """Create the remote release with retries for transient failures."""

    if not config.publish_token:
        raise RuntimeError("Release publishing requires the explicit token input.")
    if not config.api_url:
        raise RuntimeError("Release API URL is not set")

    release_body = release_api_body(release_notes)
    endpoint = (
        f"{config.api_url.rstrip('/')}/repos/"
        f"{config.repository_owner}/{config.repository_name}/releases"
    )
    payload_data = {
        "tag_name": f"v{config.version}",
        "target_commitish": "main",
        "name": f"Release v{config.version}",
        "body": release_body,
        "draft": False,
        "prerelease": prerelease,
    }
    if config.host is RuntimeHost.GITEA and config.trigger_release_workflows:
        payload_data["trigger_workflows"] = True
    payload = json.dumps(payload_data).encode("utf-8")

    for attempt in range(1, max_attempts + 1):
        print(f"🚀 Try {attempt}/{max_attempts}: creating release v{config.version} …")

        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Authorization": f"token {config.publish_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        status: int | None = None
        response_text = ""
        try:
            with urllib.request.urlopen(request) as response:
                status = response.getcode()
                response_text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            status = error.code
            response_text = error.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as error:
            response_text = str(error.reason)

        if status == 201:
            print("✅ Release created (201).")
            return True
        if status == 409:
            print("🔁 Release already exists (409) – skipping.")
            return False

        suffix = status if status is not None else "request error"
        print(f"⚠️  Release attempt failed (HTTP {suffix})")
        if response_text:
            print(response_text)

        if attempt >= max_attempts:
            raise RuntimeError("❌ Giving up.")

        sleep_fn(delay_seconds * attempt)


def run_release_flow(config: ReleaseConfig, *, cwd: Path) -> ReleaseFlowResult:
    """Execute changelog generation, tagging, and release publication."""

    print(f"📦 Version: {config.version}")
    generate_release_changelog(config, cwd=cwd)

    changelog_text = config.changelog_file.read_text(encoding="utf-8")
    release_notes = extract_release_notes(changelog_text, config.version)

    commit_release_changelog(config, cwd=cwd)
    create_release_tag(config, release_notes, cwd=cwd)

    tag_name = f"v{config.version}"
    prerelease = is_configured_prerelease_version(config.version)
    if prerelease:
        print("ℹ️  Detected configured pre-release label.")

    release_created = create_release(config, release_notes, prerelease=prerelease)
    print("🎉 Workflow finished successfully.")
    return ReleaseFlowResult(
        release_created=release_created,
        release_prerelease=prerelease,
        release_tag=tag_name,
    )
