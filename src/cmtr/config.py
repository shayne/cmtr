from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tomllib
from typing import Any

from .errors import ConfigError


@dataclass(frozen=True)
class Config:
    model: str
    max_diff_bytes: int
    max_patch_lines: int
    max_log_entries: int
    max_log_paths: int
    max_log_body_lines: int
    timeout_seconds: float
    reasoning_effort: str
    text_verbosity: str
    prefer_codex: bool
    base_url: str | None
    organization: str | None


DEFAULT_CONFIG = Config(
    model="gpt-5.2",
    max_diff_bytes=12_000,
    max_patch_lines=400,
    max_log_entries=20,
    max_log_paths=4,
    max_log_body_lines=6,
    timeout_seconds=60.0,
    reasoning_effort="none",
    text_verbosity="low",
    prefer_codex=False,
    base_url=None,
    organization=None,
)

CONFIG_KEYS = set(DEFAULT_CONFIG.__dict__.keys())


def load_config(repo_root: Path, overrides: dict[str, Any] | None = None) -> Config:
    data: dict[str, Any] = {}
    data.update(_read_global_config())
    cmtr_toml = repo_root / "cmtr.toml"
    if cmtr_toml.exists():
        data.update(_read_cmtr_toml(cmtr_toml))
    data.update(_read_env())
    if overrides:
        data.update({k: v for k, v in overrides.items() if v is not None})
    return _apply_config(DEFAULT_CONFIG, data)


def global_config_path() -> Path:
    xdg_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_home:
        base = Path(xdg_home)
    else:
        try:
            base = Path.home() / ".config"
        except Exception as exc:
            raise ConfigError(
                "Unable to resolve a config directory. Set XDG_CONFIG_HOME."
            ) from exc
    return base / "cmtr" / "config.toml"


def _read_cmtr_toml(path: Path) -> dict[str, Any]:
    try:
        contents = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Failed to read {path}: {exc}") from exc
    if not isinstance(contents, dict):
        raise ConfigError("cmtr.toml must be a table")
    return contents


def _read_global_config() -> dict[str, Any]:
    path = global_config_path()
    if not path.exists():
        return {}
    try:
        contents = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Failed to read {path}: {exc}") from exc
    if not isinstance(contents, dict):
        raise ConfigError("config.toml must be a table")
    return contents


def read_global_config() -> dict[str, Any]:
    return _read_global_config()


def write_global_config(data: dict[str, Any]) -> None:
    path = global_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _serialize_toml(data)
    path.write_text(text, encoding="utf-8")


def set_global_value(key: str, value: Any) -> None:
    if key not in CONFIG_KEYS:
        raise ConfigError(f"Unknown config key: {key}")
    data = read_global_config()
    data[key] = value
    write_global_config(data)


def unset_global_value(key: str) -> None:
    if key not in CONFIG_KEYS:
        raise ConfigError(f"Unknown config key: {key}")
    data = read_global_config()
    if key in data:
        data.pop(key)
        write_global_config(data)


def coerce_config_value(key: str, value: Any) -> Any:
    return _coerce_value(key, value)


def _read_env() -> dict[str, Any]:
    env_map = {
        "model": "CMTR_MODEL",
        "max_diff_bytes": "CMTR_MAX_DIFF_BYTES",
        "max_patch_lines": "CMTR_MAX_PATCH_LINES",
        "max_log_entries": "CMTR_MAX_LOG_ENTRIES",
        "max_log_paths": "CMTR_MAX_LOG_PATHS",
        "max_log_body_lines": "CMTR_MAX_LOG_BODY_LINES",
        "timeout_seconds": "CMTR_TIMEOUT_SECONDS",
        "reasoning_effort": "CMTR_REASONING_EFFORT",
        "text_verbosity": "CMTR_TEXT_VERBOSITY",
        "prefer_codex": "CMTR_PREFER_CODEX",
        "base_url": "OPENAI_BASE_URL",
        "organization": "OPENAI_ORG",
    }
    data: dict[str, Any] = {}
    for key, env_key in env_map.items():
        value = os.getenv(env_key)
        if value is not None:
            data[key] = value
    return data


def _apply_config(config: Config, data: dict[str, Any]) -> Config:
    values = config.__dict__.copy()
    for key, raw_value in data.items():
        if key not in values:
            continue
        value = _coerce_value(key, raw_value)
        values[key] = value
    return Config(**values)


def _coerce_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in {
        "max_diff_bytes",
        "max_patch_lines",
        "max_log_entries",
        "max_log_paths",
        "max_log_body_lines",
    }:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{key} must be an integer") from exc
    if key == "timeout_seconds":
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError("timeout_seconds must be a number") from exc
    if key == "prefer_codex":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        raise ConfigError("prefer_codex must be a boolean")
    if isinstance(value, str):
        return value
    return value


def _serialize_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in sorted(data.keys()):
        value = data[key]
        lines.append(f"{key} = {_format_toml_value(value)}")
    return "\n".join(lines) + "\n"


def _format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return '""'
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace("\"", "\\\"")
    return f"\"{escaped}\""
