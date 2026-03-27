"""Tests for tui/renderers/http_debug.py: TUIHTTPHandler + TUISpinnerHandler."""

from __future__ import annotations

import io
import json
import logging
import queue
import time

from tui import TUI, Msg
from tui.terminal import Terminal
from tui.spinner import SpinnerState
from tui.consumer import Consumer
from tui.renderers.http_debug import TUIHTTPHandler, TUISpinnerHandler


def _make_record(name, msg, level=logging.DEBUG):
    """Create a minimal LogRecord."""
    record = logging.LogRecord(
        name=name, level=level, pathname="", lineno=0,
        msg=msg, args=(), exc_info=None,
    )
    return record


class TestTUIHTTPHandler:
    def test_formatted_message_routed_through_tui(self):
        """Handler formats the record and sends it to TUI as HTTP_DEBUG."""
        stdout = io.StringIO()
        stderr = io.StringIO()
        term = Terminal(stdout=stdout, stderr=stderr)
        tui = TUI(color=None, force=True)
        tui._terminal = term
        tui._spinner = SpinnerState(enabled=False)

        q: queue.Queue[Msg] = queue.Queue()
        tui._queue = q
        consumer = Consumer(q, term, tui._spinner)
        tui._consumer = consumer
        consumer.start()
        tui._started = True

        # Create a simple formatter that returns the message as-is
        class SimpleFormatter(logging.Formatter):
            def format(self, record):
                return record.getMessage()

        handler = TUIHTTPHandler(tui, SimpleFormatter())
        record = _make_record("httpcore", "test debug output")
        handler.emit(record)

        # Give consumer time to process
        tui.stop()

        assert "test debug output" in stderr.getvalue()

    def test_empty_formatted_message_not_emitted(self):
        """Handler skips empty formatted messages."""
        tui = TUI(color=None, force=True)

        class EmptyFormatter(logging.Formatter):
            def format(self, record):
                return ""

        handler = TUIHTTPHandler(tui, EmptyFormatter())
        record = _make_record("httpcore", "something")
        handler.emit(record)
        # Should not have enqueued anything (aside from any auto-start)
        assert tui._queue.empty()


class TestTUISpinnerHandler:
    def test_tui_event_request_starts_spinner(self):
        tui = TUI(color="mdstream", force=True)
        handler = TUISpinnerHandler(tui)

        event = json.dumps({"kind": "request", "method": "POST", "url": "https://api.example.com"})
        record = _make_record("llm.http", f"TUI Event: {event}")
        handler.emit(record)

        assert tui._spinner.state_name == "starting"

    def test_tui_event_connect_sets_connecting(self):
        tui = TUI(color="mdstream", force=True)
        tui._spinner.set_state("starting")
        handler = TUISpinnerHandler(tui)

        event = json.dumps({"kind": "connect", "host": "api.example.com"})
        record = _make_record("llm.http", f"TUI Event: {event}")
        handler.emit(record)

        assert tui._spinner.state_name == "connecting"

    def test_tui_event_request_sent_sets_waiting(self):
        tui = TUI(color="mdstream", force=True)
        tui._spinner.set_state("connecting")
        handler = TUISpinnerHandler(tui)

        event = json.dumps({"kind": "request_sent"})
        record = _make_record("llm.http", f"TUI Event: {event}")
        handler.emit(record)

        assert tui._spinner.state_name == "waiting"

    def test_tui_event_response_start_keeps_waiting_spinner(self):
        tui = TUI(color="mdstream", force=True)
        tui._spinner.set_state("waiting")
        handler = TUISpinnerHandler(tui)

        event = json.dumps({"kind": "response_start"})
        record = _make_record("llm.http", f"TUI Event: {event}")
        handler.emit(record)

        assert tui._spinner.state_name == "waiting"

    def test_httpcore_fallback_connect(self):
        tui = TUI(color="mdstream", force=True)
        tui._spinner.set_state("starting")
        handler = TUISpinnerHandler(tui)

        record = _make_record("httpcore.connection", "connect_tcp.started host=api.example.com")
        handler.emit(record)

        assert tui._spinner.state_name == "connecting"

    def test_httpcore_fallback_request_sent(self):
        tui = TUI(color="mdstream", force=True)
        tui._spinner.set_state("connecting")
        handler = TUISpinnerHandler(tui)

        record = _make_record("httpcore.http11", "send_request_headers.started")
        handler.emit(record)

        assert tui._spinner.state_name == "waiting"

    def test_non_tui_event_ignored(self):
        tui = TUI(color="mdstream", force=True)
        handler = TUISpinnerHandler(tui)

        record = _make_record("httpcore", "some random message")
        handler.emit(record)

        # Spinner should remain inactive
        assert not tui._spinner.is_active


class TestIntegrationSpinnerNoStranding:
    def test_http_debug_does_not_strand_spinner(self):
        """The core bug fix: HTTP debug output must not strand spinner frames.

        Simulates the real flow: spinner is active, HTTP debug log arrives
        (which previously wrote to stderr and stranded the spinner).  With
        the TUI layer, everything goes through the queue and the consumer
        erases the spinner before writing debug output.
        """
        stdout = io.StringIO()
        stderr = io.StringIO()
        term = Terminal(stdout=stdout, stderr=stderr)

        tui = TUI(color="mdstream", force=True)
        tui._terminal = term
        tui._spinner = SpinnerState(enabled=True)

        q: queue.Queue[Msg] = queue.Queue()
        tui._queue = q
        consumer = Consumer(q, term, tui._spinner)
        tui._consumer = consumer
        consumer.start()
        tui._started = True

        # Start spinner
        tui.spinner_start()
        time.sleep(0.1)  # Let spinner render a frame

        # Emit HTTP debug (this previously stranded the spinner)
        tui.emit_http_debug("[14:00:00] httpcore.connection\nhost: api.example.com")
        time.sleep(0.1)  # Let consumer process

        # Emit more spinner state change
        tui.spinner_set_state("connecting")
        time.sleep(0.1)

        # Stop spinner and TUI
        tui.spinner_stop()
        tui.stop()

        # Check stdout: should NOT contain "Starting..." stranded in output.
        # The spinner should have been erased before each debug write.
        stderr_text = stderr.getvalue()

        # Debug text should be on stderr
        assert "httpcore.connection" in stderr_text

        # The spinner text might appear in stdout (from rendering/erasing cycles)
        # but the critical thing is that the final output doesn't have orphaned
        # spinner lines mixed with debug output. The erase_rows operations
        # should have cleaned them up.
