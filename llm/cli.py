import click
from click_default_group import DefaultGroup
import datetime
import json
from .migrations import migrate
import openai
import os
import pathlib
from platformdirs import user_data_dir
import sqlite_utils
import sys
import warnings

warnings.simplefilter("ignore", ResourceWarning)

DEFAULT_MODEL = "gpt-3.5-turbo"


@click.group(
    cls=DefaultGroup,
    default="prompt",
    default_if_no_args=True,
)
@click.version_option()
def cli():
    "Access large language models from the command-line"


@cli.command(name="prompt")
@click.argument("prompt", required=False)
@click.option("--system", help="System prompt to use")
@click.option("-4", "--gpt4", is_flag=True, help="Use GPT-4")
@click.option("-m", "--model", help="Model to use")
@click.option("--no-stream", is_flag=True, help="Do not stream output")
@click.option("-n", "--no-log", is_flag=True, help="Don't log to database")
@click.option(
    "_continue",
    "-c",
    "--continue",
    is_flag=True,
    flag_value=-1,
    help="Continue the most recent conversation.",
)
@click.option(
    "chat_id",
    "--chat",
    help="Continue the conversation with the given chat ID.",
    type=int,
)
@click.option("--key", help="API key to use")
def prompt(prompt, system, gpt4, model, no_stream, no_log, _continue, chat_id, key):
    "Execute a prompt against on OpenAI model"
    if prompt is None:
        # Read from stdin instead
        prompt = sys.stdin.read()
    openai.api_key = get_key(key, "openai", "OPENAI_API_KEY")
    if gpt4:
        model = "gpt-4"
    messages = []
    if _continue:
        _continue = -1
        if chat_id:
            raise click.ClickException("Cannot use --continue and --chat together")
    else:
        _continue = chat_id
    chat_id, history = get_history(_continue)
    history_model = None
    if history:
        for entry in history:
            if entry.get("system"):
                messages.append({"role": "system", "content": entry["system"]})
            messages.append({"role": "user", "content": entry["prompt"]})
            messages.append({"role": "assistant", "content": entry["response"]})
            history_model = entry["model"]
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    if model is None:
        model = history_model or DEFAULT_MODEL
    try:
        if no_stream:
            response = openai.ChatCompletion.create(
                model=model,
                messages=messages,
            )
            content = response.choices[0].message.content
            log(no_log, system, prompt, content, model, chat_id)
            print(content)
        else:
            response = []
            for chunk in openai.ChatCompletion.create(
                model=model,
                messages=messages,
                stream=True,
            ):
                content = chunk["choices"][0].get("delta", {}).get("content")
                if content is not None:
                    response.append(content)
                    print(content, end="")
                    sys.stdout.flush()
            print("")
            log(no_log, system, prompt, "".join(response), model, chat_id)
    except openai.error.AuthenticationError as ex:
        raise click.ClickException("{}: {}".format(ex.error.type, ex.error.code))
    except openai.error.OpenAIError as ex:
        raise click.ClickException(str(ex))


@cli.command()
def init_db():
    "Ensure ~/.llm/log.db SQLite database exists"
    path = get_log_db_path()
    if os.path.exists(path):
        return
    # Ensure directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite_utils.Database(path)
    db.vacuum()


@cli.group()
def keys():
    "Manage API keys for different models"


@keys.command()
def path():
    "Output path to keys.json file"
    click.echo(keys_path())


def keys_path():
    return os.environ.get("LLM_KEYS_PATH") or os.path.join(user_dir(), "keys.json")


def user_dir():
    return user_data_dir("io.datasette.llm", "Datasette")


@keys.command(name="set")
@click.argument("name")
@click.option("--value", prompt="Enter key", hide_input=True, help="Value to set")
def set_(name, value):
    """
    Save a key in keys.json

    Example usage:

    \b
        $ llm keys set openai
        Enter key: ...
    """
    default = {"// Note": "This file stores secret API credentials. Do not share!"}
    path = pathlib.Path(keys_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(default))
    try:
        current = json.loads(path.read_text())
    except json.decoder.JSONDecodeError:
        current = default
    current[name] = value
    path.write_text(json.dumps(current, indent=2) + "\n")


@cli.command()
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
@click.option("-t", "--truncate", is_flag=True, help="Truncate long strings in output")
def logs(count, path, truncate):
    path = path or get_log_db_path()
    if not os.path.exists(path):
        raise click.ClickException("No log database found at {}".format(path))
    db = sqlite_utils.Database(path)
    migrate(db)
    rows = list(
        db["log"].rows_where(order_by="-rowid", select="rowid, *", limit=count or None)
    )
    if truncate:
        for row in rows:
            row["prompt"] = _truncate_string(row["prompt"])
            row["response"] = _truncate_string(row["response"])
    click.echo(json.dumps(list(rows), indent=2))


def _truncate_string(s, max_length=100):
    if len(s) > max_length:
        return s[: max_length - 3] + "..."
    return s


def get_key(key_arg, default_key, env_var=None):
    keys = load_keys()
    if key_arg in keys:
        return keys[key_arg]
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    if key_arg:
        return key_arg
    default = keys.get(default_key)
    if not default:
        message = "No key found - add one using 'llm keys set {}'".format(default_key)
        if env_var:
            message += " or set the {} environment variable".format(env_var)
        raise click.ClickException(message)
    return default


def load_keys():
    path = pathlib.Path(keys_path())
    if path.exists():
        return json.loads(path.read_text())
    else:
        return {}


def get_log_db_path():
    return os.path.expanduser("~/.llm/log.db")


def log(no_log, system, prompt, response, model, chat_id=None):
    if no_log:
        return
    log_path = get_log_db_path()
    if not os.path.exists(log_path):
        return
    db = sqlite_utils.Database(log_path)
    migrate(db)
    db["log"].insert(
        {
            "system": system,
            "prompt": prompt,
            "chat_id": chat_id,
            "response": response,
            "model": model,
            "timestamp": str(datetime.datetime.utcnow()),
        },
    )


def get_history(chat_id):
    if chat_id is None:
        return None, []
    log_path = get_log_db_path()
    if not os.path.exists(log_path):
        raise click.ClickException(
            "This feature requires logging. Run `llm init-db` to create ~/.llm/log.db"
        )
    db = sqlite_utils.Database(log_path)
    migrate(db)
    if chat_id == -1:
        # Return the most recent chat
        last_row = list(db["log"].rows_where(order_by="-id", limit=1))
        if last_row:
            chat_id = last_row[0].get("chat_id") or last_row[0].get("id")
        else:  # Database is empty
            return None, []
    rows = db["log"].rows_where(
        "id = ? or chat_id = ?", [chat_id, chat_id], order_by="id"
    )
    return chat_id, rows
