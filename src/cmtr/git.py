from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Iterable, Sequence

from .errors import GitError


@dataclass(frozen=True)
class CommitMessage:
    subject: str
    body: str


@dataclass(frozen=True)
class LogContext:
    path: str
    entries: list[CommitMessage]


def run_git(args: Sequence[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        message = stderr or stdout or "Unknown git error"
        raise GitError(message)
    return result.stdout


def has_commits(repo_root: Path) -> bool:
    try:
        run_git(["rev-parse", "--verify", "HEAD"], repo_root)
    except GitError:
        return False
    return True


def get_repo_root(cwd: Path) -> Path:
    output = run_git(["rev-parse", "--show-toplevel"], cwd)
    return Path(output.strip())


def get_hooks_dir(repo_root: Path) -> Path:
    output = run_git(["rev-parse", "--git-path", "hooks"], repo_root)
    return Path(output.strip())


def get_staged_files(repo_root: Path) -> list[str]:
    output = run_git(["diff", "--cached", "--name-only", "-z"], repo_root)
    entries = [entry for entry in output.split("\0") if entry]
    return entries


def get_name_status(repo_root: Path) -> str:
    return run_git(["diff", "--cached", "--name-status"], repo_root).strip()


def get_diff_stat(repo_root: Path) -> str:
    return run_git(["diff", "--cached", "--stat"], repo_root).strip()


def get_diff_patch(repo_root: Path) -> str:
    return run_git(["diff", "--cached"], repo_root)


def gather_log_context(
    repo_root: Path,
    staged_files: Sequence[str],
    max_paths: int,
    max_entries: int,
) -> list[LogContext]:
    log_paths = _select_log_paths(staged_files, max_paths)
    contexts: list[LogContext] = []
    for path in log_paths:
        entries = _get_log_entries(repo_root, path, max_entries)
        if entries:
            contexts.append(LogContext(path=path, entries=entries))
    if not contexts:
        entries = _get_log_entries(repo_root, None, max_entries)
        if entries:
            contexts.append(LogContext(path="repository", entries=entries))
    return contexts


def _get_log_entries(
    repo_root: Path, path: str | None, max_entries: int
) -> list[CommitMessage]:
    if max_entries <= 0:
        return []
    args = [
        "log",
        f"--max-count={max_entries}",
        "--pretty=format:%s%n%b%n----END----",
    ]
    if path:
        args.extend(["--", path])
    try:
        output = run_git(args, repo_root)
    except GitError:
        return []
    entries: list[CommitMessage] = []
    for chunk in output.split("----END----"):
        text = chunk.strip("\n")
        if not text.strip():
            continue
        lines = text.splitlines()
        subject = lines[0].strip()
        body = "\n".join(line.rstrip() for line in lines[1:]).strip()
        entries.append(CommitMessage(subject=subject, body=body))
    return entries


def _select_log_paths(staged_files: Sequence[str], max_paths: int) -> list[str]:
    if not staged_files or max_paths <= 0:
        return []
    staged_files = [file for file in staged_files if file]
    paths: set[str] = set()
    shared = _common_prefix(staged_files)
    if shared:
        paths.add(shared)
    groups: dict[str, list[str]] = {}
    for file in staged_files:
        parts = _split_parts(file)
        if not parts:
            continue
        groups.setdefault(parts[0], []).append(file)
    for group_files in groups.values():
        if len(group_files) < 2:
            continue
        prefix = _common_prefix(group_files)
        if prefix:
            paths.add(prefix)
    for file in staged_files:
        if any(_is_prefix(path, file) for path in paths):
            continue
        parent = str(Path(file).parent)
        if parent == ".":
            paths.add(file)
        else:
            paths.add(parent)
    ordered = sorted(paths, key=lambda p: (-len(_split_parts(p)), p))
    return ordered[:max_paths]


def _split_parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def _common_prefix(paths: Sequence[str]) -> str:
    parts_list = [_split_parts(path) for path in paths if path]
    if not parts_list:
        return ""
    min_len = min(len(parts) for parts in parts_list)
    prefix: list[str] = []
    for index in range(min_len):
        segment = parts_list[0][index]
        if all(parts[index] == segment for parts in parts_list):
            prefix.append(segment)
        else:
            break
    return "/".join(prefix)


def _is_prefix(prefix: str, path: str) -> bool:
    prefix_parts = _split_parts(prefix)
    path_parts = _split_parts(path)
    if not prefix_parts:
        return False
    if len(prefix_parts) > len(path_parts):
        return False
    return path_parts[: len(prefix_parts)] == prefix_parts
