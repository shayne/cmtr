from __future__ import annotations

import json
import re


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


def _is_assistant_preamble(line: str) -> bool:
    text = line.strip().lower().rstrip(":")
    if text in {
        "here you go",
        "here's my suggestion",
        "i'd suggest",
        "i would suggest",
        "i suggest",
        "i recommend",
    }:
        return True
    if text.startswith(
        (
            "i recommend the following commit message",
            "i would recommend the following commit message",
            "i'd recommend the following commit message",
        )
    ):
        return True
    if "commit message" not in text:
        return False
    return text.startswith(("here is", "here's", "sure", "the commit message"))
