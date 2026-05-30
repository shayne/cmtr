from pathlib import Path

import pytest
from typer.testing import CliRunner

import cmtr.cli as cli
from cmtr.config import (
    DEFAULT_CONFIG,
    load_config,
    read_global_config,
    write_global_config,
)
from cmtr.errors import ConfigError


def test_default_config_prefers_codex(tmp_path: Path) -> None:
    assert load_config(tmp_path).prefer_codex is True


def test_default_config_uses_current_official_models(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config.model == "gpt-5.5"
    assert config.codex_model == "gpt-5.5"
    assert config.reasoning_effort is None
    assert DEFAULT_CONFIG.reasoning_effort is None


def test_load_config_reads_codex_model_from_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CMTR_CODEX_MODEL", "gpt-custom-codex")

    config = load_config(tmp_path)

    assert config.codex_model == "gpt-custom-codex"
    assert config.model == "gpt-5.5"


def test_load_config_reads_openai_org_id_from_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_ORG_ID", "org_123")

    config = load_config(tmp_path)

    assert config.organization == "org_123"


def test_load_config_reads_openai_project_id_from_env(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_PROJECT_ID", "proj_123")

    config = load_config(tmp_path)

    assert config.project == "proj_123"


def test_load_config_rejects_unknown_repo_keys(tmp_path: Path) -> None:
    (tmp_path / "cmtr.toml").write_text('modell = "typo"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="Unknown config key: modell"):
        load_config(tmp_path)


def test_load_config_reports_malformed_repo_config(tmp_path: Path) -> None:
    (tmp_path / "cmtr.toml").write_text('model = "unterminated\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="Failed to parse"):
        load_config(tmp_path)


@pytest.mark.parametrize(
    "key,value",
    [
        ("max_diff_bytes", "-1"),
        ("max_patch_lines", "-1"),
        ("max_log_entries", "-1"),
        ("max_log_paths", "-1"),
        ("max_log_body_lines", "-1"),
        ("timeout_seconds", "0"),
    ],
)
def test_load_config_rejects_invalid_ranges(
    tmp_path: Path, key: str, value: str
) -> None:
    (tmp_path / "cmtr.toml").write_text(f"{key} = {value}\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(tmp_path)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_load_config_rejects_non_finite_timeout(tmp_path: Path, value: str) -> None:
    (tmp_path / "cmtr.toml").write_text(
        f"timeout_seconds = {value}\n", encoding="utf-8"
    )

    with pytest.raises(ConfigError, match="finite"):
        load_config(tmp_path)


@pytest.mark.parametrize(
    "key",
    [
        "max_diff_bytes",
        "max_patch_lines",
        "max_log_entries",
        "max_log_paths",
        "max_log_body_lines",
    ],
)
def test_load_config_rejects_boolean_integer_limits(tmp_path: Path, key: str) -> None:
    (tmp_path / "cmtr.toml").write_text(f"{key} = true\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=f"{key} must be an integer"):
        load_config(tmp_path)


@pytest.mark.parametrize(
    "key",
    [
        "max_diff_bytes",
        "max_patch_lines",
        "max_log_entries",
        "max_log_paths",
        "max_log_body_lines",
    ],
)
def test_load_config_rejects_float_integer_limits(tmp_path: Path, key: str) -> None:
    (tmp_path / "cmtr.toml").write_text(f"{key} = 1.5\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=f"{key} must be an integer"):
        load_config(tmp_path)


def test_load_config_rejects_boolean_timeout(tmp_path: Path) -> None:
    (tmp_path / "cmtr.toml").write_text("timeout_seconds = true\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="timeout_seconds must be a number"):
        load_config(tmp_path)


@pytest.mark.parametrize("key", ["model", "codex_model"])
def test_load_config_rejects_empty_model_names(tmp_path: Path, key: str) -> None:
    (tmp_path / "cmtr.toml").write_text(f'{key} = "  "\n', encoding="utf-8")

    with pytest.raises(ConfigError, match=f"{key} must not be empty"):
        load_config(tmp_path)


def test_load_config_trims_string_settings(tmp_path: Path) -> None:
    (tmp_path / "cmtr.toml").write_text(
        "\n".join(
            [
                'model = " gpt-5.5 "',
                'codex_model = " gpt-5.5 "',
                'reasoning_effort = " low "',
                'text_verbosity = " medium "',
                'base_url = " https://api.openai.com/v1 "',
                'organization = " org_123 "',
                'project = " proj_123 "',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.model == "gpt-5.5"
    assert config.codex_model == "gpt-5.5"
    assert config.reasoning_effort == "low"
    assert config.text_verbosity == "medium"
    assert config.base_url == "https://api.openai.com/v1"
    assert config.organization == "org_123"
    assert config.project == "proj_123"


@pytest.mark.parametrize(
    "key,value",
    [
        ("model", "123"),
        ("codex_model", "123"),
        ("reasoning_effort", "1"),
        ("text_verbosity", "1"),
        ("base_url", "123"),
        ("organization", "123"),
        ("project", "123"),
    ],
)
def test_load_config_rejects_non_string_string_settings(
    tmp_path: Path, key: str, value: str
) -> None:
    (tmp_path / "cmtr.toml").write_text(f"{key} = {value}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=f"{key} must be a string"):
        load_config(tmp_path)


@pytest.mark.parametrize(
    "key",
    ["base_url", "organization", "project", "reasoning_effort", "text_verbosity"],
)
def test_load_config_treats_blank_optional_strings_as_unset(
    tmp_path: Path, key: str
) -> None:
    (tmp_path / "cmtr.toml").write_text(f'{key} = "  "\n', encoding="utf-8")

    config = load_config(tmp_path)

    assert getattr(config, key) is None


def test_config_list_shows_global_defaults_not_repo_or_env_overrides(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CMTR_MODEL", "env-model")
    (tmp_path / "cmtr.toml").write_text('model = "repo-model"\n', encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["config", "list"])

    assert result.exit_code == 0
    assert "model = gpt-5.5 (default)" in result.output
    assert "env-model" not in result.output
    assert "repo-model" not in result.output


def test_config_list_formats_booleans_like_config_values(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    config_path = tmp_path / "xdg" / "cmtr" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("prefer_codex = false\n", encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["config", "list"])

    assert result.exit_code == 0
    assert "prefer_codex = false (override)" in result.output


def test_config_get_formats_booleans_like_config_values(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    config_path = tmp_path / "xdg" / "cmtr" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("prefer_codex = false\n", encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["config", "get", "prefer_codex"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "false"


def test_config_get_shows_default_value_when_unset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    result = CliRunner().invoke(cli.app, ["config", "get", "model"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "gpt-5.5"


def test_config_get_rejects_invalid_global_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    config_path = tmp_path / "xdg" / "cmtr" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('prefer_codex = "maybe"\n', encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["config", "get", "prefer_codex"])

    assert result.exit_code == 1
    assert "prefer_codex must be a boolean" in result.output


def test_config_list_reports_malformed_global_config(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    config_path = tmp_path / "xdg" / "cmtr" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('model = "unterminated\n', encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["config", "list"])

    assert result.exit_code == 1
    assert "cmtr error: Failed to parse" in result.output
    assert "TOMLDecodeError" not in result.output


def test_write_global_config_escapes_multiline_strings(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    write_global_config({"project": "line\nnext"})

    assert read_global_config()["project"] == "line\nnext"


def test_config_unset_removes_unknown_existing_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    config_path = tmp_path / "xdg" / "cmtr" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('modell = "typo"\nmodel = "custom"\n', encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["config", "unset", "modell"])

    assert result.exit_code == 0
    text = config_path.read_text(encoding="utf-8")
    assert "modell" not in text
    assert 'model = "custom"' in text
