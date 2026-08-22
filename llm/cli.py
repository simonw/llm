import asyncio
import base64
import inspect
import io
import json
import os
import pathlib
import re
import readline
import shutil
import sqlite3
import sys
import textwrap
import warnings
from collections.abc import Iterable
from dataclasses import asdict
from importlib.metadata import version
from runpy import run_module
from typing import Any, cast

import click
import httpx2
import pydantic
import sqlite_utils
import yaml
from click_default_group import DefaultGroup
from sqlite_utils.utils import Format, rows_from_file

from llm import (
    AsyncConversation,
    AsyncKeyModel,
    AsyncResponse,
    Attachment,
    CancelToolCall,
    Collection,
    Conversation,
    Fragment,
    KeyModel,
    Response,
    ServerSideTool,
    Template,
    Tool,
    Toolbox,
    UnknownModelError,
    encode,
    get_async_model,
    get_default_embedding_model,
    get_default_model,
    get_embedding_model,
    get_embedding_model_aliases,
    get_embedding_models_with_aliases,
    get_fragment_loaders,
    get_model,
    get_model_aliases,
    get_models_with_aliases,
    get_plugins,
    get_template_loaders,
    get_tools,
    remove_alias,
    set_alias,
    set_default_embedding_model,
    set_default_model,
    user_dir,
)
from llm.models import ChainResponse, _BaseChainResponse, _BaseConversation

from .logs import (
    LogStore,
    legacy_log_row_extras,
    log_row_extras,
    merged_log_rows,
)
from .migrations import migrate
from .plugins import load_plugins, pm
from .utils import (
    ensure_fragment,
    extract_fenced_code_block,
    find_unused_key,
    has_plugin_prefix,
    instantiate_from_spec,
    make_schema_id,
    maybe_fenced_code,
    mimetype_from_path,
    mimetype_from_string,
    multi_schema,
    output_rows_as_json,
    resolve_schema_input,
    schema_dsl,
    schema_summary,
    token_usage_string,
    truncate_string,
)

warnings.simplefilter("ignore", ResourceWarning)

DEFAULT_TEMPLATE = "prompt: "


class FragmentNotFound(Exception):
    pass


def display_stream_events(events, *, show_reasoning=True):
    """Consume a sync iterator of StreamEvents and write them.

    Text events go to stdout. Reasoning events go to stderr in dim style.
    A newline is written to stderr at each reasoning→text transition so
    the assistant text starts on a fresh visual line.
    """
    was_reasoning = False
    for event in events:
        if event.type == "text":
            if was_reasoning and show_reasoning:
                click.echo("", err=True)
                was_reasoning = False
            click.echo(event.chunk, nl=False)
        elif event.type == "reasoning" and show_reasoning:
            was_reasoning = True
            click.echo(click.style(event.chunk, dim=True), nl=False, err=True)


async def display_async_stream_events(events, *, show_reasoning=True):
    """Async counterpart of display_stream_events."""
    was_reasoning = False
    async for event in events:
        if event.type == "text":
            if was_reasoning and show_reasoning:
                click.echo("", err=True)
                was_reasoning = False
            click.echo(event.chunk, nl=False)
        elif event.type == "reasoning" and show_reasoning:
            was_reasoning = True
            click.echo(click.style(event.chunk, dim=True), nl=False, err=True)


def _run_chat(
    model_label,
    prompt_callback,
    *,
    db=None,
    initial_fragments=None,
    initial_attachments=None,
    transform_prompt=None,
    after_response=None,
    show_reasoning=True,
):
    """Run the terminal chat loop shared by managed and transient models."""
    click.echo(f"Chatting with {model_label}")
    click.echo("Type 'exit' or 'quit' to exit")
    click.echo("Type '!multi' to enter multiple lines, then '!end' to finish")
    click.echo("Type '!edit' to open your default editor and modify the prompt")
    if db is not None:
        click.echo(
            "Type '!fragment <my_fragment> [<another_fragment> ...]' to insert one or more fragments"
        )

    argument_fragments = list(initial_fragments or [])
    argument_attachments = list(initial_attachments or [])
    in_multi = False
    accumulated = []
    accumulated_fragments = []
    accumulated_attachments = []
    end_token = "!end"

    while True:
        prompt = click.prompt("", prompt_suffix="> " if not in_multi else "")
        fragments = []
        attachments = []
        if argument_fragments:
            fragments += argument_fragments
            # Fragments from command options are added to the first message only.
            argument_fragments = []
        if argument_attachments:
            attachments = argument_attachments
            argument_attachments = []
        if prompt.strip().startswith("!multi"):
            in_multi = True
            bits = prompt.strip().split()
            if len(bits) > 1:
                end_token = "!end {}".format(" ".join(bits[1:]))
            continue
        if prompt.strip() == "!edit":
            edited_prompt = click.edit()
            if edited_prompt is None:
                click.echo("Editor closed without saving.", err=True)
                continue
            prompt = edited_prompt.strip()
        if db is not None and prompt.strip().startswith("!fragment "):
            prompt, fragments, attachments = process_fragments_in_chat(db, prompt)

        if in_multi:
            if prompt.strip() == end_token:
                prompt = "\n".join(accumulated)
                fragments = accumulated_fragments
                attachments = accumulated_attachments
                in_multi = False
                accumulated = []
                accumulated_fragments = []
                accumulated_attachments = []
            else:
                if prompt:
                    accumulated.append(prompt)
                accumulated_fragments += fragments
                accumulated_attachments += attachments
                continue

        if prompt.strip() in ("exit", "quit"):
            break
        if transform_prompt is not None:
            prompt = transform_prompt(prompt)

        response = prompt_callback(prompt, fragments, attachments)
        display_stream_events(
            response.stream_events(),
            show_reasoning=show_reasoning,
        )
        if after_response is not None:
            after_response(response)
        print()


def validate_fragment_alias(ctx, param, value):
    if not re.match(r"^[a-zA-Z0-9_-]+$", value):
        raise click.BadParameter("Fragment alias must be alphanumeric")
    return value


def resolve_fragments(
    db: sqlite_utils.Database, fragments: Iterable[str], allow_attachments: bool = False
) -> list[Fragment | Attachment]:
    """
    Resolve fragment strings into a mixed of llm.Fragment() and llm.Attachment() objects.
    """

    def _load_by_alias(fragment: str) -> tuple[str | None, str | None]:
        rows = list(
            db.query(
                """
                select content, source from fragments
                left join fragment_aliases on fragments.id = fragment_aliases.fragment_id
                where alias = :alias or hash = :alias limit 1
                """,
                {"alias": fragment},
            )
        )
        if rows:
            row = rows[0]
            return row["content"], row["source"]
        return None, None

    # The fragment strings could be URLs or paths or plugin references
    resolved: list[Fragment | Attachment] = []
    for fragment in fragments:
        if fragment.startswith(("http://", "https://")):
            llm_version = version("llm")
            headers = {"User-Agent": f"llm/{llm_version} (https://llm.datasette.io/)"}
            client = httpx2.Client(
                follow_redirects=True, max_redirects=3, headers=headers
            )
            response = client.get(fragment)
            response.raise_for_status()
            resolved.append(Fragment(response.text, fragment))
        elif fragment == "-":
            resolved.append(Fragment(sys.stdin.read(), "-"))
        elif has_plugin_prefix(fragment) and not pathlib.Path(fragment).exists():
            prefix, rest = fragment.split(":", 1)
            loaders = get_fragment_loaders()
            if prefix not in loaders:
                raise FragmentNotFound(f"Unknown fragment prefix: {prefix}")
            loader = loaders[prefix]
            try:
                result = loader(rest)
                if not isinstance(result, list):
                    result = [result]
                if not allow_attachments and any(
                    isinstance(r, Attachment) for r in result
                ):
                    raise FragmentNotFound(
                        f"Fragment loader {prefix} returned a disallowed attachment"
                    )
                resolved.extend(result)
            except Exception as ex:  # noqa: BLE001
                raise FragmentNotFound(f"Could not load fragment {fragment}: {ex}")
        else:
            # Try from the DB
            content, source = _load_by_alias(fragment)
            if content is not None:
                resolved.append(Fragment(content, source))
            else:
                # Now try path
                path = pathlib.Path(fragment)
                if path.exists():
                    resolved.append(Fragment(path.read_text(), str(path.resolve())))
                else:
                    raise FragmentNotFound(f"Fragment '{fragment}' not found")
    return resolved


def process_fragments_in_chat(
    db: sqlite_utils.Database, prompt: str
) -> tuple[str, list[Fragment], list[Attachment]]:
    """
    Process any !fragment commands in a chat prompt and return the modified prompt plus resolved fragments and attachments.
    """
    prompt_lines = []
    fragments = []
    attachments = []
    for line in prompt.splitlines():
        if line.startswith("!fragment "):
            try:
                fragment_strs = line.strip().removeprefix("!fragment ").split()
                fragments_and_attachments = resolve_fragments(
                    db, fragments=fragment_strs, allow_attachments=True
                )
                fragments += [
                    fragment
                    for fragment in fragments_and_attachments
                    if isinstance(fragment, Fragment)
                ]
                attachments += [
                    attachment
                    for attachment in fragments_and_attachments
                    if isinstance(attachment, Attachment)
                ]
            except FragmentNotFound as ex:
                raise click.ClickException(str(ex))
        else:
            prompt_lines.append(line)
    return "\n".join(prompt_lines), fragments, attachments


class AttachmentError(Exception):
    """Exception raised for errors in attachment resolution."""


def resolve_attachment(value):
    """
    Resolve an attachment from a string value which could be:
    - "-" for stdin
    - A URL
    - A file path

    Returns an Attachment object.
    Raises AttachmentError if the attachment cannot be resolved.
    """
    if value == "-":
        content = sys.stdin.buffer.read()
        # Try to guess type
        mimetype = mimetype_from_string(content)
        if mimetype is None:
            raise AttachmentError("Could not determine mimetype of stdin")
        return Attachment(type=mimetype, path=None, url=None, content=content)

    if "://" in value:
        # Confirm URL exists and try to guess type
        try:
            response = httpx2.head(value)
            response.raise_for_status()
            mimetype = response.headers.get("content-type")
        except httpx2.HTTPError as ex:
            raise AttachmentError(str(ex))
        return Attachment(type=mimetype, path=None, url=value, content=None)

    # Check that the file exists
    path = pathlib.Path(value)
    if not path.exists():
        raise AttachmentError(f"File {value} does not exist")
    path = path.resolve()

    # Try to guess type
    mimetype = mimetype_from_path(str(path))
    if mimetype is None:
        raise AttachmentError(f"Could not determine mimetype of {value}")

    return Attachment(type=mimetype, path=str(path), url=None, content=None)


class AttachmentType(click.ParamType):
    name = "attachment"

    def convert(self, value, param, ctx):
        try:
            return resolve_attachment(value)
        except AttachmentError as e:
            self.fail(str(e), param, ctx)


def resolve_attachment_with_type(value: str, mimetype: str) -> Attachment:
    if "://" in value:
        attachment = Attachment(mimetype, None, value, None)
    elif value == "-":
        content = sys.stdin.buffer.read()
        attachment = Attachment(mimetype, None, None, content)
    else:
        # Look for file
        path = pathlib.Path(value)
        if not path.exists():
            raise click.BadParameter(f"File {value} does not exist")
        path = path.resolve()
        attachment = Attachment(mimetype, str(path), None, None)
    return attachment


def attachment_types_callback(ctx, param, values) -> list[Attachment]:
    collected = []
    for value, mimetype in values:
        collected.append(resolve_attachment_with_type(value, mimetype))
    return collected


def _apply_template(template, prompt, params, system):
    """Apply a loaded template to a prompt and system prompt."""
    try:
        uses_input = "input" in template.vars()
        input_ = prompt if uses_input else ""
        template_prompt, template_system = template.evaluate(input_, params)
    except Template.MissingVariables as ex:
        raise click.ClickException(str(ex))
    if template_system and not system:
        system = template_system
    if template_prompt:
        if prompt and not uses_input:
            prompt = f"{template_prompt}\n{prompt}"
        else:
            prompt = template_prompt
    return prompt, system


def _merge_template_options(template, options):
    """Add template options unless the same option was provided explicitly."""
    merged_options = list(options)
    specified_options = dict(merged_options)
    for option_name, option_value in (template.options or {}).items():
        if option_name not in specified_options:
            merged_options.append((option_name, option_value))
    return merged_options


def _merge_template_attachments(template, attachments, attachment_types):
    """Resolve and prepend attachments declared by a loaded template."""
    if template.attachments:
        attachments = [
            resolve_attachment(value) for value in template.attachments
        ] + list(attachments)
    if template.attachment_types:
        attachment_types = [
            resolve_attachment_with_type(item.value, item.type)
            for item in template.attachment_types
        ] + list(attachment_types)
    return attachments, attachment_types


def _merge_template_tools(template, tools, python_tools):
    """Prepend trusted tool definitions declared by a loaded template."""
    if template.tools:
        tools = [*template.tools, *tools]
    if template.functions and template._functions_is_trusted:
        python_tools = [template.functions, *python_tools]
    return tools, python_tools


def json_validator(object_name):
    def validator(ctx, param, value):
        if value is None:
            return value
        try:
            obj = json.loads(value)
            if not isinstance(obj, dict):
                raise click.BadParameter(f"{object_name} must be a JSON object")
            return obj
        except json.JSONDecodeError:
            raise click.BadParameter(f"{object_name} must be valid JSON")

    return validator


def schema_option(fn):
    click.option(
        "schema_input",
        "--schema",
        help="Schema DSL, JSON schema, filepath or ID",
    )(fn)
    return fn


def tool_options(fn):
    """Add the shared CLI options for selecting and executing tools."""
    decorators = (
        click.option(
            "tools",
            "-T",
            "--tool",
            multiple=True,
            help="Name of a tool to make available to the model",
        ),
        click.option(
            "python_tools",
            "--functions",
            multiple=True,
            help="Python code block or file path defining functions to register as tools",
        ),
        click.option(
            "tools_debug",
            "--td",
            "--tools-debug",
            is_flag=True,
            help="Show full details of tool executions",
            envvar="LLM_TOOLS_DEBUG",
        ),
        click.option(
            "tools_approve",
            "--ta",
            "--tools-approve",
            is_flag=True,
            help="Manually approve every tool execution",
        ),
        click.option(
            "chain_limit",
            "--cl",
            "--chain-limit",
            type=int,
            default=5,
            help=(
                "How many chained tool responses to allow, "
                "default 5, set 0 for unlimited"
            ),
        ),
    )
    for decorator in reversed(decorators):
        fn = decorator(fn)
    return fn


@click.group(
    cls=DefaultGroup,
    default="prompt",
    default_if_no_args=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option()
def cli():
    """
    Access Large Language Models from the command-line

    Documentation: https://llm.datasette.io/

    LLM can run models from many different providers. Consult the
    plugin directory for a list of available models:

    https://llm.datasette.io/en/stable/plugins/directory.html

    To get started with OpenAI, obtain an API key from them and:

    \b
        $ llm keys set openai
        Enter key: ...

    Then execute a prompt like this:

        llm 'Five outrageous names for a pet pelican'

    For a full list of prompting options run:

        llm prompt --help
    """


@cli.command(name="prompt")
@click.argument("prompt", required=False)
@click.option("-s", "--system", help="System prompt to use")
@click.option("model_id", "-m", "--model", help="Model to use", envvar="LLM_MODEL")
@click.option(
    "-d",
    "--database",
    type=click.Path(readable=True, dir_okay=False),
    help="Path to log database",
)
@click.option(
    "queries",
    "-q",
    "--query",
    multiple=True,
    help="Use first model matching these strings",
)
@click.option(
    "attachments",
    "-a",
    "--attachment",
    type=AttachmentType(),
    multiple=True,
    help="Attachment path or URL or -",
)
@click.option(
    "attachment_types",
    "--at",
    "--attachment-type",
    type=(str, str),
    multiple=True,
    callback=attachment_types_callback,
    help="\b\nAttachment with explicit mimetype,\n--at image.jpg image/jpeg",
)
@tool_options
@click.option(
    "options",
    "-o",
    "--option",
    type=(str, str),
    multiple=True,
    help="key/value options for the model",
)
@click.option(
    "show_model_options",
    "--options",
    is_flag=True,
    help="Show options for the selected model",
)
@schema_option
@click.option(
    "--schema-multi",
    help="Schema for multiple results",
)
@click.option(
    "fragments",
    "-f",
    "--fragment",
    multiple=True,
    help="Fragment (alias, URL, hash or file path) to add to the prompt",
)
@click.option(
    "system_fragments",
    "--sf",
    "--system-fragment",
    multiple=True,
    help="Fragment to add to system prompt",
)
@click.option(
    "-t",
    "--template",
    multiple=True,
    help="Template to use; can be repeated to combine templates",
)
@click.option(
    "-p",
    "--param",
    multiple=True,
    type=(str, str),
    help="Parameters for template",
)
@click.option("--no-stream", is_flag=True, help="Do not stream output")
@click.option("-n", "--no-log", is_flag=True, help="Don't log to database")
@click.option("--log", is_flag=True, help="Log prompt and response to the database")
@click.option("-R", "--hide-reasoning", is_flag=True, help="Hide reasoning output")
@click.option(
    "_continue",
    "-c",
    "--continue",
    is_flag=True,
    flag_value=-1,
    help="Continue the most recent conversation.",
)
@click.option(
    "conversation_id",
    "--cid",
    "--conversation",
    help="Continue the conversation with the given ID.",
)
@click.option("--key", help="API key to use")
@click.option("--save", help="Save prompt with this template name")
@click.option("async_", "--async", is_flag=True, help="Run prompt asynchronously")
@click.option("-u", "--usage", is_flag=True, help="Show token usage")
@click.option("-x", "--extract", is_flag=True, help="Extract first fenced code block")
@click.option(
    "extract_last",
    "--xl",
    "--extract-last",
    is_flag=True,
    help="Extract last fenced code block",
)
@click.option(
    "json_output",
    "--json",
    is_flag=True,
    help="Output the response as JSON, same format as llm logs --json",
)
def prompt(
    prompt,
    system,
    model_id,
    database,
    queries,
    attachments,
    attachment_types,
    tools,
    python_tools,
    tools_debug,
    tools_approve,
    chain_limit,
    options,
    show_model_options,
    schema_input,
    schema_multi,
    fragments,
    system_fragments,
    template,
    param,
    no_stream,
    no_log,
    log,
    hide_reasoning,
    _continue,
    conversation_id,
    key,
    save,
    async_,
    usage,
    extract,
    extract_last,
    json_output,
):
    """
    Execute a prompt

    Documentation: https://llm.datasette.io/en/stable/usage.html

    Examples:

    \b
        llm 'Capital of France?'
        llm 'Capital of France?' -m gpt-5.5
        llm 'Capital of France?' -s 'answer in Spanish'

    Multi-modal models can be called with attachments like this:

    \b
        llm 'Extract text from this image' -a image.jpg
        llm 'Describe' -a https://static.simonwillison.net/static/2024/pelicans.jpg
        cat image | llm 'describe image' -a -
        # With an explicit mimetype:
        cat image | llm 'describe image' --at - image/jpeg

    Structured output schemas:

    Use --schema to request one JSON object, or --schema-multi to request
    multiple objects returned in an "items" array. Both options accept a
    concise schema DSL. Define each field as NAME [TYPE]: DESCRIPTION, with
    the type and description both optional. Separate fields with commas:

    \b
        llm --schema 'name, age int, active bool' 'Invent a dog'

    Supported types are str, int, float and bool. The default is str and every
    listed field is required. Descriptions provide extra instructions to the
    model. Use one field per line if descriptions contain commas:

    \b
        llm --schema-multi '
        name: the dog's name
        age int: the dog's age in years
        bio: a short bio, no more than three sentences
        ' 'Invent three dogs'

    JSON Schema is also accepted.

    The -x/--extract option returns just the content of the first ``` fenced code
    block, if one is present. If none are present it returns the full response.

    \b
        llm 'JavaScript function for reversing a string' -x
    """
    if log and no_log:
        raise click.ClickException("--log and --no-log are mutually exclusive")

    if queries and not model_id:
        # Use -q options to find model with shortest model_id
        matches = []
        for model_with_aliases in get_models_with_aliases():
            if all(model_with_aliases.matches(q) for q in queries):
                matches.append(model_with_aliases.model.model_id)
        if not matches:
            raise click.ClickException(
                "No model found matching queries {}".format(", ".join(queries))
            )
        model_id = min(matches, key=len)

    if show_model_options and not (conversation_id or _continue or template):
        model_id = model_id or get_default_model()
        try:
            if async_:
                get_async_model(model_id)
            else:
                get_model(model_id)
        except UnknownModelError as ex:
            raise click.ClickException(ex)
        click.echo(render_model_with_options(model_id, async_=async_))
        return

    log_path = pathlib.Path(database) if database else logs_db_path()
    (log_path.parent).mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(log_path)
    migrate(db)

    if schema_multi:
        schema_input = schema_multi

    schema = resolve_schema_input(db, schema_input, load_template)

    if schema_multi:
        # Convert that schema into multiple "items" of the same schema
        schema = multi_schema(schema)

    def read_prompt():
        nonlocal prompt, schema

        # Is there extra prompt available on stdin?
        stdin_prompt = None
        if not sys.stdin.isatty():
            stdin_prompt = sys.stdin.read()

        if stdin_prompt:
            bits = [stdin_prompt]
            if prompt:
                bits.append(prompt)
            prompt = " ".join(bits)

        if (
            prompt is None
            and not save
            and sys.stdin.isatty()
            and not attachments
            and not attachment_types
            and not schema
            and not fragments
        ):
            # Hang waiting for input to stdin (unless --save)
            prompt = sys.stdin.read()
        return prompt

    if save:
        # We are saving their prompt/system/etc to a new template
        # Fields to save: prompt, system, model - and more in the future
        disallowed_options = []
        for option, var in (
            ("--template", template),
            ("--continue", _continue),
            ("--cid", conversation_id),
        ):
            if var:
                disallowed_options.append(option)
        if disallowed_options:
            raise click.ClickException(
                "--save cannot be used with {}".format(", ".join(disallowed_options))
            )
        path = template_dir() / f"{save}.yaml"
        to_save = {}
        if model_id:
            model_aliases = get_model_aliases()
            try:
                to_save["model"] = model_aliases[model_id].model_id
            except KeyError:
                raise click.ClickException(f"'{model_id}' is not a known model")
        prompt = read_prompt()
        if prompt:
            to_save["prompt"] = prompt
        if system:
            to_save["system"] = system
        if param:
            to_save["defaults"] = dict(param)
        if extract:
            to_save["extract"] = True
        if extract_last:
            to_save["extract_last"] = True
        if schema:
            to_save["schema_object"] = schema
        if fragments:
            to_save["fragments"] = list(fragments)
        if system_fragments:
            to_save["system_fragments"] = list(system_fragments)
        if python_tools:
            to_save["functions"] = "\n\n".join(python_tools)
        if tools:
            to_save["tools"] = list(tools)
        if attachments:
            # Only works for attachments with a path or url
            to_save["attachments"] = [
                (a.path or a.url) for a in attachments if (a.path or a.url)
            ]
        if attachment_types:
            to_save["attachment_types"] = [
                {"type": a.type, "value": a.path or a.url}
                for a in attachment_types
                if (a.path or a.url)
            ]
        if options:
            # Need to validate and convert their types first
            model = get_model(model_id or get_default_model())
            try:
                options_model = model.Options(**dict(options))
                # Use model_dump(mode="json") so Enums become their .value strings
                to_save["options"] = {
                    k: v
                    for k, v in options_model.model_dump(mode="json").items()
                    if v is not None
                }
            except pydantic.ValidationError as ex:
                raise click.ClickException(render_errors(ex.errors()))
        path.write_text(
            yaml.safe_dump(
                to_save,
                indent=4,
                default_flow_style=False,
                sort_keys=False,
            ),
            "utf-8",
        )
        return

    if template:
        params = dict(param)
        template_objs = []
        for template_name in template:
            try:
                template_objs.append(load_template(template_name))
            except LoadTemplateError as ex:
                raise click.ClickException(str(ex))

        # Prepend list-valued fields in template order, ahead of CLI values
        for template_obj in reversed(template_objs):
            if template_obj.fragments:
                fragments = [*template_obj.fragments, *fragments]
            if template_obj.system_fragments:
                system_fragments = [
                    *template_obj.system_fragments,
                    *system_fragments,
                ]
            tools, python_tools = _merge_template_tools(
                template_obj, tools, python_tools
            )

        # Read stdin before applying the first template so templates compose
        # from left to right, with each one receiving the previous result.
        if any("input" in template_obj.vars() for template_obj in template_objs):
            prompt = read_prompt()

        for template_obj in template_objs:
            if not (extract or extract_last):
                extract = template_obj.extract
                extract_last = template_obj.extract_last
            if template_obj.schema_object:
                schema = template_obj.schema_object
            if template_obj.options:
                options = _merge_template_options(template_obj, options)
            prompt, system = _apply_template(template_obj, prompt, params, system)
            if model_id is None and template_obj.model:
                model_id = template_obj.model

        # Like fragments and tools, template attachments precede CLI values
        # and retain the order in which their templates were specified.
        for template_obj in reversed(template_objs):
            attachments, attachment_types = _merge_template_attachments(
                template_obj, attachments, attachment_types
            )
    if extract or extract_last or json_output:
        no_stream = True

    conversation = None
    if conversation_id or _continue:
        # Load the conversation - loads most recent if no ID provided
        try:
            conversation = load_conversation(
                conversation_id, async_=async_, database=database
            )
        except UnknownModelError as ex:
            raise click.ClickException(str(ex))

    if conversation_tools := _get_conversation_tools(conversation, tools):
        tools = conversation_tools

    # Figure out which model we are using
    if model_id is None:
        if conversation:
            model_id = conversation.model.model_id
        else:
            model_id = get_default_model()

    # Now resolve the model
    try:
        if async_:
            model = get_async_model(model_id)
        else:
            model = get_model(model_id)
    except UnknownModelError as ex:
        raise click.ClickException(ex)

    if show_model_options:
        click.echo(render_model_with_options(model_id, async_=async_))
        return

    if conversation is None:
        # Always work through a conversation, even for a one-off prompt.
        # The legacy logger invents one anyway and throws the id away;
        # creating it here means both writers agree on which conversation
        # (and so which thread) this response belongs to.
        conversation = model.conversation()

    if conversation:
        # To ensure it can see the key
        conversation.model = model

    # Validate options
    validated_options = {}
    if options:
        # Validate with pydantic
        try:
            validated_options = {
                key: value
                for key, value in model.Options(**dict(options))
                if value is not None
            }
        except pydantic.ValidationError as ex:
            raise click.ClickException(render_errors(ex.errors()))

    # Add on any default model options
    default_options = get_model_options(model.model_id)
    for key_, value in default_options.items():
        if key_ not in validated_options:
            validated_options[key_] = value

    kwargs = {}

    resolved_attachments = [*attachments, *attachment_types]

    should_stream = model.can_stream and not no_stream
    if not should_stream:
        kwargs["stream"] = False

    if isinstance(model, (KeyModel, AsyncKeyModel)):
        kwargs["key"] = key

    prompt = read_prompt()
    response = None

    try:
        fragments_and_attachments = resolve_fragments(
            db, fragments, allow_attachments=True
        )
        resolved_fragments = [
            fragment
            for fragment in fragments_and_attachments
            if isinstance(fragment, Fragment)
        ]
        resolved_attachments.extend(
            attachment
            for attachment in fragments_and_attachments
            if isinstance(attachment, Attachment)
        )
        resolved_system_fragments = resolve_fragments(db, system_fragments)
    except FragmentNotFound as ex:
        raise click.ClickException(str(ex))

    prompt_method = model.prompt
    if conversation:
        prompt_method = conversation.prompt

    tool_kwargs = _tool_chain_kwargs(
        tools, python_tools, tools_debug, tools_approve, chain_limit, model=model
    )
    if tool_kwargs:
        prompt_method = conversation.chain
        kwargs["options"] = validated_options
        kwargs.update(tool_kwargs)
    else:
        # Merge in options for the .prompt() methods
        kwargs.update(validated_options)

    if hide_reasoning:
        kwargs["hide_reasoning"] = True

    try:
        if async_:

            async def inner():
                if should_stream:
                    response = prompt_method(
                        prompt,
                        attachments=resolved_attachments,
                        system=system,
                        schema=schema,
                        fragments=resolved_fragments,
                        system_fragments=resolved_system_fragments,
                        **kwargs,
                    )
                    await display_async_stream_events(
                        response.astream_events(),
                        show_reasoning=not hide_reasoning,
                    )
                    print()
                else:
                    response = prompt_method(
                        prompt,
                        fragments=resolved_fragments,
                        attachments=resolved_attachments,
                        schema=schema,
                        system=system,
                        system_fragments=resolved_system_fragments,
                        **kwargs,
                    )
                    text = await response.text()
                    if extract or extract_last:
                        text = (
                            extract_fenced_code_block(text, last=extract_last) or text
                        )
                    if not json_output:
                        print(text)
                return response

            response = asyncio.run(inner())
        else:
            response = prompt_method(
                prompt,
                fragments=resolved_fragments,
                attachments=resolved_attachments,
                system=system,
                schema=schema,
                system_fragments=resolved_system_fragments,
                **kwargs,
            )
            if should_stream:
                display_stream_events(
                    response.stream_events(),
                    show_reasoning=not hide_reasoning,
                )
                print()
            else:
                text = response.text()
                if extract or extract_last:
                    text = extract_fenced_code_block(text, last=extract_last) or text
                if not json_output:
                    print(text)
    # List of exceptions that should never be raised in pytest:
    except (ValueError, NotImplementedError) as ex:
        raise click.ClickException(str(ex))
    except Exception as ex:
        # All other exceptions should raise in pytest, show to user otherwise
        if getattr(sys, "_called_from_test", False) or os.environ.get(
            "LLM_RAISE_ERRORS", None
        ):
            raise
        raise click.ClickException(str(ex))

    if usage:
        if isinstance(response, ChainResponse):
            responses = response._responses
        else:
            responses = [response]
        for response_object in responses:
            # Show token usage to stderr in yellow
            click.echo(
                click.style(
                    f"Token usage: {response_object.token_usage()}",
                    fg="yellow",
                    bold=True,
                ),
                err=True,
            )

    # Log responses to the database
    log_db = None
    if (logs_on() or log) and not no_log:
        log_db = db
    elif json_output:
        # --json needs logged rows, so use a temporary in-memory database
        log_db = sqlite_utils.Database(memory=True)
        migrate(log_db)

    if log_db is not None:
        # Could be Response, AsyncResponse, ChainResponse, AsyncChainResponse
        if isinstance(response, AsyncResponse):
            response = asyncio.run(response.to_sync_response())
        # At this point ALL forms should have a log_to_db() method that works:
        response.log_to_db(log_db)

    if json_output:
        if isinstance(response, _BaseChainResponse):
            response_ids = [response_.id for response_ in response._responses]
        else:
            response_ids = [response.id]
        click.echo(logs_json_for_response_ids(log_db, response_ids))


@cli.command()
@click.option("-s", "--system", help="System prompt to use")
@click.option("model_id", "-m", "--model", help="Model to use", envvar="LLM_MODEL")
@click.option(
    "_continue",
    "-c",
    "--continue",
    is_flag=True,
    flag_value=-1,
    help="Continue the most recent conversation.",
)
@click.option(
    "conversation_id",
    "--cid",
    "--conversation",
    help="Continue the conversation with the given ID.",
)
@click.option(
    "fragments",
    "-f",
    "--fragment",
    multiple=True,
    help="Fragment (alias, URL, hash or file path) to add to the prompt",
)
@click.option(
    "system_fragments",
    "--sf",
    "--system-fragment",
    multiple=True,
    help="Fragment to add to system prompt",
)
@click.option("-t", "--template", help="Template to use")
@click.option(
    "-p",
    "--param",
    multiple=True,
    type=(str, str),
    help="Parameters for template",
)
@click.option(
    "options",
    "-o",
    "--option",
    type=(str, str),
    multiple=True,
    help="key/value options for the model",
)
@click.option(
    "-d",
    "--database",
    type=click.Path(readable=True, dir_okay=False),
    help="Path to log database",
)
@click.option("--no-stream", is_flag=True, help="Do not stream output")
@click.option("-R", "--hide-reasoning", is_flag=True, help="Hide reasoning output")
@click.option("--key", help="API key to use")
@tool_options
def chat(
    system,
    model_id,
    _continue,
    conversation_id,
    fragments,
    system_fragments,
    template,
    param,
    options,
    no_stream,
    hide_reasoning,
    key,
    database,
    tools,
    python_tools,
    tools_debug,
    tools_approve,
    chain_limit,
):
    """
    Hold an ongoing chat with a model.
    """
    # Left and right arrow keys to move cursor:
    if sys.platform != "win32":
        readline.parse_and_bind("\\e[D: backward-char")
        readline.parse_and_bind("\\e[C: forward-char")
    else:
        readline.parse_and_bind("bind -x '\\e[D: backward-char'")
        readline.parse_and_bind("bind -x '\\e[C: forward-char'")
    log_path = pathlib.Path(database) if database else logs_db_path()
    (log_path.parent).mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(log_path)
    migrate(db)

    conversation = None
    if conversation_id or _continue:
        # Load the conversation - loads most recent if no ID provided
        try:
            conversation = load_conversation(conversation_id, database=database)
        except UnknownModelError as ex:
            raise click.ClickException(str(ex))

    if conversation_tools := _get_conversation_tools(conversation, tools):
        tools = conversation_tools

    template_obj = None
    if template:
        params = dict(param)
        try:
            template_obj = load_template(template)
        except LoadTemplateError as ex:
            raise click.ClickException(str(ex))
        if model_id is None and template_obj.model:
            model_id = template_obj.model
        tools, python_tools = _merge_template_tools(template_obj, tools, python_tools)

    # Figure out which model we are using
    if model_id is None:
        if conversation:
            model_id = conversation.model.model_id
        else:
            model_id = get_default_model()

    # Now resolve the model
    try:
        model = get_model(model_id)
    except KeyError:
        raise click.ClickException(f"'{model_id}' is not a known model")

    if conversation is None:
        # Start a fresh conversation for this chat
        conversation = Conversation(model=model)
    else:
        # Ensure it can see the API key
        conversation.model = model

    # Validate options
    validated_options = get_model_options(model.model_id)
    if options:
        try:
            validated_options = {
                key: value
                for key, value in model.Options(**dict(options))
                if value is not None
            }
        except pydantic.ValidationError as ex:
            raise click.ClickException(render_errors(ex.errors()))

    kwargs = {}
    if validated_options:
        kwargs["options"] = validated_options

    kwargs.update(
        _tool_chain_kwargs(
            tools,
            python_tools,
            tools_debug,
            tools_approve,
            chain_limit,
            model=model,
        )
    )

    should_stream = model.can_stream and not no_stream
    if not should_stream:
        kwargs["stream"] = False

    if key and isinstance(model, KeyModel):
        kwargs["key"] = key
    if hide_reasoning:
        kwargs["hide_reasoning"] = True

    try:
        fragments_and_attachments = resolve_fragments(
            db, fragments, allow_attachments=True
        )
        argument_fragments = [
            fragment
            for fragment in fragments_and_attachments
            if isinstance(fragment, Fragment)
        ]
        argument_attachments = [
            attachment
            for attachment in fragments_and_attachments
            if isinstance(attachment, Attachment)
        ]
        argument_system_fragments = resolve_fragments(db, system_fragments)
    except FragmentNotFound as ex:
        raise click.ClickException(str(ex))

    def transform_chat_prompt(prompt):
        nonlocal system
        if template_obj:
            prompt, system = _apply_template(template_obj, prompt, params, system)
        return prompt

    def execute_chat_prompt(prompt, fragments, attachments):
        nonlocal system, argument_system_fragments
        response = conversation.chain(
            prompt,
            fragments=fragments,
            system_fragments=argument_system_fragments,
            attachments=attachments,
            system=system,
            **kwargs,
        )

        # System prompt and system fragments only sent for the first message
        system = None
        argument_system_fragments = []
        return response

    _run_chat(
        model.model_id,
        execute_chat_prompt,
        db=db,
        initial_fragments=argument_fragments,
        initial_attachments=argument_attachments,
        transform_prompt=transform_chat_prompt,
        after_response=lambda response: response.log_to_db(db),
        show_reasoning=not hide_reasoning,
    )


def load_conversation(
    conversation_id: str | None,
    async_=False,
    database=None,
) -> _BaseConversation | None:
    log_path = pathlib.Path(database) if database else logs_db_path()
    db = sqlite_utils.Database(log_path)
    migrate(db)
    if conversation_id is None:
        # Most recent conversation from either generation of tables -
        # thread ids are conversation ids, so the union dedupes rows
        # from the dual-write era.
        matches = list(db.query("""
                select id from (
                    select id from threads
                    union
                    select id from conversations
                ) order by id desc limit 1
                """))
        if matches:
            conversation_id = matches[0]["id"]
        else:
            return None
    try:
        row = cast(sqlite_utils.db.Table, db["conversations"]).get(conversation_id)
    except sqlite_utils.db.NotFoundError:
        # No legacy record - reconstruct the equivalent from the thread
        # and its most recent turn's model.
        try:
            thread_row = cast(sqlite_utils.db.Table, db["threads"]).get(conversation_id)
        except sqlite_utils.db.NotFoundError:
            raise click.ClickException(
                f"No conversation found with id={conversation_id}"
            )
        model_match = next(
            db.query(
                "select model from turns where thread_id = ? order by id desc limit 1",
                [conversation_id],
            ),
            None,
        )
        if model_match is None:
            raise click.ClickException(
                f"No conversation found with id={conversation_id}"
            )
        row = {
            "id": conversation_id,
            "name": thread_row["name"],
            "model": model_match["model"],
        }
    # Inflate that conversation
    conversation_class = AsyncConversation if async_ else Conversation
    response_class = AsyncResponse if async_ else Response
    conversation = conversation_class.from_row(row)
    for response in db["responses"].rows_where(
        "conversation_id = ?", [conversation_id], order_by="id"
    ):
        response_obj = response_class.from_row(db, response)
        if conversation.responses:
            previous_response = conversation.responses[-1]
            # SQLite rows store each response's legacy current-turn inputs
            # (prompt text, attachments, tool_results), not the full
            # prompt.messages chain. Rebuild that chain here so follow-up
            # prompts via `llm -c` satisfy the Prompt.messages invariant.
            response_obj.prompt._explicit_messages = (
                list(previous_response.prompt.messages)
                + list(previous_response._messages_now())
                + list(response_obj.prompt.messages)
            )
        conversation.responses.append(response_obj)

    # If this conversation has a thread in the content-addressed tables,
    # take the history from there. That chain is the exact message list
    # that was sent and returned, so reasoning signatures and provider
    # metadata survive - unlike the rebuild above, which can only work
    # from the flattened legacy columns.
    try:
        conversation.loaded_messages = LogStore(db).thread_messages(conversation_id)
    except KeyError:
        pass

    # Plugin and server-side tools recorded against the first turn, for
    # the same reuse-on-continue behaviour the rebuilt responses provide.
    # Configured instances are collapsed into a single spec string like
    # Datasette({"url": "..."}) - the same format -T accepts - so the
    # instance can be reconstructed with its configuration.
    loaded_tools = []
    seen_instance_ids = set()
    supported_server_side_tool_names = {
        tool_class.__name__
        for tool_class in conversation.model.supported_server_side_tools
    }
    for tool_row in db.query(
        """
        select tools.name, tools.plugin, turn_tools.instance_id,
            tool_instances.name as instance_name,
            tool_instances.arguments as instance_arguments
        from tools
        join turn_tools on turn_tools.tool_id = tools.id
        left join tool_instances on tool_instances.id = turn_tools.instance_id
        where turn_tools.turn_id = (
            select id from turns where thread_id = ? order by id limit 1
        )
        """,
        [conversation_id],
    ):
        if (
            tool_row["plugin"] is None
            and tool_row["instance_name"] not in supported_server_side_tool_names
        ):
            continue
        if tool_row["instance_id"] is None:
            loaded_tools.append(tool_row["name"])
        elif tool_row["instance_id"] not in seen_instance_ids:
            seen_instance_ids.add(tool_row["instance_id"])
            arguments = tool_row["instance_arguments"]
            if arguments and arguments != "{}":
                loaded_tools.append(
                    "{}({})".format(tool_row["instance_name"], arguments)
                )
            else:
                loaded_tools.append(tool_row["instance_name"])
    conversation.loaded_tools = loaded_tools

    return conversation


@cli.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def keys():
    "Manage stored API keys for different models"


@keys.command(name="list")
def keys_list():
    "List names of all stored keys"
    path = user_dir() / "keys.json"
    if not path.exists():
        click.echo("No keys found")
        return
    keys = json.loads(path.read_text())
    for key in sorted(keys.keys()):
        if key != "// Note":
            click.echo(key)


@keys.command(name="path")
def keys_path_command():
    "Output the path to the keys.json file"
    click.echo(user_dir() / "keys.json")


@keys.command(name="get")
@click.argument("name")
def keys_get(name):
    """
    Return the value of a stored key

    Example usage:

    \b
        export OPENAI_API_KEY=$(llm keys get openai)
    """
    path = user_dir() / "keys.json"
    if not path.exists():
        raise click.ClickException("No keys found")
    keys = json.loads(path.read_text())
    try:
        click.echo(keys[name])
    except KeyError:
        raise click.ClickException(f"No key found with name '{name}'")


@keys.command(name="set")
@click.argument("name")
@click.option("--value", prompt="Enter key", hide_input=True, help="Value to set")
def keys_set(name, value):
    """
    Save a key in the keys.json file

    Example usage:

    \b
        $ llm keys set openai
        Enter key: ...
    """
    default = {"// Note": "This file stores secret API credentials. Do not share!"}
    path = user_dir() / "keys.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(default))
        path.chmod(0o600)
    try:
        current = json.loads(path.read_text())
    except json.decoder.JSONDecodeError:
        current = default
    current[name] = value
    path.write_text(json.dumps(current, indent=2) + "\n")


@cli.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def logs():
    "Tools for exploring logged prompts and responses"


@logs.command(name="path")
def logs_path():
    "Output the path to the logs.db file"
    click.echo(logs_db_path())


@logs.command(name="status")
def logs_status():
    "Show current status of database logging"
    path = logs_db_path()
    if not path.exists():
        click.echo(f"No log database found at {path}")
        return
    if logs_on():
        click.echo("Logging is ON for all prompts".format())
    else:
        click.echo("Logging is OFF".format())
    db = sqlite_utils.Database(path)
    migrate(db)
    click.echo(f"Found log database at {path}")
    click.echo("Number of threads logged:\t{}".format(db["threads"].count))
    click.echo("Number of turns logged:\t\t{}".format(db["turns"].count))
    legacy_conversations = db["conversations"].count
    legacy_responses = db["responses"].count
    if legacy_conversations or legacy_responses:
        click.echo(f"Number of legacy conversations:\t{legacy_conversations}")
        click.echo(f"Number of legacy responses:\t{legacy_responses}")
    click.echo(f"Database file size: \t\t{_human_readable_size(path.stat().st_size)}")


@logs.command(name="backup")
@click.argument("path", type=click.Path(dir_okay=True, writable=True))
def backup(path):
    "Backup your logs database to this file"
    logs_path = logs_db_path()
    path = pathlib.Path(path)
    db = sqlite_utils.Database(logs_path)
    try:
        db.execute("vacuum into ?", [str(path)])
    except Exception as ex:  # noqa: BLE001
        raise click.ClickException(str(ex))
    click.echo(f"Backed up {_human_readable_size(path.stat().st_size)} to {path}")


@logs.command(name="on")
def logs_turn_on():
    "Turn on logging for all prompts"
    path = user_dir() / "logs-off"
    if path.exists():
        path.unlink()


@logs.command(name="off")
def logs_turn_off():
    "Turn off logging for all prompts"
    path = user_dir() / "logs-off"
    path.touch()


def annotate_log_rows(db, rows, expand=False, truncate=False):
    """
    Modify log rows from the merged reader in place: attach fragments
    and tool information, decode (or, if truncate is on, remove) their
    JSON columns and strip the reader's internal keys.

    Returns a dict mapping row id to its attachments, for
    log_rows_as_json and the rendered output.
    """
    store = LogStore(db)
    # New rows carry their extras in the row's parts; legacy rows
    # batch-fetch from the legacy tables.
    legacy_extras = legacy_log_row_extras(
        db, [row["id"] for row in rows if row.get("_legacy")]
    )
    extras_by_id = {
        row["id"]: (
            legacy_extras[row["id"]]
            if row.get("_legacy")
            else log_row_extras(store, row)
        )
        for row in rows
    }
    for row in rows:
        for internal in (
            "_input_parts",
            "_output_parts",
            "_parent_message_hash",
            "_input_message_hashes",
            "_output_message_hashes",
            "_tip_message_hash",
            "_legacy",
            "_search_rank",
        ):
            row.pop(internal, None)
        extras = extras_by_id[row["id"]]
        if truncate:
            row["prompt"] = truncate_string(row["prompt"] or "")
            row["response"] = truncate_string(row["response"] or "")
        # Add prompt and system fragments
        for key in ("prompt_fragments", "system_fragments"):
            row[key] = [
                {
                    "hash": fragment["hash"],
                    "content": (
                        fragment["content"]
                        if expand
                        else truncate_string(fragment["content"])
                    ),
                    "aliases": json.loads(fragment["aliases"]),
                }
                for fragment in extras[key]
            ]
        # Either decode or remove all JSON keys
        keys = list(row.keys())
        for key in keys:
            if key.endswith("_json") and row[key] is not None:
                if truncate:
                    del row[key]
                else:
                    row[key] = json.loads(row[key])
        row.update(
            {
                "tools": extras["tools"],
                "tool_calls": extras["tool_calls"],
                "tool_results": extras["tool_results"],
            }
        )
    return {id: extras["attachments"] for id, extras in extras_by_id.items()}


def log_rows_as_json(rows, attachments_by_id):
    "Serialize annotated log rows to the JSON used by 'llm logs --json'"
    for row in rows:
        row["attachments"] = [
            {k: v for k, v in attachment.items() if k != "response_id"}
            for attachment in attachments_by_id.get(row["id"], [])
        ]
    return json.dumps(list(rows), indent=2)


def logs_json_for_response_ids(db, ids):
    """
    Return the JSON that 'llm logs --json' would output for these response IDs,
    in chronological order
    """
    if not ids:
        return "[]"
    rows = merged_log_rows(LogStore(db), ids=list(ids))
    # Newest first out of the reader, chronological out here
    rows.reverse()
    return log_rows_as_json(rows, annotate_log_rows(db, rows))


@logs.command(name="list")
@click.option(
    "-n",
    "--count",
    type=int,
    default=None,
    help="Number of entries to show - defaults to 3, use 0 for all",
)
@click.option(
    "-p",
    "--path",
    type=click.Path(readable=True, exists=True, dir_okay=False),
    help="Path to log database",
    hidden=True,
)
@click.option(
    "-d",
    "--database",
    type=click.Path(readable=True, exists=True, dir_okay=False),
    help="Path to log database",
)
@click.option("-m", "--model", help="Filter by model or model alias")
@click.option("-q", "--query", help="Search for logs matching this string")
@click.option(
    "fragments",
    "--fragment",
    "-f",
    help="Filter for prompts using these fragments",
    multiple=True,
)
@click.option(
    "tools",
    "-T",
    "--tool",
    multiple=True,
    help="Filter for prompts with results from these tools",
)
@click.option(
    "any_tools",
    "--tools",
    is_flag=True,
    help="Filter for prompts with results from any tools",
)
@schema_option
@click.option(
    "--schema-multi",
    help="JSON schema used for multiple results",
)
@click.option(
    "-l", "--latest", is_flag=True, help="Return latest results matching search query"
)
@click.option(
    "--data", is_flag=True, help="Output newline-delimited JSON data for schema"
)
@click.option("--data-array", is_flag=True, help="Output JSON array of data for schema")
@click.option("--data-key", help="Return JSON objects from array in this key")
@click.option(
    "--data-ids", is_flag=True, help="Attach corresponding IDs to JSON objects"
)
@click.option("-t", "--truncate", is_flag=True, help="Truncate long strings in output")
@click.option(
    "-s", "--short", is_flag=True, help="Shorter YAML output with truncated prompts"
)
@click.option("-u", "--usage", is_flag=True, help="Include token usage")
@click.option("-r", "--response", is_flag=True, help="Just output the last response")
@click.option("-x", "--extract", is_flag=True, help="Extract first fenced code block")
@click.option(
    "extract_last",
    "--xl",
    "--extract-last",
    is_flag=True,
    help="Extract last fenced code block",
)
@click.option(
    "current_conversation",
    "-c",
    "--current",
    is_flag=True,
    flag_value=-1,
    help="Show logs from the current conversation",
)
@click.option(
    "conversation_id",
    "--cid",
    "--conversation",
    help="Show logs for this conversation ID",
)
@click.option("--id-gt", help="Return responses with ID > this")
@click.option("--id-gte", help="Return responses with ID >= this")
@click.option(
    "json_output",
    "--json",
    is_flag=True,
    help="Output logs as JSON",
)
@click.option(
    "--expand",
    "-e",
    is_flag=True,
    help="Expand fragments to show their content",
)
def logs_list(
    count,
    path,
    database,
    model,
    query,
    fragments,
    tools,
    any_tools,
    schema_input,
    schema_multi,
    latest,
    data,
    data_array,
    data_key,
    data_ids,
    truncate,
    short,
    usage,
    response,
    extract,
    extract_last,
    current_conversation,
    conversation_id,
    id_gt,
    id_gte,
    json_output,
    expand,
):
    "Show logged prompts and their responses"
    if database and not path:
        path = database
    path = pathlib.Path(path or logs_db_path())
    if not path.exists():
        raise click.ClickException(f"No log database found at {path}")
    db = sqlite_utils.Database(path)
    migrate(db)

    if schema_multi:
        schema_input = schema_multi
    schema = resolve_schema_input(db, schema_input, load_template)
    if schema_multi:
        schema = multi_schema(schema)

    if short and (json_output or response):
        invalid = " or ".join(
            [
                flag[0]
                for flag in (("--json", json_output), ("--response", response))
                if flag[1]
            ]
        )
        raise click.ClickException(f"Cannot use --short and {invalid} together")

    if response and not current_conversation and not conversation_id:
        current_conversation = True

    if current_conversation:
        try:
            # Thread ids are conversation ids and both id spaces are
            # ULIDs, so the most recent of either world wins.
            conversation_id = next(db.query("""
                    select conversation_id from (
                        select thread_id as conversation_id, id from turns
                        union all
                        select conversation_id, id from responses
                    ) order by id desc limit 1
                    """))["conversation_id"]
        except StopIteration:
            # No conversations yet
            raise click.ClickException("No conversations found")

    # For --conversation set limit 0, if not explicitly set
    if count is None:
        if conversation_id:
            count = 0
        else:
            count = 3

    model_id = None
    if model:
        # Resolve alias, if any
        try:
            model_id = get_model(model).model_id
        except UnknownModelError:
            # Maybe they uninstalled a model, use the -m option as-is
            model_id = model

    fragment_hashes = [fragment.id() for fragment in resolve_fragments(db, fragments)]

    schema_id = make_schema_id(schema)[0] if schema else None

    store = LogStore(db)
    try:
        rows = merged_log_rows(
            store,
            count=count if count and count > 0 else None,
            model_id=model_id,
            thread_id=conversation_id,
            fragment_hashes=fragment_hashes,
            tool_names=tools,
            any_tools=any_tools,
            schema_id=schema_id,
            id_gt=id_gt,
            id_gte=id_gte,
            query=query,
            latest=latest,
        )
    except sqlite3.OperationalError as ex:
        if query:
            # Almost certainly FTS5 syntax - unbalanced quotes, stray
            # operators and the like
            raise click.ClickException(
                f"Invalid search query: {ex} - see the FTS5 query syntax "
                "documentation at https://sqlite.org/fts5.html#full_text_query_syntax"
            )
        raise

    # Newest first out of the query, but read chronologically - except
    # for search results, which are already most-relevant first.
    if not query and not data:
        rows.reverse()

    if data or data_array or data_key or data_ids:
        # Special case for --data to output valid JSON
        to_output = []
        for row in rows:
            response = row["response"] or ""
            try:
                decoded = json.loads(response)
                if (
                    isinstance(decoded, dict)
                    and (data_key in decoded)
                    and all(isinstance(item, dict) for item in decoded[data_key])
                ):
                    new_items = list(decoded[data_key])
                else:
                    new_items = [decoded]
                if data_ids:
                    for item in new_items:
                        item[find_unused_key(item, "response_id")] = row["id"]
                        item[find_unused_key(item, "conversation_id")] = row[
                            "conversation_id"
                        ]
                to_output.extend(new_items)
            except ValueError:
                pass
        for line in output_rows_as_json(to_output, nl=not data_array, compact=True):
            click.echo(line)
        return

    attachments_by_id = annotate_log_rows(db, rows, expand=expand, truncate=truncate)

    output = None
    if json_output:
        # Output as JSON if requested
        output = log_rows_as_json(rows, attachments_by_id)
    elif extract or extract_last:
        # Extract and return first code block
        for row in rows:
            output = extract_fenced_code_block(row["response"], last=extract_last)
            if output is not None:
                break
    elif response and rows:
        # Just output the last response
        output = rows[-1]["response"]

    if output is not None:
        click.echo(output)
    else:
        # Output neatly formatted human-readable logs
        def _fenced_block(value):
            # Fenced code block, indented to nest inside a list item
            num_backticks = 3
            while "`" * num_backticks in value:
                num_backticks += 1
            fence = "`" * num_backticks
            return textwrap.indent(f"{fence}\n{value}\n{fence}", "    ")

        def _inline_code(value):
            num_backticks = 1
            while "`" * num_backticks in value:
                num_backticks += 1
            delimiter = "`" * num_backticks
            if value.startswith("`") or value.endswith("`"):
                return f"{delimiter} {value} {delimiter}"
            return f"{delimiter}{value}{delimiter}"

        def _format_tool_call_arguments(arguments):
            if not isinstance(arguments, dict) or not arguments:
                return f"    Arguments: {_inline_code(json.dumps(arguments))}"
            lines = []
            for key, value in arguments.items():
                if isinstance(value, str):
                    lines.append(f"    {key}:")
                    lines.append(_fenced_block(value))
                else:
                    lines.append(f"    {key}: {_inline_code(json.dumps(value))}")
            return "\n".join(lines)

        def _token_usage_markdown(input_tokens, output_tokens, token_details):
            usage = token_usage_string(input_tokens, output_tokens, None)
            if token_details:
                details = _inline_code(json.dumps(token_details))
                if usage:
                    return f"{usage}, {details}"
                return details
            return usage

        def _display_tool_results(tool_results):
            for tool_result in tool_results:
                attachments = ""
                for attachment in tool_result["attachments"]:
                    desc = ""
                    if attachment.get("type"):
                        desc += attachment["type"] + ": "
                    if attachment.get("path"):
                        desc += attachment["path"]
                    elif attachment.get("url"):
                        desc += attachment["url"]
                    elif attachment.get("content"):
                        desc += f"<{attachment['content_length']:,} bytes>"
                    attachments += f"\n    - {desc}"
                click.echo(
                    "- **{}**: `{}`  \n{}{}{}".format(
                        tool_result["name"],
                        tool_result["tool_call_id"],
                        _fenced_block(tool_result["output"]),
                        (
                            "  \n    **Error**: {}\n".format(tool_result["exception"])
                            if tool_result["exception"]
                            else ""
                        ),
                        attachments,
                    )
                )

        def _display_fragments(fragments, title):
            if not fragments:
                return
            if not expand:
                content = "\n".join(
                    ["- {}".format(fragment["hash"]) for fragment in fragments]
                )
            else:
                # <details><summary> for each one
                bits = []
                for fragment in fragments:
                    bits.append(
                        "<details><summary>{}</summary>\n{}\n</details>".format(
                            fragment["hash"], maybe_fenced_code(fragment["content"])
                        )
                    )
                content = "\n".join(bits)
            click.echo(f"\n### {title}\n\n{content}")

        current_system = None
        should_show_conversation = True
        seen_tool_hashes = set()
        for row in rows:
            if short:
                system = truncate_string(
                    row["system"] or "", 120, normalize_whitespace=True
                )
                prompt = truncate_string(
                    row["prompt"] or "", 120, normalize_whitespace=True, keep_end=True
                )
                cid = row["conversation_id"]
                attachments = attachments_by_id.get(row["id"])
                obj = {
                    "model": row["model"],
                    "datetime": row["datetime_utc"].split(".")[0],
                    "conversation": cid,
                }
                if row["tool_calls"]:
                    obj["tool_calls"] = [
                        "{}({})".format(
                            tool_call["name"], json.dumps(tool_call["arguments"])
                        )
                        for tool_call in row["tool_calls"]
                    ]
                if row["tool_results"]:
                    obj["tool_results"] = [
                        "{}: {}".format(
                            tool_result["name"], truncate_string(tool_result["output"])
                        )
                        for tool_result in row["tool_results"]
                    ]
                if system:
                    obj["system"] = system
                if prompt:
                    obj["prompt"] = prompt
                if attachments:
                    items = []
                    for attachment in attachments:
                        details = {"type": attachment["type"]}
                        if attachment.get("path"):
                            details["path"] = attachment["path"]
                        if attachment.get("url"):
                            details["url"] = attachment["url"]
                        items.append(details)
                    obj["attachments"] = items
                for key in ("prompt_fragments", "system_fragments"):
                    obj[key] = [fragment["hash"] for fragment in row[key]]
                if usage and (row["input_tokens"] or row["output_tokens"]):
                    usage_details = {
                        "input": row["input_tokens"],
                        "output": row["output_tokens"],
                    }
                    if row["token_details"]:
                        usage_details["details"] = json.loads(row["token_details"])
                    obj["usage"] = usage_details
                click.echo(yaml.dump([obj], sort_keys=False).strip())
                continue
            # Not short, output Markdown
            click.echo(
                "# {}{}\n{}".format(
                    row["datetime_utc"].split(".")[0],
                    (
                        "    conversation: {} id: {}".format(
                            row["conversation_id"], row["id"]
                        )
                        if should_show_conversation
                        else ""
                    ),
                    (
                        (
                            "\nModel: **{}**{}\n".format(
                                row["model"],
                                (
                                    " (resolved: **{}**)".format(row["resolved_model"])
                                    if row["resolved_model"]
                                    else ""
                                ),
                            )
                        )
                        if should_show_conversation
                        else ""
                    ),
                )
            )
            # In conversation log mode only show it for the first one
            if conversation_id:
                should_show_conversation = False
            click.echo("## Prompt\n\n{}".format(row["prompt"] or "-- none --"))
            _display_fragments(row["prompt_fragments"], "Prompt fragments")
            if row["options_json"]:
                options = row["options_json"]
                if isinstance(options, str):
                    options = json.loads(options)
                if options:
                    options_text = "\n".join(
                        f"- {key}: {value}" for key, value in options.items()
                    )
                    click.echo(f"\n## Options\n\n{options_text}")
            if row["system"] != current_system:
                if row["system"] is not None:
                    click.echo("\n## System\n\n{}".format(row["system"]))
                current_system = row["system"]
            _display_fragments(row["system_fragments"], "System fragments")
            if row["schema_json"]:
                click.echo(
                    "\n## Schema\n\n```json\n{}\n```".format(
                        json.dumps(row["schema_json"], indent=2)
                    )
                )
            # Show tool calls and results
            if row["tools"]:
                click.echo("\n### Tools\n")

                def echo_tool(tool, indent=""):
                    if tool["hash"] in seen_tool_hashes:
                        block = "- **{}**: `{}`".format(tool["name"], tool["hash"][:7])
                    else:
                        seen_tool_hashes.add(tool["hash"])
                        block = "- **{}**: `{}`  \n{}  \n    Arguments: `{}`".format(
                            tool["name"],
                            tool["hash"],
                            textwrap.indent(
                                (tool["description"] or "").rstrip(), "    "
                            ),
                            json.dumps(tool["input_schema"].get("properties", {})),
                        )
                    click.echo(textwrap.indent(block, indent))

                # Tools provided by the same configured toolbox instance
                # nest beneath one instance line rather than repeating it
                plain_tools = []
                by_instance: dict = {}
                for tool in row["tools"]:
                    instance = tool.get("instance")
                    if instance:
                        key = (instance["name"], instance["arguments"])
                        by_instance.setdefault(key, []).append(tool)
                    else:
                        plain_tools.append(tool)
                for tool in plain_tools:
                    echo_tool(tool)
                for (name, arguments), instance_tools in by_instance.items():
                    click.echo(
                        "- `{}({})`:".format(
                            name,
                            arguments if arguments and arguments != "{}" else "",
                        )
                    )
                    for tool in instance_tools:
                        echo_tool(tool, "    ")
            # Results the model was given arrived with the prompt;
            # server-executed results happened during the response and
            # render there instead.
            local_tool_results = [
                tool_result
                for tool_result in row["tool_results"]
                if not tool_result.get("server_executed")
            ]
            server_tool_results = [
                tool_result
                for tool_result in row["tool_results"]
                if tool_result.get("server_executed")
            ]
            if local_tool_results:
                click.echo("\n### Tool results\n")
                _display_tool_results(local_tool_results)
            attachments = attachments_by_id.get(row["id"])
            if attachments:
                click.echo("\n### Attachments\n")
                for i, attachment in enumerate(attachments, 1):
                    if attachment["path"]:
                        path = attachment["path"]
                        click.echo(
                            "{}. **{}**: `{}`".format(i, attachment["type"], path)
                        )
                    elif attachment["url"]:
                        click.echo(
                            "{}. **{}**: {}".format(
                                i, attachment["type"], attachment["url"]
                            )
                        )
                    elif attachment["content_length"]:
                        click.echo(
                            "{}. **{}**: `<{} bytes>`".format(
                                i,
                                attachment["type"],
                                f"{attachment['content_length']:,}",
                            )
                        )

            # If a schema was provided and the row is valid JSON, pretty print and syntax highlight it
            response = row["response"]
            if row["schema_json"]:
                try:
                    parsed = json.loads(response)
                    response = f"```json\n{json.dumps(parsed, indent=2)}\n```"
                except ValueError:
                    pass
            if row.get("reasoning"):
                click.echo("\n## Reasoning\n\n{}".format(row["reasoning"].rstrip()))
            click.echo("\n## Response\n")
            if row["tool_calls"]:
                click.echo("### Tool calls\n")
                for tool_call in row["tool_calls"]:
                    click.echo(
                        "- **{}**: `{}`  \n{}".format(
                            tool_call["name"],
                            tool_call["tool_call_id"],
                            _format_tool_call_arguments(tool_call["arguments"]),
                        )
                    )
                click.echo("")
            if server_tool_results:
                click.echo("### Tool results\n")
                _display_tool_results(server_tool_results)
                click.echo("")
            if response:
                click.echo(f"{response}\n")
            if usage:
                token_usage = _token_usage_markdown(
                    row["input_tokens"],
                    row["output_tokens"],
                    json.loads(row["token_details"]) if row["token_details"] else None,
                )
                if token_usage:
                    click.echo(f"## Token usage\n\n{token_usage}\n")


@cli.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def models():
    "Manage available models"


_type_lookup = {
    "number": "float",
    "integer": "int",
    "string": "str",
    "object": "dict",
}


def model_matches_id_or_alias(model_with_aliases, model_ids):
    ids_and_aliases = set(
        [model_with_aliases.model.model_id] + model_with_aliases.aliases
    )
    return ids_and_aliases.intersection(model_ids)


def render_model_with_aliases(
    model_with_aliases,
    *,
    options=False,
    async_=False,
    models_that_have_shown_options=None,
):
    extra_info = []
    if model_with_aliases.aliases:
        extra_info.append("aliases: {}".format(", ".join(model_with_aliases.aliases)))
    model = model_with_aliases.model if not async_ else model_with_aliases.async_model
    output = str(model)
    if extra_info:
        output += " ({})".format(", ".join(extra_info))
    if options and model.Options.model_json_schema()["properties"]:
        output += "\n  Options:"
        for name, field in model.Options.model_json_schema()["properties"].items():
            any_of = field.get("anyOf")
            if any_of is None:
                any_of = [{"type": field.get("type", "str")}]
            types = ", ".join(
                [
                    _type_lookup.get(item.get("type"), item.get("type", "str"))
                    for item in any_of
                    if item.get("type") != "null"
                ]
            )
            bits = ["\n    ", name, ": ", types]
            description = field.get("description", "")
            if (
                description
                and models_that_have_shown_options is not None
                and model.__class__ not in models_that_have_shown_options
            ):
                wrapped = textwrap.wrap(description, 70)
                bits.append("\n      ")
                bits.extend("\n      ".join(wrapped))
            output += "".join(bits)
        if models_that_have_shown_options is not None:
            models_that_have_shown_options.add(model.__class__)
    if options and model.attachment_types:
        attachment_types = ", ".join(sorted(model.attachment_types))
        wrapper = textwrap.TextWrapper(
            width=min(max(shutil.get_terminal_size().columns, 30), 70),
            initial_indent="    ",
            subsequent_indent="    ",
        )
        output += f"\n  Attachment types:\n{wrapper.fill(attachment_types)}"
    features = (
        []
        + (["streaming"] if model.can_stream else [])
        + (["schemas"] if model.supports_schema else [])
        + (["tools"] if model.supports_tools else [])
        + (["async"] if model_with_aliases.async_model else [])
    )
    if options and features:
        output += "\n  Features:\n{}".format(
            "\n".join(f"  - {feature}" for feature in features)
        )
    if options and hasattr(model, "needs_key") and model.needs_key:
        output += "\n  Keys:"
        if hasattr(model, "needs_key") and model.needs_key:
            output += f"\n    key: {model.needs_key}"
        if hasattr(model, "key_env_var") and model.key_env_var:
            output += f"\n    env_var: {model.key_env_var}"
    return output


def render_model_with_options(model_id, *, async_=False):
    for model_with_aliases in get_models_with_aliases():
        if model_matches_id_or_alias(model_with_aliases, [model_id]):
            return render_model_with_aliases(
                model_with_aliases,
                options=True,
                async_=async_,
                models_that_have_shown_options=set(),
            )
    raise click.ClickException(f"'{model_id}' is not a known model")


@models.command(name="list")
@click.option(
    "--options", is_flag=True, help="Show options for each model, if available"
)
@click.option("async_", "--async", is_flag=True, help="List async models")
@click.option("--schemas", is_flag=True, help="List models that support schemas")
@click.option("--tools", is_flag=True, help="List models that support tools")
@click.option("json_", "--json", is_flag=True, help="Output as JSON")
@click.option(
    "-q",
    "--query",
    multiple=True,
    help="Search for models matching these strings",
)
@click.option("model_ids", "-m", "--model", help="Specific model IDs", multiple=True)
def models_list(options, async_, schemas, tools, json_, query, model_ids):
    "List available models"
    models_that_have_shown_options = set()
    json_models = []
    for model_with_aliases in get_models_with_aliases():
        if async_ and not model_with_aliases.async_model:
            continue
        # Only show models where every provided query string matches
        if query and not all(model_with_aliases.matches(q) for q in query):
            continue
        if model_ids and not model_matches_id_or_alias(model_with_aliases, model_ids):
            continue
        if schemas and not model_with_aliases.model.supports_schema:
            continue
        if tools and not model_with_aliases.model.supports_tools:
            continue
        if json_:
            model = (
                model_with_aliases.async_model if async_ else model_with_aliases.model
            )
            model_json = {
                "model_id": model.model_id,
                "aliases": model_with_aliases.aliases,
                "can_stream": model.can_stream,
                "supports_schema": model.supports_schema,
                "supports_tools": model.supports_tools,
                "supports_async": model_with_aliases.async_model is not None,
                "attachment_types": sorted(model.attachment_types),
                "server_side_tools": [
                    {
                        "name": tool_class.__name__,
                        "plugin": getattr(tool_class, "plugin", None),
                    }
                    for tool_class in model.supported_server_side_tools
                ],
            }
            if options:
                model_json["options"] = model.Options.model_json_schema()["properties"]
            json_models.append(model_json)
            continue
        click.echo(
            render_model_with_aliases(
                model_with_aliases,
                options=options,
                async_=async_,
                models_that_have_shown_options=models_that_have_shown_options,
            )
        )
    if json_:
        click.echo(json.dumps(json_models, indent=2))
        return
    if not query and not options and not schemas and not model_ids:
        click.echo(f"Default: {get_default_model()}")


@models.command(name="default")
@click.argument("model", required=False)
def models_default(model):
    "Show or set the default model"
    if not model:
        click.echo(get_default_model())
        return
    # Validate it is a known model
    try:
        model = get_model(model)
        set_default_model(model.model_id)
    except KeyError:
        raise click.ClickException(f"Unknown model: {model}")


@cli.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def templates():
    "Manage stored prompt templates"


@templates.command(name="list")
def templates_list():
    "List available prompt templates"
    path = template_dir()
    pairs = []
    for file in path.glob("*.yaml"):
        name = file.stem
        try:
            template = load_template(name)
        except LoadTemplateError:
            # Skip invalid templates
            continue
        text = []
        if template.system:
            text.append(f"system: {template.system}")
            if template.prompt:
                text.append(f" prompt: {template.prompt}")
        else:
            text = [template.prompt if template.prompt else ""]
        pairs.append((name, "".join(text).replace("\n", " ")))
    try:
        max_name_len = max(len(p[0]) for p in pairs)
    except ValueError:
        return
    else:
        fmt = "{name:<" + str(max_name_len) + "} : {prompt}"
        for name, prompt in sorted(pairs):
            text = fmt.format(name=name, prompt=prompt)
            click.echo(display_truncated(text))


@templates.command(name="show")
@click.argument("name")
def templates_show(name):
    "Show the specified prompt template"
    try:
        template = load_template(name)
    except LoadTemplateError:
        raise click.ClickException(f"Template '{name}' not found or invalid")
    click.echo(
        yaml.dump(
            {k: v for k, v in template.model_dump().items() if v is not None},
            indent=4,
            default_flow_style=False,
        )
    )


@templates.command(name="edit")
@click.argument("name")
def templates_edit(name):
    "Edit the specified prompt template using the default $EDITOR"
    # First ensure it exists
    path = template_dir() / f"{name}.yaml"
    if not path.exists():
        path.write_text(DEFAULT_TEMPLATE, "utf-8")
    click.edit(filename=str(path))
    # Validate that template
    load_template(name)


@templates.command(name="path")
def templates_path():
    "Output the path to the templates directory"
    click.echo(template_dir())


@templates.command(name="loaders")
def templates_loaders():
    "Show template loaders registered by plugins"
    found = False
    for prefix, loader in get_template_loaders().items():
        found = True
        docs = "Undocumented"
        if loader.__doc__:
            docs = textwrap.dedent(loader.__doc__).strip()
        click.echo(f"{prefix}:")
        click.echo(textwrap.indent(docs, "  "))
    if not found:
        click.echo("No template loaders found")


@cli.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def schemas():
    "Manage stored schemas"


@schemas.command(name="list")
@click.option(
    "-p",
    "--path",
    type=click.Path(readable=True, exists=True, dir_okay=False),
    help="Path to log database",
    hidden=True,
)
@click.option(
    "-d",
    "--database",
    type=click.Path(readable=True, exists=True, dir_okay=False),
    help="Path to log database",
)
@click.option(
    "queries",
    "-q",
    "--query",
    multiple=True,
    help="Search for schemas matching this string",
)
@click.option("--full", is_flag=True, help="Output full schema contents")
@click.option("json_", "--json", is_flag=True, help="Output as JSON")
@click.option("nl", "--nl", is_flag=True, help="Output as newline-delimited JSON")
def schemas_list(path, database, queries, full, json_, nl):
    "List stored schemas"
    if database and not path:
        path = database
    path = pathlib.Path(path or logs_db_path())
    if not path.exists():
        raise click.ClickException(f"No log database found at {path}")
    db = sqlite_utils.Database(path)
    migrate(db)

    params = []
    where_sql = ""
    if queries:
        where_bits = ["schemas.content like ?" for _ in queries]
        where_sql += " where {}".format(" and ".join(where_bits))
        params.extend(f"%{q}%" for q in queries)

    sql = f"""
    select
      schemas.id,
      schemas.content,
      max(responses.datetime_utc) as recently_used,
      count(*) as times_used
    from schemas
    join responses
      on responses.schema_id = schemas.id
    {where_sql} group by responses.schema_id
    order by recently_used
    """
    rows = db.query(sql, params)

    if json_ or nl:
        for line in output_rows_as_json(rows, json_cols={"content"}, nl=nl):
            click.echo(line)
        return

    for row in rows:
        click.echo("- id: {}".format(row["id"]))
        if full:
            click.echo(
                "  schema: |\n{}".format(
                    textwrap.indent(
                        json.dumps(json.loads(row["content"]), indent=2), "    "
                    )
                )
            )
        else:
            click.echo(
                "  summary: |\n    {}".format(
                    schema_summary(json.loads(row["content"]))
                )
            )
        click.echo(
            "  usage: |\n    {} time{}, most recently {}".format(
                row["times_used"],
                "s" if row["times_used"] != 1 else "",
                row["recently_used"],
            )
        )


@schemas.command(name="show")
@click.argument("schema_id")
@click.option(
    "-p",
    "--path",
    type=click.Path(readable=True, exists=True, dir_okay=False),
    help="Path to log database",
    hidden=True,
)
@click.option(
    "-d",
    "--database",
    type=click.Path(readable=True, exists=True, dir_okay=False),
    help="Path to log database",
)
def schemas_show(schema_id, path, database):
    "Show a stored schema"
    if database and not path:
        path = database
    path = pathlib.Path(path or logs_db_path())
    if not path.exists():
        raise click.ClickException(f"No log database found at {path}")
    db = sqlite_utils.Database(path)
    migrate(db)

    try:
        row = db["schemas"].get(schema_id)
    except sqlite_utils.db.NotFoundError:
        raise click.ClickException("Invalid schema ID")
    click.echo(json.dumps(json.loads(row["content"]), indent=2))


@schemas.command(name="dsl")
@click.argument("input")
@click.option("--multi", is_flag=True, help="Wrap in an array")
def schemas_dsl_debug(input, multi):
    """
    Convert LLM's schema DSL to a JSON schema

    \b
        llm schema dsl 'name, age int, bio: their bio'
    """
    schema = schema_dsl(input, multi)
    click.echo(json.dumps(schema, indent=2))


@cli.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def tools():
    "Manage tools that can be made available to LLMs"


@tools.command(name="list")
@click.argument("tool_defs", nargs=-1)
@click.option("json_", "--json", is_flag=True, help="Output as JSON")
@click.option("model_id", "-m", "--model", help="List tools supported by this model")
@click.option(
    "python_tools",
    "--functions",
    help="Python code block or file path defining functions to register as tools",
    multiple=True,
)
def tools_list(tool_defs, json_, model_id, python_tools):
    "List available tools, optionally including tools supported by a model"

    model = None
    if model_id:
        try:
            model = get_model(model_id)
        except UnknownModelError as ex:
            raise click.ClickException(str(ex))

    server_side_tools = []
    if model is not None:
        for tool_class in model.supported_server_side_tools:
            try:
                signature = str(inspect.signature(tool_class))
            except (ValueError, TypeError):
                signature = "(...)"
            server_side_tools.append(
                {
                    "name": tool_class.__name__,
                    "description": inspect.getdoc(tool_class),
                    "signature": signature,
                    "server_side": True,
                }
            )

    def introspect_tools(toolbox):
        # Instances report their tools(), which may be generated dynamically.
        # Classes can only report tools for their introspectable methods.
        if isinstance(toolbox, Toolbox):
            if not toolbox._prepared:
                toolbox.prepare()
                toolbox._prepared = True
            tool_iter = toolbox.tools()
        else:
            tool_iter = toolbox.method_tools()
        methods = []
        for tool in tool_iter:
            methods.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "arguments": tool.input_schema,
                    "implementation": tool.implementation,
                }
            )
        return methods

    toolbox_specs: dict[int, str] = {}
    if tool_defs:
        tools = {}
        gathered = _gather_tools(tool_defs, python_tools)
        # _gather_tools returns --functions tools first, then one per spec
        specs = [None] * (len(gathered) - len(tool_defs)) + list(tool_defs)
        for spec, tool in zip(specs, gathered):
            if hasattr(tool, "name"):
                tools[tool.name] = tool
            else:
                tools[tool.__class__.__name__] = tool
            if spec is not None and isinstance(tool, Toolbox):
                toolbox_specs[id(tool)] = spec
    else:
        tools = get_tools()
        if python_tools:
            for code_or_path in python_tools:
                for tool in _tools_from_code(code_or_path):
                    tools[tool.name] = tool

    output_tools = []
    output_toolboxes = []
    tool_objects = []
    toolbox_infos = []
    for name, tool in sorted(tools.items()):
        if isinstance(tool, Tool):
            tool_objects.append(tool)
            output_tools.append(
                {
                    "name": name,
                    "description": tool.description,
                    "arguments": tool.input_schema,
                    "plugin": tool.plugin,
                }
            )
        else:
            toolbox_class = tool if isinstance(tool, type) else tool.__class__
            # Overriding tools() or prepare() means the toolbox generates
            # tools at runtime
            is_dynamic = any(
                getattr(toolbox_class, method) is not getattr(Toolbox, method)
                for method in ("tools", "prepare", "prepare_async")
            )
            introspected = introspect_tools(tool)
            toolbox_infos.append((name, tool, toolbox_class, is_dynamic, introspected))
            output_toolboxes.append(
                {
                    "name": name,
                    "dynamic": is_dynamic,
                    "tools": [
                        {
                            "name": tool_info["name"],
                            "description": tool_info["description"],
                            "arguments": tool_info["arguments"],
                        }
                        for tool_info in introspected
                    ],
                }
            )
    if json_:
        output = {"tools": output_tools, "toolboxes": output_toolboxes}
        if model is not None:
            output["server_side_tools"] = server_side_tools
        click.echo(json.dumps(output, indent=2))
    else:
        for tool in tool_objects:
            sig = "()"
            if tool.implementation:
                sig = str(inspect.signature(tool.implementation))
            click.echo(
                "{}{}{}\n".format(
                    tool.name,
                    sig,
                    f" (plugin: {tool.plugin})" if tool.plugin else "",
                )
            )
            if tool.description:
                click.echo(textwrap.indent(tool.description.strip(), "  ") + "\n")
        for name, toolbox, toolbox_class, is_dynamic, introspected in toolbox_infos:
            if is_dynamic and isinstance(toolbox, type):
                # A dynamic toolbox class has no tools until it is
                # instantiated - show its constructor and docstring instead
                try:
                    constructor_sig = str(inspect.signature(toolbox_class))
                except (ValueError, TypeError):
                    constructor_sig = "(...)"
                plugin = getattr(toolbox_class, "plugin", None)
                click.echo(
                    "{}{}{}\n".format(
                        name,
                        constructor_sig,
                        f" (plugin: {plugin})" if plugin else "",
                    )
                )
                doc = toolbox_class.__doc__
                if doc:
                    click.echo(textwrap.indent(inspect.cleandoc(doc), "  ") + "\n")
            else:
                click.echo(toolbox_specs.get(id(toolbox), name) + ":\n")
            for tool_info in introspected:
                sig = "()"
                if tool_info["implementation"]:
                    sig = (
                        str(inspect.signature(tool_info["implementation"]))
                        .replace("(self, ", "(")
                        .replace("(self)", "()")
                    )
                click.echo(f"  {tool_info['name']}{sig}\n")
                if tool_info["description"]:
                    click.echo(
                        textwrap.indent(tool_info["description"].strip(), "    ") + "\n"
                    )
        if model is not None and server_side_tools:
            click.echo(
                f"Server-side tools for {model.model_id} "
                "(executed by the provider):\n"
            )
            for tool_info in server_side_tools:
                click.echo(f"{tool_info['name']}{tool_info['signature']}\n")
                if tool_info["description"]:
                    click.echo(textwrap.indent(tool_info["description"], "  ") + "\n")


@cli.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def aliases():
    "Manage model aliases"


@aliases.command(name="list")
@click.option("json_", "--json", is_flag=True, help="Output as JSON")
def aliases_list(json_):
    "List current aliases"
    to_output = []
    for alias, model in get_model_aliases().items():
        if alias != model.model_id:
            to_output.append((alias, model.model_id, ""))
    for alias, embedding_model in get_embedding_model_aliases().items():
        if alias != embedding_model.model_id:
            to_output.append((alias, embedding_model.model_id, "embedding"))
    if json_:
        click.echo(
            json.dumps({key: value for key, value, type_ in to_output}, indent=4)
        )
        return
    if not to_output:
        return
    max_alias_length = max(len(a) for a, _, _ in to_output)
    fmt = "{alias:<" + str(max_alias_length) + "} : {model_id}{type_}"
    for alias, model_id, type_ in to_output:
        click.echo(
            fmt.format(
                alias=alias, model_id=model_id, type_=f" ({type_})" if type_ else ""
            )
        )


@aliases.command(name="set")
@click.argument("alias")
@click.argument("model_id", required=False)
@click.option(
    "-q",
    "--query",
    multiple=True,
    help="Set alias for model matching these strings",
)
def aliases_set(alias, model_id, query):
    """
    Set an alias for a model

    Example usage:

    \b
        llm aliases set luna gpt-5.6-luna

    Alternatively you can omit the model ID and specify one or more -q options.
    The first model matching all of those query strings will be used.

    \b
        llm aliases set luna -q gpt -q luna
    """
    if not model_id:
        if not query:
            raise click.ClickException(
                "You must provide a model_id or at least one -q option"
            )
        # Search for the first model matching all query strings
        found = None
        for model_with_aliases in get_models_with_aliases():
            if all(model_with_aliases.matches(q) for q in query):
                found = model_with_aliases
                break
        if not found:
            raise click.ClickException(
                "No model found matching query: " + ", ".join(query)
            )
        model_id = found.model.model_id
        set_alias(alias, model_id)
        click.echo(
            f"Alias '{alias}' set to model '{model_id}'",
            err=True,
        )
    else:
        set_alias(alias, model_id)


@aliases.command(name="remove")
@click.argument("alias")
def aliases_remove(alias):
    """
    Remove an alias

    Example usage:

    \b
        $ llm aliases remove turbo
    """
    try:
        remove_alias(alias)
    except KeyError as ex:
        raise click.ClickException(ex.args[0])


@aliases.command(name="path")
def aliases_path():
    "Output the path to the aliases.json file"
    click.echo(user_dir() / "aliases.json")


@cli.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def fragments():
    """
    Manage fragments that are stored in the database

    Fragments are reusable snippets of text that are shared across multiple prompts.
    """


@fragments.command(name="list")
@click.option(
    "queries",
    "-q",
    "--query",
    multiple=True,
    help="Search for fragments matching these strings",
)
@click.option("--aliases", is_flag=True, help="Show only fragments with aliases")
@click.option("json_", "--json", is_flag=True, help="Output as JSON")
def fragments_list(queries, aliases, json_):
    "List current fragments"
    db = sqlite_utils.Database(logs_db_path())
    migrate(db)
    params = {}
    where_bits = []
    if aliases:
        where_bits.append("fragment_aliases.alias is not null")
    for param_count, q in enumerate(queries, start=1):
        p = f"p{param_count}"
        params[p] = q
        where_bits.append(f"""
            (fragments.hash = :{p} or fragment_aliases.alias = :{p}
            or fragments.source like '%' || :{p} || '%'
            or fragments.content like '%' || :{p} || '%')
        """)
    where = "\n      and\n  ".join(where_bits)
    if where:
        where = " where " + where
    sql = f"""
    select
        fragments.hash,
        json_group_array(fragment_aliases.alias) filter (
            where
            fragment_aliases.alias is not null
        ) as aliases,
        fragments.datetime_utc,
        fragments.source,
        fragments.content
    from
        fragments
    left join
        fragment_aliases on fragment_aliases.fragment_id = fragments.id
    {where}
    group by
        fragments.id, fragments.hash, fragments.content, fragments.datetime_utc, fragments.source
    order by fragments.datetime_utc
    """
    results = list(db.query(sql, params))
    for result in results:
        result["aliases"] = json.loads(result["aliases"])
    if json_:
        click.echo(json.dumps(results, indent=4))
    else:
        yaml.add_representer(
            str,
            lambda dumper, data: dumper.represent_scalar(
                "tag:yaml.org,2002:str", data, style="|" if "\n" in data else None
            ),
        )
        for result in results:
            result["content"] = truncate_string(result["content"])
            click.echo(yaml.dump([result], sort_keys=False, width=sys.maxsize).strip())


@fragments.command(name="set")
@click.argument("alias", callback=validate_fragment_alias)
@click.argument("fragment")
def fragments_set(alias, fragment):
    """
    Set an alias for a fragment

    Accepts an alias and a file path, URL, hash or '-' for stdin

    Example usage:

    \b
        llm fragments set mydocs ./docs.md
    """
    db = sqlite_utils.Database(logs_db_path())
    migrate(db)
    try:
        resolved = resolve_fragments(db, [fragment])[0]
    except FragmentNotFound as ex:
        raise click.ClickException(str(ex))
    migrate(db)
    alias_sql = """
    insert into fragment_aliases (alias, fragment_id)
    values (:alias, :fragment_id)
    on conflict(alias) do update set
        fragment_id = excluded.fragment_id;
    """
    with db.atomic():
        fragment_id = ensure_fragment(db, resolved)
        db.execute(alias_sql, {"alias": alias, "fragment_id": fragment_id})


@fragments.command(name="show")
@click.argument("alias_or_hash")
def fragments_show(alias_or_hash):
    """
    Display the fragment stored under an alias or hash

    \b
        llm fragments show mydocs
    """
    db = sqlite_utils.Database(logs_db_path())
    migrate(db)
    try:
        resolved = resolve_fragments(db, [alias_or_hash])[0]
    except FragmentNotFound as ex:
        raise click.ClickException(str(ex))
    click.echo(resolved)


@fragments.command(name="remove")
@click.argument("alias", callback=validate_fragment_alias)
def fragments_remove(alias):
    """
    Remove a fragment alias

    Example usage:

    \b
        llm fragments remove docs
    """
    db = sqlite_utils.Database(logs_db_path())
    migrate(db)
    db.execute("delete from fragment_aliases where alias = :alias", {"alias": alias})


@fragments.command(name="loaders")
def fragments_loaders():
    """Show fragment loaders registered by plugins"""
    from llm import get_fragment_loaders

    found = False
    for prefix, loader in get_fragment_loaders().items():
        if found:
            # Extra newline on all after the first
            click.echo("")
        found = True
        docs = "Undocumented"
        if loader.__doc__:
            docs = textwrap.dedent(loader.__doc__).strip()
        click.echo(f"{prefix}:")
        click.echo(textwrap.indent(docs, "  "))
    if not found:
        click.echo("No fragment loaders found")


@cli.command(name="plugins")
@click.option("--all", help="Include built-in default plugins", is_flag=True)
@click.option(
    "hooks", "--hook", help="Filter for plugins that implement this hook", multiple=True
)
def plugins_list(all, hooks):
    "List installed plugins"
    plugins = get_plugins(all)
    hooks = set(hooks)
    if hooks:
        plugins = [plugin for plugin in plugins if hooks.intersection(plugin["hooks"])]
    click.echo(json.dumps(plugins, indent=2))


def display_truncated(text):
    console_width = shutil.get_terminal_size()[0]
    if len(text) > console_width:
        return text[: console_width - 3] + "..."
    else:
        return text


@cli.command()
@click.argument("packages", nargs=-1, required=False)
@click.option(
    "-U", "--upgrade", is_flag=True, help="Upgrade packages to latest version"
)
@click.option(
    "-e",
    "--editable",
    help="Install a project in editable mode from this path",
)
@click.option(
    "--force-reinstall",
    is_flag=True,
    help="Reinstall all packages even if they are already up-to-date",
)
@click.option(
    "--no-cache-dir",
    is_flag=True,
    help="Disable the cache",
)
@click.option(
    "--pre",
    is_flag=True,
    help="Include pre-release and development versions",
)
def install(packages, upgrade, editable, force_reinstall, no_cache_dir, pre):
    """Install packages from PyPI into the same environment as LLM"""
    args = ["pip", "install"]
    if upgrade:
        args += ["--upgrade"]
    if editable:
        args += ["--editable", editable]
    if force_reinstall:
        args += ["--force-reinstall"]
    if no_cache_dir:
        args += ["--no-cache-dir"]
    if pre:
        args += ["--pre"]
    args += list(packages)
    sys.argv = args
    run_module("pip", run_name="__main__")


@cli.command()
@click.argument("packages", nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="Don't ask for confirmation")
def uninstall(packages, yes):
    """Uninstall Python packages from the LLM environment"""
    sys.argv = ["pip", "uninstall"] + list(packages) + (["-y"] if yes else [])
    run_module("pip", run_name="__main__")


@cli.command()
@click.argument("collection", required=False)
@click.argument("id", required=False)
@click.option(
    "-i",
    "--input",
    type=click.Path(exists=True, readable=True, allow_dash=True),
    help="File to embed",
)
@click.option(
    "-m", "--model", help="Embedding model to use", envvar="LLM_EMBEDDING_MODEL"
)
@click.option("--key", help="API key to use")
@click.option("--store", is_flag=True, help="Store the text itself in the database")
@click.option(
    "-d",
    "--database",
    type=click.Path(file_okay=True, allow_dash=False, dir_okay=False, writable=True),
    envvar="LLM_EMBEDDINGS_DB",
)
@click.option(
    "-c",
    "--content",
    help="Content to embed",
)
@click.option("--binary", is_flag=True, help="Treat input as binary data")
@click.option(
    "--metadata",
    help="JSON object metadata to store",
    callback=json_validator("metadata"),
)
@click.option(
    "format_",
    "-f",
    "--format",
    type=click.Choice(["json", "blob", "base64", "hex"]),
    help="Output format",
)
def embed(
    collection,
    id,
    input,
    model,
    key,
    store,
    database,
    content,
    binary,
    metadata,
    format_,
):
    """Embed text and store or return the result"""
    if collection and not id:
        raise click.ClickException("Must provide both collection and id")

    if store and not collection:
        raise click.ClickException("Must provide collection when using --store")

    # Lazy load this because we do not need it for -c or -i versions
    def get_db():
        if database:
            return sqlite_utils.Database(database)
        else:
            return sqlite_utils.Database(user_dir() / "embeddings.db")

    collection_obj = None
    model_obj = None
    if collection:
        db = get_db()
        if Collection.exists(db, collection):
            # Load existing collection and use its model
            collection_obj = Collection(collection, db)
            model_obj = collection_obj.model()
        else:
            # We will create a new one, but that means model is required
            if not model:
                model = get_default_embedding_model()
                if model is None:
                    raise click.ClickException(
                        "You need to specify an embedding model (no default model is set)"
                    )
            collection_obj = Collection(collection, db=db, model_id=model)
            model_obj = collection_obj.model()

    if model_obj is None:
        if model is None:
            model = get_default_embedding_model()
        try:
            model_obj = get_embedding_model(model)
        except UnknownModelError:
            raise click.ClickException(
                "You need to specify an embedding model (no default model is set)"
            )

    show_output = True
    if collection and (format_ is None):
        show_output = False

    # Resolve input text
    if not content:
        if not input or input == "-":
            # Read from stdin
            input_source = sys.stdin.buffer if binary else sys.stdin
            content = input_source.read()
        else:
            mode = "rb" if binary else "r"
            with open(input, mode) as f:
                content = f.read()

    if not content:
        raise click.ClickException("No content provided")

    if collection_obj:
        embedding = collection_obj.embed(
            id, content, metadata=metadata, store=store, key=key
        )
    else:
        embedding = model_obj.embed(content, key=key)

    if show_output:
        if format_ == "json" or format_ is None:
            click.echo(json.dumps(embedding))
        elif format_ == "blob":
            click.echo(encode(embedding))
        elif format_ == "base64":
            click.echo(base64.b64encode(encode(embedding)).decode("ascii"))
        elif format_ == "hex":
            click.echo(encode(embedding).hex())


@cli.command()
@click.argument("collection")
@click.argument(
    "input_path",
    type=click.Path(exists=True, dir_okay=False, allow_dash=True, readable=True),
    required=False,
)
@click.option(
    "--format",
    type=click.Choice(["json", "csv", "tsv", "nl"]),
    help="Format of input file - defaults to auto-detect",
)
@click.option(
    "--files",
    type=(click.Path(file_okay=False, dir_okay=True, allow_dash=False), str),
    multiple=True,
    help="Embed files in this directory - specify directory and glob pattern",
)
@click.option(
    "encodings",
    "--encoding",
    help="Encodings to try when reading --files",
    multiple=True,
)
@click.option("--binary", is_flag=True, help="Treat --files as binary data")
@click.option("--sql", help="Read input using this SQL query")
@click.option(
    "--attach",
    type=(str, click.Path(file_okay=True, dir_okay=False, allow_dash=False)),
    multiple=True,
    help="Additional databases to attach - specify alias and file path",
)
@click.option(
    "--batch-size", type=int, help="Batch size to use when running embeddings"
)
@click.option("--prefix", help="Prefix to add to the IDs", default="")
@click.option(
    "-m", "--model", help="Embedding model to use", envvar="LLM_EMBEDDING_MODEL"
)
@click.option("--key", help="API key to use")
@click.option(
    "--prepend",
    help="Prepend this string to all content before embedding",
)
@click.option("--store", is_flag=True, help="Store the text itself in the database")
@click.option(
    "-d",
    "--database",
    type=click.Path(file_okay=True, allow_dash=False, dir_okay=False, writable=True),
    envvar="LLM_EMBEDDINGS_DB",
)
def embed_multi(
    collection,
    input_path,
    format,
    files,
    encodings,
    binary,
    sql,
    attach,
    batch_size,
    prefix,
    model,
    key,
    prepend,
    store,
    database,
):
    """
    Store embeddings for multiple strings at once in the specified collection.

    Input data can come from one of three sources:

    \b
    1. A CSV, TSV, JSON or JSONL file:
       - CSV/TSV: First column is ID, remaining columns concatenated as content
       - JSON: Array of objects with "id" field and content fields
       - JSONL: Newline-delimited JSON objects

    \b
       Examples:
         llm embed-multi docs input.csv
         cat data.json | llm embed-multi docs -
         llm embed-multi docs input.json --format json

    \b
    2. A SQL query against a SQLite database:
       - First column returned is used as ID
       - Other columns concatenated to form content

    \b
       Examples:
         llm embed-multi docs --sql "SELECT id, title, body FROM posts"
         llm embed-multi docs --attach blog blog.db --sql "SELECT id, content FROM blog.posts"

    \b
    3. Files in directories matching glob patterns:
       - Each file becomes one embedding
       - Relative file paths become IDs

    \b
       Examples:
         llm embed-multi docs --files docs '**/*.md'
         llm embed-multi images --files photos '*.jpg' --binary
         llm embed-multi texts --files texts '*.txt' --encoding utf-8 --encoding latin-1
    """
    if binary and not files:
        raise click.UsageError("--binary must be used with --files")
    if binary and encodings:
        raise click.UsageError("--binary cannot be used with --encoding")
    if not input_path and not sql and not files:
        raise click.UsageError("Either --sql or input path or --files is required")

    if files and (input_path or sql or format):
        raise click.UsageError("Cannot use --files with --sql, input path or --format")

    if database:
        db = sqlite_utils.Database(database)
    else:
        db = sqlite_utils.Database(user_dir() / "embeddings.db")

    for alias, attach_path in attach:
        db.attach(alias, attach_path)

    model_id = model or get_default_embedding_model()
    try:
        collection_obj = Collection(
            collection, db=db, model_id=model_id, create=model_id is not None
        )
    except (Collection.DoesNotExist, UnknownModelError):
        raise click.ClickException(
            "You need to specify an embedding model (no default model is set)"
        )

    expected_length = None
    if files:
        encodings = encodings or ("utf-8", "latin-1")

        def count_files():
            i = 0
            for directory, pattern in files:
                for path in pathlib.Path(directory).glob(pattern):
                    i += 1
            return i

        def iterate_files():
            for directory, pattern in files:
                p = pathlib.Path(directory)
                if not p.exists() or not p.is_dir():
                    # fixes issue/274 - raise error if directory does not exist
                    raise click.UsageError(f"Invalid directory: {directory}")
                for path in pathlib.Path(directory).glob(pattern):
                    if path.is_dir():
                        continue  # fixed issue/280 - skip directories
                    relative = path.relative_to(directory)
                    content = None
                    if binary:
                        content = path.read_bytes()
                    else:
                        for encoding in encodings:
                            try:
                                content = path.read_text(encoding=encoding)
                            except UnicodeDecodeError:
                                continue
                    if content is None:
                        # Log to stderr
                        click.echo(
                            f"Could not decode text in file {path}",
                            err=True,
                        )
                    else:
                        yield {"id": str(relative), "content": content}

        expected_length = count_files()
        rows = iterate_files()
    elif sql:
        rows = db.query(sql)
        count_sql = f"select count(*) as c from ({sql})"
        expected_length = next(db.query(count_sql))["c"]
    else:

        def load_rows(fp):
            return rows_from_file(fp, Format[format.upper()] if format else None)[0]

        try:
            if input_path != "-":
                # Read the file twice - first time is to get a count
                expected_length = 0
                with open(input_path, "rb") as fp:
                    for _ in load_rows(fp):
                        expected_length += 1

            if input_path != "-":

                def rows_from_input():
                    with open(input_path, "rb") as fp:
                        yield from load_rows(fp)

                rows = rows_from_input()
            else:
                rows = load_rows(io.BufferedReader(sys.stdin.buffer))
        except json.JSONDecodeError as ex:
            raise click.ClickException(str(ex))

    with click.progressbar(
        rows, label="Embedding", show_percent=True, length=expected_length
    ) as rows:

        def tuples() -> Iterable[tuple[str, bytes | str]]:
            for row in rows:
                values = list(row.values())
                id: str = prefix + str(values[0])
                content: bytes | str | None = None
                if binary:
                    content = cast(bytes, values[1])
                else:
                    content = " ".join(v or "" for v in values[1:])
                if prepend and isinstance(content, str):
                    content = prepend + content
                yield id, content or ""

        embed_kwargs = {"store": store, "key": key}
        if batch_size:
            embed_kwargs["batch_size"] = batch_size
        collection_obj.embed_multi(tuples(), **embed_kwargs)


@cli.command()
@click.argument("collection")
@click.argument("id", required=False)
@click.option(
    "-i",
    "--input",
    type=click.Path(exists=True, readable=True, allow_dash=True),
    help="File to embed for comparison",
)
@click.option("-c", "--content", help="Content to embed for comparison")
@click.option("--binary", is_flag=True, help="Treat input as binary data")
@click.option(
    "-n", "--number", type=int, default=10, help="Number of results to return"
)
@click.option("-p", "--plain", is_flag=True, help="Output in plain text format")
@click.option(
    "-d",
    "--database",
    type=click.Path(file_okay=True, allow_dash=False, dir_okay=False, writable=True),
    envvar="LLM_EMBEDDINGS_DB",
)
@click.option("--prefix", help="Just IDs with this prefix", default="")
def similar(collection, id, input, content, binary, number, plain, database, prefix):
    """
    Return top N similar IDs from a collection using cosine similarity.

    Example usage:

    \b
        llm similar my-collection -c "I like cats"

    Or to find content similar to a specific stored ID:

    \b
        llm similar my-collection 1234
    """
    if not id and not content and not input:
        raise click.ClickException("Must provide content or an ID for the comparison")

    if database:
        db = sqlite_utils.Database(database)
    else:
        db = sqlite_utils.Database(user_dir() / "embeddings.db")

    if not db["embeddings"].exists():
        raise click.ClickException("No embeddings table found in database")

    try:
        collection_obj = Collection(collection, db, create=False)
    except Collection.DoesNotExist:
        raise click.ClickException("Collection does not exist")

    if id:
        try:
            results = collection_obj.similar_by_id(id, number, prefix=prefix)
        except Collection.DoesNotExist:
            raise click.ClickException("ID not found in collection")
    else:
        # Resolve input text
        if not content:
            if not input or input == "-":
                # Read from stdin
                input_source = sys.stdin.buffer if binary else sys.stdin
                content = input_source.read()
            else:
                mode = "rb" if binary else "r"
                with open(input, mode) as f:
                    content = f.read()
        if not content:
            raise click.ClickException("No content provided")
        results = collection_obj.similar(content, number, prefix=prefix)

    for result in results:
        if plain:
            click.echo(f"{result.id} ({result.score})\n")
            if result.content:
                click.echo(textwrap.indent(result.content, "  "))
            if result.metadata:
                click.echo(textwrap.indent(json.dumps(result.metadata), "  "))
            click.echo("")
        else:
            click.echo(json.dumps(asdict(result)))


@cli.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def embed_models():
    "Manage available embedding models"


@embed_models.command(name="list")
@click.option(
    "-q",
    "--query",
    multiple=True,
    help="Search for embedding models matching these strings",
)
def embed_models_list(query):
    "List available embedding models"
    output = []
    for model_with_aliases in get_embedding_models_with_aliases():
        if query and not all(model_with_aliases.matches(q) for q in query):
            continue
        s = str(model_with_aliases.model)
        if model_with_aliases.aliases:
            s += " (aliases: {})".format(", ".join(model_with_aliases.aliases))
        output.append(s)
    click.echo("\n".join(output))


@embed_models.command(name="default")
@click.argument("model", required=False)
@click.option(
    "--remove-default", is_flag=True, help="Reset to specifying no default model"
)
def embed_models_default(model, remove_default):
    "Show or set the default embedding model"
    if not model and not remove_default:
        default = get_default_embedding_model()
        if default is None:
            click.echo("<No default embedding model set>", err=True)
        else:
            click.echo(default)
        return
    # Validate it is a known model
    try:
        if remove_default:
            set_default_embedding_model(None)
        else:
            model = get_embedding_model(model)
            set_default_embedding_model(model.model_id)
    except KeyError:
        raise click.ClickException(f"Unknown embedding model: {model}")


@cli.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def collections():
    "View and manage collections of embeddings"


@collections.command(name="path")
def collections_path():
    "Output the path to the embeddings database"
    click.echo(user_dir() / "embeddings.db")


@collections.command(name="list")
@click.option(
    "-d",
    "--database",
    type=click.Path(file_okay=True, allow_dash=False, dir_okay=False, writable=True),
    envvar="LLM_EMBEDDINGS_DB",
    help="Path to embeddings database",
)
@click.option("json_", "--json", is_flag=True, help="Output as JSON")
def embed_db_collections(database, json_):
    "View a list of collections"
    database = database or (user_dir() / "embeddings.db")
    db = sqlite_utils.Database(str(database))
    if not db["collections"].exists():
        raise click.ClickException(f"No collections table found in {database}")
    rows = db.query("""
    select
        collections.name,
        collections.model,
        count(embeddings.id) as num_embeddings
    from
        collections left join embeddings
        on collections.id = embeddings.collection_id
    group by
        collections.name, collections.model
    """)
    if json_:
        click.echo(json.dumps(list(rows), indent=4))
    else:
        for row in rows:
            click.echo("{}: {}".format(row["name"], row["model"]))
            click.echo(
                "  {} embedding{}".format(
                    row["num_embeddings"], "s" if row["num_embeddings"] != 1 else ""
                )
            )


@collections.command(name="delete")
@click.argument("collection")
@click.option(
    "-d",
    "--database",
    type=click.Path(file_okay=True, allow_dash=False, dir_okay=False, writable=True),
    envvar="LLM_EMBEDDINGS_DB",
    help="Path to embeddings database",
)
def collections_delete(collection, database):
    """
    Delete the specified collection

    Example usage:

    \b
        llm collections delete my-collection
    """
    database = database or (user_dir() / "embeddings.db")
    db = sqlite_utils.Database(str(database))
    try:
        collection_obj = Collection(collection, db, create=False)
    except Collection.DoesNotExist:
        raise click.ClickException("Collection does not exist")
    collection_obj.delete()


@models.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def options():
    "Manage default options for models"


@options.command(name="list")
def options_list():
    """
    List default options for all models

    Example usage:

    \b
        llm models options list
    """
    options = get_all_model_options()
    if not options:
        click.echo("No default options set for any models.", err=True)
        return

    for model_id, model_options in options.items():
        click.echo(f"{model_id}:")
        for key, value in model_options.items():
            click.echo(f"  {key}: {value}")


@options.command(name="show")
@click.argument("model")
def options_show(model):
    """
    List default options set for a specific model

    Example usage:

    \b
        llm models options show gpt-4.1
    """
    import llm

    try:
        # Resolve alias to model ID
        model_obj = llm.get_model(model)
        model_id = model_obj.model_id
    except llm.UnknownModelError:
        # Use as-is if not found
        model_id = model

    options = get_model_options(model_id)
    if not options:
        click.echo(f"No default options set for model '{model_id}'.", err=True)
        return

    for key, value in options.items():
        click.echo(f"{key}: {value}")


@options.command(name="set")
@click.argument("model")
@click.argument("key")
@click.argument("value")
def options_set(model, key, value):
    """
    Set a default option for a model

    Example usage:

    \b
        llm models options set gpt-4.1 temperature 0.5
    """
    import llm

    try:
        # Resolve alias to model ID
        model_obj = llm.get_model(model)
        model_id = model_obj.model_id

        # Validate option against model schema
        try:
            # Create a test Options object to validate
            test_options = {key: value}
            model_obj.Options(**test_options)
        except pydantic.ValidationError as ex:
            raise click.ClickException(render_errors(ex.errors()))

    except llm.UnknownModelError:
        # Use as-is if not found
        model_id = model

    set_model_option(model_id, key, value)
    click.echo(f"Set default option {key}={value} for model {model_id}", err=True)


@options.command(name="clear")
@click.argument("model")
@click.argument("key", required=False)
def options_clear(model, key):
    """
    Clear default option(s) for a model

    Example usage:

    \b
        llm models options clear gpt-4.1
        # Or for a single option
        llm models options clear gpt-4.1 temperature
    """
    import llm

    try:
        # Resolve alias to model ID
        model_obj = llm.get_model(model)
        model_id = model_obj.model_id
    except llm.UnknownModelError:
        # Use as-is if not found
        model_id = model

    cleared_keys = []
    if not key:
        cleared_keys = list(get_model_options(model_id).keys())
        for key_ in cleared_keys:
            clear_model_option(model_id, key_)
    else:
        cleared_keys.append(key)
        clear_model_option(model_id, key)
    if cleared_keys:
        if len(cleared_keys) == 1:
            click.echo(f"Cleared option '{cleared_keys[0]}' for model {model_id}")
        else:
            click.echo(
                f"Cleared {', '.join(cleared_keys)} options for model {model_id}"
            )


def template_dir():
    path = user_dir() / "templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_db_path():
    return user_dir() / "logs.db"


def get_history(chat_id):
    if chat_id is None:
        return None, []
    log_path = logs_db_path()
    db = sqlite_utils.Database(log_path)
    migrate(db)
    if chat_id == -1:
        # Return the most recent chat
        last_row = list(db["logs"].rows_where(order_by="-id", limit=1))
        if last_row:
            chat_id = last_row[0].get("chat_id") or last_row[0].get("id")
        else:  # Database is empty
            return None, []
    rows = db["logs"].rows_where(
        "id = ? or chat_id = ?", [chat_id, chat_id], order_by="id"
    )
    return chat_id, rows


def render_errors(errors):
    output = []
    for error in errors:
        output.append(", ".join(error["loc"]))
        output.append("  " + error["msg"])
    return "\n".join(output)


load_plugins()

pm.hook.register_commands(cli=cli)


def _human_readable_size(size_bytes):
    if size_bytes == 0:
        return "0B"

    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = 0

    while size_bytes >= 1024 and i < len(size_name) - 1:
        size_bytes /= 1024.0
        i += 1

    return f"{size_bytes:.2f}{size_name[i]}"


def logs_on():
    return not (user_dir() / "logs-off").exists()


def get_all_model_options() -> dict:
    """
    Get all default options for all models
    """
    path = user_dir() / "model_options.json"
    if not path.exists():
        return {}

    try:
        options = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}

    return options


def get_model_options(model_id: str) -> dict:
    """
    Get default options for a specific model

    Args:
        model_id: Return options for model with this ID

    Returns:
        A dictionary of model options
    """
    path = user_dir() / "model_options.json"
    if not path.exists():
        return {}

    try:
        options = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}

    return options.get(model_id, {})


def set_model_option(model_id: str, key: str, value: Any) -> None:
    """
    Set a default option for a model.

    Args:
        model_id: The model ID
        key: The option key
        value: The option value
    """
    path = user_dir() / "model_options.json"
    if path.exists():
        try:
            options = json.loads(path.read_text())
        except json.JSONDecodeError:
            options = {}
    else:
        options = {}

    # Ensure the model has an entry
    if model_id not in options:
        options[model_id] = {}

    # Set the option
    options[model_id][key] = value

    # Save the options
    path.write_text(json.dumps(options, indent=2))


def clear_model_option(model_id: str, key: str) -> None:
    """
    Clear a model option

    Args:
        model_id: The model ID
        key: Key to clear
    """
    path = user_dir() / "model_options.json"
    if not path.exists():
        return

    try:
        options = json.loads(path.read_text())
    except json.JSONDecodeError:
        return

    if model_id not in options:
        return

    if key in options[model_id]:
        del options[model_id][key]
        if not options[model_id]:
            del options[model_id]

    path.write_text(json.dumps(options, indent=2))


class LoadTemplateError(ValueError):
    pass


def _parse_yaml_template(name, content):
    try:
        loaded = yaml.safe_load(content)
    except yaml.YAMLError as ex:
        raise LoadTemplateError(f"Invalid YAML: {ex!s}")
    if isinstance(loaded, str):
        return Template(name=name, prompt=loaded)
    loaded["name"] = name
    try:
        return Template(**loaded)
    except pydantic.ValidationError as ex:
        msg = "A validation error occurred:\n"
        msg += render_errors(ex.errors())
        raise LoadTemplateError(msg)


def load_template(name: str) -> Template:
    "Load template, or raise LoadTemplateError(msg)"
    if name.startswith(("https://", "http://")):
        response = httpx2.get(name)
        try:
            response.raise_for_status()
        except httpx2.HTTPStatusError as ex:
            raise LoadTemplateError(f"Could not load template {name}: {ex}")
        return _parse_yaml_template(name, response.text)

    potential_path = pathlib.Path(name)

    if has_plugin_prefix(name) and not potential_path.exists():
        prefix, rest = name.split(":", 1)
        loaders = get_template_loaders()
        if prefix not in loaders:
            raise LoadTemplateError(f"Unknown template prefix: {prefix}")
        loader = loaders[prefix]
        try:
            return loader(rest)
        except Exception as ex:  # noqa: BLE001
            raise LoadTemplateError(f"Could not load template {name}: {ex}")

    # Try local file
    if potential_path.exists():
        path = potential_path
    else:
        # Look for template in template_dir()
        path = template_dir() / f"{name}.yaml"
    if not path.exists():
        raise LoadTemplateError(f"Invalid template: {name}")
    content = path.read_text()
    template_obj = _parse_yaml_template(name, content)
    # We trust functions here because they came from the filesystem
    template_obj._functions_is_trusted = True
    return template_obj


def _tools_from_code(code_or_path: str) -> list[Tool]:
    """
    Treat all Python functions in the code as tools
    """
    if "\n" not in code_or_path and code_or_path.endswith(".py"):
        try:
            code_or_path = pathlib.Path(code_or_path).read_text()
        except FileNotFoundError:
            raise click.ClickException(f"File not found: {code_or_path}")
    namespace: dict[str, Any] = {}
    tools = []
    try:
        exec(code_or_path, namespace)  # noqa: S102
    except SyntaxError as ex:
        raise click.ClickException(f"Error in --functions definition: {ex}")
    # Register all callables in the locals dict:
    for name, value in namespace.items():
        if callable(value) and not name.startswith("_"):
            tools.append(Tool.function(value))
    return tools


def _debug_tool_call(_, tool_call, tool_result):
    click.echo(
        click.style(
            f"\nTool call: {tool_call.name}({tool_call.arguments})",
            fg="yellow",
            bold=True,
        ),
        err=True,
    )
    output = ""
    attachments = ""
    if tool_result.attachments:
        attachments += "\nAttachments:\n"
        for attachment in tool_result.attachments:
            attachments += f"  {attachment!r}\n"

    try:
        output = json.dumps(json.loads(tool_result.output), indent=2)
    except ValueError:
        output = tool_result.output
    output += attachments
    click.echo(
        click.style(
            textwrap.indent(output, "  ") + ("\n" if not tool_result.exception else ""),
            fg="green",
            bold=True,
        ),
        err=True,
    )
    if tool_result.exception:
        click.echo(
            click.style(
                f"  Exception: {tool_result.exception}",
                fg="red",
                bold=True,
            ),
            err=True,
        )


def _approve_tool_call(_, tool_call):
    click.echo(
        click.style(
            f"Tool call: {tool_call.name}({tool_call.arguments})",
            fg="yellow",
            bold=True,
        ),
        err=True,
    )
    if not click.confirm("Approve tool call?"):
        raise CancelToolCall("User cancelled tool call")


def _gather_tools(
    tool_specs: list[str], python_tools: list[str], model=None
) -> list[Tool | Toolbox | ServerSideTool]:
    tools: list[Tool | Toolbox | ServerSideTool] = []
    if python_tools:
        for code_or_path in python_tools:
            tools.extend(_tools_from_code(code_or_path))
    registered_tools = get_tools()
    server_side_tool_classes = {
        tool_class.__name__: tool_class
        for tool_class in (
            model.supported_server_side_tools if model is not None else ()
        )
    }
    available_tools = {**registered_tools, **server_side_tool_classes}
    registered_classes = {
        key: value for key, value in available_tools.items() if inspect.isclass(value)
    }
    bad_tools = [
        tool
        for tool in tool_specs
        if tool.split("(", 1)[0].strip() not in available_tools
    ]
    if bad_tools:
        raise click.ClickException(
            "Tool(s) {} not found. Available tools: {}".format(
                ", ".join(bad_tools), ", ".join(available_tools.keys())
            )
        )
    for tool_spec in tool_specs:
        if not tool_spec[0].isupper():
            # It's a function
            tools.append(available_tools[tool_spec])
        else:
            # It's a class
            tools.append(instantiate_from_spec(registered_classes, tool_spec))
    return tools


def _tool_chain_kwargs(
    tool_specs, python_tools, tools_debug, tools_approve, chain_limit, model=None
):
    """Build Conversation.chain() keyword arguments for CLI-selected tools."""
    tool_implementations = _gather_tools(tool_specs, python_tools, model=model)
    if not tool_implementations:
        return {}
    kwargs = {
        "tools": tool_implementations,
        "chain_limit": chain_limit,
    }
    if tools_debug:
        kwargs["after_call"] = _debug_tool_call
    if tools_approve:
        kwargs["before_call"] = _approve_tool_call
    return kwargs


def _get_conversation_tools(conversation, tools):
    if not conversation or tools:
        return None
    if conversation.responses:
        # Copy plugin tools from first response in conversation
        initial_tools = conversation.responses[0].prompt.tools
        if initial_tools:
            # Only tools from plugins:
            return [tool.name for tool in initial_tools if tool.plugin]
    elif conversation.loaded_tools:
        # Conversation loaded from the message store - tool names and
        # toolbox specs were read from turn_tools instead of rebuilt
        # responses.
        return list(conversation.loaded_tools)
