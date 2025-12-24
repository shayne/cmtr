from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .config import Config
from .errors import UserError
from .git import (
    LogContext,
    gather_log_context,
    get_diff_patch,
    get_diff_stat,
    get_name_status,
    get_repo_root,
    get_staged_files,
    has_commits,
)
from .openai_client import generate_commit_message
from .prompt import PromptContext, build_system_prompt, build_user_prompt


@dataclass(frozen=True)
class CommitContext:
    repo_root: Path
    staged_files: Sequence[str]
    name_status: str
    diff_stat: str
    diff_patch: str
    diff_was_truncated: bool
    log_contexts: Sequence[LogContext]
    has_commit_history: bool


def collect_context(repo_root: Path, config: Config) -> CommitContext:
    staged_files = get_staged_files(repo_root)
    if not staged_files:
        raise UserError("No staged changes found. Stage files before running cmtr.")
    name_status = get_name_status(repo_root)
    diff_stat = get_diff_stat(repo_root)
    diff_patch_raw = get_diff_patch(repo_root)
    diff_patch, diff_truncated = _truncate_diff(
        diff_patch_raw,
        max_bytes=config.max_diff_bytes,
        max_lines=config.max_patch_lines,
    )
    has_commit_history = has_commits(repo_root)
    if has_commit_history:
        log_contexts = gather_log_context(
            repo_root,
            staged_files,
            max_paths=config.max_log_paths,
            max_entries=config.max_log_entries,
        )
    else:
        log_contexts = []
    return CommitContext(
        repo_root=repo_root,
        staged_files=staged_files,
        name_status=name_status,
        diff_stat=diff_stat,
        diff_patch=diff_patch,
        diff_was_truncated=diff_truncated,
        log_contexts=log_contexts,
        has_commit_history=has_commit_history,
    )


def generate_message(
    repo_root: Path,
    config: Config,
    api_key: str,
) -> str:
    context = collect_context(repo_root, config)
    prompt_context = PromptContext(
        staged_files=context.staged_files,
        name_status=context.name_status,
        diff_stat=context.diff_stat,
        diff_patch=context.diff_patch,
        log_contexts=context.log_contexts,
        max_log_body_lines=config.max_log_body_lines,
        diff_was_truncated=context.diff_was_truncated,
        has_commit_history=context.has_commit_history,
    )
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(prompt_context)
    if not user_prompt:
        raise UserError("Unable to build prompt from staged changes.")
    return generate_commit_message(
        config=config,
        api_key=api_key,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )


def resolve_repo_root(cwd: Path) -> Path:
    return get_repo_root(cwd)


def _truncate_diff(diff: str, max_bytes: int, max_lines: int) -> tuple[str, bool]:
    truncated = False
    text = diff
    if max_lines > 0:
        lines = text.splitlines()
        if len(lines) > max_lines:
            text = "\n".join(lines[:max_lines])
            truncated = True
    if max_bytes > 0:
        encoded = text.encode("utf-8")
        if len(encoded) > max_bytes:
            text = _truncate_bytes(text, max_bytes)
            truncated = True
    return text, truncated


def _truncate_bytes(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes]
    while truncated and (truncated[-1] & 0b1100_0000) == 0b1000_0000:
        truncated = truncated[:-1]
    return truncated.decode("utf-8", errors="ignore")
