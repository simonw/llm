"""Tests for the TUI loading spinner."""

import io
import logging
import sys
import time

from tools.spinner import (
    COLORS,
    CURSOR_UP_ONE,
    DEFAULT_SPINNER,
    DIM,
    ERASE_LINE,
    RESET,
    Spinner,
    SPINNER_STATES,
    SPINNERS,
)


class TestSpinnerDisabled:
    """A disabled spinner is a complete no-op."""

    def test_all_methods_are_noop(self):
        s = Spinner(enabled=False)
        s.start()
        s.set_state("connecting")
        s.hide()
        s.unhide()
        s.stop()
        assert not s.is_running

    def test_stop_before_start(self):
        s = Spinner(enabled=False)
        s.stop()  # should not raise


class TestSpinnerLifecycle:
    """Thread lifecycle: start, state transitions, stop."""

    def test_start_and_stop(self):
        s = Spinner(enabled=True)
        s.start()
        assert s.is_running
        s.stop()
        assert not s.is_running

    def test_stop_is_idempotent(self):
        s = Spinner(enabled=True)
        s.start()
        s.stop()
        s.stop()
        s.stop()
        assert not s.is_running

    def test_stop_without_start(self):
        s = Spinner(enabled=True)
        s.stop()  # should not raise

    def test_initial_state_is_starting(self):
        s = Spinner(enabled=True)
        s.start()
        assert s._state == "starting"
        s.stop()

    def test_state_transitions(self):
        s = Spinner(enabled=True)
        s.start()
        s.set_state("connecting")
        assert s._state == "connecting"
        s.set_state("waiting")
        assert s._state == "waiting"
        s.set_state("tool_calling", tool_name="web_search")
        assert s._state == "tool_calling"
        s.stop()

    def test_thread_is_daemon(self):
        s = Spinner(enabled=True)
        s.start()
        assert s._thread.daemon
        s.stop()


class TestSpinnerLabels:
    """Label formatting and state config."""

    def test_label_with_kwargs(self):
        s = Spinner(enabled=True)
        s.start()
        s.set_state("tool_calling", tool_name="web_search")
        cfg = SPINNER_STATES["tool_calling"]
        label = cfg["label"].format(tool_name="web_search")
        assert label == "Calling web_search..."
        s.stop()

    def test_all_states_have_required_keys(self):
        required = {"label", "color", "timeout"}
        for name, cfg in SPINNER_STATES.items():
            assert required.issubset(cfg.keys()), f"State {name!r} missing keys"

    def test_all_spinners_have_required_keys(self):
        for name, cfg in SPINNERS.items():
            assert "frames" in cfg, f"Spinner {name!r} missing frames"
            assert "interval" in cfg, f"Spinner {name!r} missing interval"
            assert len(cfg["frames"]) >= 2, f"Spinner {name!r} needs >= 2 frames"

    def test_state_spinner_refs_are_valid(self):
        for name, cfg in SPINNER_STATES.items():
            spinner_ref = cfg.get("spinner", DEFAULT_SPINNER)
            assert (
                spinner_ref in SPINNERS
            ), f"State {name!r} references unknown spinner {spinner_ref!r}"


class TestSpinnerStale:
    """Timeout / stale indicator."""

    def test_stale_suffix_after_timeout(self, monkeypatch):
        s = Spinner(enabled=True)
        s.start()
        s.set_state("starting")
        # Fast-forward time past the timeout
        with s._lock:
            s._state_entered_at = time.monotonic() - 999
        # Capture output
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        with s._lock:
            s._render_frame()
        monkeypatch.undo()
        assert "(stale)" in buf.getvalue()
        s.stop()


class TestSpinnerHide:
    """Hide / unhide behavior."""

    def test_hide_and_unhide(self):
        s = Spinner(enabled=True)
        s.start()
        s.hide()
        assert s._hidden
        s.unhide()
        assert not s._hidden
        s.stop()

    def test_unhide_renders_with_ephemeral_separator(self, monkeypatch):
        s = Spinner(enabled=True)
        s._state = "waiting"
        s._state_entered_at = time.monotonic()
        s._separator_before_next_frame = True
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        with s._lock:
            s._render_frame()
        monkeypatch.undo()
        assert buf.getvalue().startswith(f"\n{ERASE_LINE}")
        assert s._separator_visible is True

    def test_hide_with_separator_repositions_for_log_output(self, monkeypatch):
        s = Spinner(enabled=True)
        s._separator_visible = True
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        s.hide()
        monkeypatch.undo()
        assert buf.getvalue() == f"{ERASE_LINE}{CURSOR_UP_ONE}\r"


class TestSpinnerPersist:
    """Persist vs clear behavior on stop()."""

    def test_clear_default(self, monkeypatch):
        """Without HTTP debug, stop() clears the spinner line (no trailing newline)."""
        monkeypatch.delenv("LLM_SPINNER_PERSIST", raising=False)
        monkeypatch.delenv("LLM_SPINNER_CLEAR", raising=False)
        monkeypatch.delenv("LLM_HTTP_DEBUG", raising=False)
        monkeypatch.delenv("NO_COLOR", raising=False)
        s = Spinner(enabled=True)
        s.start()
        s.set_state("waiting")
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        s.stop()
        monkeypatch.undo()
        output = buf.getvalue()
        assert "Waiting for response..." not in output
        assert ERASE_LINE in output

    def test_persist_mode(self, monkeypatch):
        """LLM_SPINNER_PERSIST=1 keeps a static line in scrollback."""
        monkeypatch.setenv("LLM_SPINNER_PERSIST", "1")
        monkeypatch.setenv("LLM_SPINNER_PERSIST_TEXT", ">")
        monkeypatch.setenv("NO_COLOR", "1")
        s = Spinner(enabled=True)
        s.start()
        s.set_state("waiting")
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        s.stop()
        monkeypatch.undo()
        output = buf.getvalue()
        assert "\n> Waiting for response...\n\n" in output

    def test_explicit_persist_with_http_debug(self, monkeypatch):
        """Persist requires LLM_SPINNER_PERSIST=1 even with HTTP debug."""
        monkeypatch.setenv("LLM_SPINNER_PERSIST", "1")
        monkeypatch.delenv("LLM_SPINNER_CLEAR", raising=False)
        monkeypatch.setenv("LLM_HTTP_DEBUG", "2")
        monkeypatch.setenv("NO_COLOR", "1")
        s = Spinner(enabled=True)
        s.start()
        s.set_state("waiting")
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        s.stop()
        monkeypatch.undo()
        output = buf.getvalue()
        assert (
            f"\n{SPINNERS[DEFAULT_SPINNER]['persist']} Waiting for response...\n\n"
            in output
        )

    def test_http_debug_2_does_not_auto_persist(self, monkeypatch):
        """LLM_HTTP_DEBUG=2 alone does NOT enable persist."""
        monkeypatch.setenv("LLM_HTTP_DEBUG", "2")
        monkeypatch.delenv("LLM_SPINNER_PERSIST", raising=False)
        monkeypatch.delenv("LLM_SPINNER_CLEAR", raising=False)
        monkeypatch.setenv("NO_COLOR", "1")
        s = Spinner(enabled=True)
        s.start()
        s.set_state("waiting")
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        s.stop()
        monkeypatch.undo()
        output = buf.getvalue()
        assert "Waiting for response..." not in output
        assert ERASE_LINE in output

    def test_stop_cleans_up_separator(self, monkeypatch):
        """stop() clears both spinner line and separator when separator is visible."""
        monkeypatch.delenv("LLM_SPINNER_PERSIST", raising=False)
        monkeypatch.delenv("LLM_SPINNER_CLEAR", raising=False)
        monkeypatch.delenv("NO_COLOR", raising=False)
        s = Spinner(enabled=True)
        s.start()
        s.set_state("waiting")
        # Simulate hide/unhide cycle leaving a separator
        s._separator_visible = True
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        s.stop()
        monkeypatch.undo()
        output = buf.getvalue()
        # Should clear spinner line AND go up to clear separator
        assert CURSOR_UP_ONE in output
        assert output.count(ERASE_LINE) >= 2

    def test_legacy_clear_alias_true(self, monkeypatch):
        monkeypatch.setenv("LLM_SPINNER_CLEAR", "1")
        s = Spinner(enabled=True)
        assert s._persist_on_stop is False

    def test_legacy_clear_alias_false(self, monkeypatch):
        monkeypatch.setenv("LLM_SPINNER_CLEAR", "0")
        s = Spinner(enabled=True)
        assert s._persist_on_stop is True

    def test_persist_flag_takes_precedence_over_legacy_clear(self, monkeypatch):
        monkeypatch.setenv("LLM_SPINNER_PERSIST", "1")
        monkeypatch.setenv("LLM_SPINNER_CLEAR", "1")
        s = Spinner(enabled=True)
        assert s._persist_on_stop is True

    def test_persist_padding(self, monkeypatch):
        monkeypatch.setenv("LLM_SPINNER_PERSIST", "1")
        monkeypatch.setenv("LLM_SPINNER_PERSIST_TEXT", ">")
        monkeypatch.setenv("LLM_SPINNER_PADDING_BEFORE", "1")
        monkeypatch.setenv("LLM_SPINNER_PADDING_AFTER", "1")
        monkeypatch.setenv("NO_COLOR", "1")
        s = Spinner(enabled=True)
        s.start()
        s.set_state("waiting")
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        s.stop()
        monkeypatch.undo()
        output = buf.getvalue()
        assert "\n> Waiting for response...\n\n" in output

    def test_persisted_symbol_uses_dim_text_style_without_spinner_color(
        self, monkeypatch
    ):
        monkeypatch.setenv("LLM_SPINNER_PERSIST", "1")
        monkeypatch.delenv("NO_COLOR", raising=False)
        s = Spinner(enabled=True)
        s.start()
        s.set_state("waiting")
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        s.stop()
        monkeypatch.undo()
        output = buf.getvalue()
        expected = f"{DIM}{SPINNERS[DEFAULT_SPINNER]['persist']} Waiting for response...{RESET}"
        assert expected in output
        assert COLORS["cyan"] not in output


class TestSpinnerLogCoordination:
    """Verify _QuietStreamHandler hides/unhides the spinner around stderr writes."""

    class FakeSpinner:
        """Records hide/unhide calls in order."""

        enabled = True

        def __init__(self):
            self.calls = []

        def hide(self):
            self.calls.append("hide")

        def unhide(self):
            self.calls.append("unhide")

    def _make_handler(self):
        from llm.utils import _QuietStreamHandler

        handler = _QuietStreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        return handler

    def _make_record(self, msg="test log line"):
        return logging.LogRecord(
            "httpcore.http11",
            logging.DEBUG,
            "",
            0,
            msg,
            (),
            None,
        )

    def test_hide_unhide_called_around_emit(self):
        handler = self._make_handler()
        spinner = self.FakeSpinner()
        handler._spinner = spinner

        handler.emit(self._make_record())

        assert spinner.calls == ["hide", "unhide"]

    def test_unhide_called_on_write_exception(self):
        """unhide() must be called even if the stream write raises."""
        handler = self._make_handler()
        spinner = self.FakeSpinner()
        handler._spinner = spinner

        # Replace stream with one that raises on write
        class BadStream:
            def write(self, _):
                raise OSError("broken pipe")

            def flush(self):
                pass

        handler.stream = BadStream()
        handler.emit(self._make_record())

        assert spinner.calls == ["hide", "unhide"]

    def test_no_spinner_no_crash(self):
        """When _spinner is None, emit works normally without hiding."""
        handler = self._make_handler()
        buf = io.StringIO()
        handler.stream = buf

        assert handler._spinner is None
        handler.emit(self._make_record())

        assert buf.getvalue() == "test log line\n"

    def test_empty_message_skips_hide(self):
        """Empty messages are suppressed entirely — no hide/unhide needed."""
        handler = self._make_handler()
        spinner = self.FakeSpinner()
        handler._spinner = spinner

        class EmptyFormatter(logging.Formatter):
            def format(self, record):
                return ""

        handler.setFormatter(EmptyFormatter())

        handler.emit(self._make_record())

        assert spinner.calls == []

    def test_attach_registers_spinner_on_quiet_handlers(self):
        """_attach_log_handler sets _spinner on existing _QuietStreamHandler instances."""
        from llm.utils import _QuietStreamHandler

        handler = _QuietStreamHandler()
        logger = logging.getLogger("httpcore")
        logger.addHandler(handler)

        spinner = Spinner(enabled=True)
        try:
            spinner.start()
            assert handler._spinner is spinner
            spinner.stop()
            assert handler._spinner is None
        finally:
            spinner.stop()
            logger.removeHandler(handler)

    def test_detach_preserves_other_spinners_reference(self):
        """_detach_log_handler won't clear a reference belonging to a different spinner."""
        from llm.utils import _QuietStreamHandler

        handler = _QuietStreamHandler()
        logger = logging.getLogger("httpcore")
        logger.addHandler(handler)

        spinner_a = Spinner(enabled=True)
        spinner_b = Spinner(enabled=True)
        try:
            spinner_a.start()
            assert handler._spinner is spinner_a
            # Simulate spinner_b taking over (e.g. in chat mode, new prompt)
            handler._spinner = spinner_b
            # spinner_a stops — should NOT clear spinner_b's reference
            spinner_a.stop()
            assert (
                handler._spinner is spinner_b
            ), "detach cleared another spinner's reference"
        finally:
            spinner_a.stop()
            spinner_b.stop()
            handler._spinner = None
            logger.removeHandler(handler)

    def test_hide_unhide_surrounds_stderr_write(self):
        """Integration: hide() happens before stderr write, unhide() after."""
        from llm.utils import _QuietStreamHandler

        operations = []

        class RecordingStream:
            def write(self, data):
                operations.append(("stderr_write", data.strip()))

            def flush(self):
                pass

        class RecordingSpinner:
            enabled = True

            def hide(self):
                operations.append(("hide",))

            def unhide(self):
                operations.append(("unhide",))

        handler = _QuietStreamHandler(RecordingStream())
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler._spinner = RecordingSpinner()

        record = self._make_record("connect_tcp.started host='example.com'")
        handler.emit(record)

        assert len(operations) == 3
        assert operations[0] == ("hide",)
        assert operations[1][0] == "stderr_write"
        assert "connect_tcp" in operations[1][1]
        assert operations[2] == ("unhide",)
