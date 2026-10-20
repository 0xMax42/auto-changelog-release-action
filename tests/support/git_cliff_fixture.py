"""Deterministic Git histories for git-cliff golden-file integration tests."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

START_DATE = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


@dataclass
class GitCliffFixture:
    root: Path
    commit_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.git("init", "--initial-branch=main", "--object-format=sha1")
        self.git("config", "user.name", "Fixture User")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "tag.gpgsign", "false")
        self.git("config", "core.hooksPath", os.devnull)

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "Fixture User",
                "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "Fixture User",
                "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                "TZ": "UTC",
                "LC_ALL": "C",
            }
        )
        timestamp = START_DATE + timedelta(minutes=self.commit_count)
        date = timestamp.strftime("%Y-%m-%dT%H:%M:%S+0000")
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
        return env

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            env=self._environment(),
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def commit(self, subject: str, *, body: str | None = None) -> str:
        self.commit_count += 1
        marker = self.root / "history" / f"{self.commit_count:03d}.txt"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(subject + "\n", encoding="utf-8")
        self.git("add", ".")
        command = ["commit", "-m", subject]
        if body is not None:
            command.extend(["-m", body])
        self.git(*command)
        return self.git("rev-parse", "HEAD")

    def tag(self, name: str) -> None:
        self.git("tag", "-a", name, "-m", name)
