class CmtrError(Exception):
    """Base error for cmtr failures."""


class UserError(CmtrError):
    """An error caused by user input or environment."""


class GitError(CmtrError):
    """A git command failed."""


class ConfigError(CmtrError):
    """Configuration is invalid."""


class OpenAIError(CmtrError):
    """OpenAI request failed or returned unusable output."""


class CodexError(CmtrError):
    """Codex CLI invocation failed or returned unusable output."""
