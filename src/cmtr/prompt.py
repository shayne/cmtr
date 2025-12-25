from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .git import LogContext


@dataclass(frozen=True)
class PromptContext:
    staged_files: Sequence[str]
    name_status: str
    diff_stat: str
    diff_patch: str
    log_contexts: Sequence[LogContext]
    max_log_body_lines: int
    diff_was_truncated: bool
    diff_was_filtered: bool
    has_commit_history: bool


def build_system_prompt() -> str:
    return (
        "You are an expert software engineer writing concise, accurate Git commit messages. "
        "Use the provided staged diff and commit history examples to match the repository's style.\n"
        "Rules:\n"
        "- Output ONLY the commit message text (subject line, optional body).\n"
        "- Use imperative mood and be specific about the change.\n"
        "- Follow the style patterns in the examples (prefixes, casing, punctuation, body formatting).\n"
        "- Prefer a single-line subject unless a body adds essential context.\n"
        "- If a body is needed, separate it from the subject with a blank line.\n"
        "- Keep the subject concise (aim ~50 chars unless examples show otherwise)."
    )


def build_user_prompt(context: PromptContext) -> str:
    lines: list[str] = []
    if context.name_status:
        lines.append("Staged files (name-status):")
        lines.append(context.name_status)
        lines.append("")
    if context.diff_stat:
        lines.append("Diff stat:")
        lines.append(context.diff_stat)
        lines.append("")
    if context.diff_patch:
        label = "Diff patch"
        qualifiers: list[str] = []
        if context.diff_was_truncated:
            qualifiers.append("truncated")
        if context.diff_was_filtered:
            qualifiers.append("filtered")
        if qualifiers:
            label += f" ({', '.join(qualifiers)})"
        lines.append(f"{label}:")
        lines.append(context.diff_patch)
        lines.append("")
    if context.log_contexts:
        lines.append("Recent commit message examples by path:")
        for log_context in context.log_contexts:
            lines.append(f"[{log_context.path}]")
            for idx, entry in enumerate(log_context.entries, start=1):
                lines.append(f"{idx}. {entry.subject}")
                if entry.body:
                    body_lines = entry.body.splitlines()
                    if context.max_log_body_lines > 0:
                        body_lines = body_lines[: context.max_log_body_lines]
                    if body_lines:
                        lines.extend(body_lines)
                lines.append("")
    elif not context.has_commit_history:
        lines.append("Commit history: none detected.")
        lines.append(
            "Default to common git commit conventions: a concise imperative subject"
            " (aim for ~50 characters) and add a body only when it clarifies why or"
            " impact. If a body is needed, separate it with a blank line and wrap"
            " lines around 72 characters. If you choose to add a type/scope prefix,"
            " follow Conventional Commits (<type>(scope): <description>)."
        )
    return "\n".join(lines).strip()
