from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from .config import Config
from .errors import OpenAIError
from .message import is_usable_commit_message


_TEXT_OUTPUT_RULE = (
    "- Output ONLY the commit message text (subject line, optional body)."
)
_STRUCTURED_OUTPUT_RULE = (
    "- Write the commit message text (subject line, optional body) as the JSON "
    'string value for key "message".'
)
_COMMIT_MESSAGE_TEXT_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "name": "commit_message",
    "description": (
        "A generated Git commit message. The message value must contain only the "
        "commit message subject and optional body, with no surrounding prose."
    ),
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The commit message subject and optional body.",
            }
        },
        "required": ["message"],
        "additionalProperties": False,
    },
}


def generate_commit_message(
    config: Config,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    try:
        client = OpenAI(
            api_key=api_key,
            base_url=config.base_url,
            organization=config.organization,
            project=config.project,
            timeout=config.timeout_seconds,
            max_retries=2,
        )
        create_args: dict[str, Any] = {
            "model": config.model,
            "input": [
                {"role": "system", "content": _structured_system_prompt(system_prompt)},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": 200,
            "store": False,
            "text": _text_config(config),
        }
        if config.reasoning_effort:
            create_args["reasoning"] = {"effort": config.reasoning_effort}
        response = client.responses.create(**create_args)
    except Exception as exc:
        raise OpenAIError(f"OpenAI request failed: {exc}") from exc
    _raise_for_incomplete_response(response)
    output_text = _extract_output_text(response)
    if not output_text:
        raise OpenAIError("OpenAI response contained no text")
    message = _extract_structured_message(output_text)
    if not is_usable_commit_message(message):
        raise OpenAIError("OpenAI response contained no usable commit message")
    return message


def _text_config(config: Config) -> dict[str, Any]:
    text: dict[str, Any] = {"format": _COMMIT_MESSAGE_TEXT_FORMAT}
    if config.text_verbosity:
        text["verbosity"] = config.text_verbosity
    return text


def _structured_system_prompt(system_prompt: str) -> str:
    lines = []
    for line in system_prompt.strip().splitlines():
        if line.strip() == _TEXT_OUTPUT_RULE:
            lines.append(_STRUCTURED_OUTPUT_RULE)
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _extract_structured_message(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OpenAIError(
            "OpenAI response contained invalid structured output"
        ) from exc
    if not isinstance(data, dict):
        raise OpenAIError("OpenAI response contained invalid structured output")
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        raise OpenAIError("OpenAI response contained no structured commit message")
    return message.strip()


def _extract_output_text(response: Any) -> str:
    output_text = _response_field(response, "output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    output = _response_field(response, "output")
    if not output:
        return ""
    parts: list[str] = []
    for item in output:
        item_type = getattr(item, "type", None)
        if item_type is None and isinstance(item, dict):
            item_type = item.get("type")
        if item_type != "message":
            continue
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content")
        if not content:
            continue
        for chunk in content:
            chunk_type = getattr(chunk, "type", None)
            if chunk_type is None and isinstance(chunk, dict):
                chunk_type = chunk.get("type")
            if chunk_type not in {"output_text", "text"}:
                continue
            text = getattr(chunk, "text", None)
            if text is None and isinstance(chunk, dict):
                text = chunk.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def _raise_for_incomplete_response(response: Any) -> None:
    status = _response_field(response, "status")
    if status is None or status == "completed":
        return
    details = _response_field(response, "incomplete_details")
    reason = _response_field(details, "reason")
    if not reason:
        error = _response_field(response, "error")
        reason = _response_field(error, "message") or _response_field(error, "code")
    suffix = f" ({reason})" if reason else ""
    raise OpenAIError(f"OpenAI response was {status}{suffix}")


def _response_field(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)
