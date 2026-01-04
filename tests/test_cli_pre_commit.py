from __future__ import annotations

from pathlib import Path
import subprocess

from typer.testing import CliRunner

import cmtr.cli as cli
import cmtr.hook as hook


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)


def test_hook_pre_commit_runs_install(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".pre-commit-config.yaml").write_text("repos:\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hook.shutil, "which", lambda _: "/usr/local/bin/uvx")

    called: dict[str, object] = {}

    def fake_run_pre_commit(repo_root: Path) -> None:
        called["repo_root"] = repo_root

    monkeypatch.setattr(cli, "_run_pre_commit_install", fake_run_pre_commit)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--hook"], input="y\ny\n")

    assert result.exit_code == 0
    assert called["repo_root"] == tmp_path
    text = (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "entry: uvx cmtr@latest prepare-commit-msg" in text
    assert "default_stages: [pre-commit]" in text


def test_hook_pre_commit_skips_install_on_decline(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".pre-commit-config.yaml").write_text("repos:\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hook.shutil, "which", lambda _: "/usr/local/bin/uvx")

    def fail_run_pre_commit(*args, **kwargs):
        raise AssertionError("pre-commit install should not run")

    monkeypatch.setattr(cli, "_run_pre_commit_install", fail_run_pre_commit)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--hook"], input="y\nn\n")

    assert result.exit_code == 0


def test_hook_pre_commit_detects_existing_cmtr_hook(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".pre-commit-config.yaml").write_text(
        """repos:\n  - repo: local\n    hooks:\n      - id: prepare-commit-msg\n        entry: uvx cmtr@latest prepare-commit-msg\n        language: system\n""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    def fail_run_pre_commit(*args, **kwargs):
        raise AssertionError("pre-commit install should not run")

    monkeypatch.setattr(cli, "_run_pre_commit_install", fail_run_pre_commit)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--hook"], input="y\n")

    assert result.exit_code == 0
    assert "Nothing to do." in result.output


def test_hook_pre_commit_requires_force_for_other_hook(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".pre-commit-config.yaml").write_text(
        """repos:\n  - repo: local\n    hooks:\n      - id: prepare-commit-msg\n        entry: scripts/prepare-commit-msg\n        language: system\n""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hook.shutil, "which", lambda _: "/usr/local/bin/uvx")
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--hook"])

    assert result.exit_code == 1
