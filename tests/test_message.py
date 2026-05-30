from cmtr.message import is_usable_commit_message


def test_bracket_prefixed_subject_is_usable() -> None:
    assert is_usable_commit_message("[docs] update README")


def test_comment_only_message_is_not_usable() -> None:
    assert not is_usable_commit_message("# generated comment")


def test_message_with_comment_body_line_is_not_usable() -> None:
    assert not is_usable_commit_message("feat: add thing\n\n# generated comment")


def test_message_with_subject_is_usable() -> None:
    assert is_usable_commit_message("feat: add thing\n\nBody")


def test_multiline_message_without_blank_body_separator_is_not_usable() -> None:
    assert not is_usable_commit_message("feat: add thing\nExplain why.")


def test_placeholder_message_is_not_usable() -> None:
    assert not is_usable_commit_message("TODO")
    assert not is_usable_commit_message("TBD")


def test_bare_assistant_preamble_is_not_usable() -> None:
    assert not is_usable_commit_message("Here is the commit message:")
    assert not is_usable_commit_message("The commit message would be:")
    assert not is_usable_commit_message("The commit message should be:")
    assert not is_usable_commit_message("Here you go:")
    assert not is_usable_commit_message("Here's my suggestion:")
    assert not is_usable_commit_message("I'd suggest:")
    assert not is_usable_commit_message("I suggest:")
    assert not is_usable_commit_message("I recommend:")
    assert not is_usable_commit_message("I recommend the following commit message:")


def test_bullet_list_subject_is_not_usable() -> None:
    assert not is_usable_commit_message("- feat: add thing")


def test_unclosed_fence_subject_is_not_usable() -> None:
    assert not is_usable_commit_message("```gitcommit\nfeat: add thing")
    assert not is_usable_commit_message("```gitcommit")


def test_json_like_subject_is_not_usable() -> None:
    assert not is_usable_commit_message('{"message": "feat: add thing"}')
    assert not is_usable_commit_message('["feat: add thing"]')


def test_context_leak_message_is_not_usable() -> None:
    assert not is_usable_commit_message("diff --git a/a b/a\n+change")
    assert not is_usable_commit_message("index 1234567..89abcde 100644")
    assert not is_usable_commit_message("<context>\n<diff_patch>")


def test_message_may_start_with_index_when_not_diff_metadata() -> None:
    assert is_usable_commit_message("index generated docs")


def test_conflict_marker_message_is_not_usable() -> None:
    assert not is_usable_commit_message("feat: add thing\n<<<<<<< HEAD")
