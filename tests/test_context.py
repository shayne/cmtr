from dataclasses import replace
from pathlib import Path
import subprocess

import pytest

from cmtr.config import DEFAULT_CONFIG
import cmtr.git as git
from cmtr.core import collect_context
from cmtr.errors import UserError
from cmtr.git import get_diff_numstat


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _commit_file(repo: Path, path: str, contents: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding="utf-8")
    subprocess.run(["git", "add", path], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"feat: add {path}"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_collect_context_includes_rename_metadata(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_file(tmp_path, "old.txt", "hello\n")
    subprocess.run(["git", "mv", "old.txt", "new.txt"], cwd=tmp_path, check=True)

    context = collect_context(tmp_path, DEFAULT_CONFIG)
    entries = get_diff_numstat(tmp_path)

    assert context.staged_files == ["new.txt"]
    assert "R100\told.txt\tnew.txt" in context.name_status
    assert "rename from old.txt" in context.diff_patch
    assert "rename to new.txt" in context.diff_patch
    assert any(log_context.path == "old.txt" for log_context in context.log_contexts)
    assert entries[0].path_before == "old.txt"
    assert entries[0].path == "new.txt"


def test_collect_context_includes_delete_metadata(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_file(tmp_path, "gone.txt", "goodbye\n")
    (tmp_path / "gone.txt").unlink()
    subprocess.run(["git", "add", "gone.txt"], cwd=tmp_path, check=True)

    context = collect_context(tmp_path, DEFAULT_CONFIG)

    assert context.staged_files == ["gone.txt"]
    assert "D\tgone.txt" in context.name_status
    assert "deleted file mode" in context.diff_patch
    assert "-goodbye" in context.diff_patch


def test_collect_context_can_limit_to_pathspec(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "included.txt").write_text("included\n", encoding="utf-8")
    (tmp_path / "excluded.txt").write_text("excluded\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "included.txt", "excluded.txt"], cwd=tmp_path, check=True
    )

    context = collect_context(tmp_path, DEFAULT_CONFIG, pathspecs=["included.txt"])

    assert context.staged_files == ["included.txt"]
    assert "included.txt" in context.diff_patch
    assert "excluded.txt" not in context.diff_patch


def test_collect_context_reports_empty_pathspec(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "included.txt").write_text("included\n", encoding="utf-8")
    subprocess.run(["git", "add", "included.txt"], cwd=tmp_path, check=True)

    with pytest.raises(UserError, match="provided pathspec"):
        collect_context(tmp_path, DEFAULT_CONFIG, pathspecs=["missing.txt"])


def test_collect_context_rejects_pathspec_with_unstaged_edits(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_file(tmp_path, "file.txt", "base\n")
    (tmp_path / "file.txt").write_text("staged\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)
    (tmp_path / "file.txt").write_text("unstaged\n", encoding="utf-8")

    with pytest.raises(UserError, match="unstaged changes"):
        collect_context(tmp_path, DEFAULT_CONFIG, pathspecs=["file.txt"])


def test_collect_context_rejects_unmerged_paths(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_file(tmp_path, "file.txt", "base\n")
    base_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=tmp_path, check=True)
    (tmp_path / "file.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "feat: feature"], cwd=tmp_path, check=True)
    subprocess.run(["git", "checkout", base_branch], cwd=tmp_path, check=True)
    (tmp_path / "file.txt").write_text("main\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "feat: main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "merge", "feature"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    with pytest.raises(UserError, match="unmerged"):
        collect_context(tmp_path, DEFAULT_CONFIG)


def test_collect_context_filters_lockfile_only_diff(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "uv.lock"], cwd=tmp_path, check=True)
    config = replace(DEFAULT_CONFIG, max_patch_lines=20, max_diff_bytes=1000)

    context = collect_context(tmp_path, config)

    assert context.diff_was_filtered
    assert "Excluded files from diff context:" in context.diff_patch
    assert "- uv.lock (excluded lock file)" in context.diff_patch
    assert "diff --git" not in context.diff_patch


def test_collect_context_replaces_invalid_utf8_diff_bytes(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "odd.txt").write_bytes(b"\xff\xfe\n")
    subprocess.run(["git", "add", "odd.txt"], cwd=tmp_path, check=True)

    context = collect_context(tmp_path, DEFAULT_CONFIG)

    assert "odd.txt" in context.diff_patch
    assert "\ufffd" in context.diff_patch


def test_get_diff_numstat_preserves_tabs_in_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        git,
        "run_git",
        lambda args, cwd: "1\t2\tfolder/file\twith-tab.txt\0",
    )

    entries = get_diff_numstat(tmp_path)

    assert entries[0].path == "folder/file\twith-tab.txt"
