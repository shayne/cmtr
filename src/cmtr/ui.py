from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Callable

from rich.console import Console
from rich.status import Status


class StatusLine(AbstractContextManager["StatusLine"]):
    def __init__(self, console: Console, message: str) -> None:
        self._console = console
        self._message = message
        self._status: Status | None = None

    def __enter__(self) -> "StatusLine":
        if self._console.is_terminal:
            self._status = self._console.status(self._message, spinner="dots")
            self._status.__enter__()
        else:
            self._console.print(self._message)
        return self

    def update(self, message: str) -> None:
        if self._status is not None:
            self._status.update(message)
        else:
            self._console.print(message)

    def __exit__(self, exc_type, exc, exc_tb) -> bool | None:
        if self._status is not None:
            return self._status.__exit__(exc_type, exc, exc_tb)
        return False
