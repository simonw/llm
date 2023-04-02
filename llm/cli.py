import click
from click_default_group import DefaultGroup
import datetime
import openai
import os
import sqlite_utils
import sys
import warnings

warnings.simplefilter("ignore", ResourceWarning)

CODE_SYSTEM_PROMPT = """
You are a code generating tool. Return just the code, with no explanation
or context other than comments in the code itself.
""".strip()


@click.group(
    cls=DefaultGroup,
    default="chatgpt",
    default_if_no_args=True,
)
@click.version_option()
def cli():
    "Access large language models from the command-line"


@cli.command()
@click.argument("prompt")
@click.option("--system", help="System prompt to use")
@click.option("-4", "--gpt4", is_flag=True, help="Use GPT-4")
@click.option("-m", "--model", help="Model to use")
@click.option("-s", "--stream", is_flag=True, help="Stream output")
@click.option("-n", "--no-log", is_flag=True, help="Don't log to database")
@click.option("--code", is_flag=True, help="System prompt to optimize for code output")
def chatgpt(prompt, system, gpt4, model, stream, no_log, code):
    "Execute prompt against ChatGPT"
    openai.api_key = get_openai_api_key()
    if gpt4:
        model = "gpt-4"
    if not model:
        model = "gpt-3.5-turbo"
    if code and system:
        raise click.ClickException("Cannot use --code and --system together")
    if code:
        system = CODE_SYSTEM_PROMPT
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
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
        log(no_log, "chatgpt", system, prompt, "".join(response), model)
    else:
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages,
        )
        content = response.choices[0].message.content
        log(no_log, "chatgpt", system, prompt, content, model)
        if code:
            content = unwrap_markdown(content)
        print(content)


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


def get_openai_api_key():
    # Expand this to home directory / ~.openai-api-key.txt
    if "OPENAI_API_KEY" in os.environ:
        return os.environ["OPENAI_API_KEY"]
    path = os.path.expanduser("~/.openai-api-key.txt")
    # If the file exists, read it
    if os.path.exists(path):
        with open(path) as fp:
            return fp.read().strip()
    raise click.ClickException(
        "No OpenAI API key found. Set OPENAI_API_KEY environment variable or create ~/.openai-api-key.txt"
    )


def get_log_db_path():
    return os.path.expanduser("~/.llm/log.db")


def log(no_log, provider, system, prompt, response, model):
    if no_log:
        return
    log_path = get_log_db_path()
    if not os.path.exists(log_path):
        return
    db = sqlite_utils.Database(log_path)
    db["log"].insert(
        {
            "provider": provider,
            "system": system,
            "prompt": prompt,
            "response": response,
            "model": model,
            "timestamp": str(datetime.datetime.utcnow()),
        }
    )


def unwrap_markdown(content):
    # Remove first and last line if they are triple backticks
    lines = [l for l in content.split("\n")]
    if lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
