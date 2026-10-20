from __future__ import annotations

import json

from auto_changelog_release_action.changelog_context import (
    PRE_RELEASE_LABELS,
    augment_context_entries,
    augment_context_json,
    augment_merge_commits,
    collect_prerelease_commits,
    ensure_target_release_entry,
    extract_type,
    flag_pre_release,
    inject_prerelease_commits,
    parse_version_parts,
)


def test_ensure_target_release_entry_adds_missing_maintenance_release() -> None:
    context = '[{"version":"v1.0.0","commits":[]}]'
    result = ensure_target_release_entry(
        context,
        tag="v1.0.1",
        commit_id="release-commit",
        timestamp=1768500000,
        repository="/repo",
    )
    entries = json.loads(result)
    assert [entry["version"] for entry in entries] == ["v1.0.1", "v1.0.0"]
    assert entries[0]["commits"] == []
    assert entries[0]["previous"]["version"] == "v1.0.0"
    assert entries[0]["timestamp"] == 1768500000
    assert entries[0]["commit_id"] == "release-commit"


def test_ensure_target_release_entry_preserves_prerelease_marker() -> None:
    result = ensure_target_release_entry(
        "[]",
        tag="v1.0.1-pre.1",
        commit_id="release-commit",
        timestamp=1768500000,
        repository="/repo",
    )
    entry = json.loads(result)[0]
    assert entry["extra"]["pre_release"] is True
    assert entry["previous"] is None


def test_ensure_target_release_entry_preserves_existing_release() -> None:
    context = '[{"version":"v1.0.1","commits":[{"id":"real"}]}]'
    assert (
        ensure_target_release_entry(
            context,
            tag="v1.0.1",
            commit_id="ignored",
            timestamp=1768500000,
            repository="/repo",
        )
        == context
    )


def test_extract_type_reads_conventional_commit_type() -> None:
    assert extract_type("feat(auth): add oauth flow") == "feat"
    assert extract_type("Merge branch 'feature/x'") is None


def test_parse_version_parts_keeps_only_configured_prereleases() -> None:
    assert parse_version_parts("v1.2.3") == ("v1.2.3", None)
    assert parse_version_parts("v1.2.3-pre.4") == ("v1.2.3", "pre.4")
    assert parse_version_parts("v1.2.3-miktex.26.2") == ("v1.2.3", None)
    assert PRE_RELEASE_LABELS == frozenset({"pre", "alpha", "beta"})


def test_augment_merge_commits_embeds_children_and_marks_mismatches() -> None:
    entry = {
        "commits": [
            {
                "id": "merge-1",
                "merge_commit": True,
                "raw_message": "feat(core): merge feature branch",
                "message": "merge feature branch",
            },
            {
                "id": "child-1",
                "raw_message": "feat(core): add endpoint",
                "message": "add endpoint",
            },
            {
                "id": "child-2",
                "raw_message": "fix(core): repair parser",
                "message": "repair parser",
            },
        ]
    }

    augment_merge_commits(
        entry,
        parents_for_merge=lambda merge_id: [merge_id, "main-parent", "topic-parent"],
        commits_between=lambda parent, merge: ["child-1", "child-2"],
    )

    assert [commit["id"] for commit in entry["commits"]] == ["merge-1"]
    children = entry["commits"][0]["extra"]["children"]
    assert [child["id"] for child in children] == ["child-1", "child-2"]
    assert children[1]["extra"]["mismatch_type"] == "fix"


def test_collect_and_inject_prerelease_commits_reuses_unique_commits() -> None:
    prerelease_entry = {
        "version": "v1.2.3-pre.1",
        "commits": [
            {"id": "a1", "message": "add prerelease feature"},
            {"id": "a1", "message": "duplicate should be ignored"},
        ],
    }
    stable_entry = {
        "version": "v1.2.3",
        "commits": [{"id": "stable-1", "message": "ship stable release"}],
    }

    prerelease_commits = collect_prerelease_commits([prerelease_entry, stable_entry])
    inject_prerelease_commits([stable_entry], prerelease_commits)

    commits = stable_entry["commits"]
    assert [commit["id"] for commit in commits] == ["stable-1", "a1"]
    assert commits[1]["extra"]["from_prerelease"] == "v1.2.3-pre.1"


def test_flag_pre_release_sets_extra_flag() -> None:
    entry = {"version": "v1.2.3-alpha.2"}

    flag_pre_release(entry)

    assert entry["extra"]["pre_release"] is True


def test_augment_context_entries_runs_full_prerelease_flow() -> None:
    prerelease_entry = {
        "version": "v2.0.0-pre.1",
        "commits": [{"id": "pre-1", "message": "preview feature"}],
    }
    stable_entry = {
        "version": "v2.0.0",
        "commits": [{"id": "stable-2", "message": "ship stable"}],
    }

    entries = augment_context_entries([prerelease_entry, stable_entry])

    assert entries[0]["extra"]["pre_release"] is True
    assert entries[1]["extra"]["pre_release"] is False
    assert [commit["id"] for commit in entries[1]["commits"]] == ["stable-2", "pre-1"]


def test_augment_context_json_returns_augmented_json() -> None:
    context_json = (
        '[{"version": "v2.0.0-pre.1", "commits": [{"id": "pre-1", "message": "preview"}]}, '
        '{"version": "v2.0.0", "commits": []}]'
    )

    augmented_json = augment_context_json(context_json)

    assert '"pre_release": true' in augmented_json
    assert '"from_prerelease": "v2.0.0-pre.1"' in augmented_json
