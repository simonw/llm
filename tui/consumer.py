"""TUI consumer thread: drains the message queue and renders to the terminal.

The consumer is the single point of terminal output.  It processes
messages in FIFO order, erasing ephemeral content (spinner) before
persistent writes and re-rendering it after.  The spinner animation is
driven by queue timeouts rather than a separate daemon thread.
"""

from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING

from .messages import Msg, MsgType
from .terminal import Terminal

if TYPE_CHECKING:
    from .spinner import SpinnerState


class Consumer(threading.Thread):
    """Dedicated consumer thread for all TUI output.

    Parameters
    ----------
    q:
        The message queue shared with the ``TUI`` object.
    terminal:
        Terminal abstraction for actual writes.
    spinner:
        Spinner state machine for ephemeral animation.
    md_renderer:
        Optional markdown renderer (StreamingMarkdownRenderer).
    """

    def __init__(
        self,
        q: queue.Queue[Msg],
        terminal: Terminal,
        spinner: SpinnerState,
        md_renderer: object | None = None,
    ):
        super().__init__(daemon=True, name="tui-consumer")
        self._q = q
        self._term = terminal
        self._spinner = spinner
        self._md = md_renderer
        self._ephemeral_rows: int = 0
        self._last_ephemeral_text: str = ""

    # ── Main loop ─────────────────────────────────────────────────

    def run(self) -> None:
        while True:
            try:
                msg = self._q.get(timeout=self._spinner.current_interval())
                if msg.kind == MsgType.STOP:
                    self._erase_ephemeral()
                    break
                try:
                    self._dispatch(msg)
                except Exception:
                    pass
            except queue.Empty:
                try:
                    self._tick_spinner()
                except Exception:
                    pass

    # ── Dispatch ──────────────────────────────────────────────────

    def _dispatch(self, msg: Msg) -> None:
        if msg.kind == MsgType.EPHEMERAL:
            self._render_ephemeral(msg.text)
        elif msg.kind == MsgType.CONTENT:
            if self._spinner.is_active:
                self._spinner.set_state(None)
            self._erase_ephemeral()
            self._render_content(msg)
        elif msg.kind == MsgType.CONTENT_FINISH:
            if self._spinner.is_active:
                self._spinner.set_state(None)
            self._erase_ephemeral()
            self._finish_content()
        elif msg.kind == MsgType.HTTP_DEBUG:
            self._erase_ephemeral()
            self._render_http_debug(msg)
            self._restore_ephemeral()
        elif msg.kind == MsgType.SEPARATOR:
            self._erase_ephemeral()
            self._term.write("\n")
            self._restore_ephemeral()
        elif msg.kind == MsgType.TOOL_STATUS:
            self._erase_ephemeral()
            fd = msg.resolve_stream()
            self._term.write(msg.text, fd=fd)
            self._restore_ephemeral()
        elif msg.kind == MsgType.ERROR:
            self._erase_ephemeral()
            self._term.write(msg.text, fd="stderr")
        else:
            # Plugin or unknown type: plain text render
            self._erase_ephemeral()
            fd = msg.resolve_stream()
            self._term.write(msg.text, fd=fd)
            self._restore_ephemeral()

    # ── Spinner / ephemeral ───────────────────────────────────────

    def _tick_spinner(self) -> None:
        if not self._spinner.is_active:
            return
        frame = self._spinner.advance_frame()
        if frame is not None:
            # Overwrite spinner line in place, preserve padding above
            self._term.clear_line()
            self._term.write(frame)
            self._last_ephemeral_text = frame
            if self._ephemeral_rows == 0:
                self._ephemeral_rows = 1

    def _render_ephemeral(self, text: str) -> None:
        """Overwrite the ephemeral region with new content."""
        self._term.clear_line()
        self._term.write(text)
        if self._ephemeral_rows == 0:
            self._ephemeral_rows = 1
        self._last_ephemeral_text = text

    def _erase_ephemeral(self) -> None:
        """Erase whatever ephemeral content is on screen."""
        if self._ephemeral_rows > 0:
            self._term.erase_rows(self._ephemeral_rows)
            self._ephemeral_rows = 0
            self._last_ephemeral_text = ""

    def _restore_ephemeral(self) -> None:
        """Re-render ephemeral content after a persistent write."""
        if self._spinner.is_active:
            frame = self._spinner.advance_frame()
            if frame is not None:
                self._term.write("\n")  # blank separator line
                self._term.clear_line()
                self._term.write(frame)
                self._ephemeral_rows = 2  # separator + spinner
                self._last_ephemeral_text = frame

    # ── Content rendering ─────────────────────────────────────────

    def _render_content(self, msg: Msg) -> None:
        if self._md is not None and hasattr(self._md, "write_chunk"):
            self._md.write_chunk(msg.text, self._term._stream("stdout"))
        else:
            self._term.write(msg.text)

    def _finish_content(self) -> None:
        if self._md is not None and hasattr(self._md, "finish"):
            self._md.finish(self._term._stream("stdout"))

    # ── HTTP debug ────────────────────────────────────────────────

    def _render_http_debug(self, msg: Msg) -> None:
        fd = msg.resolve_stream()
        text = msg.text
        if text:
            if not text.endswith("\n"):
                text += "\n"
            self._term.write(text, fd=fd)
