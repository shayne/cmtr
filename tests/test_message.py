from cmtr.message import is_usable_commit_message, sanitize_commit_message


def test_sanitize_commit_message_removes_label_line() -> None:
    assert (
        sanitize_commit_message("Commit message:\nfeat: add thing") == "feat: add thing"
    )


def test_sanitize_commit_message_removes_inline_label() -> None:
    assert (
        sanitize_commit_message("Commit message: feat: add thing") == "feat: add thing"
    )


def test_sanitize_commit_message_removes_subject_and_body_labels() -> None:
    assert (
        sanitize_commit_message("Subject: feat: add thing\n\nBody:\nExplain why.")
        == "feat: add thing\n\nExplain why."
    )


def test_sanitize_commit_message_removes_assistant_preamble() -> None:
    assert (
        sanitize_commit_message("Here is the commit message:\n\nfeat: add thing")
        == "feat: add thing"
    )


def test_sanitize_commit_message_removes_labels_after_preamble() -> None:
    assert (
        sanitize_commit_message(
            "Here is the commit message:\n\n"
            "Subject: feat: add thing\n\n"
            "Body:\n"
            "Explain why."
        )
        == "feat: add thing\n\nExplain why."
    )


def test_sanitize_commit_message_removes_inline_assistant_preamble() -> None:
    assert (
        sanitize_commit_message("Sure, here's the commit message: feat: add thing")
        == "feat: add thing"
    )


def test_sanitize_commit_message_removes_preamble_then_fence() -> None:
    assert (
        sanitize_commit_message(
            "Here is the commit message:\n\n```gitcommit\nfeat: add thing\n```"
        )
        == "feat: add thing"
    )


def test_sanitize_commit_message_extracts_json_message() -> None:
    assert (
        sanitize_commit_message('{"message": "feat: add thing"}') == "feat: add thing"
    )


def test_sanitize_commit_message_extracts_json_string() -> None:
    assert (
        sanitize_commit_message('"feat: add thing\\n\\nExplain why."')
        == "feat: add thing\n\nExplain why."
    )


def test_sanitize_commit_message_removes_single_backtick_wrapping() -> None:
    assert sanitize_commit_message("`feat: add thing`") == "feat: add thing"


def test_sanitize_commit_message_removes_label_inside_wrapping() -> None:
    assert (
        sanitize_commit_message("`Commit message: feat: add thing`")
        == "feat: add thing"
    )


def test_json_without_string_message_is_not_usable() -> None:
    message = sanitize_commit_message('{"message": 123}')

    assert not is_usable_commit_message(message)


def test_bracket_prefixed_subject_is_usable() -> None:
    assert is_usable_commit_message("[docs] update README")


def test_json_array_output_is_not_usable() -> None:
    assert not is_usable_commit_message('["feat: add thing"]')


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


def test_bullet_list_subject_is_not_usable() -> None:
    assert not is_usable_commit_message("- feat: add thing")


def test_unclosed_fence_subject_is_not_usable() -> None:
    assert not is_usable_commit_message("```gitcommit\nfeat: add thing")
    assert not is_usable_commit_message("```gitcommit")


def test_context_leak_message_is_not_usable() -> None:
    assert not is_usable_commit_message("diff --git a/a b/a\n+change")
    assert not is_usable_commit_message("index 1234567..89abcde 100644")
    assert not is_usable_commit_message("<context>\n<diff_patch>")


def test_message_may_start_with_index_when_not_diff_metadata() -> None:
    assert is_usable_commit_message("index generated docs")


def test_conflict_marker_message_is_not_usable() -> None:
    assert not is_usable_commit_message("feat: add thing\n<<<<<<< HEAD")
