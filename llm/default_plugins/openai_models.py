from llm import Model, hookimpl
import llm
from llm.utils import dicts_to_table_string
import click
import datetime
import openai
from pydantic import field_validator
import requests
from typing import List, Optional, Union
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


class Chat(Model):
    needs_key = "openai"
    key_env_var = "OPENAI_API_KEY"
    can_stream: bool = True

    class Options(llm.Options):
        temperature: Optional[float] = None
        max_tokens: Optional[int] = None
        top_p: Optional[float] = None
        frequency_penalty: Optional[float] = None
        presence_penalty: Optional[float] = None
        stop: Optional[str] = None
        logit_bias: Optional[Union[dict, str]] = None

        @field_validator("logit_bias")
        def validate_logit_bias(cls, logit_bias):
            if logit_bias is None:
                return None

            if isinstance(logit_bias, str):
                try:
                    logit_bias = json.loads(logit_bias)
                except json.JSONDecodeError:
                    raise ValueError("Invalid JSON in logit_bias string")

            validated_logit_bias = {}
            for key, value in logit_bias.items():
                try:
                    int_key = int(key)
                    int_value = int(value)
                    if -100 <= int_value <= 100:
                        validated_logit_bias[int_key] = int_value
                    else:
                        raise ValueError("Value must be between -100 and 100")
                except ValueError:
                    raise ValueError("Invalid key-value pair in logit_bias dictionary")

            return validated_logit_bias

    class Response(llm.Response):
        def __init__(self, prompt, model, stream, key):
            super().__init__(prompt, model, stream)
            self.key = key

        def iter_prompt(self, prompt):
            messages = []
            if prompt.system:
                messages.append({"role": "system", "content": prompt.system})
            messages.append({"role": "user", "content": prompt.prompt})
            openai.api_key = self.key
            self._prompt_json = {"messages": messages}
            if self.stream:
                completion = openai.ChatCompletion.create(
                    model=prompt.model.model_id,
                    messages=messages,
                    stream=True,
                    **not_nulls(prompt.options),
                )
                chunks = []
                for chunk in completion:
                    chunks.append(chunk)
                    content = chunk["choices"][0].get("delta", {}).get("content")
                    if content is not None:
                        yield content
                self._response_json = combine_chunks(chunks)
            else:
                response = openai.ChatCompletion.create(
                    model=prompt.model.model_id,
                    messages=messages,
                    stream=False,
                )
                self._response_json = response.to_dict_recursive()
                yield response.choices[0].message.content

    def __init__(self, model_id, key=None):
        self.model_id = model_id
        self.key = key

    def __str__(self):
        return "OpenAI Chat: {}".format(self.model_id)


def not_nulls(data) -> dict:
    return {key: value for key, value in data if value is not None}


def combine_chunks(chunks: List[dict]) -> dict:
    content = ""
    role = None

    for item in chunks:
        for choice in item["choices"]:
            if "role" in choice["delta"]:
                role = choice["delta"]["role"]
            if "content" in choice["delta"]:
                content += choice["delta"]["content"]
            if choice["finish_reason"] is not None:
                finish_reason = choice["finish_reason"]

    return {
        "id": chunks[0]["id"],
        "object": chunks[0]["object"],
        "model": chunks[0]["model"],
        "created": chunks[0]["created"],
        "index": chunks[0]["choices"][0]["index"],
        "role": role,
        "content": content,
        "finish_reason": finish_reason,
    }
