from __future__ import annotations

from pathlib import Path
import importlib.metadata
import os
import subprocess
import tempfile

import typer
from rich.console import Console

from .config import (
    CONFIG_KEYS,
    coerce_config_value,
    global_config_path,
    load_config,
    read_global_config,
    set_global_value,
    unset_global_value,
)
from .core import collect_context, resolve_repo_root
from .errors import CmtrError, OpenAIError, UserError
from .hook import append_failure_comment, install_hook, run_prepare_commit_msg, uninstall_hook
from .openai_client import generate_commit_message
from .prompt import PromptContext, build_system_prompt, build_user_prompt
from .ui import StatusLine


def _version_callback(value: bool) -> None:
    if not value:
        return
    try:
        version = importlib.metadata.version("cmtr")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    typer.echo(version)
    raise typer.Exit()


app = typer.Typer(
    add_completion=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)

config_app = typer.Typer(help="Manage cmtr configuration.")
app.add_typer(config_app, name="config")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    hook: bool = typer.Option(False, "--hook", help="Install the prepare-commit-msg hook."),
    uninstall: bool = typer.Option(
        False, "--uninstall-hook", help="Remove the cmtr hook."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing hook."),
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the generated commit message and exit."
    ),
    no_edit: bool = typer.Option(
        False, "--no-edit", help="Do not open the editor after generating the message."
    ),
    model: str | None = typer.Option(None, "--model", help="Override the model."),
    max_diff_bytes: int | None = typer.Option(
        None, "--max-diff-bytes", help="Max diff bytes sent to the model."
    ),
    max_patch_lines: int | None = typer.Option(
        None, "--max-patch-lines", help="Max diff lines sent to the model."
    ),
    max_log_entries: int | None = typer.Option(
        None, "--max-log-entries", help="Max git log entries per path."
    ),
    max_log_paths: int | None = typer.Option(
        None, "--max-log-paths", help="Max paths to include in git log context."
    ),
    max_log_body_lines: int | None = typer.Option(
        None, "--max-log-body-lines", help="Max commit body lines to include per log entry."
    ),
    timeout_seconds: float | None = typer.Option(
        None, "--timeout", help="OpenAI request timeout in seconds."
    ),
    reasoning_effort: str | None = typer.Option(
        None,
        "--reasoning-effort",
        help="Reasoning effort hint (e.g. none, low, medium).",
    ),
    text_verbosity: str | None = typer.Option(
        None, "--text-verbosity", help="Text verbosity hint (e.g. low, medium, high)."
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", help="Override the OpenAI API base URL."
    ),
    organization: str | None = typer.Option(
        None, "--organization", help="Override the OpenAI organization ID."
    ),
) -> None:
    ctx.obj = {
        "model": model,
        "max_diff_bytes": max_diff_bytes,
        "max_patch_lines": max_patch_lines,
        "max_log_entries": max_log_entries,
        "max_log_paths": max_log_paths,
        "max_log_body_lines": max_log_body_lines,
        "timeout_seconds": timeout_seconds,
        "reasoning_effort": reasoning_effort,
        "text_verbosity": text_verbosity,
        "base_url": base_url,
        "organization": organization,
    }

    if ctx.invoked_subcommand is not None:
        return

    console = Console()
    error_console = Console(stderr=True)

    try:
        repo_root = resolve_repo_root(Path.cwd())
        if hook:
            hook_path = install_hook(repo_root, force=force)
            console.print(f"Hook installed at {hook_path}")
            return
        if uninstall:
            hook_path = uninstall_hook(repo_root)
            console.print(f"Hook removed from {hook_path}")
            return
        config = load_config(repo_root, overrides=ctx.obj)
        api_key = _require_api_key()
        with StatusLine(console, "Analyzing staged changes...") as status:
            context = collect_context(repo_root, config)
            status.update("Generating commit message...")
            prompt_context = PromptContext(
                staged_files=context.staged_files,
                name_status=context.name_status,
                diff_stat=context.diff_stat,
                diff_patch=context.diff_patch,
                log_contexts=context.log_contexts,
                max_log_body_lines=config.max_log_body_lines,
                diff_was_truncated=context.diff_was_truncated,
                has_commit_history=context.has_commit_history,
            )
            system_prompt = build_system_prompt()
            user_prompt = build_user_prompt(prompt_context)
            message = generate_commit_message(
                config=config,
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        if dry_run:
            console.print(message)
            return
        extra_args = _filtered_git_args(ctx.args)
        exit_code = _run_git_commit(repo_root, message, extra_args, no_edit=no_edit)
        raise typer.Exit(code=exit_code)
    except CmtrError as exc:
        error_console.print(f"[red]cmtr error:[/red] {exc}")
        raise typer.Exit(code=1)
    except Exception as exc:
        error_console.print(f"[red]unexpected error:[/red] {exc}")
        raise typer.Exit(code=1)


@app.command("prepare-commit-msg", hidden=True)
def prepare_commit_msg(
    message_path: Path,
    source: str | None = typer.Argument(None),
    sha: str | None = typer.Argument(None),
    model: str | None = typer.Option(None, "--model"),
    max_diff_bytes: int | None = typer.Option(None, "--max-diff-bytes"),
    max_patch_lines: int | None = typer.Option(None, "--max-patch-lines"),
    max_log_entries: int | None = typer.Option(None, "--max-log-entries"),
    max_log_paths: int | None = typer.Option(None, "--max-log-paths"),
    max_log_body_lines: int | None = typer.Option(None, "--max-log-body-lines"),
    timeout_seconds: float | None = typer.Option(None, "--timeout"),
    reasoning_effort: str | None = typer.Option(None, "--reasoning-effort"),
    text_verbosity: str | None = typer.Option(None, "--text-verbosity"),
    base_url: str | None = typer.Option(None, "--base-url"),
    organization: str | None = typer.Option(None, "--organization"),
) -> None:
    console = Console(stderr=True)
    overrides = {
        "model": model,
        "max_diff_bytes": max_diff_bytes,
        "max_patch_lines": max_patch_lines,
        "max_log_entries": max_log_entries,
        "max_log_paths": max_log_paths,
        "max_log_body_lines": max_log_body_lines,
        "timeout_seconds": timeout_seconds,
        "reasoning_effort": reasoning_effort,
        "text_verbosity": text_verbosity,
        "base_url": base_url,
        "organization": organization,
    }
    try:
        repo_root = resolve_repo_root(Path.cwd())
        config = load_config(repo_root, overrides=overrides)
        api_key = _require_api_key()
        with StatusLine(console, "Generating commit message..."):
            exit_code = run_prepare_commit_msg(
                message_path=message_path,
                source=source,
                sha=sha,
                repo_root=repo_root,
                config=config,
                api_key=api_key,
            )
        raise typer.Exit(code=exit_code)
    except OpenAIError as exc:
        append_failure_comment(message_path, str(exc))
        console.print(f"[red]cmtr error:[/red] {exc}")
        raise typer.Exit(code=0)
    except CmtrError as exc:
        append_failure_comment(message_path, str(exc))
        console.print(f"[red]cmtr error:[/red] {exc}")
        raise typer.Exit(code=0)
    except Exception as exc:
        append_failure_comment(message_path, str(exc))
        console.print(f"[red]unexpected error:[/red] {exc}")
        raise typer.Exit(code=0)


def _require_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise UserError("OPENAI_API_KEY is not set in the environment.")
    return api_key


def _filtered_git_args(args: list[str]) -> list[str]:
    forbidden = {"-m", "--message", "-F", "--file", "--reuse-message", "-c", "-C"}
    for arg in args:
        if arg in forbidden:
            raise UserError("Do not pass -m/-F/-C/-c options; cmtr supplies the message.")
    return list(args)


def _run_git_commit(repo_root: Path, message: str, extra_args: list[str], no_edit: bool) -> int:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as temp_file:
            temp_file.write(message.strip() + "\n")
            temp_path = Path(temp_file.name)
        args = ["git", "commit", "-v", "-F", str(temp_path)]
        if not no_edit:
            args.append("--edit")
        args.extend(extra_args)
        result = subprocess.run(args, cwd=repo_root)
        return result.returncode
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def main_entry() -> None:
    app()


@config_app.command("path")
def config_path() -> None:
    try:
        typer.echo(global_config_path())
    except CmtrError as exc:
        typer.echo(f"cmtr error: {exc}", err=True)
        raise typer.Exit(code=1)


@config_app.command("list")
def config_list() -> None:
    try:
        data = read_global_config()
    except CmtrError as exc:
        typer.echo(f"cmtr error: {exc}", err=True)
        raise typer.Exit(code=1)
    defaults = load_config(Path.cwd()).__dict__
    for key in sorted(defaults.keys()):
        if key in data:
            value = data[key]
            label = "override"
        else:
            value = defaults[key]
            label = "default"
        typer.echo(f"{key} = {_format_config_value(value)} ({label})")


@config_app.command("get")
def config_get(key: str) -> None:
    try:
        if key not in CONFIG_KEYS:
            raise typer.BadParameter(f"Unknown key: {key}")
        data = read_global_config()
        if key not in data:
            raise typer.Exit(code=1)
        typer.echo(data[key])
    except CmtrError as exc:
        typer.echo(f"cmtr error: {exc}", err=True)
        raise typer.Exit(code=1)


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    try:
        if key not in CONFIG_KEYS:
            raise typer.BadParameter(f"Unknown key: {key}")
        coerced = coerce_config_value(key, value)
        set_global_value(key, coerced)
    except CmtrError as exc:
        typer.echo(f"cmtr error: {exc}", err=True)
        raise typer.Exit(code=1)


@config_app.command("unset")
def config_unset(key: str) -> None:
    try:
        if key not in CONFIG_KEYS:
            raise typer.BadParameter(f"Unknown key: {key}")
        unset_global_value(key)
    except CmtrError as exc:
        typer.echo(f"cmtr error: {exc}", err=True)
        raise typer.Exit(code=1)


def _format_config_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        return value
    return str(value)
