from cmtr.git import CommitMessage, LogContext
from cmtr.prompt import PromptContext, build_user_prompt


def test_build_user_prompt_omits_log_body_when_limit_is_zero() -> None:
    prompt = build_user_prompt(
        PromptContext(
            staged_files=["file.py"],
            name_status="M\tfile.py",
            diff_stat=" file.py | 1 +",
            diff_patch="diff --git a/file.py b/file.py\n+print('hi')\n",
            log_contexts=[
                LogContext(
                    path="file.py",
                    entries=[
                        CommitMessage(
                            subject="feat: add file",
                            body="First line\nSecond line",
                        )
                    ],
                )
            ],
            max_log_body_lines=0,
            diff_was_truncated=False,
            diff_was_filtered=False,
            has_commit_history=True,
        )
    )

    assert "<subject>feat: add file</subject>" in prompt
    assert "<body>" not in prompt
