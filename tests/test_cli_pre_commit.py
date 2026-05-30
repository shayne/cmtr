from __future__ import annotations

from pathlib import Path
import subprocess

import pytest
from typer.testing import CliRunner

import cmtr.cli as cli
import cmtr.hook as hook
from cmtr.errors import UserError
from cmtr.core import CommitContext


def _init_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=path, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


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
    assert "default_stages:" not in text
    assert "stages: [prepare-commit-msg]" in text


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


def test_hook_pre_commit_detects_existing_cmtr_hook(
    tmp_path: Path, monkeypatch
) -> None:
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


def test_hook_pre_commit_requires_force_for_other_hook(
    tmp_path: Path, monkeypatch
) -> None:
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


def test_hook_rejects_extra_git_flags_before_install(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "resolve_repo_root", lambda cwd: tmp_path)

    def fail_install(*args, **kwargs):
        raise AssertionError("hook install should not start")

    monkeypatch.setattr(cli, "install_hook", fail_install)

    result = CliRunner().invoke(cli.app, ["--hook", "--no-verify"])

    assert result.exit_code == 1
    assert "--hook does not accept git commit arguments" in result.output
    assert "hook install should not start" not in result.output


def test_uninstall_hook_rejects_extra_git_flags_before_uninstall(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "resolve_repo_root", lambda cwd: tmp_path)

    def fail_uninstall(*args, **kwargs):
        raise AssertionError("hook uninstall should not start")

    monkeypatch.setattr(cli, "uninstall_hook", fail_uninstall)

    result = CliRunner().invoke(cli.app, ["--uninstall-hook", "--no-verify"])

    assert result.exit_code == 1
    assert "--uninstall-hook does not accept git commit arguments" in result.output
    assert "hook uninstall should not start" not in result.output


def test_hook_and_uninstall_are_mutually_exclusive(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "resolve_repo_root", lambda cwd: tmp_path)

    def fail_install(*args, **kwargs):
        raise AssertionError("hook install should not start")

    monkeypatch.setattr(cli, "install_hook", fail_install)

    result = CliRunner().invoke(cli.app, ["--hook", "--uninstall-hook"])

    assert result.exit_code == 1
    assert "--hook and --uninstall-hook cannot be used together" in result.output
    assert "hook install should not start" not in result.output


def test_hook_and_uninstall_conflict_reports_before_git_repo_check(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli.app, ["--hook", "--uninstall-hook"])

    assert result.exit_code == 1
    assert "--hook and --uninstall-hook cannot be used together" in result.output
    assert "not a git repository" not in result.output


@pytest.mark.parametrize("flag", ["--force", "--global"])
def test_hook_only_options_are_rejected_for_commit_mode(
    tmp_path: Path, monkeypatch, flag: str
) -> None:
    monkeypatch.setattr(cli, "resolve_repo_root", lambda cwd: tmp_path)

    def fail_collect_context(*args, **kwargs):
        raise AssertionError("generation should not start")

    monkeypatch.setattr(cli, "collect_context", fail_collect_context)

    result = CliRunner().invoke(cli.app, ["--dry-run", flag])

    assert result.exit_code == 1
    assert f"{flag} can only be used with --hook or --uninstall-hook" in result.output
    assert "generation should not start" not in result.output


def test_prepare_commit_msg_skips_message_source_before_auth(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path)
    message_path = tmp_path / "COMMIT_EDITMSG"
    message_path.write_text("Manual subject\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex-home"))

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["prepare-commit-msg", str(message_path), "message"],
    )

    assert result.exit_code == 0
    assert message_path.read_text(encoding="utf-8") == "Manual subject\n"


def test_main_passes_configured_model_to_codex(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}
    context = CommitContext(
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

    monkeypatch.setattr(cli, "resolve_repo_root", lambda cwd: tmp_path)
    monkeypatch.setattr(cli, "collect_context", lambda repo_root, config: context)

    def fake_generate_message_from_prompts(**kwargs):
        captured.update(kwargs)
        return "feat: add greeting"

    monkeypatch.setattr(
        cli,
        "generate_message_from_prompts",
        fake_generate_message_from_prompts,
    )

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--dry-run", "--model", "gpt-custom-codex"])

    assert result.exit_code == 0
    assert captured["config"].codex_model == "gpt-custom-codex"
    assert "feat: add greeting" in result.output


def test_main_prefers_explicit_codex_model_over_model_alias(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}
    context = CommitContext(
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

    monkeypatch.setattr(cli, "resolve_repo_root", lambda cwd: tmp_path)
    monkeypatch.setattr(cli, "collect_context", lambda repo_root, config: context)
    monkeypatch.setattr(
        cli,
        "generate_message_from_prompts",
        lambda **kwargs: captured.update(kwargs) or "feat: add greeting",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "--dry-run",
            "--model",
            "gpt-api",
            "--codex-model",
            "gpt-codex",
        ],
    )

    assert result.exit_code == 0
    assert captured["config"].codex_model == "gpt-codex"


def test_main_falls_back_to_openai_when_codex_generation_fails(
    tmp_path: Path, monkeypatch
) -> None:
    context = CommitContext(
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

    monkeypatch.setattr(cli, "resolve_repo_root", lambda cwd: tmp_path)
    monkeypatch.setattr(cli, "collect_context", lambda repo_root, config: context)
    monkeypatch.setattr(cli, "_get_api_key", lambda: "test-key")

    def fake_generate_message_from_prompts(**kwargs):
        callback = kwargs.get("on_backend_status")
        if callback:
            callback("codex")
            callback("openai_fallback")
        return "feat: fallback to api"

    monkeypatch.setattr(
        cli,
        "generate_message_from_prompts",
        fake_generate_message_from_prompts,
    )

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--dry-run"])

    assert result.exit_code == 0
    assert "feat: fallback to api" in result.output


@pytest.mark.parametrize(
    "arg",
    [
        "--all",
        "-a",
        "--include",
        "-i",
        "--only",
        "-o",
        "--patch",
        "-p",
        "--interactive",
        "--dry-run",
        "--short",
        "--porcelain",
        "--long",
        "--null",
        "--branch",
        "-z",
        "--message=hello",
        "-mhello",
        "-am",
        "--file=msg.txt",
        "-Fmsg.txt",
        "--reuse-message=HEAD",
        "-CHEAD",
        "-cHEAD",
        "--fixup=HEAD",
        "--squash=HEAD",
        "--amend",
        "--allow-empty",
        "--allow-empty-message",
        "--cleanup",
        "--cleanup=strip",
        "--pathspec-from-file",
        "--pathspec-from-file=paths.txt",
        "--pathspec-file-nul",
        "--reset-author",
        "--template",
        "--template=message.txt",
        "-tfoo.txt",
    ],
)
def test_filtered_git_args_rejects_attached_message_options(arg: str) -> None:
    with pytest.raises(UserError):
        cli._filtered_git_args([arg])


@pytest.mark.parametrize(
    "args",
    [
        ["--no-verify"],
        ["-n"],
        ["--signoff"],
        ["-s"],
        ["--gpg-sign=DEADBEEF"],
        ["-Sdeadbeef"],
        ["--author", "Test User <test@example.com>"],
        ["--date", "2026-05-30T12:00:00-04:00"],
        ["--date", "-1 day"],
        ["--trailer", "Reviewed-by=Test User <test@example.com>"],
    ],
)
def test_filtered_git_args_allows_safe_commit_options(args: list[str]) -> None:
    assert cli._filtered_git_args(args) == args


@pytest.mark.parametrize(
    "args",
    [
        ["--author"],
        ["--date"],
        ["--trailer"],
        ["--date", "--"],
        ["--author="],
        ["--date="],
        ["--trailer="],
    ],
)
def test_filtered_git_args_rejects_missing_safe_option_values(
    args: list[str],
) -> None:
    with pytest.raises(UserError, match="requires a value"):
        cli._filtered_git_args(args)


def test_cli_rejects_message_flags_before_generation(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "resolve_repo_root", lambda cwd: tmp_path)

    def fail_collect_context(*args, **kwargs):
        raise AssertionError("generation should not start")

    monkeypatch.setattr(cli, "collect_context", fail_collect_context)

    result = CliRunner().invoke(cli.app, ["--dry-run", "-m", "manual"])

    assert result.exit_code == 1
    assert "cmtr supplies the message" in result.output
    assert "generation should not start" not in result.output


def test_cli_passes_extra_git_flags_to_commit(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}
    context = CommitContext(
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

    monkeypatch.setattr(cli, "resolve_repo_root", lambda cwd: tmp_path)
    monkeypatch.setattr(cli, "collect_context", lambda repo_root, config: context)
    monkeypatch.setattr(
        cli,
        "generate_message_from_prompts",
        lambda **kwargs: "feat: add file",
    )
    monkeypatch.setattr(
        cli,
        "_run_git_commit",
        lambda repo_root, message, extra_args, no_edit: (
            captured.update(
                {
                    "repo_root": repo_root,
                    "message": message,
                    "extra_args": extra_args,
                    "no_edit": no_edit,
                }
            )
            or 0
        ),
    )

    result = CliRunner().invoke(cli.app, ["--no-edit", "--no-verify"])

    assert result.exit_code == 0
    assert captured["extra_args"] == ["--no-verify"]
    assert captured["no_edit"] is True


def test_cli_passes_pathspec_after_separator_to_commit(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}
    context = CommitContext(
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

    monkeypatch.setattr(cli, "resolve_repo_root", lambda cwd: tmp_path)

    def fake_collect_context(repo_root, config, **kwargs):
        captured["pathspecs"] = kwargs.get("pathspecs")
        return context

    monkeypatch.setattr(cli, "collect_context", fake_collect_context)
    monkeypatch.setattr(
        cli,
        "generate_message_from_prompts",
        lambda **kwargs: "feat: add file",
    )
    monkeypatch.setattr(
        cli,
        "_run_git_commit",
        lambda repo_root, message, extra_args, no_edit: (
            captured.update({"extra_args": extra_args}) or 0
        ),
    )

    result = CliRunner().invoke(cli.app, ["--no-edit", "--", "file.py"])

    assert result.exit_code == 0
    assert captured["extra_args"] == ["--", "file.py"]
    assert captured["pathspecs"] == ["file.py"]


def test_cli_treats_plain_arg_after_root_option_as_pathspec(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}
    context = CommitContext(
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

    monkeypatch.setattr(cli, "resolve_repo_root", lambda cwd: tmp_path)

    def fake_collect_context(repo_root, config, **kwargs):
        captured["pathspecs"] = kwargs.get("pathspecs")
        return context

    monkeypatch.setattr(cli, "collect_context", fake_collect_context)
    monkeypatch.setattr(
        cli,
        "generate_message_from_prompts",
        lambda **kwargs: "feat: add file",
    )
    monkeypatch.setattr(
        cli,
        "_run_git_commit",
        lambda repo_root, message, extra_args, no_edit: (
            captured.update({"extra_args": extra_args}) or 0
        ),
    )

    result = CliRunner().invoke(cli.app, ["--no-edit", "file.py"])

    assert result.exit_code == 0
    assert captured["extra_args"] == ["--", "file.py"]
    assert captured["pathspecs"] == ["file.py"]


def test_cli_unknown_plain_command_does_not_start_generation(monkeypatch) -> None:
    def fail_resolve_repo_root(*args, **kwargs):
        raise AssertionError("generation should not start")

    monkeypatch.setattr(cli, "resolve_repo_root", fail_resolve_repo_root)

    result = CliRunner().invoke(cli.app, ["confg"])

    assert result.exit_code == 2
    assert "No such command 'confg'" in result.output
    assert "generation should not start" not in result.output


def test_get_api_key_treats_blank_value_as_missing(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "  ")

    assert cli._get_api_key() is None


def test_auth_status_works_outside_git_repo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex-home"))

    runner = CliRunner()
    result = runner.invoke(cli.app, ["auth", "status"])

    assert result.exit_code == 0
    assert "prefer_codex: true" in result.output
    assert "selected mode: unknown" not in result.output


def test_auth_status_treats_blank_api_key_as_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "  ")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex-home"))

    result = CliRunner().invoke(cli.app, ["auth", "status"])

    assert result.exit_code == 0
    assert "OPENAI_API_KEY: missing" in result.output
    assert "selected mode: openai" not in result.output


def test_main_reports_no_staged_changes_before_auth(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex-home"))

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--dry-run"])

    assert result.exit_code == 1
    assert "No staged changes found" in result.output
    assert "OPENAI_API_KEY is not set" not in result.output


def test_prepare_commit_msg_reports_no_staged_changes_before_auth(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path)
    message_path = tmp_path / "COMMIT_EDITMSG"
    message_path.write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex-home"))

    runner = CliRunner()
    result = runner.invoke(cli.app, ["prepare-commit-msg", str(message_path)])

    assert result.exit_code == 0
    message = message_path.read_text(encoding="utf-8")
    assert "# cmtr failed: No staged changes found" in message
    assert "OPENAI_API_KEY is not set" not in message


def test_run_git_commit_commits_message_in_real_repo(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)

    exit_code = cli._run_git_commit(
        repo_root=tmp_path,
        message="feat: add file\n\nExplain why.",
        extra_args=[],
        no_edit=True,
    )

    assert exit_code == 0
    subject = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    body = subprocess.run(
        ["git", "log", "-1", "--pretty=%b"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert subject == "feat: add file"
    assert body == "Explain why."


def test_cli_dry_run_uses_real_staged_context_without_commit(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        cli,
        "generate_message_from_prompts",
        lambda **kwargs: "feat: add file",
    )

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--dry-run"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "feat: add file"
    assert "Analyzing staged changes" in result.stderr
    log_result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert log_result.returncode != 0


def test_cli_no_edit_commits_with_fake_backend(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        cli,
        "generate_message_from_prompts",
        lambda **kwargs: "feat: add file\n\nExplain why.",
    )

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--no-edit"])

    assert result.exit_code == 0
    subject = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    body = subprocess.run(
        ["git", "log", "-1", "--pretty=%b"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert subject == "feat: add file"
    assert body == "Explain why."


def test_cli_pathspec_from_subdirectory_is_relative_to_invocation_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path)
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "file.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "sub/file.txt"], cwd=tmp_path, check=True)
    monkeypatch.chdir(subdir)
    monkeypatch.setattr(cli, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        cli,
        "generate_message_from_prompts",
        lambda **kwargs: "feat: add sub file",
    )

    result = CliRunner().invoke(cli.app, ["--no-edit", "--", "file.txt"])

    assert result.exit_code == 0
    files = subprocess.run(
        ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "sub/file.txt" in files


def test_cli_magic_exclude_pathspec_from_subdirectory_matches_git(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path)
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "keep.txt").write_text("keep\n", encoding="utf-8")
    (subdir / "skip.txt").write_text("skip\n", encoding="utf-8")
    subprocess.run(["git", "add", "sub"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: add files"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (subdir / "keep.txt").write_text("keep changed\n", encoding="utf-8")
    (subdir / "skip.txt").write_text("skip changed\n", encoding="utf-8")
    subprocess.run(["git", "add", "sub"], cwd=tmp_path, check=True)
    monkeypatch.chdir(subdir)
    monkeypatch.setattr(cli, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        cli,
        "generate_message_from_prompts",
        lambda **kwargs: "feat: update kept file",
    )

    result = CliRunner().invoke(cli.app, ["--no-edit", "--", ".", ":!skip.txt"])

    assert result.exit_code == 0
    committed_files = subprocess.run(
        ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    staged_files = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert committed_files == ["sub/keep.txt"]
    assert staged_files == ["sub/skip.txt"]


def test_cli_rejects_absolute_pathspec_outside_repo(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (tmp_path / "file.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)

    def fail_generate_message_from_prompts(**kwargs):
        raise AssertionError("generation should not start")

    monkeypatch.setattr(
        cli,
        "generate_message_from_prompts",
        fail_generate_message_from_prompts,
    )

    result = CliRunner().invoke(cli.app, ["--no-edit", "--", str(outside)])

    assert result.exit_code == 1
    assert "outside the repository" in result.output
    assert "generation should not start" not in result.output


def test_cli_uses_shared_prompt_generation(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}
    context = CommitContext(
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

    def fake_generate_message_from_prompts(**kwargs):
        captured.update(kwargs)
        callback = kwargs.get("on_backend_status")
        if callback:
            callback("openai")
        return "feat: shared generation"

    monkeypatch.setattr(cli, "resolve_repo_root", lambda cwd: tmp_path)
    monkeypatch.setattr(cli, "collect_context", lambda repo_root, config: context)
    monkeypatch.setattr(cli, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        cli,
        "generate_message_from_prompts",
        fake_generate_message_from_prompts,
        raising=False,
    )

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--dry-run"])

    assert result.exit_code == 0
    assert "feat: shared generation" in result.output
    assert captured["repo_root"] == tmp_path
    assert captured["api_key"] == "test-key"
    assert "system_prompt" in captured
    assert "user_prompt" in captured


def test_cli_print_prompt_includes_real_staged_context(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        cli,
        "generate_message_from_prompts",
        lambda **kwargs: "feat: add file",
    )

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--dry-run", "--print-prompt"])

    assert result.exit_code == 0
    assert "You are an expert software engineer" in result.output
    assert '<staged_files format="name-status">' in result.output
    assert "A      file.txt" in result.output
    assert '<diff_patch format="git-diff"' in result.output
    assert "+hello" in result.output
    assert "feat: add file" in result.output
