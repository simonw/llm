"""Thin terminal abstraction over ANSI escape sequences.

Wraps raw escape codes into named methods so call sites document intent
and tests can assert on operations rather than byte sequences.  No
external dependencies.
"""

from __future__ import annotations

import os
import sys
from typing import TextIO

# ── ANSI escape sequences ────────────────────────────────────────────

ERASE_LINE = "\r\033[K"
CURSOR_UP_FMT = "\033[{}A"
ERASE_DOWN = "\033[J"
RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"


class Terminal:
    """Thin wrapper over stdout/stderr for testable terminal control.

    Parameters
    ----------
    stdout:
        Writable file object for primary output.  Defaults to ``sys.stdout``.
    stderr:
        Writable file object for diagnostic output.  Defaults to ``sys.stderr``.
    """

    def __init__(
        self,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ):
        self.stdout: TextIO = stdout or sys.stdout
        self.stderr: TextIO = stderr or sys.stderr
        self._is_tty = hasattr(self.stdout, "isatty") and self.stdout.isatty()
        self._use_color = self._is_tty and not os.environ.get("NO_COLOR")

    # ── Properties ────────────────────────────────────────────────

    @property
    def is_tty(self) -> bool:
        return self._is_tty

    @property
    def use_color(self) -> bool:
        return self._use_color

    def width(self) -> int:
        try:
            return os.get_terminal_size().columns
        except OSError:
            return 80

    def height(self) -> int:
        try:
            return os.get_terminal_size().lines
        except OSError:
            return 24

    # ── Core write ────────────────────────────────────────────────

    def _stream(self, fd: str) -> TextIO:
        return self.stderr if fd == "stderr" else self.stdout

    def write(self, text: str, fd: str = "stdout") -> None:
        """Write *text* to the specified file descriptor and flush."""
        try:
            target = self._stream(fd)
            target.write(text)
            target.flush()
        except (BrokenPipeError, OSError):
            pass

    def write_line(self, text: str, fd: str = "stdout") -> None:
        """Write *text* followed by a newline."""
        self.write(text + "\n", fd)

    # ── Cursor and line control ───────────────────────────────────

    def clear_line(self, fd: str = "stdout") -> None:
        """Carriage return + erase to end of line."""
        self.write(ERASE_LINE, fd)

    def cursor_up(self, n: int = 1, fd: str = "stdout") -> None:
        """Move cursor up *n* rows."""
        if n > 0:
            self.write(CURSOR_UP_FMT.format(n), fd)

    def erase_down(self, fd: str = "stdout") -> None:
        """Erase from cursor to end of screen."""
        self.write(ERASE_DOWN, fd)

    def erase_rows(self, n: int, fd: str = "stdout") -> None:
        """Move up *n* rows, return to column 0, and erase everything below.

        Used to erase multi-line ephemeral content (spinner, future status
        bar) before writing persistent content.
        """
        if n <= 0:
            return
        self.cursor_up(n, fd)
        self.write("\r", fd)
        self.erase_down(fd)


# ── Test double ──────────────────────────────────────────────────────


class FakeTerminal(Terminal):
    """Records all writes for assertion in tests.

    Provides separate buffers for stdout and stderr, plus an
    ``operations`` log that records every method call in order.
    """

    def __init__(self) -> None:
        # Don't call super().__init__() -- we don't want real file objects
        self._stdout_buf: list[str] = []
        self._stderr_buf: list[str] = []
        self.operations: list[tuple[str, ...]] = []
        self._is_tty = True
        self._use_color = True

    @property
    def stdout(self) -> None:  # type: ignore[override]
        return None  # Not a real file; use stdout_text instead

    @property
    def stderr(self) -> None:  # type: ignore[override]
        return None

    @property
    def stdout_text(self) -> str:
        return "".join(self._stdout_buf)

    @property
    def stderr_text(self) -> str:
        return "".join(self._stderr_buf)

    def write(self, text: str, fd: str = "stdout") -> None:
        self.operations.append(("write", fd, text))
        if fd == "stderr":
            self._stderr_buf.append(text)
        else:
            self._stdout_buf.append(text)

    def clear_line(self, fd: str = "stdout") -> None:
        self.operations.append(("clear_line", fd))
        self.write(ERASE_LINE, fd)

    def cursor_up(self, n: int = 1, fd: str = "stdout") -> None:
        self.operations.append(("cursor_up", fd, str(n)))
        if n > 0:
            self.write(CURSOR_UP_FMT.format(n), fd)

    def erase_down(self, fd: str = "stdout") -> None:
        self.operations.append(("erase_down", fd))
        self.write(ERASE_DOWN, fd)

    def erase_rows(self, n: int, fd: str = "stdout") -> None:
        self.operations.append(("erase_rows", fd, str(n)))
        if n <= 0:
            return
        self.cursor_up(n, fd)
        self.write("\r", fd)
        self.erase_down(fd)

    def width(self) -> int:
        return 80

    def height(self) -> int:
        return 24

    def reset(self) -> None:
        """Clear all buffers and operations."""
        self._stdout_buf.clear()
        self._stderr_buf.clear()
        self.operations.clear()
