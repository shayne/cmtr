# cmtr

cmtr writes your git commit messages for you. It prefers Codex CLI (using your ChatGPT account) and also supports the OpenAI API (gpt-5.5). It uses the staged diff and recent commit history to match the repository's style.

## Quick start (recommended)

1. Install uv (if needed), then run:
   - `uvx cmtr@latest`
2. Optional: add a shell alias:
   - `alias cmtr="uvx cmtr@latest"`
3. Authenticate (preferred: Codex):
   - Codex CLI (preferred): run `npx @openai/codex@latest` and sign in (uses your ChatGPT account)
   - API key (alternative): `export OPENAI_API_KEY=...`
4. Stage changes and run:
   - `git add -A`
   - `cmtr`

Codex mode is preferred because it uses your ChatGPT account usage (not separate
API billing) and requires no API key. If Codex isn't on your PATH, cmtr will run
it via `npx @openai/codex@latest` as long as you're signed in. If Codex is
unavailable and `OPENAI_API_KEY` is set, cmtr falls back to the OpenAI API.
OpenAI API requests are sent with `store = false`.

Or install the git hook:

- `cmtr --hook`
  - Installs a `prepare-commit-msg` hook that automatically generates a commit message
    right before the commit editor opens. If there is already a message or you're in a
    rebase/fixup/squash flow, it skips.
  - If the repo sets `core.hooksPath` in its local git config, cmtr installs the hook
    in that directory. If only a global `core.hooksPath` is set, re-run with `--global`
    or set a local override with `git config --local core.hooksPath .git/hooks`.
  - If a `.pre-commit-config.yaml`/`.yml` is present, cmtr will prompt to install a
    pre-commit `prepare-commit-msg` hook instead (adds an entry that runs
    `uvx cmtr@latest prepare-commit-msg`). You may need to run
    `pre-commit install --hook-type prepare-commit-msg` after accepting.

## Usage

- `cmtr`
  - Behaves like `git commit -v`, but injects a generated commit message.
- `cmtr --dry-run`
  - Print the generated message without committing.
- `cmtr --print-prompt`
  - Print the prompts used to generate the message.
- `cmtr --no-edit`
  - Skip opening the editor after generating the message.
- `cmtr --model gpt-5.5`
  - Override the selected backend's model for this run.
- `cmtr --codex-model gpt-5.5`
  - Override only the Codex CLI model for this run.
- `cmtr --organization org_... --project proj_...`
  - Override the OpenAI organization/project for this run.
- `cmtr --hook`
  - Install the `prepare-commit-msg` hook to auto-generate messages on every commit.
- `cmtr --global --hook`
  - Install the hook in the globally configured hooks path.
- `cmtr --uninstall-hook`
  - Remove the hook.

Extra git commit flags can be passed directly (for example, `--no-verify`).
cmtr rejects message-supplying, message-shaping, and content-changing flags
such as `-a`, `-i`, `-o`, `-m`, `-F`, `-t`, `-C`, `-c`, `--amend`,
`--allow-empty`, `--cleanup`, `--fixup`, `--squash`, `--patch`,
`--interactive`, `--dry-run`, `-e`, `--edit`, `--no-edit`, `--include`, `--only`,
`--pathspec-from-file`, and their attached/long-form equivalents because cmtr
supplies the message, controls editor behavior, and analyzes the staged diff
before running `git commit`.
Safe metadata/trailer options such as `--author`, `--date`, `--signoff`,
`--gpg-sign`, and `--trailer` are passed through.
Pathspecs passed after `--` are supported and limit the prompt context to those
staged paths. They are interpreted relative to the current directory, like
`git commit`. If those paths also have unstaged edits, cmtr stops instead of
generating a message from stale staged context.
AI backends are asked to return structured JSON with a single `message` string.
cmtr validates that string before use; obvious prompt leaks, diff echoes,
conflict markers, placeholders, malformed body spacing, and comment-only output
are rejected instead of being rewritten with heuristic cleanup.

## How it builds context

- Uses staged files (`git diff --cached`) for the actual changes.
- Finds shared paths and samples recent `git log` messages on those paths to learn the repo's style.
- For unrelated staged files, samples up to `max_log_paths` high-signal paths instead of relying on only one fallback path.
- Requests structured output from the model so the generated commit message is
  returned as data, not prose wrapped around a suggestion.
- Codex mode runs from a scratch directory and receives only the generated prompt
  context, not live access to the target checkout.

## Configuration

Configuration is loaded in this order (later overrides earlier):

1. XDG config file (`~/.config/cmtr/config.toml` or `$XDG_CONFIG_HOME/cmtr/config.toml`)
2. `cmtr.toml` in the repo root (optional repo-specific overrides)
3. Environment variables
4. CLI flags

Manage global config with:

- `cmtr config path`
- `cmtr config list`
- `cmtr config get model`
- `cmtr config set model gpt-5.5`
- `cmtr config unset model`

Example config file:

```
model = "gpt-5.5"
codex_model = "gpt-5.5"
max_diff_bytes = 12000
max_patch_lines = 400
max_log_entries = 20
max_log_paths = 4
max_log_body_lines = 6
timeout_seconds = 60
reasoning_effort = ""
text_verbosity = "low"
prefer_codex = true
base_url = "https://api.openai.com/v1"
organization = "org_..."
project = "proj_..."
```

Unknown config keys and invalid numeric ranges fail fast so typoed settings do
not silently fall back to defaults. `model`/`CMTR_MODEL` configures OpenAI API
mode. `codex_model`/`CMTR_CODEX_MODEL` configures Codex mode. For one-off CLI
runs, `--model` overrides whichever backend is selected, while `--codex-model`
overrides only Codex mode.
Set `reasoning_effort` or `text_verbosity` to a blank string to avoid sending
that optional Responses API parameter for models or compatible providers that
do not support it.

Codex is preferred by default. `timeout_seconds` applies to both Codex CLI
execution and OpenAI API requests. Set `prefer_codex = false` to use the OpenAI
API first whenever `OPENAI_API_KEY` is set, while still allowing Codex when no
API key is available.
Use `cmtr auth status` to see which mode will be selected and why.

Environment variables:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_ORG_ID` (also supports `OPENAI_ORG` and `OPENAI_ORGANIZATION`)
- `OPENAI_PROJECT_ID`
- `CMTR_MODEL`
- `CMTR_CODEX_MODEL`
- `CMTR_MAX_DIFF_BYTES`
- `CMTR_MAX_PATCH_LINES`
- `CMTR_MAX_LOG_ENTRIES`
- `CMTR_MAX_LOG_PATHS`
- `CMTR_MAX_LOG_BODY_LINES`
- `CMTR_TIMEOUT_SECONDS`
- `CMTR_REASONING_EFFORT`
- `CMTR_TEXT_VERBOSITY`
- `CMTR_PREFER_CODEX`

## Development

Local development:

- `mise install`
- `mise run install`
- `mise run run`

Linting and type checking:

- `mise run lint`
- `uv run ruff check .`
- `mise run format-check`
- `uv run ruff format --check .`
- `mise run typecheck`
- `uv run ty check`

Testing and packaging:

- `mise run format`
- `uv run ruff format .`
- `mise run test`
- `uv run pytest`
- `mise run build`
- `uv build`

If you are installing manually, run `uv sync --group dev` first to install the
dev tools.

## Troubleshooting

- No staged changes: run `git add` before cmtr.
- Missing API key: set `OPENAI_API_KEY` or install/login to Codex CLI.
- Unsure which auth mode is active: run `cmtr auth status`.
- Hook failures: a `# cmtr failed: ...` comment is appended to the commit message template.
