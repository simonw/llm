"""Scoped IO capture for routing plugin output through the TUI layer.

``ScopedCapture`` is a context manager that temporarily replaces
``sys.stdout`` and ``sys.stderr`` with proxy objects.  Any ``print()``
or ``write()`` call during the scope is routed through the TUI message
queue, ensuring the consumer thread can coordinate with the spinner and
other ephemeral content.

Usage::

    with tui.scoped_capture("my_plugin"):
        plugin.run()  # Any print() goes through TUI
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from .messages import Msg, MsgType

if TYPE_CHECKING:
    from . import TUI


class _TUIWriter:
    """File-like object that routes writes through the TUI queue."""

    def __init__(self, tui: TUI, stream: str, source: str):
        self._tui = tui
        self._stream = stream
        self._source = source

    def write(self, text: str) -> int:
        if text:
            self._tui.emit(Msg(
                kind=MsgType.CONTENT,
                text=text,
                source=self._source,
                stream=self._stream,
            ))
        return len(text) if text else 0

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return "utf-8"


class ScopedCapture:
    """Context manager that captures stdout/stderr during plugin execution.

    Parameters
    ----------
    tui:
        The TUI instance to route captured output through.
    plugin_name:
        Identifier for the source of captured output.
    """

    def __init__(self, tui: TUI, plugin_name: str = ""):
        self._tui = tui
        self._plugin_name = plugin_name
        self._old_stdout = None
        self._old_stderr = None

    def __enter__(self) -> ScopedCapture:
        self._old_stdout = sys.stdout
        self._old_stderr = sys.stderr
        sys.stdout = _TUIWriter(self._tui, stream="stdout", source=self._plugin_name)  # type: ignore[assignment]
        sys.stderr = _TUIWriter(self._tui, stream="stderr", source=self._plugin_name)  # type: ignore[assignment]
        return self

    def __exit__(self, *exc: object) -> bool:
        sys.stdout = self._old_stdout  # type: ignore[assignment]
        sys.stderr = self._old_stderr  # type: ignore[assignment]
        return False
