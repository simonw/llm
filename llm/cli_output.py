"""Output and rendering helpers extracted from cli.py.

This module contains the TUI integration layer: functions for creating
a TUI instance, wrapping tool callbacks for spinner state, and the
legacy ``_ColorWriter`` retained for backward compatibility.
"""

from __future__ import annotations

from tui import TUI


def create_tui(color_mode: str | None, force: bool = False) -> TUI:
    """Create and return a TUI instance configured for the current terminal.

    Parameters
    ----------
    color_mode:
        ``"mdstream"`` for markdown rendering, ``None`` for plain.
    force:
        Treat non-TTY as TTY (for testing / LLM_TUI_FORCE).
    """
    return TUI(color=color_mode, force=force)


def wrap_tool_callbacks_for_tui(kwargs: dict, tui: TUI) -> None:
    """Wrap before_call / after_call in *kwargs* to drive TUI spinner state.

    Replaces the old ``_wrap_tool_callbacks_for_spinner``.
    """
    original_before = kwargs.get("before_call")
    original_after = kwargs.get("after_call")

    def tui_before_call(tool, tool_call):
        tui.spinner_set_state("tool_calling", tool_name=tool_call.name)
        if not tui.is_started:
            tui.spinner_start()
        if original_before:
            return original_before(tool, tool_call)

    def tui_after_call(tool, tool_call, tool_result):
        tui.spinner_set_state("starting")
        if original_after:
            return original_after(tool, tool_call, tool_result)

    kwargs["before_call"] = tui_before_call
    kwargs["after_call"] = tui_after_call
