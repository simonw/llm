from llm import AsyncModel, EmbeddingModel, Model, hookimpl
import llm
from llm.utils import (
    dicts_to_table_string,
    remove_dict_none_values,
    logging_client,
    simplify_usage_dict,
)
import click
import datetime
import httpx
import openai
import os

try:
    # Pydantic 2
    from pydantic import field_validator, Field  # type: ignore

except ImportError:
    # Pydantic 1
    from pydantic.fields import Field
    from pydantic.class_validators import validator as field_validator  # type: ignore [no-redef]

from typing import AsyncGenerator, List, Iterable, Iterator, Optional, Union
import json
import yaml


@hookimpl
def register_models(register):
    # GPT-4o
    register(
        Chat("gpt-4o", vision=True), AsyncChat("gpt-4o", vision=True), aliases=("4o",)
    )
    register(
        Chat("gpt-4o-mini", vision=True),
        AsyncChat("gpt-4o-mini", vision=True),
        aliases=("4o-mini",),
    )
    register(
        Chat("gpt-4o-audio-preview", audio=True),
        AsyncChat("gpt-4o-audio-preview", audio=True),
    )
    # 3.5 and 4
    register(
        Chat("gpt-3.5-turbo"), AsyncChat("gpt-3.5-turbo"), aliases=("3.5", "chatgpt")
    )
    register(
        Chat("gpt-3.5-turbo-16k"),
        AsyncChat("gpt-3.5-turbo-16k"),
        aliases=("chatgpt-16k", "3.5-16k"),
    )
    register(Chat("gpt-4"), AsyncChat("gpt-4"), aliases=("4", "gpt4"))
    register(Chat("gpt-4-32k"), AsyncChat("gpt-4-32k"), aliases=("4-32k",))
    # GPT-4 Turbo models
    register(Chat("gpt-4-1106-preview"), AsyncChat("gpt-4-1106-preview"))
    register(Chat("gpt-4-0125-preview"), AsyncChat("gpt-4-0125-preview"))
    register(Chat("gpt-4-turbo-2024-04-09"), AsyncChat("gpt-4-turbo-2024-04-09"))
    register(
        Chat("gpt-4-turbo"),
        AsyncChat("gpt-4-turbo"),
        aliases=("gpt-4-turbo-preview", "4-turbo", "4t"),
    )
    # o1
    register(
        Chat("o1-preview", can_stream=False, allows_system_prompt=False),
        AsyncChat("o1-preview", can_stream=False, allows_system_prompt=False),
    )
    register(
        Chat("o1-mini", can_stream=False, allows_system_prompt=False),
        AsyncChat("o1-mini", can_stream=False, allows_system_prompt=False),
    )
    # The -instruct completion model
    register(
        Completion("gpt-3.5-turbo-instruct", default_max_tokens=256),
        aliases=("3.5-instruct", "chatgpt-instruct"),
    )

    # Load extra models
    extra_path = llm.user_dir() / "extra-openai-models.yaml"
    if not extra_path.exists():
        return
    with open(extra_path) as f:
        extra_models = yaml.safe_load(f)
    for extra_model in extra_models:
        model_id = extra_model["model_id"]
        aliases = extra_model.get("aliases", [])
        model_name = extra_model["model_name"]
        api_base = extra_model.get("api_base")
        api_type = extra_model.get("api_type")
        api_version = extra_model.get("api_version")
        api_engine = extra_model.get("api_engine")
        headers = extra_model.get("headers")
        kwargs = {}
        if extra_model.get("can_stream") is False:
            kwargs["can_stream"] = False
        if extra_model.get("completion"):
            klass = Completion
        else:
            klass = Chat
        chat_model = klass(
            model_id,
            model_name=model_name,
            api_base=api_base,
            api_type=api_type,
            api_version=api_version,
            api_engine=api_engine,
            headers=headers,
            **kwargs,
        )
        if api_base:
            chat_model.needs_key = None
        if extra_model.get("api_key_name"):
            chat_model.needs_key = extra_model["api_key_name"]
        register(
            chat_model,
            aliases=aliases,
        )


@hookimpl
def register_embedding_models(register):
    register(
        OpenAIEmbeddingModel("ada-002", "text-embedding-ada-002"), aliases=("ada",)
    )
    register(OpenAIEmbeddingModel("3-small", "text-embedding-3-small"))
    register(OpenAIEmbeddingModel("3-large", "text-embedding-3-large"))
    # With varying dimensions
    register(OpenAIEmbeddingModel("3-small-512", "text-embedding-3-small", 512))
    register(OpenAIEmbeddingModel("3-large-256", "text-embedding-3-large", 256))
    register(OpenAIEmbeddingModel("3-large-1024", "text-embedding-3-large", 1024))


class OpenAIEmbeddingModel(EmbeddingModel):
    needs_key = "openai"
    key_env_var = "OPENAI_API_KEY"
    batch_size = 100

    def __init__(self, model_id, openai_model_id, dimensions=None):
        self.model_id = model_id
        self.openai_model_id = openai_model_id
        self.dimensions = dimensions

    def embed_batch(self, items: Iterable[Union[str, bytes]]) -> Iterator[List[float]]:
        kwargs = {
            "input": items,
            "model": self.openai_model_id,
        }
        if self.dimensions:
            kwargs["dimensions"] = self.dimensions
        client = openai.OpenAI(api_key=self.get_key())
        results = client.embeddings.create(**kwargs).data
        return ([float(r) for r in result.embedding] for result in results)


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
        response = httpx.get(
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


class SharedOptions(llm.Options):
    temperature: Optional[float] = Field(
        description=(
            "What sampling temperature to use, between 0 and 2. Higher values like "
            "0.8 will make the output more random, while lower values like 0.2 will "
            "make it more focused and deterministic."
        ),
        ge=0,
        le=2,
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
        ge=0,
        le=1,
        default=None,
    )
    frequency_penalty: Optional[float] = Field(
        description=(
            "Number between -2.0 and 2.0. Positive values penalize new tokens based "
            "on their existing frequency in the text so far, decreasing the model's "
            "likelihood to repeat the same line verbatim."
        ),
        ge=-2,
        le=2,
        default=None,
    )
    presence_penalty: Optional[float] = Field(
        description=(
            "Number between -2.0 and 2.0. Positive values penalize new tokens based "
            "on whether they appear in the text so far, increasing the model's "
            "likelihood to talk about new topics."
        ),
        ge=-2,
        le=2,
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
    seed: Optional[int] = Field(
        description="Integer seed to attempt to sample deterministically",
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


def _attachment(attachment):
    url = attachment.url
    base64_content = ""
    if not url or attachment.resolve_type().startswith("audio/"):
        base64_content = attachment.base64_content()
        url = f"data:{attachment.resolve_type()};base64,{base64_content}"
    if attachment.resolve_type().startswith("image/"):
        return {"type": "image_url", "image_url": {"url": url}}
    else:
        format_ = "wav" if attachment.resolve_type() == "audio/wav" else "mp3"
        return {
            "type": "input_audio",
            "input_audio": {
                "data": base64_content,
                "format": format_,
            },
        }


class _Shared:
    def __init__(
        self,
        model_id,
        key=None,
        model_name=None,
        api_base=None,
        api_type=None,
        api_version=None,
        api_engine=None,
        headers=None,
        can_stream=True,
        vision=False,
        audio=False,
        allows_system_prompt=True,
    ):
        self.model_id = model_id
        self.key = key
        self.model_name = model_name
        self.api_base = api_base
        self.api_type = api_type
        self.api_version = api_version
        self.api_engine = api_engine
        self.headers = headers
        self.can_stream = can_stream
        self.vision = vision
        self.allows_system_prompt = allows_system_prompt

        self.attachment_types = set()

        if vision:
            self.attachment_types.update(
                {
                    "image/png",
                    "image/jpeg",
                    "image/webp",
                    "image/gif",
                }
            )

        if audio:
            self.attachment_types.update(
                {
                    "audio/wav",
                    "audio/mpeg",
                }
            )

    def __str__(self):
        return "OpenAI Chat: {}".format(self.model_id)

    def build_messages(self, prompt, conversation):
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
                if prev_response.attachments:
                    attachment_message = []
                    if prev_response.prompt.prompt:
                        attachment_message.append(
                            {"type": "text", "text": prev_response.prompt.prompt}
                        )
                    for attachment in prev_response.attachments:
                        attachment_message.append(_attachment(attachment))
                    messages.append({"role": "user", "content": attachment_message})
                else:
                    messages.append(
                        {"role": "user", "content": prev_response.prompt.prompt}
                    )
                messages.append(
                    {"role": "assistant", "content": prev_response.text_or_raise()}
                )
        if prompt.system and prompt.system != current_system:
            messages.append({"role": "system", "content": prompt.system})
        if not prompt.attachments:
            messages.append({"role": "user", "content": prompt.prompt})
        else:
            attachment_message = []
            if prompt.prompt:
                attachment_message.append({"type": "text", "text": prompt.prompt})
            for attachment in prompt.attachments:
                attachment_message.append(_attachment(attachment))
            messages.append({"role": "user", "content": attachment_message})
        return messages

    def set_usage(self, response, usage):
        if not usage:
            return
        input_tokens = usage.pop("prompt_tokens")
        output_tokens = usage.pop("completion_tokens")
        usage.pop("total_tokens")
        response.set_usage(
            input=input_tokens, output=output_tokens, details=simplify_usage_dict(usage)
        )

    def get_client(self, async_=False):
        kwargs = {}
        if self.api_base:
            kwargs["base_url"] = self.api_base
        if self.api_type:
            kwargs["api_type"] = self.api_type
        if self.api_version:
            kwargs["api_version"] = self.api_version
        if self.api_engine:
            kwargs["engine"] = self.api_engine
        if self.needs_key:
            kwargs["api_key"] = self.get_key()
        else:
            # OpenAI-compatible models don't need a key, but the
            # openai client library requires one
            kwargs["api_key"] = "DUMMY_KEY"
        if self.headers:
            kwargs["default_headers"] = self.headers
        if os.environ.get("LLM_OPENAI_SHOW_RESPONSES"):
            kwargs["http_client"] = logging_client()
        if async_:
            return openai.AsyncOpenAI(**kwargs)
        else:
            return openai.OpenAI(**kwargs)

    def build_kwargs(self, prompt, stream):
        kwargs = dict(not_nulls(prompt.options))
        json_object = kwargs.pop("json_object", None)
        if "max_tokens" not in kwargs and self.default_max_tokens is not None:
            kwargs["max_tokens"] = self.default_max_tokens
        if json_object:
            kwargs["response_format"] = {"type": "json_object"}
        if stream:
            kwargs["stream_options"] = {"include_usage": True}
        return kwargs


class Chat(_Shared, Model):
    needs_key = "openai"
    key_env_var = "OPENAI_API_KEY"
    default_max_tokens = None

    class Options(SharedOptions):
        json_object: Optional[bool] = Field(
            description="Output a valid JSON object {...}. Prompt must mention JSON.",
            default=None,
        )

    def execute(self, prompt, stream, response, conversation=None):
        if prompt.system and not self.allows_system_prompt:
            raise NotImplementedError("Model does not support system prompts")
        messages = self.build_messages(prompt, conversation)
        kwargs = self.build_kwargs(prompt, stream)
        client = self.get_client()
        usage = None
        if stream:
            completion = client.chat.completions.create(
                model=self.model_name or self.model_id,
                messages=messages,
                stream=True,
                **kwargs,
            )
            chunks = []
            for chunk in completion:
                chunks.append(chunk)
                if chunk.usage:
                    usage = chunk.usage.model_dump()
                try:
                    content = chunk.choices[0].delta.content
                except IndexError:
                    content = None
                if content is not None:
                    yield content
            response.response_json = remove_dict_none_values(combine_chunks(chunks))
        else:
            completion = client.chat.completions.create(
                model=self.model_name or self.model_id,
                messages=messages,
                stream=False,
                **kwargs,
            )
            usage = completion.usage.model_dump()
            response.response_json = remove_dict_none_values(completion.model_dump())
            yield completion.choices[0].message.content
        self.set_usage(response, usage)
        response._prompt_json = redact_data({"messages": messages})


class AsyncChat(_Shared, AsyncModel):
    needs_key = "openai"
    key_env_var = "OPENAI_API_KEY"
    default_max_tokens = None

    class Options(SharedOptions):
        json_object: Optional[bool] = Field(
            description="Output a valid JSON object {...}. Prompt must mention JSON.",
            default=None,
        )

    async def execute(
        self, prompt, stream, response, conversation=None
    ) -> AsyncGenerator[str, None]:
        if prompt.system and not self.allows_system_prompt:
            raise NotImplementedError("Model does not support system prompts")
        messages = self.build_messages(prompt, conversation)
        kwargs = self.build_kwargs(prompt, stream)
        client = self.get_client(async_=True)
        usage = None
        if stream:
            completion = await client.chat.completions.create(
                model=self.model_name or self.model_id,
                messages=messages,
                stream=True,
                **kwargs,
            )
            chunks = []
            async for chunk in completion:
                if chunk.usage:
                    usage = chunk.usage.model_dump()
                chunks.append(chunk)
                try:
                    content = chunk.choices[0].delta.content
                except IndexError:
                    content = None
                if content is not None:
                    yield content
            response.response_json = remove_dict_none_values(combine_chunks(chunks))
        else:
            completion = await client.chat.completions.create(
                model=self.model_name or self.model_id,
                messages=messages,
                stream=False,
                **kwargs,
            )
            response.response_json = remove_dict_none_values(completion.model_dump())
            usage = completion.usage.model_dump()
            yield completion.choices[0].message.content
        self.set_usage(response, usage)
        response._prompt_json = redact_data({"messages": messages})


class Completion(Chat):
    class Options(SharedOptions):
        logprobs: Optional[int] = Field(
            description="Include the log probabilities of most likely N per token",
            default=None,
            le=5,
        )

    def __init__(self, *args, default_max_tokens=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_max_tokens = default_max_tokens

    def __str__(self):
        return "OpenAI Completion: {}".format(self.model_id)

    def execute(self, prompt, stream, response, conversation=None):
        if prompt.system:
            raise NotImplementedError(
                "System prompts are not supported for OpenAI completion models"
            )
        messages = []
        if conversation is not None:
            for prev_response in conversation.responses:
                messages.append(prev_response.prompt.prompt)
                messages.append(prev_response.text())
        messages.append(prompt.prompt)
        kwargs = self.build_kwargs(prompt, stream)
        client = self.get_client()
        if stream:
            completion = client.completions.create(
                model=self.model_name or self.model_id,
                prompt="\n".join(messages),
                stream=True,
                **kwargs,
            )
            chunks = []
            for chunk in completion:
                chunks.append(chunk)
                try:
                    content = chunk.choices[0].text
                except IndexError:
                    content = None
                if content is not None:
                    yield content
            combined = combine_chunks(chunks)
            cleaned = remove_dict_none_values(combined)
            response.response_json = cleaned
        else:
            completion = client.completions.create(
                model=self.model_name or self.model_id,
                prompt="\n".join(messages),
                stream=False,
                **kwargs,
            )
            response.response_json = remove_dict_none_values(completion.model_dump())
            yield completion.choices[0].text
        response._prompt_json = redact_data({"messages": messages})


def not_nulls(data) -> dict:
    return {key: value for key, value in data if value is not None}


def combine_chunks(chunks: List) -> dict:
    content = ""
    role = None
    finish_reason = None
    # If any of them have log probability, we're going to persist
    # those later on
    logprobs = []
    usage = {}

    for item in chunks:
        if item.usage:
            usage = item.usage.dict()
        for choice in item.choices:
            if choice.logprobs and hasattr(choice.logprobs, "top_logprobs"):
                logprobs.append(
                    {
                        "text": choice.text if hasattr(choice, "text") else None,
                        "top_logprobs": choice.logprobs.top_logprobs,
                    }
                )

            if not hasattr(choice, "delta"):
                content += choice.text
                continue
            role = choice.delta.role
            if choice.delta.content is not None:
                content += choice.delta.content
            if choice.finish_reason is not None:
                finish_reason = choice.finish_reason

    # Imitations of the OpenAI API may be missing some of these fields
    combined = {
        "content": content,
        "role": role,
        "finish_reason": finish_reason,
        "usage": usage,
    }
    if logprobs:
        combined["logprobs"] = logprobs
    for key in ("id", "object", "model", "created", "index"):
        value = getattr(chunks[0], key, None)
        if value is not None:
            combined[key] = value

    return combined


def redact_data(input_dict):
    """
    Recursively search through the input dictionary for any 'image_url' keys
    and modify the 'url' value to be just 'data:...'.

    Also redact input_audio.data keys
    """
    if isinstance(input_dict, dict):
        for key, value in input_dict.items():
            if (
                key == "image_url"
                and isinstance(value, dict)
                and "url" in value
                and value["url"].startswith("data:")
            ):
                value["url"] = "data:..."
            elif key == "input_audio" and isinstance(value, dict) and "data" in value:
                value["data"] = "..."
            else:
                redact_data(value)
    elif isinstance(input_dict, list):
        for item in input_dict:
            redact_data(item)
    return input_dict
