"""Tests for the TUI loading spinner."""

import io
import sys
import time

from tools.spinner import COLORS, DEFAULT_SPINNER, DIM, RESET, Spinner, SPINNER_STATES, SPINNERS


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
            assert spinner_ref in SPINNERS, (
                f"State {name!r} references unknown spinner {spinner_ref!r}"
            )


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


class TestSpinnerPersist:
    """Persist vs clear behavior on stop()."""

    def test_clear_default(self, monkeypatch):
        """Without HTTP debug, stop() clears the spinner instead of persisting it."""
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
        assert output.endswith("\n")

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

    def test_http_debug_2_persists_by_default(self, monkeypatch):
        monkeypatch.delenv("LLM_SPINNER_PERSIST", raising=False)
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
        assert f"\n{SPINNERS[DEFAULT_SPINNER]['persist']} Waiting for response...\n\n" in output

    def test_http_debug_2_persist_can_be_opted_out(self, monkeypatch):
        monkeypatch.setenv("LLM_HTTP_DEBUG", "2")
        monkeypatch.setenv("LLM_SPINNER_PERSIST", "0")
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
        assert output.endswith("\n")

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

    def test_persisted_symbol_uses_dim_text_style_without_spinner_color(self, monkeypatch):
        monkeypatch.setenv("LLM_HTTP_DEBUG", "2")
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
