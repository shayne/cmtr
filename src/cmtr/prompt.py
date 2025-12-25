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
        "Use the provided staged diff and commit history examples to match the repository's style. "
        "The user prompt uses XML-style tags (e.g. <diff_patch>, <log_examples>) and CDATA blocks "
        "to label sections; treat those tags as semantic separators, not content.\n"
        "Rules:\n"
        "- Output ONLY the commit message text (subject line, optional body).\n"
        "- Use imperative mood and be specific about the change.\n"
        "- Follow the style patterns in the examples (prefixes, casing, punctuation, body formatting).\n"
        "- Match body usage to the examples: include a body when bodies are common; omit it when they are not unless essential.\n"
        "- If a body is needed, separate it from the subject with a blank line.\n"
        "- Keep the subject concise (aim ~50 chars unless examples show otherwise)."
    )


def build_user_prompt(context: PromptContext) -> str:
    lines: list[str] = []
    lines.append("<context>")
    if context.name_status:
        lines.append('  <staged_files format="name-status">')
        lines.append(_wrap_cdata(context.name_status))
        lines.append("  </staged_files>")
    if context.diff_stat:
        lines.append('  <diff_stat format="git-diff-stat">')
        lines.append(_wrap_cdata(context.diff_stat))
        lines.append("  </diff_stat>")
    if context.diff_patch:
        attrs: list[str] = []
        if context.diff_was_truncated:
            attrs.append('truncated="true"')
        if context.diff_was_filtered:
            attrs.append('filtered="true"')
        attr_text = f" {' '.join(attrs)}" if attrs else ""
        lines.append(f'  <diff_patch format="git-diff"{attr_text}>')
        lines.append(_wrap_cdata(context.diff_patch))
        lines.append("  </diff_patch>")
    if context.log_contexts:
        lines.append("  <log_examples>")
        for log_context in context.log_contexts:
            path = _xml_escape(log_context.path)
            lines.append(f'    <path name="{path}">')
            for idx, entry in enumerate(log_context.entries, start=1):
                lines.append(f'      <commit index="{idx}">')
                lines.append(f"        <subject>{_xml_escape(entry.subject)}</subject>")
                if entry.body:
                    body_lines = entry.body.splitlines()
                    if context.max_log_body_lines > 0:
                        body_lines = body_lines[: context.max_log_body_lines]
                    if body_lines:
                        body_text = "\n".join(body_lines)
                        lines.append(f"        <body>{_xml_escape(body_text)}</body>")
                lines.append("      </commit>")
            lines.append("    </path>")
        lines.append("  </log_examples>")
    elif not context.has_commit_history:
        lines.append('  <commit_history status="none" />')
        lines.append("  <fallback_guidance>")
        lines.append(
            _wrap_cdata(
                "Default to common git commit conventions: a concise imperative subject"
                " (aim for ~50 characters) and add a body only when it clarifies why or"
                " impact. If a body is needed, separate it with a blank line and wrap"
                " lines around 72 characters. If you choose to add a type/scope prefix,"
                " follow Conventional Commits (<type>(scope): <description>)."
            )
        )
        lines.append("  </fallback_guidance>")
    lines.append("</context>")
    return "\n".join(lines).strip()


def _wrap_cdata(text: str) -> str:
    if text is None:
        return "<![CDATA[]]>"
    safe_text = text.replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{safe_text}]]>"


def _xml_escape(text: str) -> str:
    if text is None:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
