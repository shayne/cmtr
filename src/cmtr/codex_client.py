from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile

from .config import DEFAULT_CONFIG
from .errors import CodexError
from .message import is_usable_commit_message


@dataclass(frozen=True)
class CodexStatus:
    codex_path: Path | None
    npx_path: Path | None
    auth_path: Path
    auth_exists: bool


DEFAULT_CODEX_MODEL = DEFAULT_CONFIG.codex_model
_TEXT_OUTPUT_RULE = (
    "- Output ONLY the commit message text (subject line, optional body)."
)
_CODEX_JSON_OUTPUT_RULE = (
    "- Write the commit message text (subject line, optional body) as the JSON string "
    'value for key "message".'
)


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
    timeout_seconds: float | None = None,
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

    schema_path: Path | None = None
    output_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False
        ) as schema_file:
            json.dump(schema, schema_file)
            schema_path = Path(schema_file.name)

        fd, output_name = tempfile.mkstemp(prefix="cmtr_codex_")
        os.close(fd)
        output_path = Path(output_name)

        with tempfile.TemporaryDirectory(
            prefix="cmtr_codex_workspace_"
        ) as workdir_name:
            workdir = Path(workdir_name)
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
                str(workdir),
                "--skip-git-repo-check",
                "--ephemeral",
                "-",
            ]

            env = os.environ.copy()
            if api_key and not status.auth_exists:
                env.setdefault("CODEX_API_KEY", api_key)
            if status.auth_exists:
                env.setdefault("CODEX_HOME", str(status.auth_path.parent))

            result = subprocess.run(
                cmd,
                cwd=workdir,
                input=prompt,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                env=env,
                timeout=timeout_seconds,
            )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            message = stderr or stdout
            suffix = f": {message}" if message else ""
            raise CodexError(f"Codex exec failed{suffix}")

        try:
            output_raw = output_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise CodexError(f"Failed to read Codex output: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        timeout = exc.timeout if exc.timeout is not None else timeout_seconds
        suffix = f" after {timeout:g} seconds" if timeout else ""
        raise CodexError(f"Codex exec timed out{suffix}.") from exc
    except OSError as exc:
        raise CodexError(f"Failed to run Codex CLI: {exc}") from exc
    finally:
        for path in (schema_path, output_path):
            if path is None:
                continue
            try:
                path.unlink()
            except OSError:
                pass

    message = _extract_message(output_raw)
    if not is_usable_commit_message(message):
        raise CodexError("Codex output contained no usable commit message.")
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
        _codex_system_prompt(system_prompt),
        "Use ONLY the context below. Do not run any commands. Do not infer additional changes.",
        "",
        "Context:",
        user_prompt.strip(),
        "",
        'Output ONLY JSON with key "message".',
    ]
    return "\n".join(part for part in parts if part)


def _codex_system_prompt(system_prompt: str) -> str:
    lines = []
    for line in system_prompt.strip().splitlines():
        if line.strip() == _TEXT_OUTPUT_RULE:
            lines.append(_CODEX_JSON_OUTPUT_RULE)
            continue
        lines.append(line)
    return "\n".join(lines).strip()


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
