from __future__ import annotations

from pathlib import Path
import re
import shutil
import textwrap
import tomllib

from .config import Config
from .core import generate_message
from .errors import UserError
from .git import get_hooks_dir, run_git

HOOK_MARKER = "# cmtr hook v1"
PRE_COMMIT_CONFIG_NAMES = (".pre-commit-config.yaml", ".pre-commit-config.yml")
PRE_COMMIT_HOOK_ID = "prepare-commit-msg"
PRE_COMMIT_INLINE_ENTRY = "uvx cmtr@latest prepare-commit-msg"
PRE_COMMIT_SCRIPT_ENTRY = "scripts/prepare-commit-msg"


def detect_pre_commit_config(repo_root: Path) -> Path | None:
    for name in PRE_COMMIT_CONFIG_NAMES:
        path = repo_root / name
        if path.exists():
            return path
    return None


def install_hook(repo_root: Path, force: bool, *, use_global: bool = False) -> Path:
    pre_commit_config = detect_pre_commit_config(repo_root)
    if pre_commit_config:
        if use_global:
            raise UserError("pre-commit config detected; --global is not supported.")
        return install_pre_commit_hook(repo_root, pre_commit_config, force=force)
    hooks_dir = get_hooks_dir(repo_root, use_global=use_global)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "prepare-commit-msg"
    if hook_path.exists() and not _is_our_hook(hook_path):
        if not force:
            raise UserError(
                "prepare-commit-msg hook already exists. Use --force to overwrite."
            )
    local_checkout = _detect_local_checkout()
    hook_path.write_text(_hook_script_for(local_checkout), encoding="utf-8")
    hook_path.chmod(0o755)
    return hook_path


def uninstall_hook(repo_root: Path, *, use_global: bool = False) -> Path:
    pre_commit_config = detect_pre_commit_config(repo_root)
    if pre_commit_config:
        if use_global:
            raise UserError("pre-commit config detected; --global is not supported.")
        return uninstall_pre_commit_hook(repo_root, pre_commit_config)
    hooks_dir = get_hooks_dir(repo_root, use_global=use_global)
    hook_path = hooks_dir / "prepare-commit-msg"
    if not hook_path.exists():
        raise UserError("No prepare-commit-msg hook found.")
    if not _is_our_hook(hook_path):
        raise UserError("prepare-commit-msg hook was not installed by cmtr.")
    hook_path.unlink()
    return hook_path


def run_prepare_commit_msg(
    message_path: Path,
    source: str | None,
    sha: str | None,
    repo_root: Path,
    config: Config,
    api_key: str | None,
) -> int:
    if _should_skip_source(source):
        return 0
    if _is_rebase_in_progress(repo_root):
        return 0
    if _is_fixup_or_squash(message_path):
        return 0
    if _has_existing_message(message_path):
        return 0
    try:
        message = generate_message(repo_root=repo_root, config=config, api_key=api_key)
        _write_message_prepend(message_path, message)
        return 0
    except Exception as exc:
        append_failure_comment(message_path, str(exc))
        return 0


def _should_skip_source(source: str | None) -> bool:
    if not source:
        return False
    return source in {"message", "merge", "squash", "commit", "tag", "template"}


def _write_message(path: Path, message: str) -> None:
    text = message.strip() + "\n"
    path.write_text(text, encoding="utf-8")


def _write_message_prepend(path: Path, message: str) -> None:
    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
    message_text = message.strip()
    if existing:
        text = f"{message_text}\n\n{existing}"
    else:
        text = f"{message_text}\n"
    path.write_text(text, encoding="utf-8")


def append_failure_comment(path: Path, error: str) -> None:
    comment = f"# cmtr failed: {error}\n"
    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + comment, encoding="utf-8")


def _is_our_hook(path: Path) -> bool:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return HOOK_MARKER in contents


def install_pre_commit_hook(repo_root: Path, config_path: Path, *, force: bool) -> Path:
    status = pre_commit_hook_status(config_path)
    if status == "cmtr":
        return config_path
    if status == "other":
        if not force:
            raise UserError(
                "prepare-commit-msg hook already configured in pre-commit. "
                "Re-run with --force to replace."
            )
        remove_pre_commit_hook(config_path)
    if shutil.which("uvx") is None:
        raise UserError(
            "uvx is required for pre-commit integration. Install uv/uvx and try again."
        )
    ensure_pre_commit_hook(config_path)
    return config_path


def uninstall_pre_commit_hook(repo_root: Path, config_path: Path) -> Path:
    status = pre_commit_hook_status(config_path)
    if status == "cmtr":
        remove_pre_commit_hook(config_path)
        return config_path
    if status == "other":
        raise UserError(
            "prepare-commit-msg hook is configured in pre-commit, but it is not cmtr."
        )
    raise UserError("No prepare-commit-msg hook found.")


def pre_commit_hook_status(config_path: Path) -> str:
    contents = config_path.read_text(encoding="utf-8")
    lines = contents.splitlines(keepends=True)
    return _pre_commit_hook_status(lines, config_path.parent)


def ensure_pre_commit_hook(config_path: Path) -> bool:
    contents = config_path.read_text(encoding="utf-8")
    lines = contents.splitlines(keepends=True)
    if _pre_commit_has_hook_id(lines):
        return False
    newline = "\r\n" if "\r\n" in contents else "\n"
    lines = _ensure_default_stages(lines, newline)
    new_lines = _insert_pre_commit_hook(lines, newline)
    text = "".join(new_lines)
    if text and not text.endswith(newline):
        text += newline
    config_path.write_text(text, encoding="utf-8")
    return True


def remove_pre_commit_hook(config_path: Path) -> bool:
    contents = config_path.read_text(encoding="utf-8")
    lines = contents.splitlines(keepends=True)
    hook_block = _find_hook_block_by_id(lines, PRE_COMMIT_HOOK_ID)
    if hook_block is None:
        return False
    start_index, end_index = hook_block
    new_lines = lines[:start_index] + lines[end_index:]
    newline = "\r\n" if "\r\n" in contents else "\n"
    text = "".join(new_lines)
    if text and not text.endswith(newline):
        text += newline
    config_path.write_text(text, encoding="utf-8")
    return True


def _insert_pre_commit_hook(lines: list[str], newline: str) -> list[str]:
    repos_index, repos_indent = _find_repos_line(lines)
    if repos_index is None:
        raise UserError("pre-commit config missing required `repos:` block.")
    repos_end = _find_repos_list_end(lines, repos_index, repos_indent)
    repo_indent = _infer_repo_indent(lines, repos_index, repos_indent, repos_end)
    local_repo_index, local_repo_indent = _find_local_repo(lines, repos_index, repos_end)
    if local_repo_index is not None:
        local_end = _find_repo_block_end(
            lines, local_repo_index, local_repo_indent, repos_end
        )
        hooks_index, hooks_indent = _find_hooks_line(
            lines, local_repo_index, local_end
        )
        if hooks_index is not None:
            insert_at = _find_hooks_list_end(
                lines, hooks_index, hooks_indent, local_end
            )
            hook_lines = _build_hook_item_lines(hooks_indent + 2, newline)
            return lines[:insert_at] + hook_lines + lines[insert_at:]
        hook_lines = _build_hook_item_lines(local_repo_indent + 4, newline)
        hooks_header = [" " * (local_repo_indent + 2) + f"hooks:{newline}"]
        insert_at = local_repo_index + 1
        return lines[:insert_at] + hooks_header + hook_lines + lines[insert_at:]
    hook_block = _build_local_repo_block(repo_indent, newline)
    return lines[:repos_end] + hook_block + lines[repos_end:]


def _find_hook_item_start(lines: list[str], entry_index: int) -> int:
    entry_indent = _leading_spaces(lines[entry_index])
    for index in range(entry_index, -1, -1):
        line = lines[index]
        if _is_blank_or_comment(line):
            continue
        indent = _leading_spaces(line)
        if line.lstrip().startswith("- "):
            return index
        if indent < entry_indent:
            break
    return entry_index


def _find_hook_item_end(lines: list[str], start_index: int, hook_indent: int) -> int:
    for index in range(start_index + 1, len(lines)):
        line = lines[index]
        if _is_blank_or_comment(line):
            continue
        indent = _leading_spaces(line)
        if indent <= hook_indent and line.lstrip().startswith("- "):
            return index
        if indent < hook_indent:
            return index
    return len(lines)


def _find_hook_block_by_id(lines: list[str], hook_id: str) -> tuple[int, int] | None:
    pattern = re.compile(rf"^\s*-\s*id:\s*{re.escape(hook_id)}\s*(#.*)?$")
    for index, line in enumerate(lines):
        if pattern.match(line):
            start_index = _find_hook_item_start(lines, index)
            hook_indent = _leading_spaces(lines[start_index])
            end_index = _find_hook_item_end(lines, start_index, hook_indent)
            return start_index, end_index
    return None


def _extract_entry_from_block(lines: list[str], start: int, end: int) -> str | None:
    for line in lines[start:end]:
        if "entry:" not in line:
            continue
        raw = line.split("entry:", 1)[1].strip()
        if not raw:
            continue
        value = _strip_yaml_comment(raw)
        value = _strip_quotes(value.strip())
        return value.strip() if value else None
    return None


def _strip_yaml_comment(value: str) -> str:
    if not value:
        return value
    if value[0] in {"'", '"'} and value[-1:] == value[0]:
        return value
    for token in (" #", "\t#", "  #"):
        if token in value:
            return value.split(token, 1)[0].rstrip()
    return value


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _pre_commit_hook_status(lines: list[str], repo_root: Path | None) -> str:
    hook_block = _find_hook_block_by_id(lines, PRE_COMMIT_HOOK_ID)
    if hook_block is None:
        return "missing"
    entry = _extract_entry_from_block(lines, hook_block[0], hook_block[1])
    if entry and _is_cmtr_pre_commit_entry(entry):
        return "cmtr"
    return "other"


def _is_cmtr_pre_commit_entry(entry: str) -> bool:
    if entry == PRE_COMMIT_INLINE_ENTRY:
        return True
    if entry.startswith(PRE_COMMIT_INLINE_ENTRY + " "):
        return True
    return False


def _pre_commit_has_hook_id(lines: list[str]) -> bool:
    pattern = re.compile(rf"^\s*-\s*id:\s*{re.escape(PRE_COMMIT_HOOK_ID)}\s*(#.*)?$")
    return any(pattern.match(line) for line in lines)


def _find_repos_line(lines: list[str]) -> tuple[int | None, int]:
    for index, line in enumerate(lines):
        if re.match(r"^\s*repos:\s*(#.*)?$", line):
            return index, _leading_spaces(line)
    return None, 0


def _find_repos_list_end(lines: list[str], start: int, repos_indent: int) -> int:
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if _is_blank_or_comment(line):
            continue
        indent = _leading_spaces(line)
        if indent <= repos_indent:
            return index
    return len(lines)


def _find_repo_block_end(
    lines: list[str], start: int, repo_indent: int, repos_end: int
) -> int:
    for index in range(start + 1, repos_end):
        line = lines[index]
        if _is_blank_or_comment(line):
            continue
        indent = _leading_spaces(line)
        if indent <= repo_indent and line.lstrip().startswith("- "):
            return index
        if indent < repo_indent:
            return index
    return repos_end


def _infer_repo_indent(
    lines: list[str], repos_index: int, repos_indent: int, repos_end: int
) -> int:
    for index in range(repos_index + 1, repos_end):
        line = lines[index]
        if _is_blank_or_comment(line):
            continue
        indent = _leading_spaces(line)
        if line.lstrip().startswith("-"):
            return indent
        if indent > repos_indent:
            return indent
        break
    return repos_indent + 2


def _find_local_repo(
    lines: list[str], repos_index: int, repos_end: int
) -> tuple[int | None, int]:
    for index in range(repos_index + 1, repos_end):
        line = lines[index]
        if re.match(r"^\s*-\s*repo:\s*local\s*(#.*)?$", line):
            return index, _leading_spaces(line)
    return None, 0


def _find_hooks_line(
    lines: list[str], repo_index: int, repo_end: int
) -> tuple[int | None, int]:
    for index in range(repo_index + 1, repo_end):
        line = lines[index]
        if re.match(r"^\s*hooks:\s*(#.*)?$", line):
            return index, _leading_spaces(line)
    return None, 0


def _find_hooks_list_end(
    lines: list[str], hooks_index: int, hooks_indent: int, repo_end: int
) -> int:
    for index in range(hooks_index + 1, repo_end):
        line = lines[index]
        if _is_blank_or_comment(line):
            continue
        if _leading_spaces(line) <= hooks_indent:
            return index
    return repo_end


def _build_hook_item_lines(hook_indent: int, newline: str) -> list[str]:
    key_indent = hook_indent + 2
    return [
        " " * hook_indent + f"- id: {PRE_COMMIT_HOOK_ID}{newline}",
        " " * key_indent + f"name: {PRE_COMMIT_HOOK_ID}{newline}",
        " " * key_indent + f"entry: {PRE_COMMIT_INLINE_ENTRY}{newline}",
        " " * key_indent + f"language: system{newline}",
        " " * key_indent + f"stages: [{PRE_COMMIT_HOOK_ID}]{newline}",
    ]


def _build_local_repo_block(repo_indent: int, newline: str) -> list[str]:
    hooks_indent = repo_indent + 2
    hook_indent = hooks_indent + 2
    return [
        " " * repo_indent + f"- repo: local{newline}",
        " " * hooks_indent + f"hooks:{newline}",
        *_build_hook_item_lines(hook_indent, newline),
    ]


def _leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _ensure_default_stages(lines: list[str], newline: str) -> list[str]:
    if _has_default_stages(lines):
        return lines
    repos_index, _ = _find_repos_line(lines)
    insert_at = repos_index if repos_index is not None else len(lines)
    return (
        lines[:insert_at]
        + [f"default_stages: [pre-commit]{newline}", newline]
        + lines[insert_at:]
    )


def _has_default_stages(lines: list[str]) -> bool:
    pattern = re.compile(r"^\s*default_stages\s*:")
    return any(pattern.match(line) for line in lines)

def _git_dir(repo_root: Path) -> Path:
    output = run_git(["rev-parse", "--git-dir"], repo_root).strip()
    git_dir = Path(output)
    if not git_dir.is_absolute():
        git_dir = repo_root / git_dir
    return git_dir


def _is_rebase_in_progress(repo_root: Path) -> bool:
    git_dir = _git_dir(repo_root)
    return (git_dir / "rebase-merge" / "interactive").exists() or (
        git_dir / "rebase-apply"
    ).exists()


def _is_fixup_or_squash(message_path: Path) -> bool:
    if not message_path.exists():
        return False
    for line in message_path.read_text(encoding="utf-8").splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("fixup") or stripped.startswith("squash"):
            return True
    return False


def _has_existing_message(message_path: Path) -> bool:
    if not message_path.exists():
        return False
    for line in message_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            break
        if line.strip():
            return True
    return False


def _hook_script() -> str:
    return _hook_script_for(None)


def _hook_script_for(local_checkout: Path | None) -> str:
    if local_checkout:
        repo_path = local_checkout.as_posix()
        script = f"""#!/bin/sh
{HOOK_MARKER}
# Generated by: cmtr --hook

CMTR_REPO="{repo_path}"

if [ -d "$CMTR_REPO" ] && [ -f "$CMTR_REPO/pyproject.toml" ]; then
  if command -v mise >/dev/null 2>&1; then
    (cd "$CMTR_REPO" && mise exec -- uv run cmtr prepare-commit-msg "$@")
  elif command -v uv >/dev/null 2>&1; then
    (cd "$CMTR_REPO" && uv run cmtr prepare-commit-msg "$@")
  else
    echo "cmtr: uv not found; skipping commit message generation" >&2
  fi
else
  if command -v uvx >/dev/null 2>&1; then
    uvx cmtr@latest prepare-commit-msg "$@"
  else
    echo "cmtr: uvx not found; skipping commit message generation" >&2
  fi
fi
"""
        return textwrap.dedent(script)
    script = f"""#!/bin/sh
{HOOK_MARKER}
# Generated by: cmtr --hook

if command -v uvx >/dev/null 2>&1; then
  uvx cmtr@latest prepare-commit-msg "$@"
else
  echo "cmtr: uvx not found; skipping commit message generation" >&2
fi
"""
    return textwrap.dedent(script)


def _detect_local_checkout() -> Path | None:
    current = Path(__file__).resolve()
    for parent in current.parents:
        pyproject = parent / "pyproject.toml"
        if pyproject.exists() and (parent / "src" / "cmtr").exists():
            if _is_cmtr_pyproject(pyproject) and (parent / ".git").exists():
                return parent
            return None
    return None


def _is_cmtr_pyproject(path: Path) -> bool:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return False
    project = data.get("project", {})
    if not isinstance(project, dict):
        return False
    return project.get("name") == "cmtr"
