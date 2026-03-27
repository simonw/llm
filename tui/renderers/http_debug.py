"""HTTP debug logging handlers for the TUI layer.

``TUIHTTPHandler`` formats HTTP log records via ``HTTPColorFormatter``
and routes the result through the TUI message queue.  This replaces
``_QuietStreamHandler`` which wrote directly to stderr, causing
cursor-interleaving bugs with the spinner.

``TUISpinnerHandler`` drives spinner state transitions from structured
``llm.http`` TUI lifecycle events.  This replaces ``SpinnerLogHandler``
from ``llm/utils.py``.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tui import TUI


class TUIHTTPHandler(logging.Handler):
    """Format HTTP log records and route them through the TUI queue.

    Replaces ``_QuietStreamHandler``: instead of writing formatted text
    directly to stderr (where it can interleave with the spinner), this
    handler sends it through the TUI message queue so the consumer thread
    can erase the spinner, write the debug output, and re-render the
    spinner atomically.
    """

    def __init__(self, tui: TUI, formatter: logging.Formatter):
        super().__init__(level=logging.DEBUG)
        self._tui = tui
        self._formatter = formatter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            formatted = self._formatter.format(record)
        except Exception:
            self.handleError(record)
            return
        if not formatted:
            return
        self._tui.emit_http_debug(
            formatted,
            request_id=getattr(record, "request_id", ""),
        )


class TUISpinnerHandler(logging.Handler):
    """Drive spinner state transitions from TUI lifecycle events.

    Replaces ``SpinnerLogHandler`` from ``llm/utils.py``.  Watches
    ``llm.http`` structured events and raw httpcore/openai logs to
    update the spinner state via the TUI object.
    """

    def __init__(self, tui: TUI):
        super().__init__(level=logging.DEBUG)
        self._tui = tui

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            return

        # Structured TUI events from llm.http logger (preferred source)
        if record.name == "llm.http" and msg.startswith("TUI Event: "):
            try:
                _, _, json_str = msg.partition("TUI Event: ")
                data = json.loads(json_str)
            except (json.JSONDecodeError, ValueError):
                return

            kind = data.get("kind")
            if kind == "request":
                self._tui.spinner_start()
                self._tui.spinner_set_state("starting")
            elif kind in ("connect", "tls"):
                self._tui.spinner_set_state("connecting")
            elif kind == "request_sent":
                self._tui.spinner_set_state("waiting")
            elif kind == "response_start":
                # Keep spinner visible between response headers and first chunk.
                # The spinner is stopped by the content path once output begins.
                self._tui.spinner_set_state("waiting")
            return

        # Fallback: raw httpcore / openai log messages
        if record.name.startswith("httpcore"):
            if "connect_tcp.started" in msg or "start_tls.started" in msg:
                self._tui.spinner_set_state("connecting")
            elif "send_request_headers.started" in msg:
                self._tui.spinner_set_state("waiting")
        elif record.name.startswith("openai"):
            if "Request options" in msg or "Sending HTTP Request" in msg:
                self._tui.spinner_set_state("waiting")
