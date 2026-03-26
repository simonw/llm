"""Message types and dataclass for the TUI layer.

Every piece of terminal output flows through the TUI as a ``Msg``.  Core
message types are defined by the ``MsgType`` enum.  Plugins can register
additional types via ``register_msg_type`` and provide a custom renderer;
unknown types fall back to plain text output.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Optional


class MsgType(enum.Enum):
    """Core message types understood by the TUI consumer."""

    CONTENT = "content"  # LLM response text chunk
    CONTENT_FINISH = "content_finish"  # Signal: stream ended, flush renderer
    EPHEMERAL = "ephemeral"  # Spinner/status (erased before next persistent write)
    HTTP_DEBUG = "http_debug"  # HTTP debug log record
    TOOL_STATUS = "tool_status"  # Tool calling/running status
    SEPARATOR = "separator"  # Blank line between sections
    ERROR = "error"  # Error display
    STOP = "stop"  # Poison pill: consumer thread exits


# Default output stream per MsgType.  "stdout" or "stderr".
# Per-message override via Msg.stream takes precedence.
STREAM_DEFAULTS: dict[MsgType, str] = {
    MsgType.CONTENT: "stdout",
    MsgType.CONTENT_FINISH: "stdout",
    MsgType.EPHEMERAL: "stdout",
    MsgType.HTTP_DEBUG: "stderr",
    MsgType.TOOL_STATUS: "stderr",
    MsgType.SEPARATOR: "stdout",
    MsgType.ERROR: "stderr",
    MsgType.STOP: "stdout",
}


# ── Plugin extension registry ────────────────────────────────────────

_plugin_types: dict[str, str] = {}


def register_msg_type(name: str) -> str:
    """Register a plugin message type.

    Returns *name* so callers can use it as the ``kind`` field in a ``Msg``.
    The TUI consumer renders unknown types as plain text to the default
    stream (stdout).
    """
    _plugin_types[name] = name
    return name


def is_registered(kind: MsgType | str) -> bool:
    """True if *kind* is a core type or a registered plugin type."""
    if isinstance(kind, MsgType):
        return True
    return kind in _plugin_types


# ── Message dataclass ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Msg:
    """A single unit of terminal output.

    Parameters
    ----------
    kind:
        Core ``MsgType`` or a plugin-registered string.
    text:
        The text payload.
    source:
        Origin identifier (e.g. ``"openai"``, ``"spinner"``, ``"plugin.foo"``).
    request_id:
        HTTP request identifier for correlating debug output.
    chunk_index:
        Sequential index within a streaming response.
    is_final:
        True for the last chunk of a streaming response.
    ts:
        Monotonic timestamp (for latency tracking, ordering).
    meta:
        Arbitrary key-value metadata for renderers.
    stream:
        Per-message output stream override.  ``None`` uses the default
        for this ``MsgType`` (see ``STREAM_DEFAULTS``).
    """

    kind: MsgType | str
    text: str = ""
    source: str = ""
    request_id: str = ""
    chunk_index: int = 0
    is_final: bool = False
    ts: float = field(default_factory=time.monotonic)
    meta: dict[str, Any] = field(default_factory=dict)
    stream: Optional[str] = None

    def resolve_stream(self) -> str:
        """Return the effective output stream for this message."""
        if self.stream is not None:
            return self.stream
        if isinstance(self.kind, MsgType):
            return STREAM_DEFAULTS.get(self.kind, "stdout")
        return "stdout"
