from __future__ import annotations

from dataclasses import replace

import pytest

import cmtr.openai_client as openai_client
from cmtr.config import DEFAULT_CONFIG
from cmtr.errors import OpenAIError


class _FakeResponses:
    def __init__(self, output_text: str) -> None:
        self._output_text = output_text

    def create(self, **kwargs):
        return type("Response", (), {"output_text": self._output_text})()


class _FakeOpenAI:
    output_text = ""

    def __init__(self, **kwargs) -> None:
        self.responses = _FakeResponses(self.output_text)


def test_openai_message_strips_markdown_fence(monkeypatch) -> None:
    _FakeOpenAI.output_text = "```gitcommit\nfeat: add thing\n```"
    monkeypatch.setattr(openai_client, "OpenAI", _FakeOpenAI)

    message = openai_client.generate_commit_message(
        config=DEFAULT_CONFIG,
        api_key="test",
        system_prompt="system",
        user_prompt="user",
    )

    assert message == "feat: add thing"


def test_openai_request_disables_response_storage(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {"output_text": "feat: add thing"})()

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr(openai_client, "OpenAI", FakeOpenAI)

    message = openai_client.generate_commit_message(
        config=DEFAULT_CONFIG,
        api_key="test",
        system_prompt="system",
        user_prompt="user",
    )

    assert message == "feat: add thing"
    assert captured["store"] is False


def test_openai_request_omits_reasoning_by_default(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {"output_text": "feat: add thing"})()

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr(openai_client, "OpenAI", FakeOpenAI)

    message = openai_client.generate_commit_message(
        config=DEFAULT_CONFIG,
        api_key="test",
        system_prompt="system",
        user_prompt="user",
    )

    assert message == "feat: add thing"
    assert "reasoning" not in captured


def test_openai_client_receives_project(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs):
            return type("Response", (), {"output_text": "feat: add thing"})()

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self.responses = FakeResponses()

    monkeypatch.setattr(openai_client, "OpenAI", FakeOpenAI)

    message = openai_client.generate_commit_message(
        config=replace(DEFAULT_CONFIG, project="proj_123"),
        api_key="test",
        system_prompt="system",
        user_prompt="user",
    )

    assert message == "feat: add thing"
    assert captured["project"] == "proj_123"


def test_openai_message_rejects_empty_sanitized_output(monkeypatch) -> None:
    _FakeOpenAI.output_text = "```\n\n```"
    monkeypatch.setattr(openai_client, "OpenAI", _FakeOpenAI)

    with pytest.raises(OpenAIError, match="no usable commit message"):
        openai_client.generate_commit_message(
            config=DEFAULT_CONFIG,
            api_key="test",
            system_prompt="system",
            user_prompt="user",
        )


def test_openai_message_rejects_comment_only_output(monkeypatch) -> None:
    _FakeOpenAI.output_text = "# generated comment"
    monkeypatch.setattr(openai_client, "OpenAI", _FakeOpenAI)

    with pytest.raises(OpenAIError, match="no usable commit message"):
        openai_client.generate_commit_message(
            config=DEFAULT_CONFIG,
            api_key="test",
            system_prompt="system",
            user_prompt="user",
        )


def test_openai_message_rejects_context_leak(monkeypatch) -> None:
    _FakeOpenAI.output_text = "diff --git a/file.py b/file.py\n+print('hi')"
    monkeypatch.setattr(openai_client, "OpenAI", _FakeOpenAI)

    with pytest.raises(OpenAIError, match="no usable commit message"):
        openai_client.generate_commit_message(
            config=DEFAULT_CONFIG,
            api_key="test",
            system_prompt="system",
            user_prompt="user",
        )


def test_openai_rejects_incomplete_response_even_with_text(monkeypatch) -> None:
    class FakeResponses:
        def create(self, **kwargs):
            return {
                "output_text": "feat: truncated",
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
            }

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr(openai_client, "OpenAI", FakeOpenAI)

    with pytest.raises(OpenAIError, match="incomplete.*max_output_tokens"):
        openai_client.generate_commit_message(
            config=DEFAULT_CONFIG,
            api_key="test",
            system_prompt="system",
            user_prompt="user",
        )
