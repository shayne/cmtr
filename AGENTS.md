# Repository Guidelines

## Project Structure & Module Organization
- `src/cmtr/`: Python package and CLI entry point (`cmtr:main`).
- `pyproject.toml`: Project metadata, dependencies, and build config (uv).
- `mise.toml`: Tool versions and task shortcuts.
- `README.md`: User-facing docs (currently empty).
- `LICENSE`: MIT license.

## Build, Test, and Development Commands
Use mise for tools/tasks and uv for environment management.
- `mise install`: Install tool versions (Python via mise).
- `mise run install`: Create/update the uv environment (`uv sync`).
- `mise run run`: Run the CLI (`uv run cmtr`).

Direct uv equivalents (if you prefer):
- `uv sync`: Install dependencies and lock environment.
- `uv run cmtr`: Execute the CLI in the project env.

## Coding Style & Naming Conventions
- Language: Python (target 3.14.2+; see `.python-version`).
- Indentation: 4 spaces, no tabs.
- Naming: `snake_case` for functions/variables, `PascalCase` for classes.
- Formatting/linting: no tools configured yet; keep changes minimal and readable.

## Testing Guidelines
- No test framework is configured yet, and there is no `tests/` directory.
- If you add tests, prefer `pytest` and place files under `tests/` named `test_*.py`.
- Run tests via `uv run pytest` once configured.

## Commit & Pull Request Guidelines
- Git history is empty, so there is no established commit message convention yet.
- When opening a PR, include:
  - A short summary of changes.
  - How to run or verify the change (commands/output).
  - Linked issue or context if applicable.

## Configuration Tips
- Update `pyproject.toml` when adding dependencies or CLI scripts.
- Keep `mise.toml` in sync with required tool versions and tasks.
