"""Shared subprocess wrappers for git and CLI commands used by the action."""

from __future__ import annotations

import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path


def _format_command(args: Sequence[str]) -> str:
    """Render a command for human-readable diagnostics."""

    return shlex.join(str(arg) for arg in args)


def _emit_process_failure(
    args: Sequence[str],
    *,
    returncode: int | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
    reason: str | None = None,
) -> None:
    """Print a concise diagnostic block for failed external commands."""

    print(f"External command failed: {_format_command(args)}", file=sys.stderr)
    if returncode is not None:
        print(f"Exit code: {returncode}", file=sys.stderr)
    if reason:
        print(reason, file=sys.stderr)
    if stdout:
        print("--- stdout ---", file=sys.stderr)
        print(stdout.rstrip(), file=sys.stderr)
    if stderr:
        print("--- stderr ---", file=sys.stderr)
        print(stderr.rstrip(), file=sys.stderr)


def run_command(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    stdin: int | None = None,
    check: bool = True,
    merge_stderr: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a command and capture text output with the action defaults."""

    command = list(args)

    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            input=input_text,
            stdin=stdin,
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
        )
    except subprocess.CalledProcessError as error:
        _emit_process_failure(
            error.cmd if isinstance(error.cmd, Sequence) else command,
            returncode=error.returncode,
            stdout=error.stdout,
            stderr=error.stderr,
        )
        raise
    except FileNotFoundError as error:
        _emit_process_failure(command, reason=str(error))
        raise


def run_command_stdout(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    check: bool = True,
    merge_stderr: bool = False,
) -> str:
    """Run a command and return stripped stdout."""

    return run_command(
        args,
        cwd=cwd,
        env=env,
        input_text=input_text,
        check=check,
        merge_stderr=merge_stderr,
    ).stdout.strip()


def run_git(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
    merge_stderr: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a git command with the shared subprocess settings."""

    return run_command(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=check,
        merge_stderr=merge_stderr,
    )


def run_git_stdout(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
    merge_stderr: bool = False,
) -> str:
    """Run a git command and return stripped stdout."""

    return run_git(
        args,
        cwd=cwd,
        env=env,
        check=check,
        merge_stderr=merge_stderr,
    ).stdout.strip()
