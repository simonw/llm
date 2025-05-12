import click
import hashlib
import httpx
import json
import pathlib
import puremagic
import re
import sqlite_utils
import textwrap
from typing import Any, List, Dict, Optional, Tuple

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


def output_rows_as_json(rows, nl=False):
    """
    Output rows as JSON - either newline-delimited or an array

    Parameters:
    - rows: List of dictionaries to output
    - nl: Boolean, if True, use newline-delimited JSON

    Returns:
    - String with formatted JSON output
    """
    if not rows:
        return "" if nl else "[]"

    lines = []
    end_i = len(rows) - 1
    for i, row in enumerate(rows):
        is_first = i == 0
        is_last = i == end_i

        line = "{firstchar}{serialized}{maybecomma}{lastchar}".format(
            firstchar=("[" if is_first else " ") if not nl else "",
            serialized=json.dumps(row),
            maybecomma="," if (not nl and not is_last) else "",
            lastchar="]" if (is_last and not nl) else "",
        )
        lines.append(line)

    return "\n".join(lines)


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
    insert into tools (hash, name, description, input_schema)
    values (:hash, :name, :description, :input_schema)
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
