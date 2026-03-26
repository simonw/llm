"""Pure spinner state machine for the TUI layer.

``SpinnerState`` holds animation state (current frame, label, timing) but
does NOT own a thread or write to the terminal.  The TUI consumer thread
calls ``advance_frame()`` on each tick to get the next ANSI-formatted
frame string, then writes it via the ``Terminal`` abstraction.

This replaces the old ``tools.spinner.Spinner`` class which combined
state, threading, and IO into one object.
"""

from __future__ import annotations

import os
import time
import threading
from typing import Any

from .terminal import RESET, DIM

# ── Spinner frame sequences (ported from tools/spinner.py) ───────────

SPINNERS: dict[str, dict[str, Any]] = {
    "toggle3": {
        "frames": ["\u25a1", "\u25a0"],
        "persist": "\u25e6",
        "interval": 0.12,
    },
    "dots": {
        "frames": [
            "\u280b",
            "\u2819",
            "\u2839",
            "\u2838",
            "\u283c",
            "\u2834",
            "\u2826",
            "\u2827",
            "\u2807",
            "\u280f",
        ],
        "persist": "\u2022",
        "interval": 0.08,
    },
    "line": {
        "frames": ["-", "\\", "|", "/"],
        "persist": "\u2502",
        "interval": 0.13,
    },
    "dot": {
        "frames": ["\u25cf", " "],
        "persist": "\u25cf",
        "interval": 0.25,
    },
}

DEFAULT_SPINNER = "dot"

# ── ANSI color codes ─────────────────────────────────────────────────

COLORS: dict[str, str] = {
    "cyan": "\033[36m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "red": "\033[31m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
}

# ── State definitions ────────────────────────────────────────────────

SPINNER_STATES: dict[str, dict[str, Any]] = {
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


# ── SpinnerState ─────────────────────────────────────────────────────


class SpinnerState:
    """Pure state machine for spinner animation.

    Thread-safe: ``set_state`` can be called from any thread.  The
    consumer thread calls ``advance_frame()`` to get the next rendered
    string.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._lock = threading.Lock()
        self._state: str | None = None
        self._state_kwargs: dict[str, str] = {}
        self._state_entered_at: float = 0.0
        self._frame_idx: int = 0
        self._use_color: bool = not os.environ.get("NO_COLOR")

    # ── Public API ────────────────────────────────────────────────

    def set_state(self, name: str | None, **kwargs: str) -> None:
        """Change the spinner state.  Thread-safe.

        Pass ``None`` to deactivate the spinner.
        """
        if not self.enabled:
            return
        with self._lock:
            if name is None:
                self._state = None
                return
            # Only reset frame index when the spinner definition changes
            # (e.g. "dot" -> "dots").  Same spinner across states keeps
            # the animation smooth during rapid transitions.
            old_spinner = SPINNER_STATES.get(self._state or "", {}).get(
                "spinner", DEFAULT_SPINNER
            )
            new_spinner = SPINNER_STATES.get(name, {}).get("spinner", DEFAULT_SPINNER)
            if old_spinner != new_spinner:
                self._frame_idx = 0
            self._state = name
            self._state_kwargs = dict(kwargs)
            self._state_entered_at = time.monotonic()

    def advance_frame(self) -> str | None:
        """Return the next ANSI-formatted frame string, or None if inactive.

        Called by the consumer thread on each tick.  Advances the frame
        counter internally.
        """
        with self._lock:
            if self._state is None:
                return None
            cfg = SPINNER_STATES.get(self._state)
            if cfg is None:
                return None

            spinner_name = cfg.get("spinner", DEFAULT_SPINNER)
            spinner_def = SPINNERS.get(spinner_name, SPINNERS[DEFAULT_SPINNER])
            frames = spinner_def["frames"]
            frame = frames[self._frame_idx % len(frames)]
            self._frame_idx += 1

            label = cfg["label"].format(**self._state_kwargs)

            # Stale indicator
            elapsed = time.monotonic() - self._state_entered_at
            timeout = cfg.get("timeout", 30)
            if elapsed > timeout:
                label += f" {DIM}(stale){RESET}" if self._use_color else " (stale)"

            if self._use_color:
                color = COLORS.get(cfg.get("color", "cyan"), COLORS["cyan"])
                return f"{color}{frame}{RESET} {DIM}{label}{RESET}"
            return f"{frame} {label}"

    def current_interval(self) -> float:
        """Return the animation interval in seconds for the current state."""
        with self._lock:
            if self._state is None:
                return 0.25  # Default idle interval
            cfg = SPINNER_STATES.get(self._state, {})
            spinner_name = cfg.get("spinner", DEFAULT_SPINNER)
            return SPINNERS.get(spinner_name, SPINNERS[DEFAULT_SPINNER])["interval"]

    @property
    def is_active(self) -> bool:
        """True if the spinner has an active state."""
        with self._lock:
            return self._state is not None

    @property
    def state_name(self) -> str | None:
        """Current state name (for testing/debugging)."""
        with self._lock:
            return self._state
