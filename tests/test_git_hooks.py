from cmtr.git import HooksPathEntry, parse_hooks_path_entries


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
