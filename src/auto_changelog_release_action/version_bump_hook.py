"""Execute an opt-in post-bump hook before the action owns the version commit."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from auto_changelog_release_action.process_utils import run_command, run_git, run_git_stdout
from auto_changelog_release_action.versioning import extract_version

# PATH and HOME are needed by runner-installed tools and their toolchain caches.
# Forward only named runtime/toolchain settings, never the entire runner environment.
HOOK_ENV_KEYS = (
    "PATH",
    "HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "CARGO_HOME",
    "RUSTUP_HOME",
    "RUSTUP_TOOLCHAIN",
)


@dataclass(frozen=True)
class HookContext:
    root: Path
    files: tuple[str, ...]
    head: str
    ref: str


def _status(root: Path) -> list[str]:
    result = run_git(
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--no-renames",
            "--ignore-submodules=none",
        ],
        cwd=root,
    )
    return [entry for entry in result.stdout.split("\0") if entry]


def _validate_file(root: Path, value: str, *, required: bool) -> str:
    path = Path(value)
    if (
        not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or ".git" in path.parts
    ):
        raise ValueError(f"Invalid repository-relative version bump file: {value!r}")
    target = root / path
    if target.resolve() != target or target.is_symlink():
        raise ValueError(f"Version bump file must not traverse symlinks: {value!r}")
    if (required or target.exists()) and not target.is_file():
        raise ValueError(f"Version bump file must be a regular file: {value!r}")
    return path.as_posix()


def prepare_hook(version_file: str, additional_files: str) -> HookContext:
    """Validate the opt-in hook prerequisites before modifying the version file."""
    root = Path(run_git_stdout(["rev-parse", "--show-toplevel"])).resolve()
    if Path.cwd().resolve() != root:
        raise RuntimeError("Post-version-bump hook requires the repository root")
    if _status(root):
        raise RuntimeError("Post-version-bump hook requires a clean worktree and index")
    primary = _validate_file(root, version_file, required=True)
    files = [primary]
    for line in additional_files.splitlines():
        if line.strip():
            files.append(_validate_file(root, line.strip(), required=False))
    return HookContext(
        root=root,
        files=tuple(dict.fromkeys(files)),
        head=run_git_stdout(["rev-parse", "HEAD"], cwd=root),
        ref=run_git_stdout(["rev-parse", "--symbolic-full-name", "HEAD"], cwd=root),
    )


def run_hook(
    context: HookContext,
    script: str,
    *,
    version_before: str,
    version_after: str,
    bump: str,
    version_regex: str,
) -> None:
    """Run trusted workflow code, then verify its effects before staging any files."""
    env = {key: os.environ[key] for key in HOOK_ENV_KEYS if key in os.environ}
    env.setdefault("PATH", os.defpath)
    env.update(
        VERSION_BEFORE=version_before,
        VERSION_AFTER=version_after,
        VERSION_BUMP=bump,
        VERSION_FILE=context.files[0],
    )
    result = run_command(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-s"],
        cwd=context.root,
        env=env,
        input_text=script,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    if (
        run_git_stdout(["rev-parse", "HEAD"], cwd=context.root) != context.head
        or run_git_stdout(["rev-parse", "--symbolic-full-name", "HEAD"], cwd=context.root)
        != context.ref
    ):
        raise RuntimeError("Post-version-bump hook must not change HEAD or the current branch")

    for entry in _status(context.root):
        if entry[:2] != "??" and entry[0] != " ":
            raise RuntimeError("Post-version-bump hook must not stage changes")
        if entry[3:] not in context.files:
            raise RuntimeError(f"Post-version-bump hook changed an undeclared file: {entry[3:]}")

    for file in context.files:
        _validate_file(context.root, file, required=True)
    primary = context.root / context.files[0]
    if extract_version(primary.read_text(encoding="utf-8"), version_regex) != version_after:
        raise RuntimeError("Post-version-bump hook changed the authoritative version")
