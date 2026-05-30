from __future__ import annotations

from typing import Any

from openai import OpenAI

from .config import Config
from .errors import OpenAIError
from .message import is_usable_commit_message, sanitize_commit_message


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
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": 200,
            "store": False,
        }
        if config.reasoning_effort:
            create_args["reasoning"] = {"effort": config.reasoning_effort}
        if config.text_verbosity:
            create_args["text"] = {"verbosity": config.text_verbosity}
        response = client.responses.create(**create_args)
    except Exception as exc:
        raise OpenAIError(f"OpenAI request failed: {exc}") from exc
    _raise_for_incomplete_response(response)
    message = _extract_output_text(response)
    if not message:
        raise OpenAIError("OpenAI response contained no text")
    message = sanitize_commit_message(message)
    if not is_usable_commit_message(message):
        raise OpenAIError("OpenAI response contained no usable commit message")
    return message


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
