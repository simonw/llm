import ast
import click
import contextlib
import hashlib
import httpx
import itertools
import json
import logging
import pathlib
import puremagic
import re
import sqlite_utils
import textwrap
from typing import Any, List, Dict, Optional, Tuple, Type
import os
import threading
import time
from typing import Final

from ulid import ULID

MIME_TYPE_FIXES = {
    "audio/wave": "audio/wav",
}


class Fragment(str):
    def __new__(cls, content, *args, **kwargs):
        # For immutable classes like str, __new__ creates the string object
        return super().__new__(cls, content)

    def __init__(self, content, source=""):
        # Initialize our custom attributes
        self.source = source

    def id(self):
        return hashlib.sha256(self.encode("utf-8")).hexdigest()


def mimetype_from_string(content) -> Optional[str]:
    try:
        type_ = puremagic.from_string(content, mime=True)
        return MIME_TYPE_FIXES.get(type_, type_)
    except puremagic.PureError:
        return None


def mimetype_from_path(path) -> Optional[str]:
    try:
        type_ = puremagic.from_file(path, mime=True)
        return MIME_TYPE_FIXES.get(type_, type_)
    except puremagic.PureError:
        return None


def dicts_to_table_string(
    headings: List[str], dicts: List[Dict[str, str]]
) -> List[str]:
    max_lengths = [len(h) for h in headings]

    # Compute maximum length for each column
    for d in dicts:
        for i, h in enumerate(headings):
            if h in d and len(str(d[h])) > max_lengths[i]:
                max_lengths[i] = len(str(d[h]))

    # Generate formatted table strings
    res = []
    res.append("    ".join(h.ljust(max_lengths[i]) for i, h in enumerate(headings)))

    for d in dicts:
        row = []
        for i, h in enumerate(headings):
            row.append(str(d.get(h, "")).ljust(max_lengths[i]))
        res.append("    ".join(row))

    return res


def remove_dict_none_values(d):
    """
    Recursively remove keys with value of None or value of a dict that is all values of None
    """
    if not isinstance(d, dict):
        return d
    new_dict = {}
    for key, value in d.items():
        if value is not None:
            if isinstance(value, dict):
                nested = remove_dict_none_values(value)
                if nested:
                    new_dict[key] = nested
            elif isinstance(value, list):
                new_dict[key] = [remove_dict_none_values(v) for v in value]
            else:
                new_dict[key] = value
    return new_dict


class _LogResponse(httpx.Response):
    def iter_bytes(self, *args, **kwargs):
        for chunk in super().iter_bytes(*args, **kwargs):
            click.echo(chunk.decode(), err=True)
            yield chunk


class _LogTransport(httpx.BaseTransport):
    def __init__(self, transport: httpx.BaseTransport):
        self.transport = transport

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.transport.handle_request(request)
        return _LogResponse(
            status_code=response.status_code,
            headers=response.headers,
            stream=response.stream,
            extensions=response.extensions,
        )


def _no_accept_encoding(request: httpx.Request):
    request.headers.pop("accept-encoding", None)


def _log_response(response: httpx.Response):
    request = response.request
    click.echo(f"Request: {request.method} {request.url}", err=True)
    click.echo("  Headers:", err=True)
    for key, value in request.headers.items():
        if key.lower() == "authorization":
            value = "[...]"
        if key.lower() == "cookie":
            value = value.split("=")[0] + "=..."
        click.echo(f"    {key}: {value}", err=True)
    click.echo("  Body:", err=True)
    try:
        request_body = json.loads(request.content)
        click.echo(
            textwrap.indent(json.dumps(request_body, indent=2), "    "), err=True
        )
    except json.JSONDecodeError:
        click.echo(textwrap.indent(request.content.decode(), "    "), err=True)
    click.echo(f"Response: status_code={response.status_code}", err=True)
    click.echo("  Headers:", err=True)
    for key, value in response.headers.items():
        if key.lower() == "set-cookie":
            value = value.split("=")[0] + "=..."
        click.echo(f"    {key}: {value}", err=True)
    click.echo("  Body:", err=True)


def logging_client() -> httpx.Client:
    return httpx.Client(
        transport=_LogTransport(httpx.HTTPTransport()),
        event_hooks={"request": [_no_accept_encoding], "response": [_log_response]},
    )

def _log_request_tui(request: httpx.Request):
    """Log request details to llm.http logger for TUI display."""
    logger = logging.getLogger("llm.http")
    if logger.isEnabledFor(logging.DEBUG):
        # Generate request ID for correlation and start timing
        request_id = _get_request_id()
        _start_request_timer(request_id)

        # Format as a special marker that HTTPColorFormatter can parse
        data = {
            "request_id": request_id,
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers)
        }
        logger.debug(f"TUI Request: {json.dumps(data)}")

def tui_logging_client() -> httpx.Client:
    return httpx.Client(
        event_hooks={"request": [_log_request_tui]}
    )

async def _log_request_tui_async(request: httpx.Request):
    _log_request_tui(request)

def async_tui_logging_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        event_hooks={"request": [_log_request_tui_async]}
    )



# --- Universal HTTP Logging System ---

# Thread-local storage for request timing correlation
_request_context = threading.local()

# Thread-local storage for request ID correlation in the formatter.
# Stored per-thread (not on the formatter instance) so concurrent
# requests on different threads each see their own ID.
_formatter_request_id = threading.local()


def _get_request_id() -> str:
    """Generate a short request ID for correlation."""
    if not hasattr(_request_context, 'counter'):
        _request_context.counter = 0
    _request_context.counter += 1
    return f"req-{_request_context.counter:03d}"


def _start_request_timer(request_id: str) -> None:
    """Record start time for a request."""
    if not hasattr(_request_context, 'timings'):
        _request_context.timings = {}
    _request_context.timings[request_id] = time.time()


def _get_request_elapsed(request_id: str) -> Optional[float]:
    """Get elapsed time in milliseconds for a request."""
    if not hasattr(_request_context, 'timings'):
        return None
    start = _request_context.timings.get(request_id)
    if start is None:
        return None
    elapsed_ms = (time.time() - start) * 1000
    # Clean up old timing
    del _request_context.timings[request_id]
    return elapsed_ms


class _QuietStreamHandler(logging.StreamHandler):
    """StreamHandler that suppresses empty messages.

    Python's default StreamHandler always writes ``msg + "\\n"``, even
    when *msg* is empty.  This produces phantom blank lines on stderr
    that displace the terminal cursor and break mdstream's in-place
    re-rendering.  This handler skips the write entirely when the
    formatted message is empty.
    """

    def emit(self, record):
        msg = self.format(record)
        if not msg:
            return
        try:
            self.stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)


class SafeHTTPCoreFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()

        # Suppress openai's "Sending HTTP Request" (redundant with Request options)
        if (
            record.name == "openai._base_client"
            and message.startswith("Sending HTTP Request")
        ):
            return False

        # Suppress httpx response logs - OpenAI SDK logs them better
        if record.name.startswith("httpx") and "HTTP Request:" in message:
            return False

        if record.name.startswith("httpcore"):
            # httpcore emits lifecycle event pairs (.started / .complete) for
            # each phase of an HTTP exchange.  We selectively allow events that
            # map to the four user-visible lifecycle markers:
            #
            #   ↓ Response        ← from openai SDK (receive_response_headers)
            #   ▼ Stream Start    ← receive_response_body.started
            #   ■ Stream End      ← receive_response_body.complete
            #   ✓ Response Complete ← response_closed.complete
            #
            # Everything else is noise and gets suppressed here so the
            # handler never emits a phantom "\n" for empty formatted output.

            # Allow stream lifecycle markers through
            if "response_body.started" in message:
                return True
            if "response_body.complete" in message:
                return True
            if "response_closed.complete" in message:
                return True

            # Suppress all other body events (raw data)
            if "request_body" in message or "response_body" in message:
                return False

            # Suppress response headers from httpcore (OpenAI SDK logs them)
            if "receive_response_headers" in message:
                return False

            # Suppress all other .complete events (redundant with .started)
            if ".complete" in message:
                return False

            # Suppress response_closed.started (we show .complete instead)
            if "response_closed.started" in message:
                return False

        return True


class HTTPColorFormatter(logging.Formatter):
    """
    Custom formatter for HTTP logging with colors and improved readability.

    Design decisions:
    - Records with no structured body are suppressed (e.g. bare
      "[timestamp] openai._base_client" headers are noise).
    - Every record with body content gets a leading blank line so
      sections don't appear packed together.
    - The "Response Complete" banner (from httpcore response_closed.complete)
      skips the "[timestamp] httpcore.http11" header — it adds no information
      and would appear on the same line as the last streamed chunk since
      stdout (stream) and stderr (logging) share the terminal.
    - The banner can be deferred via buffered_stream_end() so that
      mdstream's finish() re-render completes before the banner prints,
      preventing the last streamed line from being duplicated.
    - Headers are normalized from both dict (OpenAI SDK) and list-of-tuples
      (httpcore) formats via _headers_to_dict().
    - All section content uses zero extra indent — the gutter (│) already
      provides visual nesting.
    """

    # ANSI color codes
    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",  # Reset
        "BOLD": "\033[1m",  # Bold
        "DIM": "\033[2m",  # Dim
        "BLUE": "\033[34m",
        "CYAN": "\033[36m",
        "GREEN": "\033[32m",
        "MAGENTA": "\033[35m",
        "YELLOW": "\033[33m",
        "WHITE": "\033[37m",
    }

    # Logger-specific colors
    LOGGER_COLORS = {
        "httpx": "\033[94m",  # Light blue
        "httpcore": "\033[90m",  # Dark gray
        "openai": "\033[92m",  # Light green
        "anthropic": "\033[95m",  # Light magenta
        "llm.http": "\033[96m",  # Light cyan
    }

    # Box drawing characters
    BOX = {
        "tl": "╭", "tr": "╮", "bl": "╰", "br": "╯",
        "h": "─", "v": "│",
        "vr": "├", "vl": "┤", "ht": "┬", "hb": "┴",
    }

    def __init__(self, use_colors=True):
        super().__init__()
        self.use_colors = use_colors and self._supports_color()
        self.show_gutter = not os.environ.get("LLM_HTTP_UI_MINIMAL")
        self._current_request_id = ""

    def _supports_color(self):
        """Check if the terminal supports color output."""
        import os
        import sys

        if hasattr(sys.stderr, "isatty") and sys.stderr.isatty():
            term = os.environ.get("TERM", "")
            if "color" in term or term in ("xterm", "xterm-256color", "screen", "tmux"):
                return True
            if os.environ.get("NO_COLOR"):
                return False
            return True
        return False

    def format(self, record):
        if not self.use_colors:
            if self._is_stream_end(record) and self._defer_stream_end:
                formatted = self._format_plain(record)
                HTTPColorFormatter._pending_stream_end.append(formatted)
                return ""
            return self._format_plain(record)

        # Lifecycle markers render as standalone banner lines without the
        # "[timestamp] httpcore.http11" header — that's noise for the user.
        if self._is_stream_start(record):
            body = self._structured_message(record, colored=True)
            return f"\n{body}" if body else ""

        # Post-stream markers (Stream End, Response Complete) are also
        # headerless, and are deferred when mdstream is active.
        if self._is_stream_end(record):
            body = self._structured_message(record, colored=True)
            formatted = f"\n{body}" if body else ""
            if self._defer_stream_end:
                HTTPColorFormatter._pending_stream_end.append(formatted)
                return ""
            return formatted

        header = self._format_header(record, colored=True)
        body = self._structured_message(record, colored=True)

        # Suppress records with no structured body — a bare
        # "[timestamp] openai._base_client" header is noise.
        if not body:
            return ""

        # Add a blank line before every record with body content so
        # sections don't appear packed together in the terminal.
        return f"\n{header}\n{body}"

    # When True, the formatter buffers post-stream markers (Stream End
    # and Response Complete) instead of emitting them immediately.  This
    # prevents stderr output from displacing the terminal cursor between
    # the last streamed chunk and mdstream's finish() re-render, which
    # would duplicate the last line.
    _defer_stream_end = False
    _pending_stream_end: list = []

    @classmethod
    def defer_stream_end(cls, defer=True):
        cls._defer_stream_end = defer
        if not defer:
            cls._pending_stream_end = []

    @classmethod
    def flush_stream_end(cls):
        msgs = cls._pending_stream_end
        cls._pending_stream_end = []
        return msgs

    def _is_stream_start(self, record):
        """Check if this record is the Stream Start marker."""
        return (
            record.name.startswith("httpcore")
            and "response_body.started" in record.getMessage()
        )

    def _is_stream_end(self, record):
        """Check if this record is a post-stream lifecycle marker.

        Both response_body.complete (Stream End) and
        response_closed.complete (Response Complete) fire after the last
        chunk has been received, during iterator cleanup.  Both need to
        be deferred when mdstream is active so they don't displace the
        cursor before finish() re-renders the last line.
        """
        if not record.name.startswith("httpcore"):
            return False
        msg = record.getMessage()
        return "response_body.complete" in msg or "response_closed.complete" in msg


    def _format_plain(self, record):
        """Plain formatting without colors."""
        if self._is_stream_start(record) or self._is_stream_end(record):
            body = self._structured_message(record, colored=False)
            return f"\n{body}" if body else ""
        header = self._format_header(record, colored=False)
        body = self._structured_message(record, colored=False)
        if not body:
            return ""
        return f"\n{header}\n{body}"

    def _colorize_message(self, message, logger_name):
        """Add color highlights to generic message content."""
        if not self.use_colors:
            return message
        # Basic highlighting for unstructured messages
        return message

    def _format_header(self, record, *, colored: bool) -> str:
        timestamp = self.formatTime(record, "%H:%M:%S")
        timestamp = f"{timestamp}.{int(record.msecs):03d}"
        logger_root = record.name.split(".")[0]

        if colored:
            reset = self.COLORS["RESET"]
            dim = self.COLORS["DIM"]
            logger_color = self.LOGGER_COLORS.get(logger_root, dim)

            # Minimalist header: [time] logger
            return f"{dim}[{timestamp}]{reset} {logger_color}{record.name}{reset}"

        return f"[{timestamp}] {record.name}"

    def _structured_message(self, record, *, colored: bool) -> str:
        message = record.getMessage()

        if message.startswith("TUI Request:"):
            return self._format_tui_request(message, colored)

        if record.name.startswith("openai"):
            rendered = self._format_openai_message(message, colored)
            if rendered is not None:
                return rendered

        if record.name.startswith("httpx"):
            rendered = self._format_httpx_message(message, colored)
            if rendered is not None:
                return rendered

        if record.name.startswith("httpcore"):
            rendered = self._format_httpcore_message(message, colored, record)
            if rendered is not None:
                return rendered

        # Fallback for other messages
        if message.strip():
            return textwrap.indent(message, "  ")
        return ""

    def _format_tui_request(self, message: str, colored: bool) -> str:
        try:
            _, _, json_str = message.partition("TUI Request: ")
            data = json.loads(json_str)

            request_id = data.get("request_id", "")
            self._current_request_id = request_id
            method = data.get("method", "GET")
            url = data.get("url", "")
            headers = data.get("headers", {})

            # Build title with request ID
            if colored:
                id_part = f"{self.COLORS['DIM']}[{request_id}]{self.COLORS['RESET']} " if request_id else ""
                title = f"{id_part}{self.COLORS['BOLD']}{method}{self.COLORS['RESET']} {self.COLORS['BLUE']}{url}{self.COLORS['RESET']}"
            else:
                id_part = f"[{request_id}] " if request_id else ""
                title = f"{id_part}{method} {url}"

            # Build content with headers section
            lines = []
            lines.append(self._format_section_title("Headers", colored))
            lines.append(self._format_mapping(headers, colored))

            content = "\n".join(lines)
            return self._draw_section(f"➔ REQUEST {title}", content, self.COLORS["BLUE"])
        except Exception:
            return message

    def _draw_section(self, title, content, color):
        """Draw an open-ended section: header line + optional gutter, no right/bottom border."""
        if not self.use_colors:
            return f"── {title}\n{content}"

        b = self.BOX
        c = color
        r = self.COLORS["RESET"]

        # Header: ── Title ──────
        trail = 6  # short trailing dash — safe for any terminal width
        top = f"{c}{b['h']*2} {r}{title} {c}{b['h']*trail}{r}"

        gutter = f"{c}{b['v']}{r} " if self.show_gutter else "  "
        body_lines = []
        for line in content.splitlines():
            body_lines.append(f"{gutter}{line}")

        return f"{top}\n" + "\n".join(body_lines)

    # Keep old name as alias so any external callers still work
    _draw_box = _draw_section

    def _format_openai_message(self, message: str, colored: bool) -> Optional[str]:
        if message.startswith("Sending HTTP Request"):
            return ""

        # Suppress request_id — it's visible in the response header already
        if message.startswith("request_id"):
            return ""

        prefix, sep, payload = message.partition(": ")
        if not sep:
            if message.startswith("Tool call:"):
                return self._format_tool_call(message, colored)
            return None

        if prefix == "Request options":
            data = self._parse_literal(payload)
            if isinstance(data, dict):
                return self._format_openai_request(data, colored)
            return textwrap.indent(payload, "  ")

        if prefix == "HTTP Response":
            return self._format_openai_response(payload, colored)

        if prefix == "Tool call":
            return self._format_tool_call(payload, colored)

        return None

    def _format_openai_request(self, data: Dict[str, Any], colored: bool) -> str:
        lines: List[str] = []
        method = data.get("method", "GET").upper()
        url = data.get("url", "")

        # Extract model name from body for display in title
        body = data.get("json_data") or data.get("data")
        model_name = ""
        if isinstance(body, dict):
            model_name = body.get("model", "")

        # Title for the section header
        title = f"{method} {url}"
        if model_name:
            title += f" [{model_name}]"
        if colored:
            model_part = f" {self.COLORS['YELLOW']}[{model_name}]{self.COLORS['RESET']}" if model_name else ""
            title = f"{self.COLORS['BOLD']}{method}{self.COLORS['RESET']} {self.COLORS['BLUE']}{url}{self.COLORS['RESET']}{model_part}"

        # Headers
        headers = data.get("headers")
        if headers:
            lines.append(self._format_section_title("Headers", colored))
            lines.append(self._format_mapping(headers, colored))

        # Body
        body = data.get("json_data") or data.get("data")
        if body is not None:
            lines.append(self._format_section_title("Payload", colored))
            lines.append(self._format_json(body, colored))

        # Options (timeout, etc)
        meta_keys = ["stream", "stream_options", "tools", "files", "timeout"]
        misc = {k: data.get(k) for k in meta_keys if data.get(k) is not None}
        if misc:
            lines.append(self._format_section_title("Options", colored))
            lines.append(self._format_json(misc, colored))

        content = "\n".join(lines).rstrip()
        return self._draw_section(title, content, self.COLORS["BLUE"])

    def _format_openai_response(self, payload: str, colored: bool) -> Optional[str]:
        payload = payload.strip()

        # Extract headers if present
        headers_literal = None
        if " Headers(" in payload:
            front, _, tail = payload.partition(" Headers(")
            payload = front.strip()
            headers_literal = tail.rsplit(")", 1)[0]

        # Parse status line
        method = url = status = None
        match = re.match(r"(\w+)\s+([^\s]+)\s+\"([^\"]+)\"", payload)
        if match:
            method, url, status = match.groups()

        lines: List[str] = []

        # Determine color based on status code
        color = self.COLORS["GREEN"]
        status_icon = "✓"
        if status:
            code = status.split()[0] if status else ""
            if code.startswith("3"):
                color = self.COLORS["BLUE"]
                status_icon = "→"
            elif code.startswith("4"):
                color = self.COLORS["YELLOW"]
                status_icon = "⚠"
            elif code.startswith("5"):
                color = self.COLORS["RED"]
                status_icon = "✗"

        # Build title with status icon
        if colored and status:
            title = f"{color}{status_icon}{self.COLORS['RESET']} {self.COLORS['BOLD']}{status}{self.COLORS['RESET']}"
            if method and url:
                title += f" {self.COLORS['DIM']}({method} {url}){self.COLORS['RESET']}"
        else:
            title = f"{status_icon} {status}" if status else "Response"
            if method and url:
                title += f" ({method} {url})"

        # Headers - extract important ones for summary
        headers_parsed = (
            self._parse_literal(headers_literal)
            if headers_literal is not None
            else None
        )
        if headers_parsed:
            headers_dict = self._headers_to_dict(headers_parsed)
            lines.append(self._format_section_title("Headers", colored))
            lines.append(self._format_mapping(headers_dict, colored))

        # Build the "↓ Response Start" section.  The synthetic "▼ Stream"
        # marker that used to be appended here is now a real httpcore event
        # (response_body.started) handled by _format_httpcore_message.
        req_id = self._current_request_id
        if colored:
            id_part = f" {self.COLORS['DIM']}[{req_id}]{self.COLORS['RESET']}" if req_id else ""
        else:
            id_part = f" [{req_id}]" if req_id else ""
        content = "\n".join(lines) if lines else ""
        if content:
            return self._draw_section(f"↓ Response Start{id_part} {title}", content, color)
        return self._format_response_status_line(title, req_id, color, colored)

    def _format_httpx_message(self, message: str, colored: bool) -> Optional[str]:
        message = message.strip()
        if message.startswith("HTTP Request:"):
            # httpx logs "HTTP Request: METHOD URL 'protocol' status"
            _, _, rest = message.partition(":")
            rest = rest.strip()
            match = re.match(r"(\w+)\s+([^\s]+)\s+\"([^\"]+)\"", rest)

            if match:
                method, url, protocol_status = match.groups()
                # protocol_status might be "HTTP/1.1 200 OK"
                protocol_parts = protocol_status.split()
                if len(protocol_parts) > 1 and protocol_parts[0].startswith("HTTP"):
                    # It's a response-like line (status included)
                    status = " ".join(protocol_parts[1:])
                    return self._format_response_line(status, method, url, colored)
                else:
                    # It's a request-like line
                    return self._format_request_line(method, url, colored)

            return f"  {rest}"

        return None

    def _format_httpcore_message(self, message: str, colored: bool, record=None) -> Optional[str]:
        """Format httpcore lifecycle events.

        httpcore emits paired .started/.complete events for each phase.
        We render three of them as user-visible lifecycle markers:

            ▼ Stream Start      ← response_body.started
            ■ Stream End        ← response_body.complete
            ✓ Response Complete ← response_closed.complete

        (The fourth marker, ↓ Response, comes from the OpenAI SDK logger
        and is handled by _format_openai_response.)
        """
        message = message.strip()
        event, _, rest = message.partition(" ")

        # --- Lifecycle markers (rendered as standalone banner lines) ---

        # ▼ Stream Start — body streaming begins
        # httpcore event is "receive_response_body.started"
        if event == "receive_response_body.started":
            return self._format_marker("▼", "Stream Start", record, colored)

        # ■ Stream End — all chunks received
        # httpcore event is "receive_response_body.complete"
        if event == "receive_response_body.complete":
            return self._format_marker("■", "Stream End", record, colored)

        # ✓ Response Complete — HTTP connection closed
        if event == "response_closed.complete":
            return self._format_marker("✓", "Response Complete", record, colored)

        # --- Suppress noise ---

        # Suppress all other body events (raw data, request bodies)
        if "request_body" in event or "response_body" in event:
            return ""

        # Suppress .complete events (redundant with .started for these)
        if event.endswith(".complete"):
            if "receive_response_headers" not in event:
                return ""

        # Suppress receive_response_headers (OpenAI SDK logs them better)
        if "receive_response_headers" in event:
            return ""

        # Suppress response_closed.started (we show .complete instead)
        if "response_closed" in event:
            return ""

        # 3. Connection Events
        if "connect_tcp" in event or "start_tls" in event:
            if event.endswith(".complete"):
                return ""

            kv_dict = {}
            for match in re.finditer(r"(\w+)=((?:<[^>]+>)|(?:'[^']*')|(?:[^,\s]+))", rest):
                k, v = match.group(1), match.group(2).strip("'")
                kv_dict[k] = v

            title = "⚡ Connection" if "connect" in event else "⚡ TLS Handshake"
            show_keys = ("host", "port", "server_hostname", "local_address")
            filtered = {k: v for k, v in kv_dict.items() if k in show_keys}
            content = self._format_mapping(filtered, colored)
            return self._draw_section(title, content, self.COLORS["CYAN"])

        # 4. Request Headers
        if "send_request_headers" in event:
            content = "➔ Sending Request Headers"
            match = re.search(r"request=<Request \[b'(\w+)'\]>", rest)
            if match:
                content = f"➔ Sending {match.group(1)} Request"

            return self._draw_section("Request", content, self.COLORS["BLUE"])

        return None

    # --- Formatting Helpers ---

    def _format_marker(self, icon: str, label: str, record, colored: bool) -> str:
        """Format a lifecycle marker banner line.

        Produces a standalone timestamped banner like:

            ── ✓ Response Complete 12:30:16.488 ──────

        Used for Stream Start, Stream End, and Response Complete.

        Newline ownership: this method returns the bare marker line with
        NO leading or trailing newlines.  The caller (format() or
        _format_plain()) owns the single leading ``\\n`` that produces
        one blank line before the marker.  The logging handler's
        terminator provides the final ``\\n``.
        """
        ts_part = ""
        if record is not None:
            ts = self.formatTime(record, "%H:%M:%S")
            ts = f"{ts}.{int(record.msecs):03d}"
            if colored:
                ts_part = f" {self.COLORS['DIM']}{ts}{self.COLORS['RESET']}"
            else:
                ts_part = f" {ts}"
        req_id = self._current_request_id
        if colored:
            green = self.COLORS["GREEN"]
            bold = self.COLORS["BOLD"]
            dim = self.COLORS["DIM"]
            r = self.COLORS["RESET"]
            id_part = f" {dim}[{req_id}]{r}" if req_id else ""
            return f"{green}{'─' * 2} {bold}{icon} {label}{r}{id_part}{ts_part} {green}{'─' * 6}{r}"
        id_part = f" [{req_id}]" if req_id else ""
        return f"── {icon} {label}{id_part}{ts_part} ──────"

    def _format_response_status_line(self, title, req_id, color, colored):
        """Single-line response status without section body."""
        if colored:
            r = self.COLORS["RESET"]
            dim = self.COLORS["DIM"]
            id_part = f" {dim}[{req_id}]{r}" if req_id else ""
            return f"{color}{'─' * 2} {r}↓ Response Start{id_part} {title} {color}{'─' * 6}{r}"
        id_part = f" [{req_id}]" if req_id else ""
        return f"── ↓ Response Start{id_part} {title} ──────"

    def _format_request_line(self, method, url, colored):
        if colored:
            bold = self.COLORS["BOLD"]
            blue = self.COLORS["BLUE"]
            reset = self.COLORS["RESET"]
            return f"  {blue}{bold}➔ {method.upper()}{reset} {blue}{url}{reset}"
        return f"  -> {method.upper()} {url}"

    def _format_response_line(self, status, method, url, colored):
        if colored:
            bold = self.COLORS["BOLD"]
            reset = self.COLORS["RESET"]

            # Colorize status code with appropriate icon
            code = status.split()[0]
            color = self.COLORS["GREEN"]
            icon = "✓"
            if code.startswith("3"):
                color = self.COLORS["BLUE"]
                icon = "→"
            elif code.startswith("4"):
                color = self.COLORS["YELLOW"]
                icon = "⚠"
            elif code.startswith("5"):
                color = self.COLORS["RED"]
                icon = "✗"

            meta = ""
            if method and url:
                meta = f" {self.COLORS['DIM']}({method} {url}){reset}"

            return f"  {color}{bold}← {icon} {status}{reset}{meta}"
        return f"  <- {status} ({method} {url})"

    def _format_section_title(self, title, colored):
        """Render a sub-section label (e.g. "Headers:", "Payload:").

        Uses bold+dim for subtle but distinct styling, with a leading
        blank line to visually separate from the content above.
        """
        if colored:
            return f"\n{self.COLORS['DIM']}{self.COLORS['BOLD']}{title}:{self.COLORS['RESET']}"
        return f"\n{title}:"

    def _kv_line(self, key, value, colored):
        if colored:
            return f"  {self.COLORS['DIM']}{key}:{self.COLORS['RESET']} {value}"
        return f"  {key}: {value}"

    def _format_mapping(self, mapping, colored, indent=""):
        if not isinstance(mapping, dict):
            return f"{indent}{str(mapping)}"

        lines = []
        for key, value in mapping.items():
            # Show all headers including auth - useful for debugging which key is being used
            k_str = f"{self.COLORS['DIM']}{key}{self.COLORS['RESET']}" if colored else key
            lines.append(f"{indent}{k_str}: {value}")
        return "\n".join(lines)

    def _headers_to_dict(self, headers) -> Dict[str, str]:
        """Normalize headers from dict or list-of-tuples to a str→str dict."""
        if isinstance(headers, dict):
            return {str(k): str(v) for k, v in headers.items()}
        if isinstance(headers, (list, tuple)):
            d = {}
            for item in headers:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    k = item[0].decode('utf-8') if isinstance(item[0], bytes) else str(item[0])
                    v = item[1].decode('utf-8') if isinstance(item[1], bytes) else str(item[1])
                    d[k] = v
            return d
        return {}

    def _format_headers_list(self, headers, colored, indent=""):
        return self._format_mapping(self._headers_to_dict(headers), colored, indent)

    def _format_tool_call(self, payload: str, colored: bool) -> str:
        payload = payload.strip()
        if colored:
            return f"  {self.COLORS['MAGENTA']}• Tool Call:{self.COLORS['RESET']} {payload}"
        return f"  Tool Call: {payload}"

    def _truncate_body(self, text: str, max_chars: int = 500) -> str:
        """Truncate body text with indicator showing total length.
        Set LLM_HTTP_NO_TRUNCATE=1 to disable truncation."""
        if os.environ.get("LLM_HTTP_NO_TRUNCATE"):
            return text
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars]}...\n[truncated, {len(text)} chars total]"

    def _format_json(self, data: Any, colored: bool, indent: str = "", truncate: bool = True) -> str:
        """Format JSON with optional colorization and truncation."""
        try:
            text = json.dumps(self._sanitize(data), indent=2, ensure_ascii=False)

            # Apply truncation before colorization
            if truncate:
                text = self._truncate_body(text)

            if colored:
                # Colorize JSON
                # Keys
                text = re.sub(r'^\s*"([^"]+)":', f'  {self.COLORS["CYAN"]}"\\1"{self.COLORS["RESET"]}:', text, flags=re.MULTILINE)
                # String values
                text = re.sub(r': "([^"]*)"', f': {self.COLORS["GREEN"]}"\\1"{self.COLORS["RESET"]}', text)
                # Numbers/Booleans/Null
                text = re.sub(r': (true|false|null|[0-9\.]+)', f': {self.COLORS["YELLOW"]}\\1{self.COLORS["RESET"]}', text)

            if indent:
                return textwrap.indent(text, indent)
            return text
        except TypeError:
            from pprint import pformat
            text = pformat(self._sanitize(data), indent=2, compact=True)
            if truncate:
                text = self._truncate_body(text)
            if indent:
                return textwrap.indent(text, indent)
            return text

    def _sanitize(self, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: self._sanitize(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._sanitize(v) for v in data]
        if isinstance(data, (bytes, bytearray)):
            return data.decode(errors="replace")
        return data

    def _parse_literal(self, value: str):
        try:
            return ast.literal_eval(value)
        except Exception:
            return None


def _get_http_logging_config():
    """
    Determine HTTP logging configuration from environment variables.

    Uses a single env var with two levels:
    - LLM_HTTP_DEBUG=1: INFO-level (requests and responses)
    - LLM_HTTP_DEBUG=2: DEBUG-level (verbose with headers/connection details)

    Returns:
        dict: Configuration with 'enabled', 'level', and 'use_colors' keys
    """
    import os

    # Read debug level: 0=off, 1=INFO, 2=DEBUG
    raw = os.environ.get("LLM_HTTP_DEBUG") or ""
    try:
        debug_level = int(raw)
    except ValueError:
        # Any non-empty non-numeric value (e.g. "true") treated as level 1
        debug_level = 1 if raw else 0

    # Backward compat: LLM_OPENAI_SHOW_RESPONSES=1 → level 1
    if not debug_level and os.environ.get("LLM_OPENAI_SHOW_RESPONSES"):
        debug_level = 1

    if not debug_level:
        return {"enabled": False}

    level = "DEBUG" if debug_level >= 2 else "INFO"

    return {
        "enabled": True,
        "level": level,
        "use_colors": not os.environ.get("NO_COLOR"),
    }


_http_logging_configured = False


def configure_http_logging():
    """Configure Python logging for HTTP requests across all providers.

    Idempotent: safe to call multiple times.  The latch guards handler
    creation (preventing stacked handlers) while log levels are updated
    on every call so callers can change ``LLM_HTTP_DEBUG`` between
    invocations.

    Enables logging for httpx, httpcore, openai, anthropic, and the
    internal ``llm.http`` logger used for TUI request tracking.

    Environment variables:
    - LLM_HTTP_DEBUG=1: Enable INFO-level HTTP logging (requests/responses)
    - LLM_HTTP_DEBUG=2: Enable DEBUG-level HTTP logging (verbose)
    - LLM_OPENAI_SHOW_RESPONSES=1: Backward compatibility (INFO level)
    """
    global _http_logging_configured

    import logging

    config = _get_http_logging_config()
    if not config["enabled"]:
        return

    # Set up HTTP-related loggers
    log_level = getattr(logging, config["level"])

    # Core HTTP libraries — always use the resolved log_level (INFO or DEBUG).
    # Never use TRACE (level 5): it dumps raw wire bytes which leak through
    # filters and appear as duplicate response text in the terminal.
    http_loggers = ["httpx", "httpcore", "openai", "anthropic", "llm.http"]
    if config["level"] == "DEBUG":
        http_loggers.extend(["urllib3", "requests"])

    if not _http_logging_configured:
        # First call: create formatter, filter, and attach handlers.
        _http_logging_configured = True

        formatter = HTTPColorFormatter(use_colors=config.get("use_colors", True))
        safe_filter = SafeHTTPCoreFilter()

        # Configure root logger if not already configured
        if not logging.getLogger().handlers:
            handler = _QuietStreamHandler()
            handler.setFormatter(formatter)
            handler.addFilter(safe_filter)
            logging.getLogger().addHandler(handler)
            logging.getLogger().setLevel(logging.WARNING)

        for logger_name in http_loggers:
            logger = logging.getLogger(logger_name)
            logger.propagate = False

            if all(isinstance(h, logging.NullHandler) for h in logger.handlers):
                logger.handlers.clear()

            has_our_handler = any(
                isinstance(h, _QuietStreamHandler) for h in logger.handlers
            )
            if not has_our_handler:
                handler = _QuietStreamHandler()
                handler.setFormatter(formatter)
                handler.addFilter(safe_filter)
                logger.addHandler(handler)

        logging.getLogger("llm.http").info(
            f"HTTP logging enabled at {config['level']} level"
        )

    # Always update levels (even on subsequent calls) so callers can
    # change LLM_HTTP_DEBUG between invocations.
    for logger_name in http_loggers:
        logging.getLogger(logger_name).setLevel(log_level)


class SpinnerLogHandler(logging.Handler):
    """Watches httpcore/openai log events to drive spinner state transitions.

    This handler never emits text.  It only calls ``spinner.set_state()``
    when it detects HTTP lifecycle events that map to spinner states:

        connect_tcp / start_tls  →  "connecting"
        send_request_headers     →  "waiting"

    Attach to httpcore/openai loggers while the spinner is active and
    remove when the spinner stops.
    """

    def __init__(self, spinner):
        super().__init__(level=logging.DEBUG)
        self._spinner = spinner

    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return

        if record.name.startswith("httpcore"):
            if "connect_tcp.started" in msg or "start_tls.started" in msg:
                self._spinner.set_state("connecting")
            elif "send_request_headers.started" in msg:
                self._spinner.set_state("waiting")
        elif record.name.startswith("openai"):
            if "Request options" in msg or "Sending HTTP Request" in msg:
                self._spinner.set_state("waiting")


@contextlib.contextmanager
def buffered_stream_end():
    """Buffer post-stream lifecycle markers during streaming.

    Defers the Stream End and Response Complete log messages so they
    are emitted *after* mdstream's finish() re-renders the last line.
    Without this, stderr output between the last chunk and finish()
    would displace the cursor and duplicate the last line.

    Yields a callable that returns a list of buffered messages.
    """
    HTTPColorFormatter._defer_stream_end = True
    HTTPColorFormatter._pending_stream_end = []

    def get_pending():
        msgs = HTTPColorFormatter._pending_stream_end
        HTTPColorFormatter._pending_stream_end = []
        return msgs

    try:
        yield get_pending
    finally:
        HTTPColorFormatter._defer_stream_end = False


def is_http_logging_enabled() -> bool:
    """Check if HTTP logging is enabled via environment variables."""
    config = _get_http_logging_config()
    return config["enabled"]


def simplify_usage_dict(d):
    # Recursively remove keys with value 0 and empty dictionaries
    def remove_empty_and_zero(obj):
        if isinstance(obj, dict):
            cleaned = {
                k: remove_empty_and_zero(v)
                for k, v in obj.items()
                if v != 0 and v != {}
            }
            return {k: v for k, v in cleaned.items() if v is not None and v != {}}
        return obj

    return remove_empty_and_zero(d) or {}


def token_usage_string(input_tokens, output_tokens, token_details) -> str:
    bits = []
    if input_tokens is not None:
        bits.append(f"{format(input_tokens, ',')} input")
    if output_tokens is not None:
        bits.append(f"{format(output_tokens, ',')} output")
    if token_details:
        bits.append(json.dumps(token_details))
    return ", ".join(bits)


def extract_fenced_code_block(text: str, last: bool = False) -> Optional[str]:
    """
    Extracts and returns Markdown fenced code block found in the given text.

    The function handles fenced code blocks that:
    - Use at least three backticks (`).
    - May include a language tag immediately after the opening backticks.
    - Use more than three backticks as long as the closing fence has the same number.

    If no fenced code block is found, the function returns None.

    Args:
        text (str): The input text to search for a fenced code block.
        last (bool): Extract the last code block if True, otherwise the first.

    Returns:
        Optional[str]: The content of the fenced code block, or None if not found.
    """
    # Regex pattern to match fenced code blocks
    # - ^ or \n ensures that the fence is at the start of a line
    # - (`{3,}) captures the opening backticks (at least three)
    # - (\w+)? optionally captures the language tag
    # - \n matches the newline after the opening fence
    # - (.*?) non-greedy match for the code block content
    # - (?P=fence) ensures that the closing fence has the same number of backticks
    # - [ ]* allows for optional spaces between the closing fence and newline
    # - (?=\n|$) ensures that the closing fence is followed by a newline or end of string
    pattern = re.compile(
        r"""(?m)^(?P<fence>`{3,})(?P<lang>\w+)?\n(?P<code>.*?)^(?P=fence)[ ]*(?=\n|$)""",
        re.DOTALL,
    )
    matches = list(pattern.finditer(text))
    if matches:
        match = matches[-1] if last else matches[0]
        return match.group("code")
    return None


def make_schema_id(schema: dict) -> Tuple[str, str]:
    schema_json = json.dumps(schema, separators=(",", ":"))
    schema_id = hashlib.blake2b(schema_json.encode(), digest_size=16).hexdigest()
    return schema_id, schema_json


def output_rows_as_json(rows, nl=False, compact=False, json_cols=()):
    """
    Output rows as JSON - either newline-delimited or an array

    Parameters:
    - rows: Iterable of dictionaries to output
    - nl: Boolean, if True, use newline-delimited JSON
    - compact: Boolean, if True uses [{"...": "..."}\n {"...": "..."}] format
    - json_cols: Iterable of columns that contain JSON

    Yields:
    - Stream of strings to be output
    """
    current_iter, next_iter = itertools.tee(rows, 2)
    next(next_iter, None)
    first = True

    for row, next_row in itertools.zip_longest(current_iter, next_iter):
        is_last = next_row is None
        for col in json_cols:
            row[col] = json.loads(row[col])

        if nl:
            # Newline-delimited JSON: one JSON object per line
            yield json.dumps(row)
        elif compact:
            # Compact array format: [{"...": "..."}\n {"...": "..."}]
            yield "{firstchar}{serialized}{maybecomma}{lastchar}".format(
                firstchar="[" if first else " ",
                serialized=json.dumps(row),
                maybecomma="," if not is_last else "",
                lastchar="]" if is_last else "",
            )
        else:
            # Pretty-printed array format with indentation
            yield "{firstchar}{serialized}{maybecomma}{lastchar}".format(
                firstchar="[\n" if first else "",
                serialized=textwrap.indent(json.dumps(row, indent=2), "  "),
                maybecomma="," if not is_last else "",
                lastchar="\n]" if is_last else "",
            )
        first = False

    if first and not nl:
        # We didn't output any rows, so yield the empty list
        yield "[]"


def resolve_schema_input(db, schema_input, load_template):
    # schema_input might be JSON or a filepath or an ID or t:name
    if not schema_input:
        return
    if schema_input.strip().startswith("t:"):
        name = schema_input.strip()[2:]
        schema_object = None
        try:
            template = load_template(name)
            schema_object = template.schema_object
        except ValueError:
            raise click.ClickException("Invalid template: {}".format(name))
        if not schema_object:
            raise click.ClickException("Template '{}' has no schema".format(name))
        return template.schema_object
    if schema_input.strip().startswith("{"):
        try:
            return json.loads(schema_input)
        except ValueError:
            pass
    if " " in schema_input.strip() or "," in schema_input:
        # Treat it as schema DSL
        return schema_dsl(schema_input)
    # Is it a file on disk?
    path = pathlib.Path(schema_input)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except ValueError:
            raise click.ClickException("Schema file contained invalid JSON")
    # Last attempt: is it an ID in the DB?
    try:
        row = db["schemas"].get(schema_input)
        return json.loads(row["content"])
    except (sqlite_utils.db.NotFoundError, ValueError):
        raise click.BadParameter("Invalid schema")


def schema_summary(schema: dict) -> str:
    """
    Extract property names from a JSON schema and format them in a
    concise way that highlights the array/object structure.

    Args:
        schema (dict): A JSON schema dictionary

    Returns:
        str: A human-friendly summary of the schema structure
    """
    if not schema or not isinstance(schema, dict):
        return ""

    schema_type = schema.get("type", "")

    if schema_type == "object":
        props = schema.get("properties", {})
        prop_summaries = []

        for name, prop_schema in props.items():
            prop_type = prop_schema.get("type", "")

            if prop_type == "array":
                items = prop_schema.get("items", {})
                items_summary = schema_summary(items)
                prop_summaries.append(f"{name}: [{items_summary}]")
            elif prop_type == "object":
                nested_summary = schema_summary(prop_schema)
                prop_summaries.append(f"{name}: {nested_summary}")
            else:
                prop_summaries.append(name)

        return "{" + ", ".join(prop_summaries) + "}"

    elif schema_type == "array":
        items = schema.get("items", {})
        return schema_summary(items)

    return ""


def schema_dsl(schema_dsl: str, multi: bool = False) -> Dict[str, Any]:
    """
    Build a JSON schema from a concise schema string.

    Args:
        schema_dsl: A string representing a schema in the concise format.
            Can be comma-separated or newline-separated.
        multi: Boolean, return a schema for an "items" array of these

    Returns:
        A dictionary representing the JSON schema.
    """
    # Type mapping dictionary
    type_mapping = {
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "str": "string",
    }

    # Initialize the schema dictionary with required elements
    json_schema: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}

    # Check if the schema is newline-separated or comma-separated
    if "\n" in schema_dsl:
        fields = [field.strip() for field in schema_dsl.split("\n") if field.strip()]
    else:
        fields = [field.strip() for field in schema_dsl.split(",") if field.strip()]

    # Process each field
    for field in fields:
        # Extract field name, type, and description
        if ":" in field:
            field_info, description = field.split(":", 1)
            description = description.strip()
        else:
            field_info = field
            description = ""

        # Process field name and type
        field_parts = field_info.strip().split()
        field_name = field_parts[0].strip()

        # Default type is string
        field_type = "string"

        # If type is specified, use it
        if len(field_parts) > 1:
            type_indicator = field_parts[1].strip()
            if type_indicator in type_mapping:
                field_type = type_mapping[type_indicator]

        # Add field to properties
        json_schema["properties"][field_name] = {"type": field_type}

        # Add description if provided
        if description:
            json_schema["properties"][field_name]["description"] = description

        # Add field to required list
        json_schema["required"].append(field_name)

    if multi:
        return multi_schema(json_schema)
    else:
        return json_schema


def multi_schema(schema: dict) -> dict:
    "Wrap JSON schema in an 'items': [] array"
    return {
        "type": "object",
        "properties": {"items": {"type": "array", "items": schema}},
        "required": ["items"],
    }


def find_unused_key(item: dict, key: str) -> str:
    'Return unused key, e.g. for {"id": "1"} and key "id" returns "id_"'
    while key in item:
        key += "_"
    return key


def truncate_string(
    text: str,
    max_length: int = 100,
    normalize_whitespace: bool = False,
    keep_end: bool = False,
) -> str:
    """
    Truncate a string to a maximum length, with options to normalize whitespace and keep both start and end.

    Args:
        text: The string to truncate
        max_length: Maximum length of the result string
        normalize_whitespace: If True, replace all whitespace with a single space
        keep_end: If True, keep both beginning and end of string

    Returns:
        Truncated string
    """
    if not text:
        return text

    if normalize_whitespace:
        text = re.sub(r"\s+", " ", text)

    if len(text) <= max_length:
        return text

    # Minimum sensible length for keep_end is 9 characters: "a... z"
    min_keep_end_length = 9

    if keep_end and max_length >= min_keep_end_length:
        # Calculate how much text to keep at each end
        # Subtract 5 for the "... " separator
        cutoff = (max_length - 5) // 2
        return text[:cutoff] + "... " + text[-cutoff:]
    else:
        # Fall back to simple truncation for very small max_length
        return text[: max_length - 3] + "..."


def ensure_fragment(db, content):
    sql = """
    insert into fragments (hash, content, datetime_utc, source)
    values (:hash, :content, datetime('now'), :source)
    on conflict(hash) do nothing
    """
    hash_id = hashlib.sha256(content.encode("utf-8")).hexdigest()
    source = None
    if isinstance(content, Fragment):
        source = content.source
    with db.conn:
        db.execute(sql, {"hash": hash_id, "content": content, "source": source})
        return list(
            db.query("select id from fragments where hash = :hash", {"hash": hash_id})
        )[0]["id"]


def ensure_tool(db, tool):
    sql = """
    insert into tools (hash, name, description, input_schema, plugin)
    values (:hash, :name, :description, :input_schema, :plugin)
    on conflict(hash) do nothing
    """
    with db.conn:
        db.execute(
            sql,
            {
                "hash": tool.hash(),
                "name": tool.name,
                "description": tool.description,
                "input_schema": json.dumps(tool.input_schema),
                "plugin": tool.plugin,
            },
        )
        return list(
            db.query("select id from tools where hash = :hash", {"hash": tool.hash()})
        )[0]["id"]


def maybe_fenced_code(content: str) -> str:
    "Return the content as a fenced code block if it looks like code"
    is_code = False
    if content.count("<") > 10:
        is_code = True
    if not is_code:
        # Are 90% of the lines under 120 chars?
        lines = content.splitlines()
        if len(lines) > 3:
            num_short = sum(1 for line in lines if len(line) < 120)
            if num_short / len(lines) > 0.9:
                is_code = True
    if is_code:
        # Find number of backticks not already present
        num_backticks = 3
        while "`" * num_backticks in content:
            num_backticks += 1
        # Add backticks
        content = (
            "\n"
            + "`" * num_backticks
            + "\n"
            + content.strip()
            + "\n"
            + "`" * num_backticks
        )
    return content


_plugin_prefix_re = re.compile(r"^[a-zA-Z0-9_-]+:")


def has_plugin_prefix(value: str) -> bool:
    "Check if value starts with alphanumeric prefix followed by a colon"
    return bool(_plugin_prefix_re.match(value))


def _parse_kwargs(arg_str: str) -> Dict[str, Any]:
    """Parse key=value pairs where each value is valid JSON."""
    tokens = []
    buf = []
    depth = 0
    in_string = False
    string_char = ""
    escape = False

    for ch in arg_str:
        if in_string:
            buf.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == string_char:
                in_string = False
        else:
            if ch in "\"'":
                in_string = True
                string_char = ch
                buf.append(ch)
            elif ch in "{[(":
                depth += 1
                buf.append(ch)
            elif ch in "}])":
                depth -= 1
                buf.append(ch)
            elif ch == "," and depth == 0:
                tokens.append("".join(buf).strip())
                buf = []
            else:
                buf.append(ch)
    if buf:
        tokens.append("".join(buf).strip())

    kwargs: Dict[str, Any] = {}
    for token in tokens:
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"Invalid keyword spec segment: '{token}'")
        key, value_str = token.split("=", 1)
        key = key.strip()
        value_str = value_str.strip()
        try:
            value = json.loads(value_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Value for '{key}' is not valid JSON: {value_str}") from e
        kwargs[key] = value
    return kwargs


def instantiate_from_spec(class_map: Dict[str, Type], spec: str):
    """
    Instantiate a class from a specification string with flexible argument formats.

    This function parses a specification string that defines a class name and its
    constructor arguments, then instantiates the class using the provided class
    mapping. The specification supports multiple argument formats for flexibility.

    Parameters
    ----------
    class_map : Dict[str, Type]
        A mapping from class names (strings) to their corresponding class objects.
        Only classes present in this mapping can be instantiated.
    spec : str
        A specification string defining the class to instantiate and its arguments.

        Format: "ClassName" or "ClassName(arguments)"

        Supported argument formats:
        - Empty: ClassName() - calls constructor with no arguments
        - JSON object: ClassName({"key": "value", "other": 42}) - unpacked as **kwargs
        - Single JSON value: ClassName("hello") or ClassName([1,2,3]) - passed as single positional argument
        - Key-value pairs: ClassName(name="test", count=5, items=[1,2]) - parsed as individual kwargs
          where values must be valid JSON

    Returns
    -------
    object
        An instance of the specified class, constructed with the parsed arguments.

    Raises
    ------
    ValueError
        If the spec string format is invalid, if the class name is not found in
        class_map, if JSON parsing fails, or if argument parsing encounters errors.
    """
    m = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\((.*)\))?\s*$", spec)
    if not m:
        raise ValueError(f"Invalid spec string: '{spec}'")
    class_name, arg_body = m.group(1), (m.group(2) or "").strip()
    if class_name not in class_map:
        raise ValueError(f"Unknown class '{class_name}'")

    cls = class_map[class_name]

    # No arguments at all
    if arg_body == "":
        return cls()

    # Starts with { -> JSON object to kwargs
    if arg_body.lstrip().startswith("{"):
        try:
            kw = json.loads(arg_body)
        except json.JSONDecodeError as e:
            raise ValueError("Argument JSON object is not valid JSON") from e
        if not isinstance(kw, dict):
            raise ValueError("Top-level JSON must be an object when using {} form")
        return cls(**kw)

    # Starts with quote / number / [ / t f n for single positional JSON value
    if re.match(r'\s*(["\[\d\-]|true|false|null)', arg_body, re.I):
        try:
            positional_value = json.loads(arg_body)
        except json.JSONDecodeError as e:
            raise ValueError("Positional argument must be valid JSON") from e
        return cls(positional_value)

    # Otherwise treat as key=value pairs
    kwargs = _parse_kwargs(arg_body)
    return cls(**kwargs)


NANOSECS_IN_MILLISECS = 1000000
TIMESTAMP_LEN = 6
RANDOMNESS_LEN = 10

_lock: Final = threading.Lock()
_last: Optional[bytes] = None  # 16-byte last produced ULID


def monotonic_ulid() -> ULID:
    """
    Return a ULID instance that is guaranteed to be *strictly larger* than every
    other ULID returned by this function inside the same process.

    It works the same way the reference JavaScript `monotonicFactory` does:
    * If the current call happens in the same millisecond as the previous
        one, the 80-bit randomness part is incremented by exactly one.
    * As soon as the system clock moves forward, a brand-new ULID with
        cryptographically secure randomness is generated.
    * If more than 2**80 ULIDs are requested within a single millisecond
        an `OverflowError` is raised (practically impossible).
    """
    global _last

    now_ms = time.time_ns() // NANOSECS_IN_MILLISECS

    with _lock:
        # First call
        if _last is None:
            _last = _fresh(now_ms)
            return ULID(_last)

        # Decode timestamp from the last ULID we handed out
        last_ms = int.from_bytes(_last[:TIMESTAMP_LEN], "big")

        # If the millisecond is the same, increment the randomness
        if now_ms == last_ms:
            rand_int = int.from_bytes(_last[TIMESTAMP_LEN:], "big") + 1
            if rand_int >= 1 << (RANDOMNESS_LEN * 8):
                raise OverflowError(
                    "Randomness overflow: > 2**80 ULIDs requested "
                    "in one millisecond!"
                )
            randomness = rand_int.to_bytes(RANDOMNESS_LEN, "big")
            _last = _last[:TIMESTAMP_LEN] + randomness
            return ULID(_last)

        # New millisecond, start fresh
        _last = _fresh(now_ms)
        return ULID(_last)


def _fresh(ms: int) -> bytes:
    """Build a brand-new 16-byte ULID for the given millisecond."""
    timestamp = int.to_bytes(ms, TIMESTAMP_LEN, "big")
    randomness = os.urandom(RANDOMNESS_LEN)
    return timestamp + randomness
