from pathlib import Path
import os
import subprocess

import pytest

import cmtr.codex_client as codex_client
from cmtr.errors import CodexError
from cmtr.prompt import build_system_prompt


def test_codex_prompt_uses_json_output_without_conflicting_text_rule() -> None:
    prompt = codex_client._build_codex_prompt(
        build_system_prompt(),
        "<context>diff</context>",
    )

    assert "- Output ONLY the commit message text" not in prompt
    assert 'JSON string value for key "message"' in prompt
    assert 'Output ONLY JSON with key "message".' in prompt


def test_codex_failure_removes_temp_output_file(tmp_path: Path, monkeypatch) -> None:
    output_path = tmp_path / "codex-output.json"

    def fake_mkstemp(prefix: str) -> tuple[int, str]:
        fd = os.open(output_path, os.O_CREAT | os.O_RDWR)
        return fd, str(output_path)

    monkeypatch.setattr(codex_client.tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(
        codex_client,
        "codex_status",
        lambda: codex_client.CodexStatus(
            codex_path=Path("/usr/local/bin/codex"),
            npx_path=None,
            auth_path=tmp_path / "auth.json",
            auth_exists=True,
        ),
    )
    monkeypatch.setattr(
        codex_client.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="failed",
        ),
    )

    with pytest.raises(CodexError):
        codex_client.generate_commit_message_with_codex(
            repo_root=tmp_path,
            system_prompt="system",
            user_prompt="user",
            model="gpt-test",
            api_key=None,
        )

    assert not output_path.exists()


def test_codex_runs_from_scratch_directory_not_repo_root(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        codex_client,
        "codex_status",
        lambda: codex_client.CodexStatus(
            codex_path=Path("/usr/local/bin/codex"),
            npx_path=None,
            auth_path=tmp_path / "auth.json",
            auth_exists=True,
        ),
    )

    def fake_run(cmd: list[str], **kwargs):
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text('{"message": "feat: isolate codex"}', encoding="utf-8")
        captured["workspace"] = Path(cmd[cmd.index("-C") + 1])
        captured["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(codex_client.subprocess, "run", fake_run)

    message = codex_client.generate_commit_message_with_codex(
        repo_root=tmp_path,
        system_prompt="system",
        user_prompt="user",
        model="gpt-test",
        api_key=None,
    )

    assert message == "feat: isolate codex"
    assert captured["workspace"] != tmp_path
    assert captured["cwd"] == captured["workspace"]


def test_codex_reports_undecodable_output_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        codex_client,
        "codex_status",
        lambda: codex_client.CodexStatus(
            codex_path=Path("/usr/local/bin/codex"),
            npx_path=None,
            auth_path=tmp_path / "auth.json",
            auth_exists=True,
        ),
    )

    def fake_run(cmd: list[str], **kwargs):
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_bytes(b"\xff\xfe\n")
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(codex_client.subprocess, "run", fake_run)

    with pytest.raises(CodexError, match="Failed to read Codex output"):
        codex_client.generate_commit_message_with_codex(
            repo_root=tmp_path,
            system_prompt="system",
            user_prompt="user",
            model="gpt-test",
            api_key=None,
        )


def test_codex_reports_non_utf8_failure_output(tmp_path: Path, monkeypatch) -> None:
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        "#!/bin/sh\nprintf '\\377' >&2\nexit 1\n",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    monkeypatch.setattr(
        codex_client,
        "codex_status",
        lambda: codex_client.CodexStatus(
            codex_path=fake_codex,
            npx_path=None,
            auth_path=tmp_path / "auth.json",
            auth_exists=True,
        ),
    )

    with pytest.raises(CodexError, match="Codex exec failed"):
        codex_client.generate_commit_message_with_codex(
            repo_root=tmp_path,
            system_prompt="system",
            user_prompt="user",
            model="gpt-test",
            api_key=None,
        )


def test_codex_allows_scratch_directory_outside_git_repo(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        codex_client,
        "codex_status",
        lambda: codex_client.CodexStatus(
            codex_path=Path("/usr/local/bin/codex"),
            npx_path=None,
            auth_path=tmp_path / "auth.json",
            auth_exists=True,
        ),
    )

    def fake_run(cmd: list[str], **kwargs):
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text(
            '{"message": "feat: allow isolated codex"}',
            encoding="utf-8",
        )
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(codex_client.subprocess, "run", fake_run)

    message = codex_client.generate_commit_message_with_codex(
        repo_root=tmp_path,
        system_prompt="system",
        user_prompt="user",
        model="gpt-test",
        api_key=None,
    )

    assert message == "feat: allow isolated codex"
    assert "--skip-git-repo-check" in captured["cmd"]


def test_codex_uses_ephemeral_session(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        codex_client,
        "codex_status",
        lambda: codex_client.CodexStatus(
            codex_path=Path("/usr/local/bin/codex"),
            npx_path=None,
            auth_path=tmp_path / "auth.json",
            auth_exists=True,
        ),
    )

    def fake_run(cmd: list[str], **kwargs):
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text(
            '{"message": "feat: avoid session files"}',
            encoding="utf-8",
        )
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(codex_client.subprocess, "run", fake_run)

    message = codex_client.generate_commit_message_with_codex(
        repo_root=tmp_path,
        system_prompt="system",
        user_prompt="user",
        model="gpt-test",
        api_key=None,
    )

    assert message == "feat: avoid session files"
    assert "--ephemeral" in captured["cmd"]


def test_codex_passes_timeout_to_subprocess(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        codex_client,
        "codex_status",
        lambda: codex_client.CodexStatus(
            codex_path=Path("/usr/local/bin/codex"),
            npx_path=None,
            auth_path=tmp_path / "auth.json",
            auth_exists=True,
        ),
    )

    def fake_run(cmd: list[str], **kwargs):
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text('{"message": "feat: honor timeout"}', encoding="utf-8")
        captured["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(codex_client.subprocess, "run", fake_run)

    message = codex_client.generate_commit_message_with_codex(
        repo_root=tmp_path,
        system_prompt="system",
        user_prompt="user",
        model="gpt-test",
        api_key=None,
        timeout_seconds=12.5,
    )

    assert message == "feat: honor timeout"
    assert captured["timeout"] == 12.5


def test_codex_timeout_raises_codex_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        codex_client,
        "codex_status",
        lambda: codex_client.CodexStatus(
            codex_path=Path("/usr/local/bin/codex"),
            npx_path=None,
            auth_path=tmp_path / "auth.json",
            auth_exists=True,
        ),
    )

    def fake_run(cmd: list[str], **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(codex_client.subprocess, "run", fake_run)

    with pytest.raises(CodexError, match="timed out"):
        codex_client.generate_commit_message_with_codex(
            repo_root=tmp_path,
            system_prompt="system",
            user_prompt="user",
            model="gpt-test",
            api_key=None,
            timeout_seconds=1.0,
        )


def test_codex_message_strips_markdown_fence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        codex_client,
        "codex_status",
        lambda: codex_client.CodexStatus(
            codex_path=Path("/usr/local/bin/codex"),
            npx_path=None,
            auth_path=tmp_path / "auth.json",
            auth_exists=True,
        ),
    )

    def fake_run(cmd: list[str], **kwargs):
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text(
            '{"message": "```gitcommit\\nfeat: add thing\\n```"}',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(codex_client.subprocess, "run", fake_run)

    message = codex_client.generate_commit_message_with_codex(
        repo_root=tmp_path,
        system_prompt="system",
        user_prompt="user",
        model="gpt-test",
        api_key=None,
    )

    assert message == "feat: add thing"


def test_codex_message_rejects_empty_sanitized_output(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        codex_client,
        "codex_status",
        lambda: codex_client.CodexStatus(
            codex_path=Path("/usr/local/bin/codex"),
            npx_path=None,
            auth_path=tmp_path / "auth.json",
            auth_exists=True,
        ),
    )

    def fake_run(cmd: list[str], **kwargs):
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text('{"message": "```\\n\\n```"}', encoding="utf-8")
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(codex_client.subprocess, "run", fake_run)

    with pytest.raises(CodexError, match="no usable commit message"):
        codex_client.generate_commit_message_with_codex(
            repo_root=tmp_path,
            system_prompt="system",
            user_prompt="user",
            model="gpt-test",
            api_key=None,
        )
