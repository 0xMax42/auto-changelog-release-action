from __future__ import annotations

from pathlib import Path

from auto_changelog_release_action.cliff_config import (
    CLIFF_TEMPLATE_NAME,
    ensure_cliff_config,
    render_cliff_config_template,
    split_repository_slug,
)
from auto_changelog_release_action.runtime_host import RuntimeHost

EXAMPLE_GITEA_SERVER_URL = "https://git.example.invalid"


def test_split_repository_slug_matches_shell_behavior() -> None:
    assert split_repository_slug("actions/auto-changelog-release-action") == (
        "actions",
        "auto-changelog-release-action",
    )
    assert split_repository_slug("") == ("", "")
    assert split_repository_slug("standalone") == ("standalone", "standalone")


def test_render_cliff_config_template_replaces_all_placeholders() -> None:
    rendered = render_cliff_config_template(
        '[remote.%REMOTE_TYPE%]\nowner = "%OWNER%"\nrepo = "%REPO%"\nurl = "%SERVER_URL%"\ncompare = "%COMPARE_OPERATOR%"\n',
        host=RuntimeHost.GITEA,
        repository="actions/auto-changelog-release-action",
        server_url=EXAMPLE_GITEA_SERVER_URL,
    )

    assert "%REMOTE_TYPE%" not in rendered
    assert "%OWNER%" not in rendered
    assert "%REPO%" not in rendered
    assert "%COMPARE_OPERATOR%" not in rendered
    assert "%SERVER_URL%" not in rendered
    assert "[remote.gitea]" in rendered
    assert 'owner = "actions"' in rendered
    assert 'repo = "auto-changelog-release-action"' in rendered
    assert 'compare = ".."' in rendered
    assert f'url = "{EXAMPLE_GITEA_SERVER_URL}"' in rendered


def test_repo_template_keeps_host_placeholders() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    template_text = (repo_root / CLIFF_TEMPLATE_NAME).read_text(encoding="utf-8")

    assert "[remote.%REMOTE_TYPE%]" in template_text
    assert "remote.%REMOTE_TYPE%.owner" in template_text
    assert "/compare/{{ previous.version }}%COMPARE_OPERATOR%{{ version }}" in template_text
    assert "/releases/tag/{{ commit.extra.from_prerelease }}" in template_text


def test_real_checked_in_gitea_template_renders_expected_links() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    template_text = (repo_root / CLIFF_TEMPLATE_NAME).read_text(encoding="utf-8")

    rendered = render_cliff_config_template(
        template_text,
        host=RuntimeHost.GITEA,
        repository="actions/auto-changelog-release-action",
        server_url=EXAMPLE_GITEA_SERVER_URL,
    )

    assert "%REMOTE_TYPE%" not in rendered
    assert "%COMPARE_OPERATOR%" not in rendered
    assert "%SERVER_URL%" not in rendered
    assert "[remote.gitea]" in rendered
    assert 'replace = "https://git.example.invalid"' in rendered
    assert "<SERVER_URL>/{{ remote.gitea.owner }}/{{ remote.gitea.repo }}" in rendered
    assert "/compare/{{ previous.version }}..{{ version }}" in rendered
    assert "/commit/{{ commit.id }}" in rendered
    assert "/releases/tag/{{ commit.extra.from_prerelease }}" in rendered
    assert "[remote.github]" not in rendered
    assert "/compare/{{ previous.version }}...{{ version }}" not in rendered


def test_ensure_cliff_config_writes_rendered_template_when_missing(tmp_path: Path) -> None:
    (tmp_path / CLIFF_TEMPLATE_NAME).write_text(
        '[remote.%REMOTE_TYPE%]\nowner = "%OWNER%"\nrepo = "%REPO%"\nurl = "%SERVER_URL%"\ncompare = "%COMPARE_OPERATOR%"\n',
        encoding="utf-8",
    )
    cliff_path = tmp_path / "cliff.toml"

    created = ensure_cliff_config(
        cliff_path,
        templates_root=tmp_path,
        host=RuntimeHost.GITEA,
        repository="actions/auto-changelog-release-action",
        server_url="https://git.example.invalid",
    )

    assert created is True
    assert cliff_path.read_text(encoding="utf-8") == (
        "[remote.gitea]\n"
        'owner = "actions"\n'
        'repo = "auto-changelog-release-action"\n'
        'url = "https://git.example.invalid"\n'
        'compare = ".."\n'
    )


def test_ensure_cliff_config_preserves_existing_file(tmp_path: Path) -> None:
    (tmp_path / CLIFF_TEMPLATE_NAME).write_text("ignored", encoding="utf-8")
    cliff_path = tmp_path / "cliff.toml"
    cliff_path.write_text("existing", encoding="utf-8")

    created = ensure_cliff_config(
        cliff_path,
        templates_root=tmp_path,
        host=RuntimeHost.GITEA,
        repository="actions/auto-changelog-release-action",
        server_url=EXAMPLE_GITEA_SERVER_URL,
    )

    assert created is False
    assert cliff_path.read_text(encoding="utf-8") == "existing"


def test_ensure_cliff_config_renders_github_values_from_single_template(tmp_path: Path) -> None:
    (tmp_path / CLIFF_TEMPLATE_NAME).write_text(
        '[remote.%REMOTE_TYPE%]\nowner = "%OWNER%"\nrepo = "%REPO%"\nurl = "%SERVER_URL%"\ncompare = "%COMPARE_OPERATOR%"\n',
        encoding="utf-8",
    )
    cliff_path = tmp_path / "cliff.toml"

    created = ensure_cliff_config(
        cliff_path,
        templates_root=tmp_path,
        host=RuntimeHost.GITHUB,
        repository="actions/auto-changelog-release-action",
        server_url="https://github.com",
    )

    assert created is True
    assert cliff_path.read_text(encoding="utf-8") == (
        "[remote.github]\n"
        'owner = "actions"\n'
        'repo = "auto-changelog-release-action"\n'
        'url = "https://github.com"\n'
        'compare = "..."\n'
    )
