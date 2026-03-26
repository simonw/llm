"""
TUI loading spinner for the llm CLI.

Shows a single-line animated spinner with contextual state labels while
the CLI waits for network responses, tool execution, etc.  The spinner
writes to stdout via ``\\r\\033[K`` (carriage return + clear to EOL) so it
never pollutes scrollback.  When HTTP debug logging is active, the spinner
coordinates with ``_QuietStreamHandler`` via ``hide()``/``unhide()`` so that
stderr log lines don't strand spinner frames in scrollback.

Usage::

    spinner = Spinner(enabled=sys.stdout.isatty())
    spinner.start()                          # shows "□ Starting..."
    spinner.set_state("connecting")          # shows "■ Connecting..."
    spinner.stop()                           # clears by default; can persist via env

The spinner is thread-safe: ``set_state`` can be called from any thread
(e.g. a logging handler watching structured TUI lifecycle events).
"""

import os
import sys
import threading
import time

# ── Spinner frame sequences ────────────────────────────────────────────

SPINNERS = {
    "toggle3": {
        "frames": ["□", "■"],
        "persist": "◦",
        "interval": 0.12,
    },
    "dots": {
        "frames": ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
        "persist": "•",
        "interval": 0.08,
    },
    "line": {
        "frames": ["-", "\\", "|", "/"],
        "persist": "│",
        "interval": 0.13,
    },
    "dot": {
        "frames": ["●", " "],
        "persist": "●",
        "interval": 0.25,
    },
}

DEFAULT_SPINNER = "dot"


# ── ANSI helpers ───────────────────────────────────────────────────────

ERASE_LINE = "\r\033[K"
RESET = "\033[0m"
DIM = "\033[2m"

COLORS = {
    "cyan": "\033[36m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "red": "\033[31m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
}


# ── State definitions ──────────────────────────────────────────────────
#
# Each state has:
#   label    — format string (may contain {tool_name} etc.)
#   color    — ANSI color name for the spinner icon
#   spinner  — key into SPINNERS dict
#   timeout  — seconds before "(stale)" suffix appears

SPINNER_STATES = {
    "starting": {
        "label": "Starting...",
        "color": "cyan",
        "timeout": 10,
    },
    "connecting": {
        "label": "Connecting...",
        "color": "green",
        "timeout": 10,
    },
    "waiting": {
        "label": "Waiting for response...",
        "color": "yellow",
        "timeout": 30,
    },
    "tool_calling": {
        "label": "Calling {tool_name}...",
        "color": "green",
        "timeout": 30,
    },
    "tool_running": {
        "label": "Running {tool_name}...",
        "color": "green",
        "timeout": 60,
    },
}

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _should_persist_spinner() -> bool:
    if "LLM_SPINNER_PERSIST" in os.environ:
        return _env_flag("LLM_SPINNER_PERSIST", default=False)
    if "LLM_SPINNER_CLEAR" in os.environ:
        return not _env_flag("LLM_SPINNER_CLEAR", default=False)
    raw_http_debug = (os.environ.get("LLM_HTTP_DEBUG") or "").strip()
    try:
        return int(raw_http_debug) >= 2
    except ValueError:
        return False


# ── Spinner class ──────────────────────────────────────────────────────


class Spinner:
    """Thread-based terminal spinner with state-driven labels.

    Parameters
    ----------
    enabled : bool
        When False every method is a silent no-op.  Use this to skip the
        spinner when stdout is not a TTY or color is disabled.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._state = None
        self._state_kwargs = {}
        self._state_entered_at = 0.0
        self._hidden = False
        self._frame_idx = 0
        self._use_color = not os.environ.get("NO_COLOR")
        self._persist_on_stop = _should_persist_spinner()
        self._persist_text = os.environ.get("LLM_SPINNER_PERSIST_TEXT")
        self._padding_before = _env_int(
            "LLM_SPINNER_PADDING_BEFORE", 1 if self._persist_on_stop else 0
        )
        self._padding_after = _env_int(
            "LLM_SPINNER_PADDING_AFTER", 1 if self._persist_on_stop else 0
        )
        self._log_handler = None
        self._original_levels = {}

    # ── Public API ─────────────────────────────────────────────────

    def start(self, leading_newline: bool = False) -> None:
        """Start the animation thread.  First state is ``starting``.

        Parameters
        ----------
        leading_newline : bool
            If True, prepend ``\\n`` to the very first frame so the blank
            line and the spinner icon appear as one atomic write (no
            visible cursor jump).
        """
        if not self.enabled:
            return
        self._stop_event.clear()
        self._hidden = False
        self._frame_idx = 0
        self._leading_newline = leading_newline
        self.set_state("starting")
        self._attach_log_handler()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the spinner and join the animation thread.

        By default the spinner clears on stop.  Set
        ``LLM_SPINNER_PERSIST=1`` to keep a static line in scrollback.
        ``LLM_HTTP_DEBUG=2`` enables persistence by default so verbose
        request/response blocks keep their request-phase markers.
        ``LLM_SPINNER_CLEAR`` is supported as a legacy inverse alias.

        Idempotent — safe to call multiple times or on a stopped spinner.
        """
        if not self.enabled:
            return
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=1.0)
        if self._persist_on_stop:
            self._persist()
        else:
            self._erase(leave_blank_line=True)
        self._detach_log_handler()
        self._thread = None
        self._state = None

    def set_state(self, name: str, **kwargs) -> None:
        """Change the spinner state.  Thread-safe.

        Parameters
        ----------
        name : str
            Key into ``SPINNER_STATES``.
        **kwargs :
            Format parameters for the label template (e.g. ``tool_name``).
        """
        if not self.enabled:
            return
        with self._lock:
            # Only reset the frame index when the spinner definition changes
            # (e.g. switching from "dot" to "dots").  When the same spinner
            # is used across states, the animation continues smoothly and
            # rapid state changes don't restart it.
            old_spinner = SPINNER_STATES.get(self._state, {}).get(
                "spinner", DEFAULT_SPINNER
            )
            new_spinner = SPINNER_STATES.get(name, {}).get("spinner", DEFAULT_SPINNER)
            if old_spinner != new_spinner:
                self._frame_idx = 0
            self._state = name
            self._state_kwargs = kwargs
            self._state_entered_at = time.monotonic()
            self._hidden = False
            # Render immediately so the user sees the label transition
            # without waiting up to one interval.
            self._render_frame()

    def hide(self) -> None:
        """Erase the spinner line without stopping the thread."""
        if not self.enabled:
            return
        with self._lock:
            self._hidden = True
        self._erase()

    def unhide(self) -> None:
        """Re-show the spinner after a ``hide()`` call."""
        if not self.enabled:
            return
        with self._lock:
            self._hidden = False

    @property
    def is_running(self) -> bool:
        """True if the animation thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    # ── Log handler for automatic state transitions ──────────────

    _LOG_TARGETS = ("llm.http", "httpcore", "openai", "anthropic")

    def _attach_log_handler(self) -> None:
        """Add a SpinnerLogHandler to HTTP loggers for auto state transitions."""
        import logging
        from llm.utils import SpinnerLogHandler, _QuietStreamHandler

        self._log_handler = SpinnerLogHandler(self)
        for name in self._LOG_TARGETS:
            logger = logging.getLogger(name)
            logger.addHandler(self._log_handler)
            # Register on existing stream handlers so they hide/unhide
            # the spinner around stderr writes, preventing scrollback pollution.
            for h in logger.handlers:
                if isinstance(h, _QuietStreamHandler):
                    h._spinner = self
            # Ensure DEBUG events reach us even if HTTP debug is off
            if logger.level == 0 or logger.level > logging.DEBUG:
                self._original_levels[name] = logger.level
                logger.setLevel(logging.DEBUG)

    def _detach_log_handler(self) -> None:
        """Remove the SpinnerLogHandler and restore original log levels."""
        import logging
        from llm.utils import _QuietStreamHandler

        if self._log_handler is None:
            return
        for name in self._LOG_TARGETS:
            logger = logging.getLogger(name)
            logger.removeHandler(self._log_handler)
            # Unregister only if we are the current spinner (avoid clearing
            # a reference to a different spinner instance).
            for h in logger.handlers:
                if isinstance(h, _QuietStreamHandler) and h._spinner is self:
                    h._spinner = None
            if name in self._original_levels:
                logger.setLevel(self._original_levels[name])
        self._original_levels.clear()
        self._log_handler = None

    # ── Animation thread ───────────────────────────────────────────

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    if not self._hidden and self._state is not None:
                        self._render_frame()
                        self._frame_idx += 1
                # Sleep via Event.wait so stop() can interrupt immediately
                self._stop_event.wait(self._current_interval())
        finally:
            # Belt-and-suspenders: erase if thread exits unexpectedly
            self._erase()

    def _current_interval(self) -> float:
        with self._lock:
            if self._state is None:
                return 0.12
            cfg = SPINNER_STATES.get(self._state, {})
            spinner_name = cfg.get("spinner", DEFAULT_SPINNER)
            return SPINNERS.get(spinner_name, SPINNERS[DEFAULT_SPINNER])["interval"]

    # ── Rendering ──────────────────────────────────────────────────

    def _render_frame(self) -> None:
        """Write one spinner frame to stdout.  Must be called with lock held."""
        cfg = SPINNER_STATES.get(self._state)
        if cfg is None:
            return

        spinner_name = cfg.get("spinner", DEFAULT_SPINNER)
        spinner_def = SPINNERS.get(spinner_name, SPINNERS[DEFAULT_SPINNER])
        frames = spinner_def["frames"]
        frame = frames[self._frame_idx % len(frames)]

        # Build the label
        label = cfg["label"].format(**self._state_kwargs)

        # Stale indicator
        elapsed = time.monotonic() - self._state_entered_at
        timeout = cfg.get("timeout", 30)
        if elapsed > timeout:
            label += f" {DIM}(stale){RESET}" if self._use_color else " (stale)"

        # Optional leading newline on the very first frame so the blank
        # line and spinner icon appear as one atomic stdout write.
        prefix = ""
        if getattr(self, "_leading_newline", False):
            prefix = "\n"
            self._leading_newline = False

        # Format: [colored icon] [dim label]
        if self._use_color:
            color = COLORS.get(cfg.get("color", "cyan"), COLORS["cyan"])
            line = f"{prefix}{ERASE_LINE}{color}{frame}{RESET} {DIM}{label}{RESET}"
        else:
            line = f"{prefix}{ERASE_LINE}{frame} {label}"

        try:
            sys.stdout.write(line)
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            # stdout closed (e.g. piped to head), stop gracefully
            self._stop_event.set()

    def _persist(self) -> None:
        """Replace the animated spinner with a dim static line in scrollback."""
        cfg = SPINNER_STATES.get(self._state)
        if not cfg:
            self._erase()
            return
        spinner_name = cfg.get("spinner", DEFAULT_SPINNER)
        spinner_def = SPINNERS.get(spinner_name, SPINNERS[DEFAULT_SPINNER])
        label = cfg["label"].format(**self._state_kwargs)
        padding_before = "\n" * self._padding_before
        padding_after = "\n" * self._padding_after
        persist_text = self._persist_text
        if persist_text is None:
            persist_text = spinner_def.get("persist", spinner_def["frames"][0])
        line_body = f"{persist_text} {label}".strip() if persist_text else label
        try:
            if self._use_color:
                line = (
                    f"{ERASE_LINE}{padding_before}"
                    f"{DIM}{line_body}{RESET}\n{padding_after}"
                )
            else:
                line = f"{ERASE_LINE}{padding_before}{line_body}\n{padding_after}"
            sys.stdout.write(line)
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            pass

    def _erase(self, leave_blank_line: bool = False) -> None:
        """Clear the spinner line from the terminal."""
        try:
            suffix = "\n" if leave_blank_line else ""
            sys.stdout.write(f"{ERASE_LINE}{suffix}")
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            pass
