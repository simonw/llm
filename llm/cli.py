import click
from click_default_group import DefaultGroup
import openai
import os
import sys


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
def chatgpt(prompt, system, gpt4, model, stream):
    "Execute prompt against ChatGPT"
    openai.api_key = get_openai_api_key()
    if gpt4:
        model = "gpt-4"
    if not model:
        model = "gpt-3.5-turbo"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    if stream:
        for chunk in openai.ChatCompletion.create(
            model=model,
            messages=messages,
            stream=True,
        ):
            content = chunk["choices"][0].get("delta", {}).get("content")
            if content is not None:
                print(content, end="")
                sys.stdout.flush()
        print("")
    else:
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages,
        )
        print(response.choices[0].message.content)


def get_openai_api_key():
    # Expand this to home directory / ~.openai-api-key.txt
    if "OPENAI_API_KEY" in os.environ:
        return os.environ["OPENAI_API_KEY"]
    path = os.path.expanduser('~/.openai-api-key.txt')
    # If the file exists, read it
    if os.path.exists(path):
        return open(path).read().strip()
    raise click.ClickException("No OpenAI API key found. Set OPENAI_API_KEY environment variable or create ~/.openai-api-key.txt")
