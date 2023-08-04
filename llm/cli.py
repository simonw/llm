import click
from click_default_group import DefaultGroup
import json
from llm import (
    Conversation,
    Response,
    Template,
    UnknownModelError,
    get_key,
    get_plugins,
    get_model,
    get_model_aliases,
    get_models_with_aliases,
    user_dir,
)

from .migrations import migrate
from .plugins import pm
import pathlib
import pydantic
from runpy import run_module
import shutil
import sqlite_utils
import sys
import textwrap
from typing import cast, Optional
import warnings
import yaml

warnings.simplefilter("ignore", ResourceWarning)

DEFAULT_MODEL = "gpt-3.5-turbo"

DEFAULT_TEMPLATE = "prompt: "


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
        if prompt is None:
            if template:
                # If running a template only consume from stdin if it has data
                if not sys.stdin.isatty():
                    prompt = sys.stdin.read()
            elif not save:
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
        db = sqlite_utils.Database(log_path)
        migrate(db)
        response.log_to_db(db)


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


@cli.group()
def keys():
    "Manage stored API keys for different models"


@keys.command(name="path")
def keys_path_command():
    "Output the path to the keys.json file"
    click.echo(user_dir() / "keys.json")


@keys.command(name="set")
@click.argument("name")
@click.option("--value", prompt="Enter key", hide_input=True, help="Value to set")
def set_(name, value):
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
left join conversations on responses.conversation_id = conversations.id{where}
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
    default=3,
    help="Number of entries to show - 0 for all",
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
def logs_list(count, path, model, query, truncate):
    "Show recent logged prompts and their responses"
    path = pathlib.Path(path or logs_db_path())
    if not path.exists():
        raise click.ClickException("No log database found at {}".format(path))
    db = sqlite_utils.Database(path)
    migrate(db)

    model_id = None
    if model:
        # Resolve alias, if any
        try:
            model_id = get_model(model).model_id
        except UnknownModelError:
            # Maybe they uninstalled a model, use the -m option as-is
            model_id = model

    sql = LOGS_SQL
    format_kwargs = {
        "limit": " limit {}".format(count) if count else "",
        "columns": LOGS_COLUMNS,
    }
    if query:
        sql = LOGS_SQL_SEARCH
        format_kwargs["extra_where"] = (
            " and responses.model = :model" if model_id else ""
        )
    else:
        format_kwargs["where"] = " where responses.model = :model" if model_id else ""

    rows = list(
        db.query(sql.format(**format_kwargs), {"model": model_id, "query": query})
    )
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
    click.echo(json.dumps(list(rows), indent=2))


@cli.group()
def models():
    "Manage available models"


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
        if options and model_with_aliases.model.Options.model_fields:
            for name, field in model_with_aliases.model.Options.model_fields.items():
                type_info = str(field.annotation).replace("typing.", "")
                if type_info.startswith("Optional["):
                    type_info = type_info[9:-1]
                if type_info.startswith("Union[") and type_info.endswith(", NoneType]"):
                    type_info = type_info[6:-11]
                bits = ["\n  ", name, ": ", type_info]
                if field.description and (
                    model_with_aliases.model.__class__
                    not in models_that_have_shown_options
                ):
                    wrapped = textwrap.wrap(field.description, 70)
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


@cli.group()
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


@cli.command(name="plugins")
def plugins_list():
    "List installed plugins"
    click.echo(json.dumps(get_plugins(), indent=2))


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


def template_dir():
    path = user_dir() / "templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _truncate_string(s, max_length=100):
    if len(s) > max_length:
        return s[: max_length - 3] + "..."
    return s


def get_default_model():
    path = user_dir() / "default_model.txt"
    if path.exists():
        return path.read_text().strip()
    else:
        return DEFAULT_MODEL


def set_default_model(model):
    path = user_dir() / "default_model.txt"
    path.write_text(model)


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
        return Template.model_validate(loaded)
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
