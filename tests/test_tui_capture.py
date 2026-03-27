"""Tests for tui/capture.py: ScopedCapture."""

from __future__ import annotations

import io
import sys

from tui import TUI
from tui.terminal import Terminal
from tui.spinner import SpinnerState
from tui.consumer import Consumer
from tui.messages import Msg

import queue


class TestScopedCapture:
    def test_print_routed_through_tui(self):
        """print() inside scoped_capture goes through the TUI queue."""
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

        with tui.scoped_capture("test_plugin"):
            print("hello from plugin")

        tui.stop()
        assert "hello from plugin" in stdout.getvalue()

    def test_stderr_captured(self):
        """stderr writes inside scoped_capture go through TUI."""
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

        original_stderr = sys.stderr
        with tui.scoped_capture("test_plugin"):
            print("error output", file=sys.stderr)
            # Inside the capture, sys.stderr is replaced
            assert sys.stderr is not original_stderr

        tui.stop()
        # After capture, sys.stderr is restored
        assert sys.stderr is original_stderr

    def test_stdout_restored_after_capture(self):
        """sys.stdout is restored to its original value after the context exits."""
        tui = TUI(color=None, force=True)
        original_stdout = sys.stdout

        with tui.scoped_capture("test"):
            assert sys.stdout is not original_stdout

        assert sys.stdout is original_stdout

    def test_stdout_restored_on_exception(self):
        """sys.stdout is restored even if the captured code raises."""
        tui = TUI(color=None, force=True)
        original_stdout = sys.stdout

        try:
            with tui.scoped_capture("test"):
                raise ValueError("boom")
        except ValueError:
            pass

        assert sys.stdout is original_stdout

    def test_source_set_on_messages(self):
        """Captured output has the plugin name as source."""
        tui = TUI(color=None, force=True)
        # Don't start consumer, just check the queue
        tui._started = True  # Prevent auto-start

        with tui.scoped_capture("my_plugin"):
            print("hi", end="")

        msg = tui._queue.get_nowait()
        assert msg.source == "my_plugin"
        assert msg.text == "hi"
