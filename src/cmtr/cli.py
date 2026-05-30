from __future__ import annotations

from pathlib import Path
import importlib.metadata
import os
import posixpath
import shutil
import subprocess
import tempfile

import click
import typer
from rich.console import Console
from typer.core import TyperGroup

from .config import (
    CONFIG_KEYS,
    DEFAULT_CONFIG,
    coerce_config_value,
    global_config_path,
    load_config,
    load_global_config,
    read_global_config,
    set_global_value,
    unset_global_value,
    write_global_config,
)
from .core import (
    build_prompts,
    collect_context,
    describe_auth_mode,
    generate_message_from_prompts,
    resolve_repo_root,
)
from .errors import CmtrError, CodexError, OpenAIError, UserError
from .codex_client import (
    codex_status,
)
from .hook import (
    append_failure_comment,
    append_failure_comment_for_repo,
    detect_pre_commit_config,
    install_hook,
    PRE_COMMIT_INLINE_ENTRY,
    pre_commit_hook_status,
    run_prepare_commit_msg,
    should_skip_prepare_commit_msg,
    uninstall_hook,
)
from .ui import StatusLine


class CmtrGroup(TyperGroup):
    def invoke(self, ctx: click.Context) -> object:
        protected_args = list(getattr(ctx, "_protected_args", []))
        if protected_args:
            args = [*protected_args, *ctx.args]
            command_name = str(args[0])
            command = self.get_command(ctx, command_name)
            if command is None and ctx.token_normalize_func is not None:
                command = self.get_command(ctx, ctx.token_normalize_func(command_name))
            if (
                command is None
                and self.invoke_without_command
                and (command_name.startswith("-") or _has_explicit_root_option(ctx))
            ):
                ctx.args = args if command_name.startswith("-") else ["--", *args]
                ctx._protected_args = []
                ctx.invoked_subcommand = None
                with ctx:
                    return click.Command.invoke(self, ctx)
        return super().invoke(ctx)


def _has_explicit_root_option(ctx: click.Context) -> bool:
    truthy_options = {
        "hook",
        "uninstall",
        "force",
        "use_global_hooks",
        "dry_run",
        "print_prompt",
        "no_edit",
    }
    value_options = {
        "model",
        "codex_model",
        "max_diff_bytes",
        "max_patch_lines",
        "max_log_entries",
        "max_log_paths",
        "max_log_body_lines",
        "timeout_seconds",
        "reasoning_effort",
        "text_verbosity",
        "base_url",
        "organization",
        "project",
        "prefer_codex",
    }
    params = ctx.params
    if any(params.get(option) for option in truthy_options):
        return True
    return any(params.get(option) is not None for option in value_options)


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
    cls=CmtrGroup,
    invoke_without_command=True,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)

config_app = typer.Typer(help="Manage cmtr configuration.")
app.add_typer(config_app, name="config")

auth_app = typer.Typer(help="Auth status and helpers.")
app.add_typer(auth_app, name="auth")


@app.callback(
    invoke_without_command=True,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def main(
    ctx: typer.Context,
    hook: bool = typer.Option(
        False, "--hook", help="Install the prepare-commit-msg hook."
    ),
    uninstall: bool = typer.Option(
        False, "--uninstall-hook", help="Remove the cmtr hook."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing hook."),
    use_global_hooks: bool = typer.Option(
        False,
        "--global",
        help="Install or remove the hook in the globally configured hooks path.",
    ),
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
    print_prompt: bool = typer.Option(
        False,
        "--print-prompt",
        help="Print the prompts before generating the message.",
    ),
    no_edit: bool = typer.Option(
        False, "--no-edit", help="Do not open the editor after generating the message."
    ),
    model: str | None = typer.Option(None, "--model", help="Override the model."),
    codex_model: str | None = typer.Option(
        None, "--codex-model", help="Override the Codex CLI model."
    ),
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
        None,
        "--max-log-body-lines",
        help="Max commit body lines to include per log entry.",
    ),
    timeout_seconds: float | None = typer.Option(
        None, "--timeout", help="Backend request timeout in seconds."
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
    project: str | None = typer.Option(
        None, "--project", help="Override the OpenAI project ID."
    ),
    prefer_codex: bool | None = typer.Option(
        None,
        "--prefer-codex/--no-prefer-codex",
        help="Prefer Codex CLI when available.",
    ),
) -> None:
    ctx.obj = {
        "model": model,
        "codex_model": codex_model if codex_model is not None else model,
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
        "project": project,
        "prefer_codex": prefer_codex,
    }

    if ctx.invoked_subcommand is not None:
        return

    console = Console()
    error_console = Console(stderr=True)
    status_console = Console(stderr=True)

    try:
        if hook and uninstall:
            raise UserError("--hook and --uninstall-hook cannot be used together.")
        invocation_cwd = Path.cwd()
        repo_root = resolve_repo_root(invocation_cwd)
        if hook:
            _reject_extra_args(ctx.args, "--hook")
            pre_commit_config = detect_pre_commit_config(repo_root)
            if pre_commit_config:
                if use_global_hooks:
                    raise UserError(
                        "pre-commit config detected; --global is not supported."
                    )
                hook_status = pre_commit_hook_status(pre_commit_config)
                if hook_status == "cmtr":
                    console.print(
                        f"cmtr pre-commit hook already configured in {pre_commit_config.name}."
                    )
                    console.print("Nothing to do.")
                    return
                if hook_status == "other" and not force:
                    raise UserError(
                        "prepare-commit-msg hook already configured in pre-commit. "
                        "Re-run with --force to replace."
                    )
                if hook_status == "other" and force:
                    console.print(
                        "pre-commit prepare-commit-msg hook found; will replace with:"
                    )
                else:
                    console.print("Will add pre-commit prepare-commit-msg hook:")
                console.print(f"  {PRE_COMMIT_INLINE_ENTRY}")
                consent = typer.confirm("Install now?", default=False)
                if not consent:
                    console.print("Hook install canceled.")
                    return
            hook_path = install_hook(
                repo_root, force=force, use_global=use_global_hooks
            )
            console.print(f"Hook installed at {hook_path}")
            if pre_commit_config:
                run_install = typer.confirm(
                    "Run `pre-commit install --hook-type prepare-commit-msg` now?",
                    default=True,
                )
                if run_install:
                    _run_pre_commit_install(repo_root)
            return
        if uninstall:
            _reject_extra_args(ctx.args, "--uninstall-hook")
            hook_path = uninstall_hook(repo_root, use_global=use_global_hooks)
            console.print(f"Hook removed from {hook_path}")
            return
        _reject_hook_only_options(force=force, use_global_hooks=use_global_hooks)
        extra_args = _filtered_git_args(ctx.args)
        pathspecs = _pathspecs_from_git_args(extra_args)
        if pathspecs is not None:
            pathspecs = _normalize_pathspecs_for_repo(
                pathspecs, repo_root=repo_root, invocation_cwd=invocation_cwd
            )
            extra_args = _replace_pathspecs(extra_args, pathspecs)
        config = load_config(repo_root, overrides=ctx.obj)
        api_key = _get_api_key()
        with StatusLine(status_console, "Analyzing staged changes...") as status:
            if pathspecs is None:
                context = collect_context(repo_root, config)
            else:
                context = collect_context(repo_root, config, pathspecs=pathspecs)
            system_prompt, user_prompt = build_prompts(context, config)
            if print_prompt:
                console.print(system_prompt, markup=False)
                if user_prompt:
                    console.print("", markup=False)
                    console.print(user_prompt, markup=False)
            message = generate_message_from_prompts(
                repo_root=repo_root,
                config=config,
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                on_backend_status=lambda backend: _update_generation_status(
                    status, backend
                ),
            )
        if dry_run:
            console.print(message)
            return
        exit_code = _run_git_commit(repo_root, message, extra_args, no_edit=no_edit)
        raise typer.Exit(code=exit_code)
    except typer.Exit:
        raise
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
    codex_model: str | None = typer.Option(None, "--codex-model"),
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
    project: str | None = typer.Option(None, "--project"),
    prefer_codex: bool | None = typer.Option(None, "--prefer-codex/--no-prefer-codex"),
) -> None:
    console = Console(stderr=True)
    repo_root: Path | None = None
    overrides = {
        "model": model,
        "codex_model": codex_model if codex_model is not None else model,
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
        "project": project,
        "prefer_codex": prefer_codex,
    }
    try:
        repo_root = resolve_repo_root(Path.cwd())
        if should_skip_prepare_commit_msg(
            message_path=message_path,
            source=source,
            repo_root=repo_root,
        ):
            raise typer.Exit(code=0)
        config = load_config(repo_root, overrides=overrides)
        api_key = _get_api_key()
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
    except typer.Exit:
        raise
    except (OpenAIError, CodexError) as exc:
        _append_prepare_failure_comment(message_path, str(exc), repo_root)
        console.print(f"[red]cmtr error:[/red] {exc}")
        raise typer.Exit(code=0)
    except CmtrError as exc:
        _append_prepare_failure_comment(message_path, str(exc), repo_root)
        console.print(f"[red]cmtr error:[/red] {exc}")
        raise typer.Exit(code=0)
    except Exception as exc:
        _append_prepare_failure_comment(message_path, str(exc), repo_root)
        console.print(f"[red]unexpected error:[/red] {exc}")
        raise typer.Exit(code=0)


def _get_api_key() -> str | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key is None:
        return None
    api_key = api_key.strip()
    if not api_key:
        return None
    return api_key


def _append_prepare_failure_comment(
    message_path: Path,
    error: str,
    repo_root: Path | None,
) -> None:
    if repo_root is None:
        append_failure_comment(message_path, error)
        return
    append_failure_comment_for_repo(message_path, error, repo_root)


def _run_pre_commit_install(repo_root: Path) -> None:
    if shutil.which("pre-commit") is None:
        raise UserError("pre-commit is not on PATH.")
    result = subprocess.run(
        ["pre-commit", "install", "--hook-type", "prepare-commit-msg"],
        cwd=repo_root,
    )
    if result.returncode != 0:
        raise UserError(
            "pre-commit install failed. Re-run manually to activate the hook."
        )


def _update_generation_status(status: StatusLine, backend: str) -> None:
    if backend == "codex":
        status.update("Generating commit message (codex)...")
    elif backend == "codex_fallback":
        status.update("Generating commit message (Codex fallback)...")
    elif backend == "openai_fallback":
        status.update("Generating commit message (OpenAI fallback)...")
    else:
        status.update("Generating commit message...")


def _reject_extra_args(args: list[str], command: str) -> None:
    if args:
        raise UserError(f"{command} does not accept git commit arguments.")


def _reject_hook_only_options(*, force: bool, use_global_hooks: bool) -> None:
    if force:
        raise UserError("--force can only be used with --hook or --uninstall-hook.")
    if use_global_hooks:
        raise UserError("--global can only be used with --hook or --uninstall-hook.")


def _filtered_git_args(args: list[str]) -> list[str]:
    error = (
        "cmtr supplies the message and analyzes the staged diff; "
        "do not pass commit message or content-changing options."
    )
    forbidden_exact = {
        "-a",
        "--all",
        "-i",
        "--include",
        "-o",
        "--only",
        "-p",
        "--patch",
        "--interactive",
        "--dry-run",
        "--short",
        "--porcelain",
        "--long",
        "--null",
        "--branch",
        "-z",
        "--amend",
        "--allow-empty",
        "--allow-empty-message",
        "--cleanup",
        "-m",
        "--message",
        "-F",
        "--file",
        "-t",
        "--template",
        "--reuse-message",
        "--reedit-message",
        "--reset-author",
        "--fixup",
        "--squash",
        "--pathspec-from-file",
        "--pathspec-file-nul",
        "-c",
        "-C",
    }
    forbidden_attached_short = ("-m", "-F", "-t", "-c", "-C")
    forbidden_short_options = {"a", "i", "o", "p", "m", "F", "t", "c", "C", "z"}
    forbidden_attached_long = (
        "--cleanup=",
        "--message=",
        "--file=",
        "--template=",
        "--reuse-message=",
        "--reedit-message=",
        "--fixup=",
        "--squash=",
        "--pathspec-from-file=",
    )
    value_options = {"--author", "--date", "--trailer"}
    attached_value_options = ("--author=", "--date=", "--trailer=")
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            break
        if not arg.startswith("-"):
            raise UserError("Pass pathspecs after -- so cmtr can analyze them.")
        if arg in forbidden_exact:
            raise UserError(error)
        if arg in value_options:
            value_index = index + 1
            if value_index >= len(args) or args[value_index] == "--":
                raise UserError(f"{arg} requires a value.")
            index += 2
            continue
        for option in attached_value_options:
            if arg.startswith(option) and not arg[len(option) :]:
                raise UserError(f"{option[:-1]} requires a value.")
        if any(arg.startswith(option) for option in forbidden_attached_long):
            raise UserError(error)
        if any(
            arg.startswith(option) and arg != option
            for option in forbidden_attached_short
        ):
            raise UserError(error)
        if _short_option_cluster_has_any(arg, forbidden_short_options):
            raise UserError(error)
        index += 1
    return list(args)


def _pathspecs_from_git_args(args: list[str]) -> list[str] | None:
    if "--" not in args:
        return None
    separator_index = args.index("--")
    pathspecs = [arg for arg in args[separator_index + 1 :] if arg]
    return pathspecs or None


def _replace_pathspecs(args: list[str], pathspecs: list[str]) -> list[str]:
    separator_index = args.index("--")
    return [*args[: separator_index + 1], *pathspecs]


def _normalize_pathspecs_for_repo(
    pathspecs: list[str],
    *,
    repo_root: Path,
    invocation_cwd: Path,
) -> list[str]:
    try:
        cwd_relative = invocation_cwd.resolve().relative_to(repo_root.resolve())
    except ValueError:
        cwd_relative = Path()
    prefix = cwd_relative.as_posix()
    normalized = []
    for pathspec in pathspecs:
        normalized.append(
            _normalize_pathspec_for_repo(pathspec, prefix=prefix, repo_root=repo_root)
        )
    return normalized


def _normalize_pathspec_for_repo(
    pathspec: str,
    *,
    prefix: str,
    repo_root: Path,
) -> str:
    magic = _split_git_magic_pathspec(pathspec)
    if magic is not None:
        magic_prefix, payload, is_top_relative = magic
        if is_top_relative or not payload:
            return pathspec
        return magic_prefix + _normalize_plain_pathspec_for_repo(
            payload, prefix=prefix, repo_root=repo_root
        )
    return _normalize_plain_pathspec_for_repo(
        pathspec, prefix=prefix, repo_root=repo_root
    )


def _normalize_plain_pathspec_for_repo(
    pathspec: str,
    *,
    prefix: str,
    repo_root: Path,
) -> str:
    path = Path(pathspec)
    if path.is_absolute():
        try:
            return (
                path.resolve(strict=False)
                .relative_to(repo_root.resolve(strict=False))
                .as_posix()
            )
        except ValueError:
            raise UserError(f"Pathspec is outside the repository: {pathspec}") from None
    if not prefix:
        return pathspec
    normalized = posixpath.normpath(posixpath.join(prefix, pathspec))
    return normalized


def _split_git_magic_pathspec(pathspec: str) -> tuple[str, str, bool] | None:
    if not pathspec.startswith(":"):
        return None
    if pathspec == ":":
        return (pathspec, "", True)
    if pathspec.startswith(":/"):
        return (":/", pathspec[2:], True)
    if pathspec.startswith((":!", ":^")):
        return (pathspec[:2], pathspec[2:], False)
    if not pathspec.startswith(":("):
        return (":", pathspec[1:], False)
    close_index = pathspec.find(")")
    if close_index < 0:
        return (":", pathspec[1:], False)
    magic_prefix = pathspec[: close_index + 1]
    magic_names = pathspec[2:close_index].split(",")
    is_top_relative = any(name.strip() in {"top", "/"} for name in magic_names)
    return (magic_prefix, pathspec[close_index + 1 :], is_top_relative)


def _short_option_cluster_has_any(arg: str, options: set[str]) -> bool:
    if not arg.startswith("-") or arg.startswith("--") or len(arg) <= 2:
        return False
    if arg[1] in {"S", "u"}:
        return False
    return any(option in arg[1:] for option in options)


def _run_git_commit(
    repo_root: Path, message: str, extra_args: list[str], no_edit: bool
) -> int:
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
        config = load_global_config()
    except CmtrError as exc:
        typer.echo(f"cmtr error: {exc}", err=True)
        raise typer.Exit(code=1)
    defaults = DEFAULT_CONFIG.__dict__
    values = config.__dict__
    for key in sorted(defaults.keys()):
        if key in data:
            value = values[key]
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
        config = load_global_config()
        typer.echo(_format_config_value(config.__dict__[key]))
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
        data = read_global_config()
        if key not in CONFIG_KEYS and key not in data:
            raise typer.BadParameter(f"Unknown key: {key}")
        if key in CONFIG_KEYS:
            unset_global_value(key)
        else:
            data.pop(key)
            write_global_config(data)
    except CmtrError as exc:
        typer.echo(f"cmtr error: {exc}", err=True)
        raise typer.Exit(code=1)


def _format_config_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return str(value)


@auth_app.command("status")
def auth_status() -> None:
    api_key = _get_api_key()
    api_key_set = api_key is not None
    status = codex_status()
    codex_installed = status.codex_path is not None
    npx_installed = status.npx_path is not None
    codex_auth = status.auth_exists
    try:
        repo_root = resolve_repo_root(Path.cwd())
    except CmtrError:
        repo_root = Path.cwd()
    try:
        config = load_config(repo_root)
        mode, reason = describe_auth_mode(config, api_key)
    except CmtrError as exc:
        config = None
        mode, reason = ("unknown", f"Failed to load config: {exc}")
    prefer_codex_value = (
        _format_config_value(config.prefer_codex) if config else "unknown"
    )
    lines = [
        f"OPENAI_API_KEY: {'set' if api_key_set else 'missing'}",
        f"codex CLI: {'found' if codex_installed else 'not found'}",
        f"npx: {'found' if npx_installed else 'not found'}",
        f"codex auth.json: {'present' if codex_auth else 'missing'}",
        f"codex auth path: {status.auth_path}",
        f"prefer_codex: {prefer_codex_value}",
        f"selected mode: {mode}",
    ]
    if reason:
        lines.append(f"note: {reason}")
    for line in lines:
        typer.echo(line)
