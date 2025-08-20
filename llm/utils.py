import click
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


# --- Universal HTTP Logging System ---


class HTTPColorFormatter(logging.Formatter):
    """
    Custom formatter for HTTP logging with colors and improved readability.
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
    }

    # Logger-specific colors
    LOGGER_COLORS = {
        "httpx": "\033[94m",  # Light blue
        "httpcore": "\033[90m",  # Dark gray
        "openai": "\033[92m",  # Light green
        "anthropic": "\033[95m",  # Light magenta
        "llm.http": "\033[96m",  # Light cyan
    }

    def __init__(self, use_colors=True):
        super().__init__()
        self.use_colors = use_colors and self._supports_color()

    def _supports_color(self):
        """Check if the terminal supports color output."""
        import os
        import sys

        # Check if we're in a terminal that supports colors
        if hasattr(sys.stderr, "isatty") and sys.stderr.isatty():
            # Check common environment variables
            term = os.environ.get("TERM", "")
            if "color" in term or term in ("xterm", "xterm-256color", "screen", "tmux"):
                return True
            # Check for NO_COLOR environment variable
            if os.environ.get("NO_COLOR"):
                return False
            # Default to True for most terminals
            return True
        return False

    def format(self, record):
        if not self.use_colors:
            return self._format_plain(record)

        # Get colors
        level_color = self.COLORS.get(record.levelname, "")
        logger_color = self.LOGGER_COLORS.get(record.name.split(".")[0], "")
        reset = self.COLORS["RESET"]
        bold = self.COLORS["BOLD"]
        dim = self.COLORS["DIM"]

        # Format timestamp
        timestamp = self.formatTime(record, "%H:%M:%S")

        # Format logger name with color
        logger_name = record.name
        if logger_color:
            logger_name = f"{logger_color}{logger_name}{reset}"

        # Format level with color
        level = record.levelname
        if level_color:
            level = f"{level_color}{bold}{level}{reset}"

        # Format message with special handling for HTTP-specific content
        message = record.getMessage()
        message = self._colorize_message(message, record.name)

        # Assemble final format
        return f"{dim}[{timestamp}]{reset} {level} {logger_name} - {message}"

    def _format_plain(self, record):
        """Plain formatting without colors."""
        timestamp = self.formatTime(record, "%H:%M:%S")
        return f"[{timestamp}] {record.levelname} {record.name} - {record.getMessage()}"

    def _colorize_message(self, message, logger_name):
        """Add color highlights to HTTP-specific message content."""
        if not self.use_colors:
            return message

        reset = self.COLORS["RESET"]

        # Highlight HTTP methods
        for method in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]:
            message = message.replace(
                f" {method} ", f' {self.COLORS["BOLD"]}{method}{reset} '
            )

        # Highlight HTTP status codes
        import re

        # Success status codes (2xx) - green
        message = re.sub(r"\b(2\d\d)\b", f'{self.COLORS["DEBUG"]}\\1{reset}', message)

        # Client error status codes (4xx) - yellow
        message = re.sub(r"\b(4\d\d)\b", f'{self.COLORS["WARNING"]}\\1{reset}', message)

        # Server error status codes (5xx) - red
        message = re.sub(r"\b(5\d\d)\b", f'{self.COLORS["ERROR"]}\\1{reset}', message)

        # Highlight URLs
        message = re.sub(
            r'(https?://[^\s"]+)', f'{self.COLORS["DIM"]}\\1{reset}', message
        )

        # Highlight important headers
        for header in ["Authorization", "Content-Type", "User-Agent"]:
            message = message.replace(
                f"'{header}'", f"'{self.COLORS['BOLD']}{header}{reset}'"
            )
            message = message.replace(
                f'"{header}"', f'"{self.COLORS["BOLD"]}{header}{reset}"'
            )

        # Highlight connection events for httpcore
        if "httpcore" in logger_name:
            for event in [
                "connect_tcp",
                "start_tls",
                "send_request",
                "receive_response",
            ]:
                if event in message:
                    message = message.replace(
                        event, f'{self.COLORS["BOLD"]}{event}{reset}'
                    )

        return message


def _get_http_logging_config():
    """
    Determine HTTP logging configuration from environment variables.

    Returns:
        dict: Configuration with 'enabled', 'level', 'format' and 'use_colors' keys
    """
    import os

    # Check various environment variables for HTTP logging
    enabled = bool(
        os.environ.get("LLM_HTTP_LOGGING")
        or os.environ.get("LLM_HTTP_DEBUG")
        or os.environ.get("LLM_HTTP_VERBOSE")
        or os.environ.get("LLM_OPENAI_SHOW_RESPONSES")  # Backward compatibility
    )

    if not enabled:
        return {"enabled": False}

    # Determine logging level
    level = "INFO"
    if os.environ.get("LLM_HTTP_DEBUG") or os.environ.get("LLM_HTTP_VERBOSE"):
        level = "DEBUG"

    return {
        "enabled": True,
        "level": level,
        # Provide a standard logging format description for reference
        "format": "%(name)s - %(levelname)s - %(message)s",
        "use_colors": not os.environ.get("NO_COLOR"),
    }


def configure_http_logging():
    """
    Configure Python logging for HTTP requests across all providers.

    This enables logging for:
    - httpx: High-level HTTP client logs
    - httpcore: Low-level HTTP connection logs
    - openai: OpenAI SDK logs
    - anthropic: Anthropic SDK logs

    Environment variables:
    - LLM_HTTP_LOGGING=1: Enable INFO-level HTTP logging
    - LLM_HTTP_DEBUG=1: Enable DEBUG-level HTTP logging
    - LLM_HTTP_VERBOSE=1: Enable DEBUG-level HTTP logging
    - LLM_OPENAI_SHOW_RESPONSES=1: Backward compatibility (INFO level)
    """
    import logging
    import os

    config = _get_http_logging_config()
    if not config["enabled"]:
        return

    # Create our custom formatter
    formatter = HTTPColorFormatter(use_colors=config.get("use_colors", True))

    # Configure root logger if not already configured
    if not logging.getLogger().handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.WARNING)  # Keep root logger quiet

    # Set up HTTP-related loggers
    log_level = getattr(logging, config["level"])

    # Core HTTP libraries
    logging.getLogger("httpx").setLevel(log_level)
    logging.getLogger("httpcore").setLevel(log_level)

    # Provider SDKs
    logging.getLogger("openai").setLevel(log_level)
    logging.getLogger("anthropic").setLevel(log_level)

    # Additional useful loggers
    if config["level"] == "DEBUG":
        logging.getLogger("urllib3").setLevel(log_level)
        logging.getLogger("requests").setLevel(log_level)

    # Configure all HTTP loggers to use our custom formatter
    http_loggers = ["httpx", "httpcore", "openai", "anthropic", "llm.http"]
    if config["level"] == "DEBUG":
        http_loggers.extend(["urllib3", "requests"])

    for logger_name in http_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(log_level)

        # If this logger doesn't have handlers, add our custom handler
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.propagate = False

    # Log that HTTP logging is enabled
    logging.getLogger("llm.http").info(
        f"HTTP logging enabled at {config['level']} level"
    )


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
