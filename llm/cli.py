import click
from click_default_group import DefaultGroup
from dataclasses import asdict
import io
import json
from llm import (
    Collection,
    Conversation,
    Response,
    Template,
    UnknownModelError,
    encode,
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
    remove_alias,
)

from .migrations import migrate
from .plugins import pm
import base64
import pathlib
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

warnings.simplefilter("ignore", ResourceWarning)

DEFAULT_MODEL = "gpt-3.5-turbo"
DEFAULT_EMBEDDING_MODEL = "ada-002"

DEFAULT_TEMPLATE = "prompt: "


def _validate_metadata_json(ctx, param, value):
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
    """
    if log and no_log:
        raise click.ClickException("--log and --no-log are mutually exclusive")

    model_aliases = get_model_aliases()

    def read_prompt():
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
        params = dict(param)
        # Cannot be used with system
        if system:
            raise click.ClickException("Cannot use -t/--template and --system together")
        template_obj = load_template(template)
        prompt = read_prompt()
        try:
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

    # Figure out which model we are using
    if model_id is None:
        if conversation:
            model_id = conversation.model.model_id
        else:
            model_id = get_default_model()

    # Now resolve the model
    try:
        model = model_aliases[model_id]
    except KeyError:
        raise click.ClickException("'{}' is not a known model".format(model_id))

    # Provide the API key, if one is needed and has been provided
    if model.needs_key:
        model.key = get_key(key, model.needs_key, model.key_env_var)

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

    should_stream = model.can_stream and not no_stream
    if not should_stream:
        validated_options["stream"] = False

    prompt = read_prompt()

    prompt_method = model.prompt
    if conversation:
        prompt_method = conversation.prompt

    try:
        response = prompt_method(prompt, system, **validated_options)
        if should_stream:
            for chunk in response:
                print(chunk, end="")
                sys.stdout.flush()
            print("")
        else:
            print(response.text())
    except Exception as ex:
        raise click.ClickException(str(ex))

    # Log to the database
    if (logs_on() or log) and not no_log:
        log_path = logs_db_path()
        (log_path.parent).mkdir(parents=True, exist_ok=True)
        db = sqlite_utils.Database(log_path)
        migrate(db)
        response.log_to_db(db)


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

    should_stream = model.can_stream and not no_stream
    if not should_stream:
        validated_options["stream"] = False

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
                prompt, system = template_obj.evaluate(prompt, params)
            except Template.MissingVariables as ex:
                raise click.ClickException(str(ex))
        if prompt.strip() in ("exit", "quit"):
            break
        response = conversation.prompt(prompt, system, **validated_options)
        # System prompt only sent for the first message:
        system = None
        for chunk in response:
            print(chunk, end="")
            sys.stdout.flush()
        response.log_to_db(db)
        print("")


def load_conversation(conversation_id: Optional[str]) -> Optional[Conversation]:
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
    conversation = Conversation.from_row(row)
    for response in db["responses"].rows_where(
        "conversation_id = ?", [conversation_id]
    ):
        conversation.responses.append(Response.from_row(response))
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
    "Show recent logged prompts and their responses"
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
        sql_format["extra_where"] = " where " + " and ".join(where_bits)

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
            click.echo("\n## Response:\n\n{}\n".format(row["response"]))


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
def models_list(options):
    "List available models"
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
    "Output the path to the aliases.json file"
    click.echo(user_dir() / "aliases.json")


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


@templates.command(name="show")
@click.argument("name")
def templates_show(name):
    "Show the specified prompt template"
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
    Store embeddings for multiple strings at once

    Input can be CSV, TSV or a JSON list of objects.

    The first column is treated as an ID - all other columns
    are assumed to be text that should be concatenated together
    in order to calculate the embeddings.

    Input data can come from one of three sources:

    \b
    1. A CSV, JSON, TSV or JSON-nl file (including on standard input)
    2. A SQL query against a SQLite database
    3. A directory of files
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
    Return top N similar IDs from a collection

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


def template_dir():
    path = user_dir() / "templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _truncate_string(s, max_length=100):
    if len(s) > max_length:
        return s[: max_length - 3] + "..."
    return s


def get_default_model(filename="default_model.txt", default=DEFAULT_MODEL):
    path = user_dir() / filename
    if path.exists():
        return path.read_text().strip()
    else:
        return default


def set_default_model(model, filename="default_model.txt"):
    path = user_dir() / filename
    if model is None and path.exists():
        path.unlink()
    else:
        path.write_text(model)


def get_default_embedding_model():
    return get_default_model("default_embedding_model.txt", None)


def set_default_embedding_model(model):
    set_default_model(model, "default_embedding_model.txt")


def logs_db_path():
    return user_dir() / "logs.db"


def load_template(name):
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
