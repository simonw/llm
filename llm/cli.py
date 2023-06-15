import click
from click_default_group import DefaultGroup
import datetime
import json
import openai
import os
from pathlib import Path
import sqlite_utils
import sys
import warnings

warnings.simplefilter("ignore", ResourceWarning)

CODE_SYSTEM_PROMPT = """
You are a code generating tool. Return just the code, with no explanation
or context other than comments in the code itself.
""".strip()

DEFAULT_MODEL = "gpt-3.5-turbo"

LOG_DB = Path().home() / ".llm" / "log.db"


@click.group(
    cls=DefaultGroup,
    default="openai",
    default_if_no_args=True,
)
@click.version_option()
def cli():
    "Access large language models from the command-line"


@cli.command(name="openai")
@click.argument("prompt", required=False)
@click.option("--system", help="System prompt to use")
@click.option("-4", "--gpt4", is_flag=True, help="Use GPT-4")
@click.option("-m", "--model", help="Model to use")
@click.option("-s", "--stream", is_flag=True, help="Stream output")
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
@click.option("--code", is_flag=True, help="System prompt to optimize for code output")
def openai_(prompt, system, gpt4, model, stream, no_log, code, _continue, chat_id):
    "Execute a prompt against on OpenAI model"
    if prompt is None:
        if sys.stdin.isatty():
            # No data being piped in and no arguments provided,
            # so show help message and exit.
            click.echo(cli.get_help(click.get_current_context()))
            return

        # Read from stdin instead
        prompt = sys.stdin.read()

    openai.api_key = get_openai_api_key()
    if gpt4:
        model = "gpt-4"
    if code and system:
        raise click.ClickException("Cannot use --code and --system together")
    if code:
        system = CODE_SYSTEM_PROMPT
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
        if stream:
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
            log(no_log, "openai", system, prompt, "".join(response), model, chat_id)
        else:
            response = openai.ChatCompletion.create(
                model=model,
                messages=messages,
            )
            content = response.choices[0].message.content
            log(no_log, "openai", system, prompt, content, model, chat_id)
            if code:
                content = unwrap_markdown(content)
            print(content)
    except openai.error.OpenAIError as ex:
        raise click.ClickException(str(ex))


@cli.command()
def init_db():
    "Ensure the log SQLite database exists"
    if LOG_DB.exists():
        return
    # Ensure directory exists
    LOG_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(LOG_DB)
    db.vacuum()


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
    if not LOG_DB.exists():
        raise click.ClickException(f"No log database found at {LOG_DB}. Run `llm init-db` to create {LOG_DB}")
    db = sqlite_utils.Database(LOG_DB)
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


def get_openai_api_key():
    # Expand this to home directory / ~.openai-api-key.txt
    if "OPENAI_API_KEY" in os.environ:
        return os.environ["OPENAI_API_KEY"]
    API_key_path = Path.home() / ".openai-api-key.txt"
    # If the file exists, read it
    if API_key_path.exists():
        with open(API_key_path) as file:
            return file.read().strip()
    raise click.ClickException(
        "No OpenAI API key found. Set OPENAI_API_KEY environment variable or create ~/.openai-api-key.txt"
    )


def log(no_log, provider, system, prompt, response, model, chat_id=None):
    if no_log:
        return
    if not LOG_DB.exists():
        return
    db = sqlite_utils.Database(LOG_DB)
    db["log"].insert(
        {
            "provider": provider,
            "system": system,
            "prompt": prompt,
            "chat_id": chat_id,
            "response": response,
            "model": model,
            "timestamp": str(datetime.datetime.utcnow()),
        },
        alter=True,
    )


def get_history(chat_id):
    if chat_id is None:
        return None, []
    if not LOG_DB.exists():
        raise click.ClickException(
            f"This feature requires logging. Run `llm init-db` to create {LOG_DB}"
        )
    db = sqlite_utils.Database(LOG_DB)
    # Check if the chat_id column exists in the DB. If not create it. This is a
    # migration path for people who have been using llm before chat_id was
    # added.
    if db["log"].columns and "chat_id" not in {
        column.name for column in db["log"].columns
    }:
        db["log"].add_column("chat_id", int)
    if chat_id == -1:
        # Return the most recent chat
        last_row = list(
            db["log"].rows_where(order_by="-rowid", limit=1, select="rowid, *")
        )
        if last_row:
            chat_id = last_row[0].get("chat_id") or last_row[0].get("rowid")
        else:  # Database is empty
            return None, []
    rows = db["log"].rows_where(
        "rowid = ? or chat_id = ?", [chat_id, chat_id], order_by="rowid"
    )
    return chat_id, rows


def unwrap_markdown(content):
    # Remove first and last line if they are triple backticks
    lines = [l for l in content.split("\n")]
    if lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
