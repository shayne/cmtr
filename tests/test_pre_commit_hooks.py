from pathlib import Path
import subprocess

import pytest

from cmtr.errors import UserError
from cmtr.config import DEFAULT_CONFIG
from cmtr.hook import (
    PRE_COMMIT_INLINE_ENTRY,
    PRE_COMMIT_SCRIPT_ENTRY,
    append_failure_comment,
    detect_pre_commit_config,
    ensure_pre_commit_hook,
    install_pre_commit_hook,
    pre_commit_hook_status,
    remove_pre_commit_hook,
    run_prepare_commit_msg,
    uninstall_pre_commit_hook,
    _hook_script_for,
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


def test_pre_commit_hook_status_cmtr_with_quoted_scalars(tmp_path: Path) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: "local"\n    hooks:\n      - id: "prepare-commit-msg"\n        name: prepare-commit-msg\n        entry: "uvx cmtr@latest prepare-commit-msg"\n        language: system\n""",
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


def test_pre_commit_hook_status_ignores_non_local_matching_hook_id(
    tmp_path: Path,
) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: https://example.com/hooks\n    rev: v1\n    hooks:\n      - id: prepare-commit-msg\n        entry: other\n        language: python\n""",
    )

    assert pre_commit_hook_status(config) == "missing"


def test_ensure_pre_commit_hook_appends_local_repo(tmp_path: Path) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: https://example.com\n    rev: v1\n    hooks:\n      - id: trailing-whitespace\n""",
    )
    assert ensure_pre_commit_hook(config)
    text = config.read_text(encoding="utf-8")
    assert "default_stages:" not in text
    assert "repo: local" in text
    assert f"entry: {PRE_COMMIT_INLINE_ENTRY}" in text
    assert "stages: [prepare-commit-msg]" in text


def test_ensure_pre_commit_hook_expands_empty_inline_repos(tmp_path: Path) -> None:
    config = _write(tmp_path / ".pre-commit-config.yaml", "repos: []\n")

    assert ensure_pre_commit_hook(config)
    text = config.read_text(encoding="utf-8")
    assert "repos: []" not in text
    assert "repos:\n" in text
    assert "repo: local" in text
    assert f"entry: {PRE_COMMIT_INLINE_ENTRY}" in text


def test_ensure_pre_commit_hook_inserts_into_existing_local_repo(
    tmp_path: Path,
) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: local\n    hooks:\n      - id: existing-hook\n        name: existing-hook\n        entry: existing-hook\n        language: system\n""",
    )
    assert ensure_pre_commit_hook(config)
    text = config.read_text(encoding="utf-8")
    assert text.count("repo: local") == 1
    assert f"entry: {PRE_COMMIT_INLINE_ENTRY}" in text


def test_ensure_pre_commit_hook_expands_empty_inline_hooks(tmp_path: Path) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: local\n    hooks: []\n""",
    )

    assert ensure_pre_commit_hook(config)
    text = config.read_text(encoding="utf-8")
    assert "hooks: []" not in text
    assert text.count("hooks:") == 1
    assert f"entry: {PRE_COMMIT_INLINE_ENTRY}" in text


def test_ensure_pre_commit_hook_adds_local_hook_when_non_local_id_matches(
    tmp_path: Path,
) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: https://example.com/hooks\n    rev: v1\n    hooks:\n      - id: prepare-commit-msg\n        entry: other\n        language: python\n""",
    )

    assert ensure_pre_commit_hook(config)
    text = config.read_text(encoding="utf-8")
    assert "repo: https://example.com/hooks" in text
    assert "entry: other" in text
    assert "repo: local" in text
    assert f"entry: {PRE_COMMIT_INLINE_ENTRY}" in text


def test_ensure_pre_commit_hook_uses_quoted_existing_local_repo(
    tmp_path: Path,
) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: "local"\n    hooks:\n      - id: existing-hook\n        name: existing-hook\n        entry: existing-hook\n        language: system\n""",
    )
    assert ensure_pre_commit_hook(config)
    text = config.read_text(encoding="utf-8")
    assert text.count("repo:") == 1
    assert f"entry: {PRE_COMMIT_INLINE_ENTRY}" in text


def test_ensure_pre_commit_hook_noop_when_entry_exists(tmp_path: Path) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: local\n    hooks:\n      - id: prepare-commit-msg\n        entry: scripts/prepare-commit-msg\n        language: system\n""",
    )
    assert not ensure_pre_commit_hook(config)


def test_ensure_pre_commit_hook_does_not_duplicate_default_stages(
    tmp_path: Path,
) -> None:
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


def test_remove_pre_commit_hook_ignores_non_local_matching_hook_id(
    tmp_path: Path,
) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: https://example.com/hooks\n    rev: v1\n    hooks:\n      - id: prepare-commit-msg\n        entry: other\n        language: python\n""",
    )

    assert not remove_pre_commit_hook(config)
    assert "entry: other" in config.read_text(encoding="utf-8")


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
    text = config.read_text(encoding="utf-8")
    assert f"entry: {PRE_COMMIT_INLINE_ENTRY}" in text
    assert "default_stages:" not in text


def test_install_pre_commit_hook_requires_uvx(tmp_path: Path, monkeypatch) -> None:
    config = _write(tmp_path / ".pre-commit-config.yaml", "repos:\n")
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(UserError):
        install_pre_commit_hook(tmp_path, config, force=False)


def test_install_pre_commit_hook_requires_force_for_other(
    tmp_path: Path, monkeypatch
) -> None:
    config = _write(
        tmp_path / ".pre-commit-config.yaml",
        """repos:\n  - repo: local\n    hooks:\n      - id: prepare-commit-msg\n        entry: other\n        language: system\n""",
    )
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/uvx")
    with pytest.raises(UserError):
        install_pre_commit_hook(tmp_path, config, force=False)


def test_local_checkout_hook_preserves_target_repo_cwd(tmp_path: Path) -> None:
    script = _hook_script_for(tmp_path)

    assert "CMTR_TARGET=$(pwd)" in script
    assert '--project "$CMTR_REPO"' in script
    assert '--directory "$CMTR_TARGET"' in script
    assert 'cd "$CMTR_REPO"' not in script


def test_local_checkout_hook_skips_when_uv_missing_even_if_mise_exists(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text('[project]\nname = "cmtr"\n')
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_mise = fake_bin / "mise"
    fake_mise.write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
    fake_mise.chmod(0o755)
    script_path = tmp_path / "prepare-commit-msg"
    script_path.write_text(_hook_script_for(checkout), encoding="utf-8")
    script_path.chmod(0o755)

    result = subprocess.run(
        [str(script_path), str(tmp_path / "COMMIT_EDITMSG")],
        cwd=tmp_path,
        env={"PATH": str(fake_bin)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "cmtr: uv not found; skipping commit message generation" in result.stderr


def test_append_failure_comment_comments_every_error_line(tmp_path: Path) -> None:
    message_path = tmp_path / "COMMIT_EDITMSG"
    message_path.write_text("# Please enter a message\n", encoding="utf-8")

    append_failure_comment(message_path, "first line\nsecond line")

    text = message_path.read_text(encoding="utf-8")
    assert "# cmtr failed: first line\n" in text
    assert "# second line\n" in text
    assert "\nsecond line\n" not in text


def test_prepare_commit_msg_failure_respects_configured_comment_char(
    tmp_path: Path, monkeypatch
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "core.commentChar", ";"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    message_path = tmp_path / "COMMIT_EDITMSG"
    message_path.write_text("; Commit template\n", encoding="utf-8")

    def fail_generate(*args, **kwargs):
        raise UserError("first line\nsecond line")

    monkeypatch.setattr("cmtr.hook.generate_message", fail_generate)

    exit_code = run_prepare_commit_msg(
        message_path=message_path,
        source="template",
        sha=None,
        repo_root=tmp_path,
        config=DEFAULT_CONFIG,
        api_key=None,
    )

    text = message_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "; cmtr failed: first line\n" in text
    assert "; second line\n" in text
    assert "# cmtr failed:" not in text
    assert "\nsecond line\n" not in text


def test_prepare_commit_msg_uses_template_source_when_template_is_empty(
    tmp_path: Path, monkeypatch
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    message_path = tmp_path / "COMMIT_EDITMSG"
    message_path.write_text("# Commit template\n", encoding="utf-8")

    monkeypatch.setattr(
        "cmtr.hook.generate_message",
        lambda repo_root, config, api_key: "feat: generated",
    )

    exit_code = run_prepare_commit_msg(
        message_path=message_path,
        source="template",
        sha=None,
        repo_root=tmp_path,
        config=DEFAULT_CONFIG,
        api_key=None,
    )

    assert exit_code == 0
    assert message_path.read_text(encoding="utf-8").startswith("feat: generated\n\n")


def test_prepare_commit_msg_respects_configured_comment_char(
    tmp_path: Path, monkeypatch
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "core.commentChar", ";"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    message_path = tmp_path / "COMMIT_EDITMSG"
    message_path.write_text("; Commit template\n", encoding="utf-8")

    monkeypatch.setattr(
        "cmtr.hook.generate_message",
        lambda repo_root, config, api_key: "feat: generated",
    )

    exit_code = run_prepare_commit_msg(
        message_path=message_path,
        source="template",
        sha=None,
        repo_root=tmp_path,
        config=DEFAULT_CONFIG,
        api_key=None,
    )

    assert exit_code == 0
    assert message_path.read_text(encoding="utf-8").startswith("feat: generated\n\n")


def test_prepare_commit_msg_skips_template_with_leading_comments_and_message(
    tmp_path: Path, monkeypatch
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    original = "# Template instructions\n\nchore: existing template message\n"
    message_path = tmp_path / "COMMIT_EDITMSG"
    message_path.write_text(original, encoding="utf-8")

    def fail_generate(*args, **kwargs):
        raise AssertionError("generation should not start")

    monkeypatch.setattr("cmtr.hook.generate_message", fail_generate)

    exit_code = run_prepare_commit_msg(
        message_path=message_path,
        source="template",
        sha=None,
        repo_root=tmp_path,
        config=DEFAULT_CONFIG,
        api_key=None,
    )

    assert exit_code == 0
    assert message_path.read_text(encoding="utf-8") == original
