from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .config import Config
from .errors import CodexError, UserError
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
from .codex_client import (
    DEFAULT_CODEX_MODEL,
    codex_status,
    generate_commit_message_with_codex,
    is_codex_available,
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
    api_key: str | None,
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
    backend = select_backend(config, api_key)
    if backend == "codex":
        try:
            return generate_commit_message_with_codex(
                repo_root=repo_root,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=DEFAULT_CODEX_MODEL,
                api_key=api_key,
            )
        except CodexError as exc:
            if config.prefer_codex:
                raise UserError(
                    f"Codex failed: {exc}. Install/login to Codex."
                ) from exc
            raise UserError(
                f"Codex failed: {exc}. Install/login to Codex or set OPENAI_API_KEY."
            ) from exc
    if not api_key:
        raise UserError("OPENAI_API_KEY is not set in the environment.")
    return generate_commit_message(
        config=config,
        api_key=api_key,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )


def resolve_repo_root(cwd: Path) -> Path:
    return get_repo_root(cwd)


def select_backend(config: Config, api_key: str | None) -> str:
    if config.prefer_codex:
        _ensure_codex_available(prefer_codex=True)
        return "codex"
    if api_key:
        return "openai"
    if is_codex_available():
        return "codex"
    _raise_codex_unavailable()
    return "openai"


def describe_auth_mode(config: Config, api_key: str | None) -> tuple[str, str | None]:
    if config.prefer_codex:
        status = codex_status()
        if status.codex_path is None and status.npx_path is None:
            return (
                "error",
                "Codex is not installed. Install Codex or run `npx @openai/codex@latest`.",
            )
        if not status.auth_exists:
            return (
                "error",
                "Codex auth not found. Run `codex` or `npx @openai/codex@latest` to sign in.",
            )
        return ("codex", None)
    if api_key:
        return ("openai", None)
    if is_codex_available():
        return ("codex", None)
    return (
        "error",
        "OPENAI_API_KEY is not set and Codex is not available. "
        "Set OPENAI_API_KEY or run `npx @openai/codex@latest` to sign in.",
    )


def _raise_codex_unavailable() -> None:
    raise UserError(
        "OPENAI_API_KEY is not set and Codex is not available. "
        "Set OPENAI_API_KEY or run `npx @openai/codex@latest` to sign in."
    )


def _ensure_codex_available(*, prefer_codex: bool) -> None:
    status = codex_status()
    if status.codex_path is None and status.npx_path is None:
        raise UserError(
            "Codex is not installed. Install Codex or run `npx @openai/codex@latest`."
        )
    if not status.auth_exists:
        message = (
            "Codex auth not found. Run `codex` or `npx @openai/codex@latest` to sign in."
        )
        if prefer_codex:
            raise UserError(message)
        raise UserError(message)


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
