"""TUI abstraction layer for the llm CLI.

All terminal output flows through this package.  The ``TUI`` class owns a
message queue and a dedicated consumer thread that serializes writes,
eliminating the cursor-interleaving bugs that occur when multiple threads
(spinner, HTTP logging, streaming) write to the terminal concurrently.
"""

from __future__ import annotations

import os
import queue
from typing import TextIO

from .messages import Msg, MsgType, register_msg_type, STREAM_DEFAULTS
from .terminal import Terminal, FakeTerminal
from .spinner import SpinnerState
from .consumer import Consumer
from .capture import ScopedCapture

__all__ = [
    "TUI",
    "Msg",
    "MsgType",
    "register_msg_type",
    "STREAM_DEFAULTS",
    "Terminal",
    "FakeTerminal",
    "SpinnerState",
    "ScopedCapture",
]


class TUI:
    """Unified terminal UI controller.

    All terminal output flows through this object.  Pass it via Click
    context and function arguments.
    """

    def __init__(
        self,
        color: str | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        force: bool = False,
    ):
        if force is False:
            force = bool(os.environ.get("LLM_TUI_FORCE"))
        self._terminal = Terminal(stdout=stdout, stderr=stderr)
        self._is_tty = force or self._terminal.is_tty
        self._color = color
        self._queue: queue.Queue[Msg] = queue.Queue()
        self._spinner = SpinnerState(enabled=self._is_tty and bool(color))
        self._md_renderer: object | None = None
        self._consumer: Consumer | None = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._consumer = Consumer(
            self._queue, self._terminal, self._spinner,
            md_renderer=self._md_renderer,
        )
        self._consumer.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._queue.put(Msg(kind=MsgType.STOP))
        if self._consumer is not None:
            self._consumer.join(timeout=2.0)
        self._started = False

    def emit(self, msg: Msg) -> None:
        if not self._is_tty and msg.kind == MsgType.EPHEMERAL:
            return
        if not self._started:
            self.start()
        self._queue.put(msg)

    def write_chunk(self, text: str, **meta: object) -> None:
        self.emit(Msg(kind=MsgType.CONTENT, text=text, meta=dict(meta)))

    def finish_content(self) -> None:
        self.emit(Msg(kind=MsgType.CONTENT_FINISH))

    def separator(self) -> None:
        self.emit(Msg(kind=MsgType.SEPARATOR))

    def spinner_start(self) -> None:
        self._spinner.set_state("starting")
        if not self._started:
            self.start()

    def spinner_set_state(self, name: str, **kwargs: str) -> None:
        self._spinner.set_state(name, **kwargs)

    def spinner_stop(self) -> None:
        self._spinner.set_state(None)

    def emit_http_debug(self, formatted_text: str, request_id: str = "") -> None:
        self.emit(Msg(
            kind=MsgType.HTTP_DEBUG, text=formatted_text,
            request_id=request_id, stream="stderr",
        ))

    def scoped_capture(self, plugin_name: str = "") -> ScopedCapture:
        return ScopedCapture(self, plugin_name)

    @property
    def terminal(self) -> Terminal:
        return self._terminal

    @property
    def is_started(self) -> bool:
        return self._started
