"""TUI abstraction layer for the llm CLI.

All terminal output flows through this package.  The ``TUI`` class owns a
message queue and a dedicated consumer thread that serializes writes,
eliminating the cursor-interleaving bugs that occur when multiple threads
(spinner, HTTP logging, streaming) write to the terminal concurrently.

Phase 1 exports only the foundation types.  The ``TUI`` controller class
is added in Phase 2 once the consumer and spinner are ready.
"""

from .messages import Msg, MsgType, register_msg_type, STREAM_DEFAULTS
from .terminal import Terminal, FakeTerminal

__all__ = [
    "Msg",
    "MsgType",
    "register_msg_type",
    "STREAM_DEFAULTS",
    "Terminal",
    "FakeTerminal",
]
