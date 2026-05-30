from dataclasses import replace
from pathlib import Path

import cmtr.core as core
from cmtr.config import DEFAULT_CONFIG
from cmtr.errors import CodexError, OpenAIError, UserError


def test_generate_message_passes_configured_model_to_codex(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}
    context = core.CommitContext(
        repo_root=tmp_path,
        staged_files=["file.py"],
        name_status="M\tfile.py",
        diff_stat=" file.py | 1 +",
        diff_patch="diff --git a/file.py b/file.py\n+print('hi')\n",
        diff_was_truncated=False,
        diff_was_filtered=False,
        log_contexts=[],
        has_commit_history=False,
    )
    config = replace(
        DEFAULT_CONFIG,
        model="gpt-api",
        codex_model="gpt-custom-codex",
    )

    monkeypatch.setattr(core, "collect_context", lambda repo_root, config: context)
    monkeypatch.setattr(core, "select_backend", lambda config, api_key: "codex")

    def fake_codex(**kwargs):
        captured.update(kwargs)
        return "feat: add greeting"

    monkeypatch.setattr(core, "generate_commit_message_with_codex", fake_codex)

    message = core.generate_message(tmp_path, config, api_key=None)

    assert message == "feat: add greeting"
    assert captured["model"] == "gpt-custom-codex"
    assert captured["timeout_seconds"] == config.timeout_seconds


def test_generate_message_uses_codex_default_model(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}
    context = core.CommitContext(
        repo_root=tmp_path,
        staged_files=["file.py"],
        name_status="M\tfile.py",
        diff_stat=" file.py | 1 +",
        diff_patch="diff --git a/file.py b/file.py\n+print('hi')\n",
        diff_was_truncated=False,
        diff_was_filtered=False,
        log_contexts=[],
        has_commit_history=False,
    )

    monkeypatch.setattr(core, "collect_context", lambda repo_root, config: context)
    monkeypatch.setattr(core, "select_backend", lambda config, api_key: "codex")

    def fake_codex(**kwargs):
        captured.update(kwargs)
        return "feat: add greeting"

    monkeypatch.setattr(core, "generate_commit_message_with_codex", fake_codex)

    core.generate_message(tmp_path, DEFAULT_CONFIG, api_key=None)

    assert captured["model"] == "gpt-5.5"


def test_select_backend_prefers_codex_when_available(monkeypatch) -> None:
    monkeypatch.setattr(core, "is_codex_available", lambda: True)

    backend = core.select_backend(DEFAULT_CONFIG, api_key="test-key")

    assert backend == "codex"


def test_select_backend_falls_back_to_api_when_codex_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(core, "is_codex_available", lambda: False)

    backend = core.select_backend(DEFAULT_CONFIG, api_key="test-key")

    assert backend == "openai"


def test_select_backend_prefers_api_when_codex_preference_disabled(monkeypatch) -> None:
    monkeypatch.setattr(core, "is_codex_available", lambda: True)
    config = replace(DEFAULT_CONFIG, prefer_codex=False)

    backend = core.select_backend(config, api_key="test-key")

    assert backend == "openai"


def test_describe_auth_mode_reports_api_fallback_when_codex_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(core, "is_codex_available", lambda: False)

    mode, reason = core.describe_auth_mode(DEFAULT_CONFIG, api_key="test-key")

    assert mode == "openai"
    assert reason == "Codex is preferred but unavailable; using OPENAI_API_KEY."


def test_generate_message_falls_back_to_openai_when_codex_fails_with_api_key(
    tmp_path: Path, monkeypatch
) -> None:
    context = core.CommitContext(
        repo_root=tmp_path,
        staged_files=["file.py"],
        name_status="M\tfile.py",
        diff_stat=" file.py | 1 +",
        diff_patch="diff --git a/file.py b/file.py\n+print('hi')\n",
        diff_was_truncated=False,
        diff_was_filtered=False,
        log_contexts=[],
        has_commit_history=False,
    )

    monkeypatch.setattr(core, "collect_context", lambda repo_root, config: context)
    monkeypatch.setattr(core, "select_backend", lambda config, api_key: "codex")
    monkeypatch.setattr(
        core,
        "generate_commit_message_with_codex",
        lambda **kwargs: (_ for _ in ()).throw(CodexError("codex failed")),
    )
    monkeypatch.setattr(
        core,
        "generate_commit_message",
        lambda **kwargs: "feat: fallback to api",
    )

    message = core.generate_message(tmp_path, DEFAULT_CONFIG, api_key="test-key")

    assert message == "feat: fallback to api"


def test_generate_message_from_prompts_reports_backend_sequence(
    tmp_path: Path, monkeypatch
) -> None:
    statuses: list[str] = []
    monkeypatch.setattr(core, "select_backend", lambda config, api_key: "codex")
    monkeypatch.setattr(
        core,
        "generate_commit_message_with_codex",
        lambda **kwargs: (_ for _ in ()).throw(CodexError("codex failed")),
    )
    monkeypatch.setattr(
        core,
        "generate_commit_message",
        lambda **kwargs: "feat: fallback to api",
    )

    message = core.generate_message_from_prompts(
        repo_root=tmp_path,
        config=DEFAULT_CONFIG,
        api_key="test-key",
        system_prompt="system",
        user_prompt="user",
        on_backend_status=statuses.append,
    )

    assert message == "feat: fallback to api"
    assert statuses == ["codex", "openai_fallback"]


def test_generate_message_reports_both_errors_when_codex_and_api_fail(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(core, "select_backend", lambda config, api_key: "codex")
    monkeypatch.setattr(
        core,
        "generate_commit_message_with_codex",
        lambda **kwargs: (_ for _ in ()).throw(CodexError("codex failed")),
    )
    monkeypatch.setattr(
        core,
        "generate_commit_message",
        lambda **kwargs: (_ for _ in ()).throw(OpenAIError("api failed")),
    )

    try:
        core.generate_message_from_prompts(
            repo_root=tmp_path,
            config=DEFAULT_CONFIG,
            api_key="test-key",
            system_prompt="system",
            user_prompt="user",
        )
    except UserError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected UserError")

    assert "Codex failed: codex failed" in message
    assert "OpenAI fallback failed: api failed" in message


def test_generate_message_falls_back_to_codex_when_api_first_fails(
    tmp_path: Path, monkeypatch
) -> None:
    statuses: list[str] = []
    captured: dict[str, object] = {}
    config = replace(DEFAULT_CONFIG, prefer_codex=False)
    monkeypatch.setattr(core, "is_codex_available", lambda: True)
    monkeypatch.setattr(
        core,
        "generate_commit_message",
        lambda **kwargs: (_ for _ in ()).throw(OpenAIError("api failed")),
    )

    def fake_codex(**kwargs):
        captured.update(kwargs)
        return "feat: fallback to codex"

    monkeypatch.setattr(core, "generate_commit_message_with_codex", fake_codex)

    message = core.generate_message_from_prompts(
        repo_root=tmp_path,
        config=config,
        api_key="test-key",
        system_prompt="system",
        user_prompt="user",
        on_backend_status=statuses.append,
    )

    assert message == "feat: fallback to codex"
    assert statuses == ["openai", "codex_fallback"]
    assert captured["api_key"] == "test-key"
