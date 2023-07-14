from llm import Model, hookimpl
import llm
from llm.utils import dicts_to_table_string
import click
import datetime
import openai
from pydantic import field_validator, Field
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
        temperature: Optional[float] = Field(
            description=(
                "What sampling temperature to use, between 0 and 2. Higher values like "
                "0.8 will make the output more random, while lower values like 0.2 will "
                "make it more focused and deterministic."
            ),
            default=None,
        )
        max_tokens: Optional[int] = Field(
            description="Maximum number of tokens to generate.", default=None
        )
        top_p: Optional[float] = Field(
            description=(
                "An alternative to sampling with temperature, called nucleus sampling, "
                "where the model considers the results of the tokens with top_p "
                "probability mass. So 0.1 means only the tokens comprising the top "
                "10% probability mass are considered. Recommended to use top_p or "
                "temperature but not both."
            ),
            default=None,
        )
        frequency_penalty: Optional[float] = Field(
            description=(
                "Number between -2.0 and 2.0. Positive values penalize new tokens based "
                "on their existing frequency in the text so far, decreasing the model's "
                "likelihood to repeat the same line verbatim."
            ),
            default=None,
        )
        presence_penalty: Optional[float] = Field(
            description=(
                "Number between -2.0 and 2.0. Positive values penalize new tokens based "
                "on whether they appear in the text so far, increasing the model's "
                "likelihood to talk about new topics."
            ),
            default=None,
        )
        stop: Optional[str] = Field(
            description=("A string where the API will stop generating further tokens."),
            default=None,
        )
        logit_bias: Optional[Union[dict, str]] = Field(
            description=(
                "Modify the likelihood of specified tokens appearing in the completion. "
                'Pass a JSON string like \'{"1712":-100, "892":-100, "1489":-100}\''
            ),
            default=None,
        )

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

    def __init__(self, model_id, key=None):
        self.model_id = model_id
        self.key = key

    def __str__(self):
        return "OpenAI Chat: {}".format(self.model_id)

    def execute(self, prompt, stream, response, conversation=None):
        messages = []
        current_system = None
        if conversation is not None:
            for prev_response in conversation.responses:
                if (
                    prev_response.prompt.system
                    and prev_response.prompt.system != current_system
                ):
                    messages.append(
                        {"role": "system", "content": prev_response.prompt.system}
                    )
                    current_system = prev_response.prompt.system
                messages.append(
                    {"role": "user", "content": prev_response.prompt.prompt}
                )
                messages.append({"role": "assistant", "content": prev_response.text()})
        if prompt.system and prompt.system != current_system:
            messages.append({"role": "system", "content": prompt.system})
        messages.append({"role": "user", "content": prompt.prompt})
        response._prompt_json = {"messages": messages}
        if stream:
            completion = openai.ChatCompletion.create(
                model=prompt.model.model_id,
                messages=messages,
                stream=True,
                api_key=self.key,
                **not_nulls(prompt.options),
            )
            chunks = []
            for chunk in completion:
                chunks.append(chunk)
                content = chunk["choices"][0].get("delta", {}).get("content")
                if content is not None:
                    yield content
            response.response_json = combine_chunks(chunks)
        else:
            completion = openai.ChatCompletion.create(
                model=prompt.model.model_id,
                messages=messages,
                api_key=self.key,
                stream=False,
            )
            response.response_json = completion.to_dict_recursive()
            yield completion.choices[0].message.content


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
