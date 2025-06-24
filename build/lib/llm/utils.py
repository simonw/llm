import click
import httpx
import json
import puremagic
import re
import textwrap
from typing import List, Dict, Optional

MIME_TYPE_FIXES = {
    "audio/wave": "audio/wav",
}


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
