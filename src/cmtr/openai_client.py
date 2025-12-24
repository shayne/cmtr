from __future__ import annotations

from typing import Any

from openai import OpenAI

from .config import Config
from .errors import OpenAIError


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
        }
        if config.reasoning_effort:
            create_args["reasoning"] = {"effort": config.reasoning_effort}
        if config.text_verbosity:
            create_args["text"] = {"verbosity": config.text_verbosity}
        response = client.responses.create(**create_args)
    except Exception as exc:
        raise OpenAIError(f"OpenAI request failed: {exc}") from exc
    message = _extract_output_text(response)
    if not message:
        raise OpenAIError("OpenAI response contained no text")
    return _sanitize_message(message)


def _extract_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    output = getattr(response, "output", None)
    if output is None and isinstance(response, dict):
        output = response.get("output")
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


def _sanitize_message(message: str) -> str:
    text = message.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            text = "\n".join(lines[1:-1]).strip()
    if text.startswith("\"") and text.endswith("\"") and len(text) > 1:
        text = text[1:-1].strip()
    if text.startswith("'") and text.endswith("'") and len(text) > 1:
        text = text[1:-1].strip()
    return text
