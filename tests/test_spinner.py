"""Tests for the TUI loading spinner."""

import io
import sys
import time

from tools.spinner import Spinner, SPINNER_STATES, SPINNERS


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
        required = {"label", "color", "spinner", "timeout", "persist_icon"}
        for name, cfg in SPINNER_STATES.items():
            assert required.issubset(cfg.keys()), f"State {name!r} missing keys"

    def test_all_spinners_have_required_keys(self):
        for name, cfg in SPINNERS.items():
            assert "frames" in cfg, f"Spinner {name!r} missing frames"
            assert "interval" in cfg, f"Spinner {name!r} missing interval"
            assert len(cfg["frames"]) >= 2, f"Spinner {name!r} needs >= 2 frames"

    def test_state_spinner_refs_are_valid(self):
        for name, cfg in SPINNER_STATES.items():
            assert cfg["spinner"] in SPINNERS, (
                f"State {name!r} references unknown spinner {cfg['spinner']!r}"
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

    def test_persist_default(self, monkeypatch):
        """Default: stop() writes a dim persist line instead of erasing."""
        monkeypatch.delenv("LLM_SPINNER_CLEAR", raising=False)
        monkeypatch.delenv("NO_COLOR", raising=False)
        s = Spinner(enabled=True)
        s.start()
        s.set_state("waiting")
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        s.stop()
        monkeypatch.undo()
        output = buf.getvalue()
        assert "⏳" in output
        assert "Waiting for response..." in output

    def test_clear_mode(self, monkeypatch):
        """LLM_SPINNER_CLEAR=1: stop() erases the spinner line."""
        monkeypatch.setenv("LLM_SPINNER_CLEAR", "1")
        s = Spinner(enabled=True)
        s.start()
        s.set_state("waiting")
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        s.stop()
        monkeypatch.undo()
        output = buf.getvalue()
        # Erase writes \r\033[K only — no persist icon
        assert "⏳" not in output

    def test_persist_icon_per_state(self):
        """Each state has a distinct persist_icon."""
        icons = {cfg["persist_icon"] for cfg in SPINNER_STATES.values()}
        assert len(icons) == len(SPINNER_STATES), "persist_icon values should be unique"
