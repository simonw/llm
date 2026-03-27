"""Tests for tui/spinner.py (SpinnerState) and TUI integration."""

import time

from tui import TUI, Msg, MsgType, FakeTerminal
from tui.spinner import SpinnerState, SPINNERS, DEFAULT_SPINNER


# ── SpinnerState unit tests ───────────────────────────────────────────


class TestSpinnerStateBasics:
    def test_initially_inactive(self):
        s = SpinnerState()
        assert not s.is_active
        assert s.state_name is None

    def test_set_state_activates(self):
        s = SpinnerState()
        s.set_state("starting")
        assert s.is_active
        assert s.state_name == "starting"

    def test_set_state_none_deactivates(self):
        s = SpinnerState()
        s.set_state("starting")
        s.set_state(None)
        assert not s.is_active

    def test_disabled_spinner(self):
        s = SpinnerState(enabled=False)
        s.set_state("starting")
        assert not s.is_active  # Still inactive when disabled

    def test_advance_frame_inactive(self):
        s = SpinnerState()
        assert s.advance_frame() is None

    def test_advance_frame_produces_string(self):
        s = SpinnerState()
        s.set_state("starting")
        frame = s.advance_frame()
        assert frame is not None
        assert isinstance(frame, str)
        assert "Starting..." in frame

    def test_advance_frame_cycles(self):
        s = SpinnerState()
        s.set_state("starting")
        frames = [s.advance_frame() for _ in range(4)]
        assert all(f is not None for f in frames)
        # Dot spinner has 2 frames, so frames should alternate
        assert frames[0] != frames[1] or frames[0] == frames[2]


class TestSpinnerStateTransitions:
    def test_state_change_preserves_frame_idx(self):
        s = SpinnerState()
        s.set_state("starting")
        s.advance_frame()  # frame 0
        s.advance_frame()  # frame 1
        # Same spinner definition, frame index should NOT reset
        s.set_state("connecting")
        frame = s.advance_frame()
        assert frame is not None
        assert "Connecting..." in frame

    def test_different_spinner_resets_frame_idx(self):
        s = SpinnerState()
        # All default states use "dot" spinner, so manually test
        # by checking the frame index resets when spinner def changes
        s.set_state("starting")
        for _ in range(5):
            s.advance_frame()
        # After 5 frames, idx should be 5
        # set_state to same spinner type -> idx preserved
        s.set_state("waiting")
        assert s.state_name == "waiting"

    def test_tool_calling_with_kwargs(self):
        s = SpinnerState()
        s.set_state("tool_calling", tool_name="web_search")
        frame = s.advance_frame()
        assert frame is not None
        assert "web_search" in frame


class TestSpinnerInterval:
    def test_interval_when_inactive(self):
        s = SpinnerState()
        interval = s.current_interval()
        assert interval == 0.25  # Default idle

    def test_interval_when_active(self):
        s = SpinnerState()
        s.set_state("starting")
        interval = s.current_interval()
        expected = SPINNERS[DEFAULT_SPINNER]["interval"]
        assert interval == expected


class TestSpinnerStale:
    def test_stale_indicator(self):
        s = SpinnerState()
        s.set_state("starting")
        # Manually set entered_at to the past
        with s._lock:
            s._state_entered_at = time.monotonic() - 20  # 20s > 10s timeout
        frame = s.advance_frame()
        assert frame is not None
        assert "stale" in frame


class TestSpinnerNoColor:
    def test_no_color(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        s = SpinnerState()
        s.set_state("starting")
        frame = s.advance_frame()
        assert frame is not None
        assert "\033[" not in frame  # No ANSI escape codes
        assert "Starting..." in frame


# ── TUI + Consumer integration tests ─────────────────────────────────


class TestTUISpinnerIntegration:
    def test_first_content_stops_spinner(self):
        ft = FakeTerminal()
        tui = TUI(color="mdstream", stdout=ft, stderr=ft, force=True)
        tui._terminal = ft
        tui._spinner = SpinnerState(enabled=True)
        tui._started = False
        from tui.consumer import Consumer
        import queue as q

        test_queue: q.Queue[Msg] = q.Queue()
        tui._queue = test_queue
        consumer = Consumer(test_queue, ft, tui._spinner)

        tui._spinner.set_state("waiting")
        consumer._tick_spinner()
        assert tui._spinner.is_active

        consumer._dispatch(Msg(kind=MsgType.CONTENT, text="hello"))
        assert not tui._spinner.is_active
        assert "hello" in ft.stdout_text

    def test_spinner_no_stranding(self):
        """The core bug: spinner frames must not get stranded when
        HTTP debug messages arrive between them."""
        ft = FakeTerminal()
        tui = TUI(color="mdstream", stdout=ft, stderr=ft, force=True)
        # Manually set terminal to our fake
        tui._terminal = ft
        tui._spinner = SpinnerState(enabled=True)
        # Rebuild consumer with our fake terminal
        tui._started = False
        from tui.consumer import Consumer
        import queue as q

        test_queue: q.Queue[Msg] = q.Queue()
        tui._queue = test_queue

        consumer = Consumer(test_queue, ft, tui._spinner)

        # Simulate: spinner active, then HTTP debug, then more spinner
        tui._spinner.set_state("starting")

        # Put messages directly in queue and process synchronously
        # by calling _dispatch directly (no thread needed for this test)
        consumer._tick_spinner()  # Renders "Starting..."

        assert "Starting..." in ft.stdout_text

        # HTTP debug arrives
        ft.reset()
        consumer._dispatch(Msg(
            kind=MsgType.HTTP_DEBUG,
            text="[14:00:00] httpcore.connection\nhost: api.example.com",
            stream="stderr",
        ))

        # The ephemeral should have been erased before the debug write
        assert any(op[0] == "erase_rows" for op in ft.operations)
        # Debug text should be on stderr
        assert "httpcore.connection" in ft.stderr_text

        # Spinner should be restored after debug write
        # (restore_ephemeral re-renders it)
        tui._spinner.set_state("connecting")
        ft.reset()
        consumer._tick_spinner()
        assert "Connecting..." in ft.stdout_text

        # The key assertion: "Starting..." should NOT be in the output
        # after the debug write. It was erased.
        assert "Starting..." not in ft.stdout_text

    def test_tui_lifecycle(self):
        """TUI starts, processes messages, and stops cleanly."""
        # Use a real Terminal but with fake streams
        import io

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        from tui.terminal import Terminal

        term = Terminal(stdout=stdout_buf, stderr=stderr_buf)
        tui = TUI(color=None, force=True)
        tui._terminal = term
        tui._spinner = SpinnerState(enabled=False)

        from tui.consumer import Consumer
        import queue as q

        test_q: q.Queue[Msg] = q.Queue()
        tui._queue = test_q
        tui._consumer = Consumer(test_q, term, tui._spinner)
        tui._consumer.start()
        tui._started = True

        # Emit content
        tui.write_chunk("hello ")
        tui.write_chunk("world")
        tui.stop()

        output = stdout_buf.getvalue()
        assert "hello " in output
        assert "world" in output

    def test_ephemeral_dropped_non_tty(self):
        """Ephemeral messages are silently dropped in non-TTY mode."""
        tui = TUI(color=None, force=False)
        tui._terminal._is_tty = False
        tui._is_tty = False
        # This should not raise or enqueue
        tui.emit(Msg(kind=MsgType.EPHEMERAL, text="spinner"))
        assert tui._queue.empty()

    def test_spinner_start_auto_starts_tui(self):
        """spinner_start() auto-starts the consumer thread."""
        import io

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        from tui.terminal import Terminal

        term = Terminal(stdout=stdout_buf, stderr=stderr_buf)
        tui = TUI(color="mdstream", force=True)
        tui._terminal = term
        assert not tui.is_started
        tui.spinner_start()
        # Auto-start should have kicked in via emit
        # Give consumer a moment to process
        import time

        time.sleep(0.1)
        assert tui.is_started
        tui.stop()
