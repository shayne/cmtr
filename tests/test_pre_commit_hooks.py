from pathlib import Path

import pytest

from cmtr.errors import UserError
from cmtr.hook import (
    PRE_COMMIT_INLINE_ENTRY,
    PRE_COMMIT_SCRIPT_ENTRY,
    detect_pre_commit_config,
    ensure_pre_commit_hook,
    install_pre_commit_hook,
    pre_commit_hook_status,
    remove_pre_commit_hook,
    uninstall_pre_commit_hook,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_detect_pre_commit_config_finds_yaml(tmp_path: Path) -> None:
    config = _write(tmp_path / ".pre-commit-config.yaml", "repos:\n")
    assert detect_pre_commit_config(tmp_path) == config


def test_pre_commit_hook_status_cmtr_inline(tmp_path: Path) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: local\n    hooks:\n      - id: prepare-commit-msg\n        name: prepare-commit-msg\n        entry: uvx cmtr@latest prepare-commit-msg\n        language: system\n""",
    )
    assert pre_commit_hook_status(config) == "cmtr"


def test_pre_commit_hook_status_other_for_script_entry(tmp_path: Path) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: local\n    hooks:\n      - id: prepare-commit-msg\n        name: prepare-commit-msg\n        entry: scripts/prepare-commit-msg\n        language: system\n""",
    )
    assert pre_commit_hook_status(config) == "other"


def test_pre_commit_hook_status_other_entry(tmp_path: Path) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: local\n    hooks:\n      - id: prepare-commit-msg\n        name: prepare-commit-msg\n        entry: other\n        language: system\n""",
    )
    assert pre_commit_hook_status(config) == "other"


def test_ensure_pre_commit_hook_appends_local_repo(tmp_path: Path) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: https://example.com\n    rev: v1\n    hooks:\n      - id: trailing-whitespace\n""",
    )
    assert ensure_pre_commit_hook(config)
    text = config.read_text(encoding="utf-8")
    assert "default_stages: [pre-commit]" in text
    assert "repo: local" in text
    assert f"entry: {PRE_COMMIT_INLINE_ENTRY}" in text


def test_ensure_pre_commit_hook_inserts_into_existing_local_repo(tmp_path: Path) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: local\n    hooks:\n      - id: existing-hook\n        name: existing-hook\n        entry: existing-hook\n        language: system\n""",
    )
    assert ensure_pre_commit_hook(config)
    text = config.read_text(encoding="utf-8")
    assert text.count("repo: local") == 1
    assert f"entry: {PRE_COMMIT_INLINE_ENTRY}" in text


def test_ensure_pre_commit_hook_noop_when_entry_exists(tmp_path: Path) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: local\n    hooks:\n      - id: prepare-commit-msg\n        entry: scripts/prepare-commit-msg\n        language: system\n""",
    )
    assert not ensure_pre_commit_hook(config)


def test_ensure_pre_commit_hook_does_not_duplicate_default_stages(tmp_path: Path) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """default_stages: [pre-commit]\n\nrepos:\n  - repo: local\n    hooks:\n      - id: existing-hook\n        entry: existing-hook\n        language: system\n""",
    )
    assert ensure_pre_commit_hook(config)
    text = config.read_text(encoding="utf-8")
    assert text.count("default_stages:") == 1


def test_remove_pre_commit_hook_removes_entry(tmp_path: Path) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: local\n    hooks:\n      - id: prepare-commit-msg\n        name: prepare-commit-msg\n        entry: scripts/prepare-commit-msg\n        language: system\n        stages: [prepare-commit-msg]\n      - id: other\n        name: other\n        entry: other\n        language: system\n""",
    )
    assert remove_pre_commit_hook(config)
    text = config.read_text(encoding="utf-8")
    assert "id: prepare-commit-msg" not in text
    assert "id: other" in text


def test_uninstall_pre_commit_hook_refuses_other(tmp_path: Path) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: local\n    hooks:\n      - id: prepare-commit-msg\n        entry: scripts/prepare-commit-msg\n        language: system\n""",
    )
    with pytest.raises(UserError):
        uninstall_pre_commit_hook(tmp_path, config)


def test_install_pre_commit_hook_updates_config(tmp_path: Path, monkeypatch) -> None:
    config = _write(tmp_path / ".pre-commit-config.yaml", "repos:\n")
    script_path = tmp_path / PRE_COMMIT_SCRIPT_ENTRY
    assert not script_path.exists()
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/uvx")
    hook_path = install_pre_commit_hook(tmp_path, config, force=False)
    assert hook_path == config
    assert not script_path.exists()
    assert f"entry: {PRE_COMMIT_INLINE_ENTRY}" in config.read_text(encoding="utf-8")


def test_install_pre_commit_hook_requires_uvx(tmp_path: Path, monkeypatch) -> None:
    config = _write(tmp_path / ".pre-commit-config.yaml", "repos:\n")
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(UserError):
        install_pre_commit_hook(tmp_path, config, force=False)


def test_install_pre_commit_hook_requires_force_for_other(tmp_path: Path, monkeypatch) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: local\n    hooks:\n      - id: prepare-commit-msg\n        entry: other\n        language: system\n""",
    )
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/uvx")
    with pytest.raises(UserError):
        install_pre_commit_hook(tmp_path, config, force=False)
