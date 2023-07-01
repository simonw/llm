from llm import Model, Prompt, OptionsError, Response, hookimpl
from llm.errors import NeedsKeyException
from llm.utils import dicts_to_table_string
import click
import datetime
from typing import Optional
import openai
import requests
import json


@hookimpl
def register_models(register):
    register(Chat("gpt-3.5-turbo"), aliases=("3.5", "chatgpt"))
    register(Chat("gpt-3.5-turbo-16k"), aliases=("chatgpt-16k", "3.5-16k"))
    register(Chat("gpt-4"), aliases=("4", "gpt4"))
    register(Chat("gpt-4-32k"), aliases=("4-32k",))


@hookimpl
def register_commands(cli):
    @cli.group(name="openai")
    def openai_():
        "Commands for working directly with the OpenAI API"

    @openai_.command()
    @click.option("json_", "--json", is_flag=True, help="Output as JSON")
    @click.option("--key", help="OpenAI API key")
    def models(json_, key):
        "List models available to you from the OpenAI API"
        from llm.cli import get_key

        api_key = get_key(key, "openai", "OPENAI_API_KEY")
        response = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if response.status_code != 200:
            raise click.ClickException(
                f"Error {response.status_code} from OpenAI API: {response.text}"
            )
        models = response.json()["data"]
        if json_:
            click.echo(json.dumps(models, indent=4))
        else:
            to_print = []
            for model in models:
                # Print id, owned_by, root, created as ISO 8601
                created_str = datetime.datetime.utcfromtimestamp(
                    model["created"]
                ).isoformat()
                to_print.append(
                    {
                        "id": model["id"],
                        "owned_by": model["owned_by"],
                        "created": created_str,
                    }
                )
            done = dicts_to_table_string("id owned_by created".split(), to_print)
            print("\n".join(done))


class ChatResponse(Response):
    def __init__(self, prompt, model, stream, key):
        super().__init__(prompt, model, stream)
        self.key = key

    def iter_prompt(self):
        messages = []
        if self.prompt.system:
            messages.append({"role": "system", "content": self.prompt.system})
        messages.append({"role": "user", "content": self.prompt.prompt})
        openai.api_key = self.key
        if self.stream:
            for chunk in openai.ChatCompletion.create(
                model=self.prompt.model.model_id,
                messages=messages,
                stream=True,
            ):
                self._debug["model"] = chunk.model
                content = chunk["choices"][0].get("delta", {}).get("content")
                if content is not None:
                    yield content
            self._done = True
        else:
            response = openai.ChatCompletion.create(
                model=self.prompt.model.model_id,
                messages=messages,
                stream=False,
            )
            self._debug["model"] = response.model
            self._debug["usage"] = response.usage
            content = response.choices[0].message.content
            self._done = True
            yield content


class Chat(Model):
    needs_key = "openai"
    key_env_var = "OPENAI_API_KEY"
    can_stream: bool = True

    def __init__(self, model_id, key=None):
        self.model_id = model_id
        self.key = key

    def execute(self, prompt: Prompt, stream: bool = True) -> ChatResponse:
        key = self.get_key()
        if key is None:
            raise NeedsKeyException(
                "{} needs an API key, label={}".format(str(self), self.needs_key)
            )
        return ChatResponse(prompt, self, stream, key=key)

    def __str__(self):
        return "OpenAI Chat: {}".format(self.model_id)
