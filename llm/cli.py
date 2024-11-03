import click
from click_default_group import DefaultGroup
from dataclasses import asdict
import io
import json
from llm import (
    Attachment,
    Collection,
    Conversation,
    Response,
    Template,
    UnknownModelError,
    encode,
    get_default_model,
    get_default_embedding_model,
    get_embedding_models_with_aliases,
    get_embedding_model_aliases,
    get_embedding_model,
    get_key,
    get_plugins,
    get_model,
    get_model_aliases,
    get_models_with_aliases,
    user_dir,
    set_alias,
    set_default_model,
    set_default_embedding_model,
    remove_alias,
)

# Import additional required libraries for functionality
from .migrations import migrate
from .plugins import pm
import base64
import httpx
import pathlib
import puremagic
import pydantic
import readline
from runpy import run_module
import shutil
import sqlite_utils
from sqlite_utils.utils import rows_from_file, Format
import sys
import textwrap
from typing import cast, Optional, Iterable, Union, Tuple
import warnings
import yaml

# Suppress specific resource-related warnings
warnings.simplefilter("ignore", ResourceWarning)

# Default template used in prompt construction
DEFAULT_TEMPLATE = "prompt: "


class AttachmentType(click.ParamType):
    """
    Custom Click parameter type to handle various attachment inputs:
    - Files from local paths
    - URLs
    - Standard input (stdin)
    """

    name = "attachment"

    def convert(self, value, param, ctx):
        """
        Convert the input value to an Attachment object.

        Args:
            value (str): The value provided as an attachment.
            param: The Click parameter instance.
            ctx: The Click context object.

        Returns:
            Attachment: The processed attachment object.

        Raises:
            click.BadParameter: If the mimetype could not be determined or the URL/file is invalid.
        """
        # Handle stdin case
        if value == "-":
            content = sys.stdin.buffer.read()
            # Try to guess type
            try:
                mimetype = puremagic.from_string(content, mime=True)
            except puremagic.PureError:
                raise click.BadParameter("Could not determine mimetype of stdin")
            return Attachment(type=mimetype, path=None, url=None, content=content)
        if "://" in value:
            # Confirm URL exists and try to guess type
            try:
                response = httpx.head(value)
                response.raise_for_status()
                mimetype = response.headers.get("content-type")
            except httpx.HTTPError as ex:
                raise click.BadParameter(str(ex))
            return Attachment(mimetype, None, value, None)
        
        # Check that the file exists
        path = pathlib.Path(value)
        if not path.exists():
            self.fail(f"File {value} does not exist", param, ctx)
        path = path.resolve()
        # Try to guess type
        mimetype = puremagic.from_file(str(path), mime=True)
        return Attachment(type=mimetype, path=str(path), url=None, content=None)


def attachment_types_callback(ctx, param, values):
    """
    Callback to process multiple attachment inputs with explicit mimetypes.

    Args:
        ctx: The Click context object.
        param: The Click parameter instance.
        values: List of (path or URL, mimetype) tuples.

    Returns:
        list: A list of processed Attachment objects.
    """
    collected = []
    for value, mimetype in values:
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
        collected.append(attachment)
    return collected


def _validate_metadata_json(ctx, param, value):
    """
    Validate and parse metadata JSON input.

    Args:
        ctx: The Click context object.
        param: The Click parameter instance.
        value (str): The JSON string to validate.

    Returns:
        dict: Parsed JSON object if valid.

    Raises:
        click.BadParameter: If the JSON string is invalid or not a dictionary.
    """
    if value is None:
        return value
    try:
        obj = json.loads(value)
        if not isinstance(obj, dict):
            raise click.BadParameter("Metadata must be a JSON object")
        return obj
    except json.JSONDecodeError:
        raise click.BadParameter("Metadata must be valid JSON")


@click.group(
    cls=DefaultGroup,
    default="prompt",
    default_if_no_args=True,
)
@click.version_option()
def cli():
    """
    Access large language models from the command-line

    Documentation: https://llm.datasette.io/

    To get started, obtain an OpenAI key and set it like this:

    \b
        $ llm keys set openai
        Enter key: ...

    Then execute a prompt like this:

        llm 'Five outrageous names for a pet pelican'
    """


@cli.command(name="prompt")
@click.argument("prompt", required=False)
@click.option("-s", "--system", help="System prompt to use")
@click.option("model_id", "-m", "--model", help="Model to use")
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
    help="Attachment with explicit mimetype",
)
@click.option(
    "options",
    "-o",
    "--option",
    type=(str, str),
    multiple=True,
    help="key/value options for the model",
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
def prompt(
    prompt,
    system,
    model_id,
    attachments,
    attachment_types,
    options,
    template,
    param,
    no_stream,
    no_log,
    log,
    _continue,
    conversation_id,
    key,
    save,
):
    """
    Execute a prompt

    Documentation: https://llm.datasette.io/en/stable/usage.html

    Examples:

    \b
    Examples:
        - Basic prompt:
            $ llm 'Capital of France?'
        - Specify a model:
            $ llm 'Capital of France?' -m gpt-4
        - Use a system prompt:
            $ llm 'Capital of France?' -s 'answer in Spanish'
        - Multi-modal example with attachments:
            $ llm 'Describe' -a image.jpg

    Multi-modal models can be called with attachments like this:

    \b
        llm 'Extract text from this image' -a image.jpg
        llm 'Describe' -a https://static.simonwillison.net/static/2024/pelicans.jpg
        cat image | llm 'describe image' -a -
        # With an explicit mimetype:
        cat image | llm 'describe image' --at - image/jpeg
    """
    
    # Ensure logging options do not conflict
    if log and no_log:
        raise click.ClickException("--log and --no-log are mutually exclusive")

    # Load model aliases for resolving model IDs
    model_aliases = get_model_aliases()

    def read_prompt():
        """
        Read the prompt input, combining any provided stdin data with the prompt argument.

        Returns:
            str: The combined prompt string.
        """
        nonlocal prompt

        # Is there extra prompt available on stdin?
        stdin_prompt = None
        if not sys.stdin.isatty():
            stdin_prompt = sys.stdin.read()

        if stdin_prompt:
            bits = [stdin_prompt]
            if prompt:
                bits.append(prompt)
            prompt = " ".join(bits)

        if prompt is None and not save and sys.stdin.isatty():
            # Hang waiting for input to stdin (unless --save)
            prompt = sys.stdin.read()
        return prompt

    if save:
    # Save the prompt/system/model to a new template file
    # Disallowed options for saving: template, continue, conversation ID
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
                # Map model alias to the model ID
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
        # Write the template data to a YAML file
        path.write_text(
            yaml.dump(
                to_save,
                indent=4,
                default_flow_style=False,
            ),
            "utf-8",
        )
        return

    if template:
        # Load and evaluate the specified template with parameters
        params = dict(param)
        # Cannot be used with system
        if system:
            raise click.ClickException("Cannot use -t/--template and --system together")
        template_obj = load_template(template)
        prompt = read_prompt()
        try:
            # Evaluate the template with the provided parameters
            prompt, system = template_obj.evaluate(prompt, params)
        except Template.MissingVariables as ex:
            raise click.ClickException(str(ex))
        if model_id is None and template_obj.model:
            model_id = template_obj.model
            
    conversation = None
    if conversation_id or _continue:
        # Load the conversation - loads most recent if no ID provided
        try:
            conversation = load_conversation(conversation_id)
        except UnknownModelError as ex:
            raise click.ClickException(str(ex))

    # Determine the model to use
    if model_id is None:
        if conversation:
            model_id = conversation.model.model_id
        else:
            model_id = get_default_model()

    #  Resolve the model using aliases
    try:
        model = model_aliases[model_id]
    except KeyError:
        raise click.ClickException("'{}' is not a known model".format(model_id))

    # Provide the API key, if one is needed and has been provided
    if model.needs_key:
        model.key = get_key(key, model.needs_key, model.key_env_var)

    if conversation:
        # Ensure the conversation can access the model's key
        conversation.model = model

    # Validate options using pydantic
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

    # Combine attachments and handle streaming
    resolved_attachments = [*attachments, *attachment_types]

    should_stream = model.can_stream and not no_stream
    if not should_stream:
        validated_options["stream"] = False

    # Read the prompt input 
    prompt = read_prompt()

    # Use the conversation's prompt method if available
    prompt_method = model.prompt
    if conversation:
        prompt_method = conversation.prompt

    try:
        # Send the prompt to the model and handle the response
        response = prompt_method(
            prompt, attachments=resolved_attachments, system=system, **validated_options
        )
        if should_stream:
            for chunk in response:
                print(chunk, end="")
                sys.stdout.flush()
            print("")
        else:
            print(response.text())
    except Exception as ex:
        raise click.ClickException(str(ex))

    # Log the response to the database if logging is enabled
    if (logs_on() or log) and not no_log:
        log_path = logs_db_path()
        (log_path.parent).mkdir(parents=True, exist_ok=True)
        db = sqlite_utils.Database(log_path)
        migrate(db)
        response.log_to_db(db)

# Chat command setup
@cli.command()
@click.option("-s", "--system", help="System prompt to use")
@click.option("model_id", "-m", "--model", help="Model to use")
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
    readline.parse_and_bind("\\e[D: backward-char")
    readline.parse_and_bind("\\e[C: forward-char")
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
        # Cannot be used with system
        if system:
            raise click.ClickException("Cannot use -t/--template and --system together")
        template_obj = load_template(template)
        if model_id is None and template_obj.model:
            model_id = template_obj.model

    # Determine the model to use
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

    # Provide the API key, if one is needed and has been provided
    if model.needs_key:
        model.key = get_key(key, model.needs_key, model.key_env_var)

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
        
    # Set streaming flag
    should_stream = model.can_stream and not no_stream
    if not should_stream:
        validated_options["stream"] = False

    # Inform the user about the chat session
    click.echo("Chatting with {}".format(model.model_id))
    click.echo("Type 'exit' or 'quit' to exit")
    click.echo("Type '!multi' to enter multiple lines, then '!end' to finish")
    
    # Handle multi-line input
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
                prompt, system = template_obj.evaluate(prompt, params)
            except Template.MissingVariables as ex:
                raise click.ClickException(str(ex))
        if prompt.strip() in ("exit", "quit"):
            break
        
        # Send the prompt and stream the response
        response = conversation.prompt(prompt, system=system, **validated_options)
        system = None # Reset system prompt after first use
        for chunk in response:
            print(chunk, end="")
            sys.stdout.flush()
        response.log_to_db(db)
        print("")


def load_conversation(conversation_id: Optional[str]) -> Optional[Conversation]:
    """
    Load a conversation by its ID from the logs database.

    If no ID is provided, the function retrieves the most recent conversation. 
    It also gathers all associated responses for the given conversation and returns 
    an inflated Conversation object.

    Args:
        conversation_id (Optional[str]): The ID of the conversation to load. If None, 
        the most recent conversation is retrieved.

    Returns:
        Optional[Conversation]: A Conversation object with all related responses, 
        or None if no conversation is found.

    Raises:
        click.ClickException: If the specified conversation ID does not exist in the database.
    """
    # Connect to the SQLite database using the provided logs database path
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
        # Attempt to retrieve the conversation row from the database
        row = cast(sqlite_utils.db.Table, db["conversations"]).get(conversation_id)
    except sqlite_utils.db.NotFoundError:
        # If the conversation is not found, raise a Click exception with a friendly message
        raise click.ClickException(
            "No conversation found with id={}".format(conversation_id)
        )
        
    # Inflate that conversation
    conversation = Conversation.from_row(row)
    # Load and append all responses associated with this conversation
    for response in db["responses"].rows_where(
        "conversation_id = ?", [conversation_id]
    ):
        conversation.responses.append(Response.from_row(db, response))
    return conversation # Return the populated Conversation object

# CLI group for managing API keys
@cli.group(
    cls=DefaultGroup, # Use DefaultGroup to handle default command behavior
    default="list", # Default command to execute if no arguments are provided
    default_if_no_args=True,
)
def keys():
    """
    Manage stored API keys for different models.

    This command group provides subcommands to list, view the path, and set API keys
    used for interacting with different models.
    """

# Command to list all stored API keys
@keys.command(name="list")
def keys_list():
    """
    List the names of all stored API keys.

    Example usage:
        $ llm keys list

    This command outputs all stored API key names, excluding any comments or notes.
    """
    path = user_dir() / "keys.json" # Path to the keys.json file
    if not path.exists(): # Check if the file exists
        click.echo("No keys found")
        return
    keys = json.loads(path.read_text()) # Read and parse the keys.json file
    for key in sorted(keys.keys()): 
        if key != "// Note": # Exclude any notes or comments in the file
            click.echo(key)

# Command to output the path to the keys.json file
@keys.command(name="path")
def keys_path_command():
    """
    Output the path to the keys.json file.

    Example usage:
        $ llm keys path

    This command prints the file path where API keys are stored.
    """
    click.echo(user_dir() / "keys.json")


@keys.command(name="set")
@click.argument("name")
@click.option("--value", prompt="Enter key", hide_input=True, help="Value to set")
def keys_set(name, value):
    """
    Save a key in the keys.json file.

    This command allows you to securely store an API key for later use.
    The key is saved in the keys.json file with restricted file permissions.

    Args:
        name (str): The name or identifier for the API key.
        value (str): The value of the API key, entered securely.

    Example usage:
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

# CLI group for exploring and managing logged prompts and responses
@cli.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def logs():
    """
    Tools for exploring logged prompts and responses.

    This command group provides options to check the status of logging, 
    view logs, and manage logging settings.
    """

# Command to output the path to the logs database
@logs.command(name="path")
def logs_path():
    
    "Output the path to the logs.db file"
    click.echo(logs_db_path())


@logs.command(name="status")
def logs_status():
    """
    Show the current status of database logging.

    Example usage:
        $ llm logs status

    This command indicates whether logging is currently enabled or disabled,
    and provides details about the logs database, including the number of
    logged conversations and responses, as well as the database file size.
    """
    path = logs_db_path()
    if not path.exists():
        click.echo("No log database found at {}".format(path))
        return
    if logs_on():
        click.echo("Logging is ON for all prompts".format())
    else:
        click.echo("Logging is OFF".format())
        
    # Connect to the database and display logging details
    db = sqlite_utils.Database(path)
    migrate(db)
    click.echo("Found log database at {}".format(path))
    click.echo("Number of conversations logged:\t{}".format(db["conversations"].count))
    click.echo("Number of responses logged:\t{}".format(db["responses"].count))
    click.echo(
        "Database file size: \t\t{}".format(_human_readable_size(path.stat().st_size))
    )

# Command to enable logging
@logs.command(name="on")
def logs_turn_on():
    """
    Turn on logging for all prompts.

    Example usage:
        $ llm logs on

    This command deletes the 'logs-off' file, which enables logging for all 
    future prompts and responses.
    """
    path = user_dir() / "logs-off"
    if path.exists():
        path.unlink()


@logs.command(name="off")
def logs_turn_off():
    """
    Turn off logging for all prompts.

    Example usage:
        $ llm logs off

    This command creates a 'logs-off' file, which disables logging for all 
    future prompts and responses.
    """
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
    conversations.name as conversation_name,
    conversations.model as conversation_model"""

LOGS_SQL = """
select
{columns}
from
    responses
left join conversations on responses.conversation_id = conversations.id{extra_where}
order by responses.id desc{limit}
"""
LOGS_SQL_SEARCH = """
select
{columns}
from
    responses
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
)
@click.option("-m", "--model", help="Filter by model or model alias")
@click.option("-q", "--query", help="Search for logs matching this string")
@click.option("-t", "--truncate", is_flag=True, help="Truncate long strings in output")
@click.option("-r", "--response", is_flag=True, help="Just output the last response")
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
@click.option(
    "json_output",
    "--json",
    is_flag=True,
    help="Output logs as JSON",
)
def logs_list(
    count,
    path,
    model,
    query,
    truncate,
    response,
    current_conversation,
    conversation_id,
    json_output,
):
    """
    Show recent logged prompts and their responses.

    This command lists entries from the logs database, allowing for filters
    such as model type, search queries, and conversation ID. The output can
    be formatted in a truncated, human-readable form or as JSON.

    Args:
        count (int, optional): Number of entries to display. Defaults to 3, use 0 for all.
        path (str, optional): Custom path to the log database file.
        model (str, optional): Filter results by model or alias.
        query (str, optional): Search query for full-text search in logs.
        truncate (bool, optional): Whether to truncate long strings in the output.
        response (bool, optional): If true, output only the last response.
        current_conversation (bool, optional): Show logs from the current conversation.
        conversation_id (str, optional): Specific conversation ID to filter logs.
        json_output (bool, optional): If true, output logs as JSON.

    Raises:
        click.ClickException: If the log database file is not found.
    """
    path = pathlib.Path(path or logs_db_path())
    if not path.exists():
        raise click.ClickException("No log database found at {}".format(path))
    db = sqlite_utils.Database(path)
    migrate(db)

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
    if model_id:
        where_bits.append("responses.model = :model")
    if conversation_id:
        where_bits.append("responses.conversation_id = :conversation_id")
    if where_bits:
        where_ = " and " if query else " where "
        sql_format["extra_where"] = where_ + " and ".join(where_bits)

    # Format the final SQL query
    final_sql = sql.format(**sql_format)
    rows = list(
        db.query(
            final_sql,
            {"model": model_id, "query": query, "conversation_id": conversation_id},
        )
    )
    # Reverse the order - we do this because we 'order by id desc limit 3' to get the
    # 3 most recent results, but we still want to display them in chronological order
    # ... except for searches where we don't do this
    if not query:
        rows.reverse()

    # Fetch any attachments associated with the responses
    ids = [row["id"] for row in rows]
    attachments = list(db.query(ATTACHMENTS_SQL.format(",".join("?" * len(ids))), ids))
    attachments_by_id = {}
    for attachment in attachments:
        attachments_by_id.setdefault(attachment["response_id"], []).append(attachment)

    for row in rows:
        if truncate:
            row["prompt"] = _truncate_string(row["prompt"])
            row["response"] = _truncate_string(row["response"])
        # Either decode or remove all JSON keys
        keys = list(row.keys())
        for key in keys:
            if key.endswith("_json") and row[key] is not None:
                if truncate:
                    del row[key]
                else:
                    row[key] = json.loads(row[key])

    if json_output:
        # Output as JSON if requested
        for row in rows:
            row["attachments"] = [
                {k: v for k, v in attachment.items() if k != "response_id"}
                for attachment in attachments_by_id.get(row["id"], [])
            ]
        click.echo(json.dumps(list(rows), indent=2))
    elif response:
        # Just output the last response
        if rows:
            click.echo(rows[-1]["response"])
    else:
        # Output neatly formatted human-readable logs
        current_system = None
        should_show_conversation = True
        for row in rows:
            click.echo(
                "# {}{}\n{}".format(
                    row["datetime_utc"].split(".")[0],
                    (
                        "    conversation: {}".format(row["conversation_id"])
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
            click.echo("## Prompt:\n\n{}".format(row["prompt"]))
            if row["system"] != current_system:
                if row["system"] is not None:
                    click.echo("\n## System:\n\n{}".format(row["system"]))
                current_system = row["system"]
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

            click.echo("\n## Response:\n\n{}\n".format(row["response"]))


@cli.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def models():
    """
    Manage available models.

    This group provides commands for listing available models and 
    setting a default model.
    """


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
def models_list(options):
    """
    List available models.

    This command lists all models, optionally showing their configuration options.
    
    Args:
        options (bool): If set, displays the available options for each model.
    """

    models_that_have_shown_options = set()
    for model_with_aliases in get_models_with_aliases():
        extra = ""
        if model_with_aliases.aliases:
            extra = " (aliases: {})".format(", ".join(model_with_aliases.aliases))
        output = str(model_with_aliases.model) + extra
        if options and model_with_aliases.model.Options.schema()["properties"]:
            for name, field in model_with_aliases.model.Options.schema()[
                "properties"
            ].items():
                any_of = field.get("anyOf")
                if any_of is None:
                    any_of = [{"type": field["type"]}]
                types = ", ".join(
                    [
                        _type_lookup.get(item["type"], item["type"])
                        for item in any_of
                        if item["type"] != "null"
                    ]
                )
                bits = ["\n  ", name, ": ", types]
                description = field.get("description", "")
                if description and (
                    model_with_aliases.model.__class__
                    not in models_that_have_shown_options
                ):
                    wrapped = textwrap.wrap(description, 70)
                    bits.append("\n    ")
                    bits.extend("\n    ".join(wrapped))
                output += "".join(bits)
            models_that_have_shown_options.add(model_with_aliases.model.__class__)
        click.echo(output)


@models.command(name="default")
@click.argument("model", required=False)
def models_default(model):
    """
    Show or set the default model.

    This command displays the current default model or sets a new 
    default model if one is provided.
    
    Args:
        model (str, optional): The model to set as default. If omitted, 
        the current default model is displayed.

    Raises:
        click.ClickException: If the specified model is unknown.
    """
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
    """
    Manage stored prompt templates.

    This group provides commands for listing, editing, and showing 
    prompt templates stored as YAML files.
    """


@templates.command(name="list")
def templates_list():
    """
    List available prompt templates.

    This command scans the templates directory and displays each template 
    with its name and a truncated version of its content.
    """
    path = template_dir()
    pairs = []
    for file in path.glob("*.yaml"):
        name = file.stem
        template = load_template(name)
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


@cli.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def aliases():
    """
    Manage model aliases.

    This group of commands allows you to set, list, and remove aliases 
    for models, making it easier to refer to models using custom names.
    """


@aliases.command(name="list")
@click.option("json_", "--json", is_flag=True, help="Output as JSON")
def aliases_list(json_):
    """
    List current aliases.

    This command displays all defined aliases and the model IDs they refer to.
    
    Options:
        --json: Outputs the alias list in JSON format.
    """
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
@click.argument("model_id")
def aliases_set(alias, model_id):
    """
    Set an alias for a model

    Example usage:

    \b
        $ llm aliases set turbo gpt-3.5-turbo
    """
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
    """
    Output the path to the aliases.json file.

    This command shows the location of the JSON file where model aliases 
    are stored on the system.
    """
    click.echo(user_dir() / "aliases.json")


@cli.command(name="plugins")
@click.option("--all", help="Include built-in default plugins", is_flag=True)
def plugins_list(all):
    "List installed plugins"
    click.echo(json.dumps(get_plugins(all), indent=2))


def display_truncated(text):
    """
    Display truncated text to fit within the console width.

    This utility function truncates a string if it exceeds the width of the console 
    and appends '...' to indicate truncation.
    
    Args:
        text (str): The text to truncate.

    Returns:
        str: Truncated text or the original text if no truncation is needed.
    """

    console_width = shutil.get_terminal_size()[0]
    if len(text) > console_width:
        return text[: console_width - 3] + "..."
    else:
        return text


@templates.command(name="show")
@click.argument("name")
def templates_show(name):
    """
    Show the specified prompt template.

    This command displays the content of a prompt template, formatted as YAML.
    
    Args:
        name (str): The name of the template to display.
    """
    template = load_template(name)
    click.echo(
        yaml.dump(
            dict((k, v) for k, v in template.dict().items() if v is not None),
            indent=4,
            default_flow_style=False,
        )
    )


@templates.command(name="edit")
@click.argument("name")
def templates_edit(name):
    """
    Edit the specified prompt template using the default $EDITOR.

    This command opens the specified prompt template in the user's default editor 
    for modifications. If the template does not exist, a default one is created.
    
    Args:
        name (str): The name of the template to edit.
    """
    # First ensure it exists
    path = template_dir() / f"{name}.yaml"
    if not path.exists():
        path.write_text(DEFAULT_TEMPLATE, "utf-8")
    click.edit(filename=path)
    # Validate that template
    load_template(name)


@templates.command(name="path")
def templates_path():
    """
    Output the path to the templates directory.

    This command shows the location of the directory where prompt templates 
    are stored on the system.
    """
    click.echo(template_dir())


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
    """
    Install packages from PyPI into the LLM environment.

    This command uses pip to install Python packages. The --upgrade, --editable, 
    --force-reinstall, and --no-cache-dir options provide additional control over 
    the installation process.

    Args:
        packages (tuple): The packages to install (can be multiple).
    
    Options:
        -U, --upgrade: Upgrade packages to the latest version.
        -e, --editable: Install a project in editable mode from the specified path.
        --force-reinstall: Reinstall packages even if they are up-to-date.
        --no-cache-dir: Disable the cache for the installation.
    """

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
    """
    Uninstall Python packages from the LLM environment.

    This command uses pip to uninstall Python packages. Use the -y option to 
    suppress confirmation prompts.

    Args:
        packages (tuple): The packages to uninstall (can be multiple).
    
    Options:
        -y, --yes: Skip confirmation prompts when uninstalling.
    """
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
@click.option("-m", "--model", help="Embedding model to use")
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
    callback=_validate_metadata_json,
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
    """
    Embed text and store or return the result.

    This command generates embeddings for the provided text and either stores them 
    in a database or outputs them in the specified format. You can provide text via 
    a file, content string, or standard input.

    Args:
        collection (str): The name of the collection to store embeddings.
        id (str): The ID to associate with the embedding.

    Options:
        -i, --input: Path to a file containing the text to embed.
        -m, --model: The embedding model to use.
        --store: Store the text in the database.
        -d, --database: Path to the embeddings database.
        -c, --content: The text content to embed.
        --binary: Treat input as binary data.
        --metadata: JSON metadata to associate with the embedding.
        -f, --format: Output format (json, blob, base64, hex).
    """
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
    help="Encoding to use when reading --files",
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
@click.option("-m", "--model", help="Embedding model to use")
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
    store,
    database,
):
    """
    Store embeddings for multiple strings at once.

    This command generates embeddings for multiple strings and stores them in the 
    specified collection. You can provide input data from files, a SQL query, or 
    a directory of files.

    Args:
        collection (str): The name of the collection to store embeddings.
        input_path (str): Path to the input file containing text data.

    Options:
        --format: Format of the input file (json, csv, tsv, nl).
        --files: Directory and glob pattern to embed files.
        --encoding: Encoding(s) to use when reading files.
        --binary: Treat input as binary data.
        --sql: SQL query to use for reading input data.
        --attach: Attach additional databases.
        --batch-size: Batch size for running embeddings.
        --prefix: Prefix to add to each ID.
        -m, --model: Embedding model to use.
        --store: Store the text itself in the database.
        -d, --database: Path to the embeddings database.
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
                id = prefix + str(values[0])
                if binary:
                    yield id, cast(bytes, values[1])
                else:
                    yield id, " ".join(v or "" for v in values[1:])

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
@click.option(
    "-d",
    "--database",
    type=click.Path(file_okay=True, allow_dash=False, dir_okay=False, writable=True),
    envvar="LLM_EMBEDDINGS_DB",
)
def similar(collection, id, input, content, binary, number, database):
    """
    Return top N similar IDs from a collection.

    This command finds and returns the top N most similar embeddings 
    from a specified collection based on the provided content or ID.

    Args:
        collection (str): Name of the collection to search.
        id (str, optional): ID of the existing embedding for comparison.

    Options:
        -i, --input: Path to a file for embedding comparison.
        -c, --content: Text content for embedding comparison.
        --binary: Indicates if the input should be treated as binary data.
        -n, --number: Number of similar results to return (default is 10).
        -d, --database: Path to the embeddings database.
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
        click.echo(json.dumps(asdict(result)))


@cli.group(
    cls=DefaultGroup,
    default="list",
    default_if_no_args=True,
)
def embed_models():
    "Manage available embedding models"


@embed_models.command(name="list")
def embed_models_list():
    "List available embedding models"
    output = []
    for model_with_aliases in get_embedding_models_with_aliases():
        s = str(model_with_aliases.model.model_id)
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
    """
    Show or set the default embedding model.

    This command lets you view or change the default embedding model. 
    Use --remove-default to reset to having no default.

    Args:
        model (str, optional): Model to set as the default.

    Options:
        --remove-default: Reset to having no default model set.
    """
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
    """
    View a list of collections.

    This command displays all available collections and the number of embeddings in each. 
    Optionally, output the results as JSON.

    Options:
        -d, --database: Path to the embeddings database.
        --json: Output the list as JSON.
    """
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
    Delete the specified collection.

    Use this command to delete an entire collection of embeddings from the database.

    Args:
        collection (str): Name of the collection to delete.

    Options:
        -d, --database: Path to the embeddings database.
    """
    database = database or (user_dir() / "embeddings.db")
    db = sqlite_utils.Database(str(database))
    try:
        collection_obj = Collection(collection, db, create=False)
    except Collection.DoesNotExist:
        raise click.ClickException("Collection does not exist")
    collection_obj.delete()


def template_dir():
    """
    Returns the path to the directory where prompt templates are stored.
    
    Creates the directory if it does not exist.

    Returns:
        Path: The path to the templates directory.
    """
    path = user_dir() / "templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _truncate_string(s, max_length=100):
    """
    Truncate a string to a specified maximum length.

    Args:
        s (str): The string to truncate.
        max_length (int): The maximum allowed length of the string.

    Returns:
        str: The truncated string, appended with "..." if truncated.
    """

    if len(s) > max_length:
        return s[: max_length - 3] + "..."
    return s


def logs_db_path():
    """
    Returns the path to the logs database file.

    Returns:
        Path: The path to the logs database file.
    """

    return user_dir() / "logs.db"


def load_template(name):
    """
    Load a template from a YAML file.

    Args:
        name (str): The name of the template to load.

    Returns:
        Template: The loaded template object.

    Raises:
        ClickException: If the template file does not exist or if the YAML is invalid.
    """

    path = template_dir() / f"{name}.yaml"
    if not path.exists():
        raise click.ClickException(f"Invalid template: {name}")
    try:
        loaded = yaml.safe_load(path.read_text())
    except yaml.YAMLError as ex:
        raise click.ClickException("Invalid YAML: {}".format(str(ex)))
    if isinstance(loaded, str):
        return Template(name=name, prompt=loaded)
    loaded["name"] = name
    try:
        return Template(**loaded)
    except pydantic.ValidationError as ex:
        msg = "A validation error occurred:\n"
        msg += render_errors(ex.errors())
        raise click.ClickException(msg)


def get_history(chat_id):
    """
    Retrieve the history of a chat based on its ID.

    Args:
        chat_id (int or None): The ID of the chat, or None to return the most recent chat.

    Returns:
        Tuple[int, List[dict]]: The chat ID and a list of log entries.

    Raises:
        ClickException: If the chat history cannot be retrieved.
    """
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
    """
    Render error messages from a list of validation errors.

    Args:
        errors (List[dict]): A list of error dictionaries.

    Returns:
        str: A formatted string containing the error messages.
    """

    output = []
    for error in errors:
        output.append(", ".join(error["loc"]))
        output.append("  " + error["msg"])
    return "\n".join(output)


pm.hook.register_commands(cli=cli)


def _human_readable_size(size_bytes):
    """
    Convert a size in bytes to a human-readable string.

    Args:
        size_bytes (int): The size in bytes.

    Returns:
        str: The size formatted as a human-readable string.
    """

    if size_bytes == 0:
        return "0B"

    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = 0

    while size_bytes >= 1024 and i < len(size_name) - 1:
        size_bytes /= 1024.0
        i += 1

    return "{:.2f}{}".format(size_bytes, size_name[i])


def logs_on():
    """
    Check if logging is enabled.

    Returns:
        bool: True if logging is enabled, False otherwise.
    """

    return not (user_dir() / "logs-off").exists()
