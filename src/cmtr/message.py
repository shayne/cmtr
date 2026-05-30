from __future__ import annotations

import json
import re


_LABEL_PREFIXES = (
    "commit message:",
    "suggested commit message:",
    "proposed commit message:",
    "recommended commit message:",
    "use this commit message:",
    "message:",
    "subject:",
)
_BODY_LABELS = {"body:", "description:"}
_PLACEHOLDER_SUBJECTS = {"todo", "tbd", "wip", "commit message"}
_LEAK_PREFIXES = (
    "diff --git ",
    "@@ ",
    "<context",
    "<diff_",
    "<staged_files",
    "<log_examples",
)
_FORBIDDEN_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")
_DIFF_INDEX_RE = re.compile(r"^index [0-9a-f]+\.\.[0-9a-f]+(?: \d{6})?$", re.I)
_LIST_SUBJECT_RE = re.compile(r"^(?:[-*]\s+|\d+[.)]\s+)")
_INLINE_ASSISTANT_PREAMBLE_RE = re.compile(
    r"^(?:sure,?\s+)?(?:here(?:\s+is|'s)\s+the\s+commit\s+message|"
    r"here\s+you\s+go|here's\s+my\s+suggestion|"
    r"the\s+commit\s+message\s+is|i(?:\s+would|'d)\s+use|"
    r"i(?:\s+would|'d)?\s+suggest)\s*:\s*(?P<message>.+)$",
    re.I,
)


def sanitize_commit_message(message: str) -> str:
    text = message.strip()
    text = _strip_fence(text)
    text = _extract_json_message(text)
    text = _strip_label(text)
    text = _strip_assistant_preamble(text)
    text = _strip_fence(text)
    text = _extract_json_message(text)
    text = _strip_label(text)
    text = _strip_body_labels(text)
    text = _strip_wrapping_markers(text)
    text = _extract_json_message(text)
    text = _strip_label(text)
    text = _strip_assistant_preamble(text)
    text = _strip_body_labels(text)
    return text


def _strip_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def is_usable_commit_message(message: str) -> bool:
    text = message.strip()
    subject = text.splitlines()[0] if text else ""
    normalized_subject = subject.strip().lower().rstrip(".")
    if not subject.strip() or subject.lstrip().startswith("#"):
        return False
    if _LIST_SUBJECT_RE.match(subject.lstrip()):
        return False
    if _is_assistant_preamble(subject):
        return False
    if _is_json_like_subject(subject):
        return False
    if normalized_subject in _PLACEHOLDER_SUBJECTS:
        return False
    lines = text.splitlines()
    if len(lines) > 1 and lines[1].strip():
        return False
    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if stripped.startswith("```"):
            return False
        if stripped.startswith("#"):
            return False
        if any(lower.startswith(prefix) for prefix in _LEAK_PREFIXES):
            return False
        if _DIFF_INDEX_RE.match(stripped):
            return False
        if any(marker in stripped for marker in _FORBIDDEN_MARKERS):
            return False
    return True


def _strip_label(text: str) -> str:
    if not text:
        return text
    lines = text.splitlines()
    first = lines[0].strip()
    first_lower = first.lower()
    for prefix in _LABEL_PREFIXES:
        if first_lower == prefix:
            return "\n".join(lines[1:]).strip()
        if first_lower.startswith(prefix + " "):
            rest = first[len(prefix) :].strip()
            return "\n".join([rest, *lines[1:]]).strip()
    return text


def _extract_json_message(text: str) -> str:
    if not text.startswith(("{", '"')):
        return text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, str):
        return data.strip()
    if not isinstance(data, dict):
        return text
    message = data.get("message")
    if isinstance(message, str):
        return message.strip()
    return text


def _is_json_like_subject(subject: str) -> bool:
    text = subject.lstrip()
    if text.startswith("{"):
        return True
    if not text.startswith("["):
        return False
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return False
    return True


def _strip_body_labels(text: str) -> str:
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if lower in _BODY_LABELS:
            _ensure_body_separator(cleaned)
            continue
        for label in _BODY_LABELS:
            if lower.startswith(label + " "):
                _ensure_body_separator(cleaned)
                cleaned.append(stripped[len(label) :].strip())
                break
        else:
            cleaned.append(line)
    return "\n".join(cleaned).strip()


def _ensure_body_separator(lines: list[str]) -> None:
    if lines and lines[-1].strip():
        lines.append("")


def _strip_wrapping_markers(text: str) -> str:
    if len(text) <= 1:
        return text
    for marker in ('"', "'", "`"):
        if text.startswith(marker) and text.endswith(marker):
            return text[1:-1].strip()
    return text


def _strip_assistant_preamble(text: str) -> str:
    lines = text.splitlines()
    if lines:
        match = _INLINE_ASSISTANT_PREAMBLE_RE.match(lines[0].strip())
        if match:
            return "\n".join([match.group("message").strip(), *lines[1:]]).strip()
    if len(lines) < 2:
        return text
    if _is_assistant_preamble(lines[0]):
        return "\n".join(lines[1:]).strip()
    return text


def _is_assistant_preamble(line: str) -> bool:
    text = line.strip().lower().rstrip(":")
    if text in {
        "here you go",
        "here's my suggestion",
        "i'd suggest",
        "i would suggest",
        "i suggest",
    }:
        return True
    if "commit message" not in text:
        return False
    return text.startswith(("here is", "here's", "sure", "the commit message"))
