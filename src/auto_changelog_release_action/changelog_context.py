"""Enriches git-cliff JSON context with merge metadata and prerelease carry-over."""

from __future__ import annotations

import copy
import json
import re
import subprocess
from collections.abc import Callable, Iterable
from typing import Any

from auto_changelog_release_action.versioning import PRE_RELEASE_LABELS, parse_version

JsonDict = dict[str, Any]
ContextEntries = list[Any]
CommitsBetweenFn = Callable[[str, str], list[str]]
ParentsForMergeFn = Callable[[str], list[str]]


def extract_type(raw_message: str) -> str | None:
    """Extract a conventional-commit style type from a commit message."""

    match = re.match(r"^(\w+)(?:\([^)]+\))?:", raw_message.strip())
    return match.group(1) if match else None


def git_commits_between(parent: str, merge: str) -> list[str]:
    """List non-merge commits between a mainline parent and a merge commit."""

    output = subprocess.check_output(
        ["git", "rev-list", f"{parent}..{merge}", "--no-merges"],
        text=True,
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def get_merge_parents(merge_commit_id: str) -> list[str]:
    """Return the merge commit id followed by its parent ids."""

    output = subprocess.check_output(
        ["git", "rev-list", "--parents", "-n", "1", merge_commit_id],
        text=True,
    ).strip()
    return output.split()


def parse_version_parts(version: str | None) -> tuple[str, str | None] | None:
    """Normalize a version tag into its base tag and optional prerelease suffix."""

    if not isinstance(version, str):
        return None

    normalized = version.strip()
    if not normalized.startswith("v"):
        return None

    try:
        parsed = parse_version(normalized[1:])
    except ValueError:
        return None

    base_version = f"v{parsed.core}"
    if parsed.label and parsed.label not in PRE_RELEASE_LABELS:
        return base_version, None

    suffix = None
    if parsed.label:
        suffix = parsed.label
        if parsed.tail:
            suffix = f"{suffix}.{parsed.tail}"

    return base_version, suffix


def augment_merge_commits(
    entry: JsonDict,
    *,
    parents_for_merge: ParentsForMergeFn = get_merge_parents,
    commits_between: CommitsBetweenFn = git_commits_between,
) -> None:
    """Attach merged child commits to merge entries and flag type mismatches."""

    commits = entry.get("commits") or []
    commits_by_id = {commit["id"]: commit for commit in commits}
    new_commits: list[JsonDict] = []
    consumed: set[str] = set()

    for commit in commits:
        if commit.get("merge_commit"):
            parents = parents_for_merge(commit["id"])
            merge_id, *parent_ids = parents
            parent_type = extract_type(commit.get("raw_message", ""))

            if len(parent_ids) >= 2:
                mainline = parent_ids[0]
                children_ids = commits_between(mainline, merge_id)

                children: list[JsonDict] = []
                for child_id in children_ids:
                    if child_id not in commits_by_id:
                        continue

                    child = commits_by_id[child_id]
                    child_type = extract_type(child.get("raw_message", ""))
                    if child_type and parent_type and child_type != parent_type:
                        extra = child.get("extra") if isinstance(child.get("extra"), dict) else {}
                        extra["mismatch_type"] = child_type
                        child["extra"] = extra
                    children.append(child)
                    consumed.add(child_id)

                extra = commit.get("extra") if isinstance(commit.get("extra"), dict) else {}
                extra["children"] = children
                commit["extra"] = extra

        new_commits.append(commit)

    entry["commits"] = [commit for commit in new_commits if commit["id"] not in consumed]


def collect_prerelease_commits(entries: Iterable[Any]) -> dict[str, list[JsonDict]]:
    """Collect prerelease commits keyed by their base release version."""

    per_base: dict[str, list[JsonDict]] = {}
    per_base_seen: dict[str, set[str]] = {}

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        parsed = parse_version_parts(entry.get("version"))
        if not parsed:
            continue
        base_version, suffix = parsed
        if not suffix:
            continue

        commits = entry.get("commits")
        if not isinstance(commits, list):
            continue

        bucket = per_base.setdefault(base_version, [])
        seen_ids = per_base_seen.setdefault(base_version, set())

        for commit in commits:
            if not isinstance(commit, dict):
                continue
            commit_id = commit.get("id")
            if not commit_id or commit_id in seen_ids:
                continue

            seen_ids.add(commit_id)
            bucket.append(
                {
                    "id": commit_id,
                    "tag": entry.get("version"),
                    "commit": commit,
                }
            )

    return per_base


def inject_prerelease_commits(
    entries: Iterable[Any], prerelease_commits: dict[str, list[JsonDict]]
) -> None:
    """Copy prerelease commits into the matching final release entry."""

    if not prerelease_commits:
        return

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        parsed = parse_version_parts(entry.get("version"))
        if not parsed:
            continue
        base_version, suffix = parsed
        if suffix:
            continue

        bucket = prerelease_commits.get(base_version)
        if not bucket:
            continue

        commits = entry.get("commits")
        if not isinstance(commits, list):
            continue

        existing_ids = {commit.get("id") for commit in commits if isinstance(commit, dict)}
        for payload in bucket:
            commit_id = payload["id"]
            if commit_id in existing_ids:
                continue

            clone = copy.deepcopy(payload["commit"])
            extra = clone.get("extra") if isinstance(clone.get("extra"), dict) else {}
            extra["from_prerelease"] = payload["tag"]
            clone["extra"] = extra
            commits.append(clone)
            existing_ids.add(commit_id)


def flag_pre_release(entry: JsonDict) -> None:
    """Mark an entry with a pre_release flag in its extra metadata."""

    parsed = parse_version_parts(entry.get("version"))
    if parsed is None:
        return

    extra = entry.get("extra")
    if not isinstance(extra, dict):
        extra = {}

    _base_version, prerelease_suffix = parsed
    extra["pre_release"] = prerelease_suffix is not None
    entry["extra"] = extra


def augment_context_entries(
    entries: ContextEntries,
    *,
    parents_for_merge: ParentsForMergeFn = get_merge_parents,
    commits_between: CommitsBetweenFn = git_commits_between,
) -> ContextEntries:
    """Apply all enrichment passes to parsed git-cliff context entries."""

    for entry in entries:
        if isinstance(entry, dict) and "commits" in entry:
            augment_merge_commits(
                entry,
                parents_for_merge=parents_for_merge,
                commits_between=commits_between,
            )

    prerelease_commits = collect_prerelease_commits(entries)
    inject_prerelease_commits(entries, prerelease_commits)

    for entry in entries:
        if isinstance(entry, dict):
            flag_pre_release(entry)

    return entries


def ensure_target_release_entry(
    context_json: str, *, tag: str, commit_id: str, timestamp: int, repository: str
) -> str:
    """Add a missing release when git-cliff drops all its skipped commits."""
    entries = json.loads(context_json)
    if any(isinstance(entry, dict) and entry.get("version") == tag for entry in entries):
        return context_json

    previous = entries[0] if entries else None
    release: JsonDict = {
        "version": tag,
        "message": None,
        "commits": [],
        "commit_id": commit_id,
        "timestamp": timestamp,
        "previous": previous,
        "repository": repository,
        "commit_range": None,
        "submodule_commits": {},
        "statistics": None,
        "extra": None,
        "bump_type": None,
        "github": {"contributors": []},
        "gitlab": {"contributors": []},
        "gitea": {"contributors": []},
        "bitbucket": {"contributors": []},
        "azure_devops": {"contributors": []},
    }
    flag_pre_release(release)
    entries.insert(0, release)
    return json.dumps(entries, indent=4)


def augment_context_json(
    context_json: str,
    *,
    parents_for_merge: ParentsForMergeFn = get_merge_parents,
    commits_between: CommitsBetweenFn = git_commits_between,
) -> str:
    """Parse, enrich, and re-serialize git-cliff context JSON."""

    entries = json.loads(context_json)
    augment_context_entries(
        entries,
        parents_for_merge=parents_for_merge,
        commits_between=commits_between,
    )
    return json.dumps(entries, indent=4)
