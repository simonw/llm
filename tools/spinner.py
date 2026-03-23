"""
TUI loading spinner for the llm CLI.

Shows a single-line animated spinner with contextual state labels while
the CLI waits for network responses, tool execution, etc.  The spinner
writes to stdout via ``\\r\\033[K`` (carriage return + clear to EOL) so it
never pollutes scrollback.

Usage::

    spinner = Spinner(enabled=sys.stdout.isatty())
    spinner.start()                          # shows "□ Starting..."
    spinner.set_state("connecting")          # shows "■ Connecting..."
    spinner.stop()                           # erases line, joins thread

The spinner is thread-safe: ``set_state`` can be called from any thread
(e.g. a logging handler watching httpcore events).
"""

import os
import sys
import threading
import time


# ── Spinner frame sequences ────────────────────────────────────────────

SPINNERS = {
    "toggle3": {
        "frames": ["□", "■"],
        "interval": 0.12,
    },
    "dots": {
        "frames": ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
        "interval": 0.08,
    },
    "line": {
        "frames": ["-", "\\", "|", "/"],
        "interval": 0.13,
    },
}

DEFAULT_SPINNER = "toggle3"


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
        "spinner": "toggle3",
        "timeout": 10,
        "persist_icon": "·",
    },
    "connecting": {
        "label": "Connecting...",
        "color": "cyan",
        "spinner": "toggle3",
        "timeout": 10,
        "persist_icon": "⚡",
    },
    "waiting": {
        "label": "Waiting for response...",
        "color": "cyan",
        "spinner": "toggle3",
        "timeout": 30,
        "persist_icon": "⏳",
    },
    "tool_calling": {
        "label": "Calling {tool_name}...",
        "color": "yellow",
        "spinner": "toggle3",
        "timeout": 30,
        "persist_icon": "🔧",
    },
    "tool_running": {
        "label": "Running {tool_name}...",
        "color": "yellow",
        "spinner": "toggle3",
        "timeout": 60,
        "persist_icon": "⚙",
    },
}


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
        self._should_clear = bool(os.environ.get("LLM_SPINNER_CLEAR"))
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

        By default the last state is persisted as a dim static line in
        scrollback.  Set ``LLM_SPINNER_CLEAR=1`` to erase instead.

        Idempotent — safe to call multiple times or on a stopped spinner.
        """
        if not self.enabled:
            return
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=1.0)
        if self._should_clear:
            self._erase()
        else:
            self._persist()
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
            self._state = name
            self._state_kwargs = kwargs
            self._state_entered_at = time.monotonic()
            self._frame_idx = 0
            self._hidden = False
            # Render immediately so the user sees the transition
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

    _LOG_TARGETS = ("httpcore", "openai", "anthropic")

    def _attach_log_handler(self) -> None:
        """Add a SpinnerLogHandler to HTTP loggers for auto state transitions."""
        import logging
        from llm.utils import SpinnerLogHandler

        self._log_handler = SpinnerLogHandler(self)
        for name in self._LOG_TARGETS:
            logger = logging.getLogger(name)
            logger.addHandler(self._log_handler)
            # Ensure DEBUG events reach us even if HTTP debug is off
            if logger.level == 0 or logger.level > logging.DEBUG:
                self._original_levels[name] = logger.level
                logger.setLevel(logging.DEBUG)

    def _detach_log_handler(self) -> None:
        """Remove the SpinnerLogHandler and restore original log levels."""
        import logging

        if self._log_handler is None:
            return
        for name in self._LOG_TARGETS:
            logger = logging.getLogger(name)
            logger.removeHandler(self._log_handler)
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
        icon = cfg.get("persist_icon", ">")
        label = cfg["label"].format(**self._state_kwargs)
        try:
            if self._use_color:
                line = f"{ERASE_LINE}{DIM}{icon} {label}{RESET}\n"
            else:
                line = f"{ERASE_LINE}{icon} {label}\n"
            sys.stdout.write(line)
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            pass

    def _erase(self) -> None:
        """Clear the spinner line from the terminal."""
        try:
            sys.stdout.write(ERASE_LINE)
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            pass
