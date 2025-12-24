from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
from typing import Any

from .errors import CodexError


@dataclass(frozen=True)
class CodexStatus:
    codex_path: Path | None
    npx_path: Path | None
    auth_path: Path
    auth_exists: bool


DEFAULT_CODEX_MODEL = "gpt-5.2-codex"


def codex_status() -> CodexStatus:
    codex_path = shutil.which("codex")
    npx_path = shutil.which("npx")
    auth_path = _codex_auth_path()
    return CodexStatus(
        codex_path=Path(codex_path) if codex_path else None,
        npx_path=Path(npx_path) if npx_path else None,
        auth_path=auth_path,
        auth_exists=auth_path.exists(),
    )


def is_codex_available() -> bool:
    status = codex_status()
    if not status.auth_exists:
        return False
    return status.codex_path is not None or status.npx_path is not None


def generate_commit_message_with_codex(
    *,
    repo_root: Path,
    system_prompt: str,
    user_prompt: str,
    model: str | None,
    api_key: str | None,
) -> str:
    if not model:
        model = DEFAULT_CODEX_MODEL
    status = codex_status()
    cmd_prefix = _resolve_codex_command(status)
    if cmd_prefix is None:
        if status.auth_exists:
            raise CodexError("Codex CLI not found and npx is unavailable.")
        raise CodexError("Codex CLI not found in PATH.")

    prompt = _build_codex_prompt(system_prompt, user_prompt)
    schema = {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
        "additionalProperties": False,
    }

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as schema_file:
        json.dump(schema, schema_file)
        schema_path = Path(schema_file.name)

    fd, output_name = tempfile.mkstemp(prefix="cmtr_codex_")
    os.close(fd)
    output_path = Path(output_name)

    cmd = [
        *cmd_prefix,
        "exec",
        *(["--model", model] if model else []),
        "--output-schema",
        str(schema_path),
        "-o",
        str(output_path),
        "--color",
        "never",
        "--sandbox",
        "read-only",
        "-C",
        str(repo_root),
        "-",
    ]

    env = os.environ.copy()
    if api_key and not status.auth_exists:
        env.setdefault("CODEX_API_KEY", api_key)
    if status.auth_exists:
        env.setdefault("CODEX_HOME", str(status.auth_path.parent))

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            capture_output=True,
            env=env,
        )
    except OSError as exc:
        raise CodexError(f"Failed to run Codex CLI: {exc}") from exc
    finally:
        try:
            schema_path.unlink()
        except OSError:
            pass

    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        message = stderr or stdout or "Codex exec failed"
        raise CodexError(message)

    try:
        output_raw = output_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CodexError(f"Failed to read Codex output: {exc}") from exc
    finally:
        try:
            output_path.unlink()
        except OSError:
            pass

    message = _extract_message(output_raw)
    if not message:
        raise CodexError("Codex output did not contain a commit message.")
    return message


def _extract_message(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if isinstance(data, dict):
        message = data.get("message")
        if isinstance(message, str):
            return message.strip()
    return ""


def _build_codex_prompt(system_prompt: str, user_prompt: str) -> str:
    parts = [
        system_prompt.strip(),
        "Use ONLY the context below. Do not run any commands. Do not infer additional changes.",
        "",
        "Context:",
        user_prompt.strip(),
        "",
        'Output ONLY JSON with key "message".',
    ]
    return "\n".join(part for part in parts if part)


def _resolve_codex_command(status: CodexStatus) -> list[str] | None:
    if status.codex_path is not None:
        return [str(status.codex_path)]
    if status.auth_exists and status.npx_path is not None:
        return [str(status.npx_path), "-y", "@openai/codex@latest"]
    return None


def _codex_auth_path() -> Path:
    codex_home = os.getenv("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "auth.json"
    return Path.home() / ".codex" / "auth.json"
