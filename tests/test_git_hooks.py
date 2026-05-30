from pathlib import Path
import os
import subprocess

from cmtr.git import (
    GitError,
    HooksPathEntry,
    get_hooks_dir,
    has_unstaged_changes,
    _select_log_paths,
    gather_log_context,
    parse_hooks_path_entries,
)


def test_parse_hooks_path_entries_ignores_unrelated_keys() -> None:
    output = "file:/repo/.git/config\tuser.name=Test User\n"
    assert parse_hooks_path_entries(output) == []


def test_parse_hooks_path_entries_parses_tab_separated_output() -> None:
    output = (
        "file:/repo/.git/config\tcore.hooksPath=.githooks\n"
        "file:/Users/me/.gitconfig\tcore.hooksPath=~/.git-hooks\n"
    )
    entries = parse_hooks_path_entries(output)
    assert entries == [
        HooksPathEntry(origin="file:/repo/.git/config", path=".githooks"),
        HooksPathEntry(origin="file:/Users/me/.gitconfig", path="~/.git-hooks"),
    ]


def test_parse_hooks_path_entries_parses_space_separated_output() -> None:
    output = "file:/repo/.git/config core.hooksPath = .githooks\n"
    entries = parse_hooks_path_entries(output)
    assert entries == [
        HooksPathEntry(origin="file:/repo/.git/config", path=".githooks"),
    ]


def test_parse_hooks_path_entries_allows_case_insensitive_key() -> None:
    output = "file:/repo/.git/config\tcore.hookspath=.githooks\n"
    entries = parse_hooks_path_entries(output)
    assert entries == [
        HooksPathEntry(origin="file:/repo/.git/config", path=".githooks"),
    ]


def test_get_hooks_dir_resolves_default_path_under_repo_root(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    hooks_dir = get_hooks_dir(tmp_path)

    assert hooks_dir == tmp_path / ".git" / "hooks"


def test_has_unstaged_changes_reports_non_utf8_git_error(
    tmp_path: Path, monkeypatch
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/bin/sh\nprintf '\\377' >&2\nexit 2\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")

    try:
        has_unstaged_changes(tmp_path, ["file.txt"])
    except GitError as exc:
        assert "\ufffd" in str(exc)
    else:
        raise AssertionError("expected GitError")


def test_select_log_paths_honors_max_paths_for_unrelated_files() -> None:
    paths = _select_log_paths(
        ["src/cmtr/cli.py", "tests/test_cli.py", "README.md"],
        max_paths=2,
        changed_lines={
            "src/cmtr/cli.py": 10,
            "tests/test_cli.py": 8,
            "README.md": 3,
        },
    )

    assert paths == ["src/cmtr", "tests"]


def test_gather_log_context_honors_max_entries(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    target = tmp_path / "file.txt"
    for index in range(12):
        target.write_text(f"{index}\n", encoding="utf-8")
        subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"feat: change {index}"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    contexts = gather_log_context(
        tmp_path,
        ["file.txt"],
        max_paths=1,
        max_entries=12,
    )

    assert len(contexts) == 1
    assert len(contexts[0].entries) == 12


def test_gather_log_context_preserves_delimiter_like_body_text(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    target = tmp_path / "file.txt"
    target.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "feat: add file",
            "-m",
            "Body before\n----END----\nBody after",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    target.write_text("changed\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)

    contexts = gather_log_context(
        tmp_path,
        ["file.txt"],
        max_paths=1,
        max_entries=1,
    )

    assert len(contexts[0].entries) == 1
    assert contexts[0].entries[0].subject == "feat: add file"
    assert contexts[0].entries[0].body == "Body before\n----END----\nBody after"


def test_gather_log_context_preserves_control_separator_body_text(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    target = tmp_path / "file.txt"
    target.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)
    body = "Body before\x1eBody after\nField marker: \x1f"
    subprocess.run(
        ["git", "commit", "-m", "feat: add file", "-m", body],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    target.write_text("changed\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)

    contexts = gather_log_context(
        tmp_path,
        ["file.txt"],
        max_paths=1,
        max_entries=1,
    )

    assert len(contexts[0].entries) == 1
    assert contexts[0].entries[0].subject == "feat: add file"
    assert contexts[0].entries[0].body == body
