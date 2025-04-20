import asyncio
import click
from click_default_group import DefaultGroup
from dataclasses import asdict
import io
import json
import os
from llm import (
    Attachment,
    AsyncConversation,
    AsyncKeyModel,
    AsyncResponse,
    Collection,
    Conversation,
    Fragment,
    Response,
    Template,
    UnknownModelError,
    KeyModel,
    encode,
    get_async_model,
    get_default_model,
    get_default_embedding_model,
    get_embedding_models_with_aliases,
    get_embedding_model_aliases,
    get_embedding_model,
    get_plugins,
    get_fragment_loaders,
    get_template_loaders,
    get_model,
    get_model_aliases,
    get_models_with_aliases,
    user_dir,
    set_alias,
    set_default_model,
    set_default_embedding_model,
    remove_alias,
)
from llm.models import _BaseConversation

from .migrations import migrate
from .plugins import pm, load_plugins
from .utils import (
    ensure_fragment,
    extract_fenced_code_block,
    find_unused_key,
    has_plugin_prefix,
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
import base64
import httpx
import pathlib
import pydantic
import re
import readline
from runpy import run_module
import shutil
import sqlite_utils
from sqlite_utils.utils import rows_from_file, Format
import sys
import textwrap
from typing import cast, Optional, Iterable, List, Union, Tuple, Any
import warnings
import yaml

warnings.simplefilter("ignore", ResourceWarning)

DEFAULT_TEMPLATE = "prompt: "


class FragmentNotFound(Exception):
    pass


def validate_fragment_alias(ctx, param, value):
    if not re.match(r"^[a-zA-Z0-9_-]+$", value):
        raise click.BadParameter("Fragment alias must be alphanumeric")
    return value


def resolve_fragments(
    db: sqlite_utils.Database, fragments: Iterable[str]
) -> List[Fragment]:
    """
    Resolve fragments into a list of (content, source) tuples
    """

    def _load_by_alias(fragment):
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

    # These can be URLs or paths or plugin references
    resolved = []
    for fragment in fragments:
        if fragment.startswith("http://") or fragment.startswith("https://"):
            client = httpx.Client(follow_redirects=True, max_redirects=3)
            response = client.get(fragment)
            response.raise_for_status()
            resolved.append(Fragment(response.text, fragment))
        elif fragment == "-":
            resolved.append(Fragment(sys.stdin.read(), "-"))
        elif has_plugin_prefix(fragment):
            prefix, rest = fragment.split(":", 1)
            loaders = get_fragment_loaders()
            if prefix not in loaders:
                raise FragmentNotFound("Unknown fragment prefix: {}".format(prefix))
            loader = loaders[prefix]
            try:
                result = loader(rest)
                if not isinstance(result, list):
                    result = [result]
                resolved.extend(result)
            except Exception as ex:
                raise FragmentNotFound(
                    "Could not load fragment {}: {}".format(fragment, ex)
                )
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


class AttachmentError(Exception):
    """Exception raised for errors in attachment resolution."""

    pass


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
            response = httpx.head(value)
            response.raise_for_status()
            mimetype = response.headers.get("content-type")
        except httpx.HTTPError as ex:
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


def attachment_types_callback(ctx, param, values) -> List[Attachment]:
    collected = []
    for value, mimetype in values:
        collected.append(resolve_attachment_with_type(value, mimetype))
    return collected


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
        help="JSON schema, filepath or ID",
    )(fn)
    return fn


@click.group(
    cls=DefaultGroup,
    default="prompt",
    default_if_no_args=True,
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
@click.option(
    "options",
    "-o",
    "--option",
    type=(str, str),
    multiple=True,
    help="key/value options for the model",
)
@schema_option
@click.option(
    "--schema-multi",
    help="JSON schema to use for multiple results",
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
@click.option("--no-stream", is_flag=True, help="Do not stream output")
@click.option("-n", "--no-log", is_flag=True, help="Don't log to database")
@click.option("--log", is_flag=True, help="Log prompt and response to the database")
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
def prompt(
    prompt,
    system,
    model_id,
    database,
    queries,
    attachments,
    attachment_types,
    options,
    schema_input,
    schema_multi,
    fragments,
    system_fragments,
    template,
    param,
    no_stream,
    no_log,
    log,
    _continue,
    conversation_id,
    key,
    save,
    async_,
    usage,
    extract,
    extract_last,
):
    """
    Execute a prompt

    Documentation: https://llm.datasette.io/en/stable/usage.html

    Examples:

    \b
        llm 'Capital of France?'
        llm 'Capital of France?' -m gpt-4o
        llm 'Capital of France?' -s 'answer in Spanish'

    Multi-modal models can be called with attachments like this:

    \b
        llm 'Extract text from this image' -a image.jpg
        llm 'Describe' -a https://static.simonwillison.net/static/2024/pelicans.jpg
        cat image | llm 'describe image' -a -
        # With an explicit mimetype:
        cat image | llm 'describe image' --at - image/jpeg

    The -x/--extract option returns just the content of the first ``` fenced code
    block, if one is present. If none are present it returns the full response.

    \b
        llm 'JavaScript function for reversing a string' -x
    """
    if log and no_log:
        raise click.ClickException("--log and --no-log are mutually exclusive")

    log_path = pathlib.Path(database) if database else logs_db_path()
    (log_path.parent).mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(log_path)
    migrate(db)

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

    if schema_multi:
        schema_input = schema_multi

    schema = resolve_schema_input(db, schema_input, load_template)

    if schema_multi:
        # Convert that schema into multiple "items" of the same schema
        schema = multi_schema(schema)

    model_aliases = get_model_aliases()

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
            try:
                to_save["model"] = model_aliases[model_id].model_id
            except KeyError:
                raise click.ClickException("'{}' is not a known model".format(model_id))
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
                to_save["options"] = dict(
                    (key, value)
                    for key, value in model.Options(**dict(options))
                    if value is not None
                )
            except pydantic.ValidationError as ex:
                raise click.ClickException(render_errors(ex.errors()))
        path.write_text(
            yaml.dump(
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
        # Cannot be used with system
        try:
            template_obj = load_template(template)
        except LoadTemplateError as ex:
            raise click.ClickException(str(ex))
        extract = template_obj.extract
        extract_last = template_obj.extract_last
        # Combine with template fragments/system_fragments
        if template_obj.fragments:
            fragments = [*template_obj.fragments, *fragments]
        if template_obj.system_fragments:
            system_fragments = [*template_obj.system_fragments, *system_fragments]
        if template_obj.schema_object:
            schema = template_obj.schema_object
        input_ = ""
        if template_obj.options:
            # Make options mutable (they start as a tuple)
            options = list(options)
            # Load any options, provided they were not set using -o already
            specified_options = dict(options)
            for option_name, option_value in template_obj.options.items():
                if option_name not in specified_options:
                    options.append((option_name, option_value))
        if "input" in template_obj.vars():
            input_ = read_prompt()
        try:
            template_prompt, template_system = template_obj.evaluate(input_, params)
            if template_prompt:
                # Combine with user prompt
                if prompt and "input" not in template_obj.vars():
                    prompt = template_prompt + "\n" + prompt
                else:
                    prompt = template_prompt
            if template_system and not system:
                system = template_system
        except Template.MissingVariables as ex:
            raise click.ClickException(str(ex))
        if model_id is None and template_obj.model:
            model_id = template_obj.model
        # Merge in any attachments
        if template_obj.attachments:
            attachments = [
                resolve_attachment(a) for a in template_obj.attachments
            ] + list(attachments)
        if template_obj.attachment_types:
            attachment_types = [
                resolve_attachment_with_type(at.value, at.type)
                for at in template_obj.attachment_types
            ] + list(attachment_types)
    if extract or extract_last:
        no_stream = True

    conversation = None
    if conversation_id or _continue:
        # Load the conversation - loads most recent if no ID provided
        try:
            conversation = load_conversation(conversation_id, async_=async_)
        except UnknownModelError as ex:
            raise click.ClickException(str(ex))

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

    if conversation:
        # To ensure it can see the key
        conversation.model = model

    # Validate options
    validated_options = {}
    if options:
        # Validate with pydantic
        try:
            validated_options = dict(
                (key, value)
                for key, value in model.Options(**dict(options))
                if value is not None
            )
        except pydantic.ValidationError as ex:
            raise click.ClickException(render_errors(ex.errors()))

    # Add on any default model options
    default_options = get_model_options(model_id)
    for key_, value in default_options.items():
        if key_ not in validated_options:
            validated_options[key_] = value

    kwargs = {**validated_options}

    resolved_attachments = [*attachments, *attachment_types]

    should_stream = model.can_stream and not no_stream
    if not should_stream:
        kwargs["stream"] = False

    if isinstance(model, (KeyModel, AsyncKeyModel)):
        kwargs["key"] = key

    prompt = read_prompt()
    response = None

    try:
        fragments = resolve_fragments(db, fragments)
        system_fragments = resolve_fragments(db, system_fragments)
    except FragmentNotFound as ex:
        raise click.ClickException(str(ex))

    prompt_method = model.prompt
    if conversation:
        prompt_method = conversation.prompt

    try:
        if async_:

            async def inner():
                if should_stream:
                    response = prompt_method(
                        prompt,
                        attachments=resolved_attachments,
                        system=system,
                        schema=schema,
                        fragments=fragments,
                        system_fragments=system_fragments,
                        **kwargs,
                    )
                    async for chunk in response:
                        print(chunk, end="")
                        sys.stdout.flush()
                    print("")
                else:
                    response = prompt_method(
                        prompt,
                        fragments=fragments,
                        attachments=resolved_attachments,
                        schema=schema,
                        system=system,
                        system_fragments=system_fragments,
                        **kwargs,
                    )
                    text = await response.text()
                    if extract or extract_last:
                        text = (
                            extract_fenced_code_block(text, last=extract_last) or text
                        )
                    print(text)
                return response

            response = asyncio.run(inner())
        else:
            response = prompt_method(
                prompt,
                fragments=fragments,
                attachments=resolved_attachments,
                system=system,
                schema=schema,
                system_fragments=system_fragments,
                **kwargs,
            )
            if should_stream:
                for chunk in response:
                    print(chunk, end="")
                    sys.stdout.flush()
                print("")
            else:
                text = response.text()
                if extract or extract_last:
                    text = extract_fenced_code_block(text, last=extract_last) or text
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

    if isinstance(response, AsyncResponse):
        response = asyncio.run(response.to_sync_response())

    if usage:
        # Show token usage to stderr in yellow
        click.echo(
            click.style(
                "Token usage: {}".format(response.token_usage()), fg="yellow", bold=True
            ),
            err=True,
        )

    # Log to the database
    if (logs_on() or log) and not no_log:
        response.log_to_db(db)


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
@click.option("--no-stream", is_flag=True, help="Do not stream output")
@click.option("--key", help="API key to use")
def chat(
    system,
    model_id,
    _continue,
    conversation_id,
    template,
    param,
    options,
    no_stream,
    key,
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
    log_path = logs_db_path()
    (log_path.parent).mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(log_path)
    migrate(db)

    conversation = None
    if conversation_id or _continue:
        # Load the conversation - loads most recent if no ID provided
        try:
            conversation = load_conversation(conversation_id)
        except UnknownModelError as ex:
            raise click.ClickException(str(ex))

    template_obj = None
    if template:
        params = dict(param)
        try:
            template_obj = load_template(template)
        except LoadTemplateError as ex:
            raise click.ClickException(str(ex))
        if model_id is None and template_obj.model:
            model_id = template_obj.model

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
        raise click.ClickException("'{}' is not a known model".format(model_id))

    if conversation is None:
        # Start a fresh conversation for this chat
        conversation = Conversation(model=model)
    else:
        # Ensure it can see the API key
        conversation.model = model

    # Validate options
    validated_options = {}
    if options:
        try:
            validated_options = dict(
                (key, value)
                for key, value in model.Options(**dict(options))
                if value is not None
            )
        except pydantic.ValidationError as ex:
            raise click.ClickException(render_errors(ex.errors()))

    kwargs = {}
    kwargs.update(validated_options)

    should_stream = model.can_stream and not no_stream
    if not should_stream:
        kwargs["stream"] = False

    if key and isinstance(model, KeyModel):
        kwargs["key"] = key

    click.echo("Chatting with {}".format(model.model_id))
    click.echo("Type 'exit' or 'quit' to exit")
    click.echo("Type '!multi' to enter multiple lines, then '!end' to finish")
    in_multi = False
    accumulated = []
    end_token = "!end"
    while True:
        prompt = click.prompt("", prompt_suffix="> " if not in_multi else "")
        if prompt.strip().startswith("!multi"):
            in_multi = True
            bits = prompt.strip().split()
            if len(bits) > 1:
                end_token = "!end {}".format(" ".join(bits[1:]))
            continue
        if in_multi:
            if prompt.strip() == end_token:
                prompt = "\n".join(accumulated)
                in_multi = False
                accumulated = []
            else:
                accumulated.append(prompt)
                continue
        if template_obj:
            try:
                template_prompt, template_system = template_obj.evaluate(prompt, params)
            except Template.MissingVariables as ex:
                raise click.ClickException(str(ex))
            if template_system and not system:
                system = template_system
            if template_prompt:
                new_prompt = template_prompt
                if prompt:
                    new_prompt += "\n" + prompt
                prompt = new_prompt
        if prompt.strip() in ("exit", "quit"):
            break
        response = conversation.prompt(prompt, system=system, **kwargs)
        # System prompt only sent for the first message:
        system = None
        for chunk in response:
            print(chunk, end="")
            sys.stdout.flush()
        response.log_to_db(db)
        print("")


def load_conversation(
    conversation_id: Optional[str], async_=False
) -> Optional[_BaseConversation]:
    db = sqlite_utils.Database(logs_db_path())
    migrate(db)
    if conversation_id is None:
        # Return the most recent conversation, or None if there are none
        matches = list(db["conversations"].rows_where(order_by="id desc", limit=1))
        if matches:
            conversation_id = matches[0]["id"]
        else:
            return None
    try:
        row = cast(sqlite_utils.db.Table, db["conversations"]).get(conversation_id)
    except sqlite_utils.db.NotFoundError:
        raise click.ClickException(
            "No conversation found with id={}".format(conversation_id)
        )
    # Inflate that conversation
    conversation_class = AsyncConversation if async_ else Conversation
    response_class = AsyncResponse if async_ else Response
    conversation = conversation_class.from_row(row)
    for response in db["responses"].rows_where(
        "conversation_id = ?", [conversation_id]
    ):
        conversation.responses.append(response_class.from_row(db, response))
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
        raise click.ClickException("No key found with name '{}'".format(name))


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
        click.echo("No log database found at {}".format(path))
        return
    if logs_on():
        click.echo("Logging is ON for all prompts".format())
    else:
        click.echo("Logging is OFF".format())
    db = sqlite_utils.Database(path)
    migrate(db)
    click.echo("Found log database at {}".format(path))
    click.echo("Number of conversations logged:\t{}".format(db["conversations"].count))
    click.echo("Number of responses logged:\t{}".format(db["responses"].count))
    click.echo(
        "Database file size: \t\t{}".format(_human_readable_size(path.stat().st_size))
    )


@logs.command(name="backup")
@click.argument("path", type=click.Path(dir_okay=True, writable=True))
def backup(path):
    "Backup your logs database to this file"
    logs_path = logs_db_path()
    path = pathlib.Path(path)
    db = sqlite_utils.Database(logs_path)
    try:
        db.execute("vacuum into ?", [str(path)])
    except Exception as ex:
        raise click.ClickException(str(ex))
    click.echo(
        "Backed up {} to {}".format(_human_readable_size(path.stat().st_size), path)
    )


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


LOGS_COLUMNS = """    responses.id,
    responses.model,
    responses.prompt,
    responses.system,
    responses.prompt_json,
    responses.options_json,
    responses.response,
    responses.response_json,
    responses.conversation_id,
    responses.duration_ms,
    responses.datetime_utc,
    responses.input_tokens,
    responses.output_tokens,
    responses.token_details,
    conversations.name as conversation_name,
    conversations.model as conversation_model,
    schemas.content as schema_json"""

LOGS_SQL = """
select
{columns}
from
    responses
left join schemas on responses.schema_id = schemas.id
left join conversations on responses.conversation_id = conversations.id{extra_where}
order by responses.id desc{limit}
"""
LOGS_SQL_SEARCH = """
select
{columns}
from
    responses
left join schemas on responses.schema_id = schemas.id
left join conversations on responses.conversation_id = conversations.id
join responses_fts on responses_fts.rowid = responses.rowid
where responses_fts match :query{extra_where}
order by responses_fts.rank desc{limit}
"""

ATTACHMENTS_SQL = """
select
    response_id,
    attachments.id,
    attachments.type,
    attachments.path,
    attachments.url,
    length(attachments.content) as content_length
from attachments
join prompt_attachments
    on attachments.id = prompt_attachments.attachment_id
where prompt_attachments.response_id in ({})
order by prompt_attachments."order"
"""


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
@schema_option
@click.option(
    "--schema-multi",
    help="JSON schema used for multiple results",
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
    schema_input,
    schema_multi,
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
        raise click.ClickException("No log database found at {}".format(path))
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
        raise click.ClickException("Cannot use --short and {} together".format(invalid))

    if response and not current_conversation and not conversation_id:
        current_conversation = True

    if current_conversation:
        try:
            conversation_id = next(
                db.query(
                    "select conversation_id from responses order by id desc limit 1"
                )
            )["conversation_id"]
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

    sql = LOGS_SQL
    if query:
        sql = LOGS_SQL_SEARCH

    limit = ""
    if count is not None and count > 0:
        limit = " limit {}".format(count)

    sql_format = {
        "limit": limit,
        "columns": LOGS_COLUMNS,
        "extra_where": "",
    }
    where_bits = []
    sql_params = {
        "model": model_id,
        "query": query,
        "conversation_id": conversation_id,
        "id_gt": id_gt,
        "id_gte": id_gte,
    }
    if model_id:
        where_bits.append("responses.model = :model")
    if conversation_id:
        where_bits.append("responses.conversation_id = :conversation_id")
    if id_gt:
        where_bits.append("responses.id > :id_gt")
    if id_gte:
        where_bits.append("responses.id >= :id_gte")
    if fragments:
        # Resolve the fragments to their hashes
        fragment_hashes = [
            fragment.id() for fragment in resolve_fragments(db, fragments)
        ]
        exists_clauses = []

        for i, fragment_hash in enumerate(fragment_hashes):
            exists_clause = f"""
            exists (
                select 1 from prompt_fragments
                where prompt_fragments.response_id = responses.id
                and prompt_fragments.fragment_id in (
                    select fragments.id from fragments
                    where hash = :f{i}
                )
                union
                select 1 from system_fragments
                where system_fragments.response_id = responses.id
                and system_fragments.fragment_id in (
                    select fragments.id from fragments
                    where hash = :f{i}
                )
            )
            """
            exists_clauses.append(exists_clause)
            sql_params["f{}".format(i)] = fragment_hash

        where_bits.append(" AND ".join(exists_clauses))
    schema_id = None
    if schema:
        schema_id = make_schema_id(schema)[0]
        where_bits.append("responses.schema_id = :schema_id")
        sql_params["schema_id"] = schema_id

    if where_bits:
        where_ = " and " if query else " where "
        sql_format["extra_where"] = where_ + " and ".join(where_bits)

    final_sql = sql.format(**sql_format)
    rows = list(db.query(final_sql, sql_params))

    # Reverse the order - we do this because we 'order by id desc limit 3' to get the
    # 3 most recent results, but we still want to display them in chronological order
    # ... except for searches where we don't do this
    if not query and not data:
        rows.reverse()

    # Fetch any attachments
    ids = [row["id"] for row in rows]
    attachments = list(db.query(ATTACHMENTS_SQL.format(",".join("?" * len(ids))), ids))
    attachments_by_id = {}
    for attachment in attachments:
        attachments_by_id.setdefault(attachment["response_id"], []).append(attachment)

    FRAGMENTS_SQL = """
    select
        {table}.response_id,
        fragments.hash,
        fragments.id as fragment_id,
        fragments.content,
        (
            select json_group_array(fragment_aliases.alias)
            from fragment_aliases
            where fragment_aliases.fragment_id = fragments.id
        ) as aliases
    from {table}
    join fragments on {table}.fragment_id = fragments.id
    where {table}.response_id in ({placeholders})
    order by {table}."order"
    """

    # Fetch any prompt or system prompt fragments
    prompt_fragments_by_id = {}
    system_fragments_by_id = {}
    for table, dictionary in (
        ("prompt_fragments", prompt_fragments_by_id),
        ("system_fragments", system_fragments_by_id),
    ):
        for fragment in db.query(
            FRAGMENTS_SQL.format(placeholders=",".join("?" * len(ids)), table=table),
            ids,
        ):
            dictionary.setdefault(fragment["response_id"], []).append(fragment)

    if data or data_array or data_key or data_ids:
        # Special case for --data to output valid JSON
        to_output = []
        for row in rows:
            response = row["response"] or ""
            try:
                decoded = json.loads(response)
                new_items = []
                if (
                    isinstance(decoded, dict)
                    and (data_key in decoded)
                    and all(isinstance(item, dict) for item in decoded[data_key])
                ):
                    for item in decoded[data_key]:
                        new_items.append(item)
                else:
                    new_items.append(decoded)
                if data_ids:
                    for item in new_items:
                        item[find_unused_key(item, "response_id")] = row["id"]
                        item[find_unused_key(item, "conversation_id")] = row["id"]
                to_output.extend(new_items)
            except ValueError:
                pass
        click.echo(output_rows_as_json(to_output, not data_array))
        return

    for row in rows:
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
                for fragment in (
                    prompt_fragments_by_id.get(row["id"], [])
                    if key == "prompt_fragments"
                    else system_fragments_by_id.get(row["id"], [])
                )
            ]
        # Either decode or remove all JSON keys
        keys = list(row.keys())
        for key in keys:
            if key.endswith("_json") and row[key] is not None:
                if truncate:
                    del row[key]
                else:
                    row[key] = json.loads(row[key])

    output = None
    if json_output:
        # Output as JSON if requested
        for row in rows:
            row["attachments"] = [
                {k: v for k, v in attachment.items() if k != "response_id"}
                for attachment in attachments_by_id.get(row["id"], [])
            ]
        output = json.dumps(list(rows), indent=2)
    elif extract or extract_last:
        # Extract and return first code block
        for row in rows:
            output = extract_fenced_code_block(row["response"], last=extract_last)
            if output is not None:
                break
    elif response:
        # Just output the last response
        if rows:
            output = rows[-1]["response"]

    if output is not None:
        click.echo(output)
    else:
        # Output neatly formatted human-readable logs
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
                        "\nModel: **{}**\n".format(row["model"])
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
                    response = "```json\n{}\n```".format(json.dumps(parsed, indent=2))
                except ValueError:
                    pass
            click.echo("\n## Response\n\n{}\n".format(response))
            if usage:
                token_usage = token_usage_string(
                    row["input_tokens"],
                    row["output_tokens"],
                    json.loads(row["token_details"]) if row["token_details"] else None,
                )
                if token_usage:
                    click.echo("## Token usage:\n\n{}\n".format(token_usage))


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


@models.command(name="list")
@click.option(
    "--options", is_flag=True, help="Show options for each model, if available"
)
@click.option("async_", "--async", is_flag=True, help="List async models")
@click.option("--schemas", is_flag=True, help="List models that support schemas")
@click.option(
    "-q",
    "--query",
    multiple=True,
    help="Search for models matching these strings",
)
@click.option("model_ids", "-m", "--model", help="Specific model IDs", multiple=True)
def models_list(options, async_, schemas, query, model_ids):
    "List available models"
    models_that_have_shown_options = set()
    for model_with_aliases in get_models_with_aliases():
        if async_ and not model_with_aliases.async_model:
            continue
        if query:
            # Only show models where every provided query string matches
            if not all(model_with_aliases.matches(q) for q in query):
                continue
        if model_ids:
            ids_and_aliases = set(
                [model_with_aliases.model.model_id] + model_with_aliases.aliases
            )
            if not ids_and_aliases.intersection(model_ids):
                continue
        if schemas and not model_with_aliases.model.supports_schema:
            continue
        extra_info = []
        if model_with_aliases.aliases:
            extra_info.append(
                "aliases: {}".format(", ".join(model_with_aliases.aliases))
            )
        model = (
            model_with_aliases.model if not async_ else model_with_aliases.async_model
        )
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
                if description and (
                    model.__class__ not in models_that_have_shown_options
                ):
                    wrapped = textwrap.wrap(description, 70)
                    bits.append("\n      ")
                    bits.extend("\n      ".join(wrapped))
                output += "".join(bits)
            models_that_have_shown_options.add(model.__class__)
        if options and model.attachment_types:
            attachment_types = ", ".join(sorted(model.attachment_types))
            wrapper = textwrap.TextWrapper(
                width=min(max(shutil.get_terminal_size().columns, 30), 70),
                initial_indent="    ",
                subsequent_indent="    ",
            )
            output += "\n  Attachment types:\n{}".format(wrapper.fill(attachment_types))
        features = (
            []
            + (["streaming"] if model.can_stream else [])
            + (["schemas"] if model.supports_schema else [])
            + (["async"] if model_with_aliases.async_model else [])
        )
        if options and features:
            output += "\n  Features:\n{}".format(
                "\n".join("  - {}".format(feature) for feature in features)
            )
        if options and hasattr(model, "needs_key") and model.needs_key:
            output += "\n  Keys:"
            if hasattr(model, "needs_key") and model.needs_key:
                output += "\n    key: {}".format(model.needs_key)
            if hasattr(model, "key_env_var") and model.key_env_var:
                output += "\n    env_var: {}".format(model.key_env_var)
        click.echo(output)
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
        raise click.ClickException("Unknown model: {}".format(model))


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
    template = load_template(name)
    click.echo(
        yaml.dump(
            dict((k, v) for k, v in template.model_dump().items() if v is not None),
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
    click.edit(filename=path)
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
def schemas_list(path, database, queries, full):
    "List stored schemas"
    if database and not path:
        path = database
    path = pathlib.Path(path or logs_db_path())
    if not path.exists():
        raise click.ClickException("No log database found at {}".format(path))
    db = sqlite_utils.Database(path)
    migrate(db)

    params = []
    where_sql = ""
    if queries:
        where_bits = ["schemas.content like ?" for _ in queries]
        where_sql += " where {}".format(" and ".join(where_bits))
        params.extend("%{}%".format(q) for q in queries)

    sql = """
    select
      schemas.id,
      schemas.content,
      max(responses.datetime_utc) as recently_used,
      count(*) as times_used
    from schemas
    join responses
      on responses.schema_id = schemas.id
    {} group by responses.schema_id
    order by recently_used
    """.format(
        where_sql
    )
    rows = db.query(sql, params)
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
        raise click.ClickException("No log database found at {}".format(path))
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
        llm aliases set mini gpt-4o-mini

    Alternatively you can omit the model ID and specify one or more -q options.
    The first model matching all of those query strings will be used.

    \b
        llm aliases set mini -q 4o -q mini
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
    param_count = 0
    where_bits = []
    if aliases:
        where_bits.append("fragment_aliases.alias is not null")
    for q in queries:
        param_count += 1
        p = f"p{param_count}"
        params[p] = q
        where_bits.append(
            f"""
            (fragments.hash = :{p} or fragment_aliases.alias = :{p}
            or fragments.source like '%' || :{p} || '%'
            or fragments.content like '%' || :{p} || '%')
        """
        )
    where = "\n      and\n  ".join(where_bits)
    if where:
        where = " where " + where
    sql = """
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
        fragments.id, fragments.hash, fragments.content, fragments.datetime_utc, fragments.source;
    """.format(
        where=where
    )
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
    with db.conn:
        fragment_id = ensure_fragment(db, resolved)
        db.conn.execute(alias_sql, {"alias": alias, "fragment_id": fragment_id})


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
    with db.conn:
        db.conn.execute(
            "delete from fragment_aliases where alias = :alias", {"alias": alias}
        )


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
def plugins_list(all):
    "List installed plugins"
    click.echo(json.dumps(get_plugins(all), indent=2))


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
def install(packages, upgrade, editable, force_reinstall, no_cache_dir):
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
    collection, id, input, model, store, database, content, binary, metadata, format_
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
        embedding = collection_obj.embed(id, content, metadata=metadata, store=store)
    else:
        embedding = model_obj.embed(content)

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

    if files:
        if input_path or sql or format:
            raise click.UsageError(
                "Cannot use --files with --sql, input path or --format"
            )

    if database:
        db = sqlite_utils.Database(database)
    else:
        db = sqlite_utils.Database(user_dir() / "embeddings.db")

    for alias, attach_path in attach:
        db.attach(alias, attach_path)

    try:
        collection_obj = Collection(
            collection, db=db, model_id=model or get_default_embedding_model()
        )
    except ValueError:
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
                            "Could not decode text in file {}".format(path),
                            err=True,
                        )
                    else:
                        yield {"id": str(relative), "content": content}

        expected_length = count_files()
        rows = iterate_files()
    elif sql:
        rows = db.query(sql)
        count_sql = "select count(*) as c from ({})".format(sql)
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

            rows = load_rows(
                open(input_path, "rb")
                if input_path != "-"
                else io.BufferedReader(sys.stdin.buffer)
            )
        except json.JSONDecodeError as ex:
            raise click.ClickException(str(ex))

    with click.progressbar(
        rows, label="Embedding", show_percent=True, length=expected_length
    ) as rows:

        def tuples() -> Iterable[Tuple[str, Union[bytes, str]]]:
            for row in rows:
                values = list(row.values())
                id: str = prefix + str(values[0])
                content: Optional[Union[bytes, str]] = None
                if binary:
                    content = cast(bytes, values[1])
                else:
                    content = " ".join(v or "" for v in values[1:])
                if prepend and isinstance(content, str):
                    content = prepend + content
                yield id, content or ""

        embed_kwargs = {"store": store}
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
def similar(collection, id, input, content, binary, number, plain, database):
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
            results = collection_obj.similar_by_id(id, number)
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
        results = collection_obj.similar(content, number)

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
        if query:
            if not all(model_with_aliases.matches(q) for q in query):
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
        raise click.ClickException("Unknown embedding model: {}".format(model))


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
        raise click.ClickException("No collections table found in {}".format(database))
    rows = db.query(
        """
    select
        collections.name,
        collections.model,
        count(embeddings.id) as num_embeddings
    from
        collections left join embeddings
        on collections.id = embeddings.collection_id
    group by
        collections.name, collections.model
    """
    )
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
        llm models options show gpt-4o
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
        llm models options set gpt-4o temperature 0.5
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
        llm models options clear gpt-4o
        # Or for a single option
        llm models options clear gpt-4o temperature
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

    return "{:.2f}{}".format(size_bytes, size_name[i])


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
        raise LoadTemplateError("Invalid YAML: {}".format(str(ex)))
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
    if name.startswith("https://") or name.startswith("http://"):
        response = httpx.get(name)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as ex:
            raise LoadTemplateError("Could not load template {}: {}".format(name, ex))
        return _parse_yaml_template(name, response.text)

    potential_path = pathlib.Path(name)

    if has_plugin_prefix(name) and not potential_path.exists():
        prefix, rest = name.split(":", 1)
        loaders = get_template_loaders()
        if prefix not in loaders:
            raise LoadTemplateError("Unknown template prefix: {}".format(prefix))
        loader = loaders[prefix]
        try:
            return loader(rest)
        except Exception as ex:
            raise LoadTemplateError("Could not load template {}: {}".format(name, ex))

    # Try local file
    if potential_path.exists():
        path = potential_path
    else:
        # Look for template in template_dir()
        path = template_dir() / f"{name}.yaml"
    if not path.exists():
        raise LoadTemplateError(f"Invalid template: {name}")
    content = path.read_text()
    return _parse_yaml_template(name, content)
