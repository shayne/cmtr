from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Iterable, Sequence

from .errors import GitError, UserError


@dataclass(frozen=True)
class CommitMessage:
    subject: str
    body: str


@dataclass(frozen=True)
class LogContext:
    path: str
    entries: list[CommitMessage]


@dataclass(frozen=True)
class DiffNumStat:
    path: str
    added: int | None
    deleted: int | None
    is_binary: bool
    path_before: str | None = None


@dataclass(frozen=True)
class HooksPathEntry:
    origin: str
    path: str


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


def get_hooks_dir(repo_root: Path, *, use_global: bool = False) -> Path:
    entries = _get_hooks_path_entries(repo_root)
    local_config = _get_local_config_path(repo_root)
    local_entry: HooksPathEntry | None = None
    global_entry: HooksPathEntry | None = None
    for entry in entries:
        origin_path = _origin_path(entry.origin, repo_root)
        if origin_path and _same_path(origin_path, local_config):
            local_entry = entry
        else:
            global_entry = entry

    if use_global:
        if global_entry:
            return _resolve_hooks_path(repo_root, global_entry.path)
        raise UserError(
            "core.hooksPath is not set globally. Configure it with:\n"
            "  git config --global core.hooksPath <path>"
        )

    if local_entry:
        return _resolve_hooks_path(repo_root, local_entry.path)

    if global_entry:
        raise UserError(
            "core.hooksPath is set in global git config. "
            "Re-run with --global to install/remove the hook there, or set a "
            "repo-local hooks path with:\n"
            "  git config --local core.hooksPath .git/hooks\n"
            "Then re-run cmtr."
        )

    output = run_git(["rev-parse", "--git-path", "hooks"], repo_root)
    return Path(output.strip())


def parse_hooks_path_entries(output: str) -> list[HooksPathEntry]:
    entries: list[HooksPathEntry] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = _split_origin_line(line)
        if not parsed:
            continue
        origin, rest = parsed
        key, value = _split_key_value(rest)
        if not key:
            continue
        if key.lower() != "core.hookspath":
            continue
        if not value:
            continue
        entries.append(HooksPathEntry(origin=origin, path=value))
    return entries


def _get_hooks_path_entries(repo_root: Path) -> list[HooksPathEntry]:
    output = run_git(["config", "--show-origin", "--list"], repo_root)
    return parse_hooks_path_entries(output)


def _get_local_config_path(repo_root: Path) -> Path:
    output = run_git(["rev-parse", "--git-path", "config"], repo_root)
    path = Path(output.strip())
    if not path.is_absolute():
        path = repo_root / path
    return path


def _resolve_hooks_path(repo_root: Path, hooks_path: str) -> Path:
    path = Path(hooks_path).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path


def _origin_path(origin: str, repo_root: Path) -> Path | None:
    if not origin.startswith("file:"):
        return None
    path = Path(origin[5:])
    if not path.is_absolute():
        path = repo_root / path
    return path


def _split_origin_line(line: str) -> tuple[str, str] | None:
    if "\t" in line:
        origin, rest = line.split("\t", 1)
        return origin, rest.strip()
    parts = line.split(None, 1)
    if len(parts) < 2:
        return None
    return parts[0], parts[1].strip()


def _split_key_value(text: str) -> tuple[str | None, str]:
    if "=" not in text:
        return None, text.strip()
    key, value = text.split("=", 1)
    return key.strip(), value.strip()


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def get_staged_files(repo_root: Path) -> list[str]:
    output = run_git(["diff", "--cached", "--name-only", "-z"], repo_root)
    entries = [entry for entry in output.split("\0") if entry]
    return entries


def get_name_status(repo_root: Path) -> str:
    return run_git(["diff", "--cached", "--name-status"], repo_root).strip()


def get_diff_stat(repo_root: Path) -> str:
    return run_git(["diff", "--cached", "--stat"], repo_root).strip()


def get_diff_patch(repo_root: Path, paths: Sequence[str] | None = None) -> str:
    args = ["diff", "--cached"]
    if paths:
        args.extend(["--", *paths])
    return run_git(args, repo_root)


def get_diff_numstat(repo_root: Path) -> list[DiffNumStat]:
    output = run_git(["diff", "--cached", "--numstat", "-z"], repo_root)
    if not output:
        return []
    parts = output.split("\0")
    entries: list[DiffNumStat] = []
    index = 0
    while index < len(parts):
        header = parts[index]
        index += 1
        if not header:
            continue
        fields = header.split("\t")
        if len(fields) < 3:
            continue
        added_raw, deleted_raw, path = fields[0], fields[1], fields[2]
        is_binary = added_raw == "-" or deleted_raw == "-"
        added = None if is_binary else int(added_raw)
        deleted = None if is_binary else int(deleted_raw)
        if path == "":
            if index + 1 >= len(parts):
                break
            path_before = parts[index]
            path_after = parts[index + 1]
            index += 2
            entries.append(
                DiffNumStat(
                    path=path_after,
                    added=added,
                    deleted=deleted,
                    is_binary=is_binary,
                    path_before=path_before,
                )
            )
        else:
            entries.append(
                DiffNumStat(
                    path=path,
                    added=added,
                    deleted=deleted,
                    is_binary=is_binary,
                )
            )
    return entries


def gather_log_context(
    repo_root: Path,
    staged_files: Sequence[str],
    max_paths: int,
    max_entries: int,
) -> list[LogContext]:
    if max_paths <= 0 or max_entries <= 0:
        return []
    target_entries = min(max_entries, 10)
    if target_entries <= 0:
        return []
    changed_lines = _build_changed_line_map(repo_root, staged_files)
    log_paths = _select_log_paths(staged_files, max_paths, changed_lines)
    contexts: list[LogContext] = []
    seen: set[tuple[str, str]] = set()
    primary_entries: list[CommitMessage] = []
    if log_paths:
        primary_path = log_paths[0]
        primary_entries = _get_log_entries(repo_root, primary_path, target_entries)
        primary_entries = _dedupe_entries(primary_entries, seen)
        if primary_entries:
            contexts.append(LogContext(path=primary_path, entries=primary_entries))
    if len(primary_entries) < target_entries:
        remaining = target_entries - len(primary_entries)
        repo_entries = _get_log_entries(repo_root, None, max_entries)
        repo_entries = _dedupe_entries(repo_entries, seen)
        if remaining < len(repo_entries):
            repo_entries = repo_entries[:remaining]
        if repo_entries:
            contexts.append(LogContext(path="repository", entries=repo_entries))
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


def _dedupe_entries(
    entries: Sequence[CommitMessage],
    seen: set[tuple[str, str]],
) -> list[CommitMessage]:
    unique: list[CommitMessage] = []
    for entry in entries:
        key = (entry.subject, entry.body)
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def _select_log_paths(
    staged_files: Sequence[str],
    max_paths: int,
    changed_lines: dict[str, int],
) -> list[str]:
    if not staged_files or max_paths <= 0:
        return []
    staged_files = [file for file in staged_files if file]
    shared = _common_prefix(staged_files)
    if not shared:
        fallback = _best_changed_path(staged_files, changed_lines)
        return [fallback] if fallback else []
    return [shared]


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


def _build_changed_line_map(
    repo_root: Path, staged_files: Sequence[str]
) -> dict[str, int]:
    if not staged_files:
        return {}
    staged_set = {file for file in staged_files if file}
    if not staged_set:
        return {}
    try:
        entries = get_diff_numstat(repo_root)
    except GitError:
        return {}
    changed: dict[str, int] = {}
    for entry in entries:
        if entry.path not in staged_set:
            continue
        added = entry.added or 0
        deleted = entry.deleted or 0
        changed[entry.path] = changed.get(entry.path, 0) + added + deleted
    return changed


def _best_changed_path(
    staged_files: Sequence[str],
    changed_lines: dict[str, int],
) -> str:
    if not staged_files:
        return ""
    scores: dict[str, int] = {}
    for file in staged_files:
        if not file:
            continue
        parent = str(Path(file).parent)
        key = file if parent == "." else parent
        scores[key] = scores.get(key, 0) + changed_lines.get(file, 0)
    if not scores:
        return ""
    ordered = sorted(
        scores.items(),
        key=lambda item: (-item[1], -len(_split_parts(item[0])), item[0]),
    )
    return ordered[0][0]
