# cmtr

cmtr writes your git commit messages for you. It uses the OpenAI API (gpt-5.2), the staged diff, and recent commit history to match the repository's style.

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
it via `npx @openai/codex@latest` as long as you're signed in. If `OPENAI_API_KEY`
is not set and you are signed into Codex, cmtr will use Codex automatically.

Or install the git hook:

- `cmtr --hook`
  - Installs a `prepare-commit-msg` hook that automatically generates a commit message
    right before the commit editor opens. If there is already a message or you're in a
    rebase/fixup/squash flow, it skips.

## Usage

- `cmtr`
  - Behaves like `git commit -v`, but injects a generated commit message.
- `cmtr --dry-run`
  - Print the generated message without committing.
- `cmtr --no-edit`
  - Skip opening the editor after generating the message.
- `cmtr --hook`
  - Install the `prepare-commit-msg` hook to auto-generate messages on every commit.
- `cmtr --uninstall-hook`
  - Remove the hook.

Extra git commit flags can be passed directly (for example, `--no-verify`). Avoid `-m/-F/-C/-c` because cmtr supplies the message.

## How it builds context

- Uses staged files (`git diff --cached`) for the actual changes.
- Finds shared paths and samples recent `git log` messages on those paths to learn the repo's style.

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
- `cmtr config set model gpt-5.2`
- `cmtr config unset model`

Example config file:

```
model = "gpt-5.2"
max_diff_bytes = 12000
max_patch_lines = 400
max_log_entries = 20
max_log_paths = 4
max_log_body_lines = 6
timeout_seconds = 60
reasoning_effort = "none"
text_verbosity = "low"
prefer_codex = false
base_url = "https://api.openai.com/v1"
organization = "org_..."
```

Set `prefer_codex = true` to force Codex CLI (even if `OPENAI_API_KEY` is set).
Use `cmtr auth status` to see which mode will be selected and why.

Environment variables:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_ORG`
- `CMTR_MODEL`
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

Type checking:

- `mise run typecheck`
- `uv run ty check`

If you are installing manually, run `uv sync --group dev` first to install the ty tool.

## Troubleshooting

- No staged changes: run `git add` before cmtr.
- Missing API key: set `OPENAI_API_KEY` or install/login to Codex CLI.
- Unsure which auth mode is active: run `cmtr auth status`.
- Hook failures: a `# cmtr failed: ...` comment is appended to the commit message template.
