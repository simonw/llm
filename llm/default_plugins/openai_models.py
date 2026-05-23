from llm import (
    AsyncConversation,
    AsyncKeyModel,
    AsyncResponse,
    Conversation,
    EmbeddingModel,
    KeyModel,
    Prompt,
    Response,
    hookimpl,
)
import llm
from llm.parts import StreamEvent
from llm.utils import (
    dicts_to_table_string,
    remove_dict_none_values,
    logging_client,
    simplify_usage_dict,
)
import click
import datetime
from enum import Enum
import httpx
import openai
import os

from pydantic import create_model, field_validator, Field

from typing import (
    Any,
    AsyncGenerator,
    cast,
    Dict,
    List,
    Iterable,
    Iterator,
    Optional,
    Union,
)
import json
import yaml


@hookimpl
def register_models(register):
    # GPT-4o
    register(
        Chat("gpt-4o", vision=True, supports_schema=True, supports_tools=True),
        AsyncChat("gpt-4o", vision=True, supports_schema=True, supports_tools=True),
        aliases=("4o",),
    )
    register(
        Chat("chatgpt-4o-latest", vision=True),
        AsyncChat("chatgpt-4o-latest", vision=True),
        aliases=("chatgpt-4o",),
    )
    register(
        Chat("gpt-4o-mini", vision=True, supports_schema=True, supports_tools=True),
        AsyncChat(
            "gpt-4o-mini", vision=True, supports_schema=True, supports_tools=True
        ),
        aliases=("4o-mini",),
    )
    for audio_model_id in (
        "gpt-4o-audio-preview",
        "gpt-4o-audio-preview-2024-12-17",
        "gpt-4o-audio-preview-2024-10-01",
        "gpt-4o-mini-audio-preview",
        "gpt-4o-mini-audio-preview-2024-12-17",
    ):
        register(
            Chat(audio_model_id, audio=True),
            AsyncChat(audio_model_id, audio=True),
        )
    # GPT-4.1
    for model_id in ("gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano"):
        register(
            Chat(model_id, vision=True, supports_schema=True, supports_tools=True),
            AsyncChat(model_id, vision=True, supports_schema=True, supports_tools=True),
            aliases=(model_id.replace("gpt-", ""),),
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
    # GPT-4.5
    register(
        Chat(
            "gpt-4.5-preview-2025-02-27",
            vision=True,
            supports_schema=True,
            supports_tools=True,
        ),
        AsyncChat(
            "gpt-4.5-preview-2025-02-27",
            vision=True,
            supports_schema=True,
            supports_tools=True,
        ),
    )
    register(
        Chat("gpt-4.5-preview", vision=True, supports_schema=True, supports_tools=True),
        AsyncChat(
            "gpt-4.5-preview", vision=True, supports_schema=True, supports_tools=True
        ),
        aliases=("gpt-4.5",),
    )
    # o1
    for model_id in ("o1", "o1-2024-12-17"):
        register(
            Responses(
                model_id,
                vision=True,
                can_stream=False,
                reasoning=True,
                supports_schema=True,
                supports_tools=True,
            ),
            AsyncResponses(
                model_id,
                vision=True,
                can_stream=False,
                reasoning=True,
                supports_schema=True,
                supports_tools=True,
            ),
        )

    register(
        Chat("o1-preview", allows_system_prompt=False),
        AsyncChat("o1-preview", allows_system_prompt=False),
    )
    register(
        Chat("o1-mini", allows_system_prompt=False),
        AsyncChat("o1-mini", allows_system_prompt=False),
    )
    register(
        Responses("o3-mini", reasoning=True, supports_schema=True, supports_tools=True),
        AsyncResponses(
            "o3-mini", reasoning=True, supports_schema=True, supports_tools=True
        ),
    )
    register(
        Responses(
            "o3", vision=True, reasoning=True, supports_schema=True, supports_tools=True
        ),
        AsyncResponses(
            "o3", vision=True, reasoning=True, supports_schema=True, supports_tools=True
        ),
    )
    register(
        Responses(
            "o4-mini",
            vision=True,
            reasoning=True,
            supports_schema=True,
            supports_tools=True,
        ),
        AsyncResponses(
            "o4-mini",
            vision=True,
            reasoning=True,
            supports_schema=True,
            supports_tools=True,
        ),
    )
    # GPT-5
    for model_id in (
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-5-2025-08-07",
        "gpt-5-mini-2025-08-07",
        "gpt-5-nano-2025-08-07",
    ):
        register(
            Responses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                supports_schema=True,
                supports_tools=True,
            ),
            AsyncResponses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                supports_schema=True,
                supports_tools=True,
            ),
        )
    # GPT-5.1
    for model_id in (
        "gpt-5.1",
        "gpt-5.1-chat-latest",
    ):
        register(
            Responses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                supports_schema=True,
                supports_tools=True,
            ),
            AsyncResponses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                supports_schema=True,
                supports_tools=True,
            ),
        )
    # GPT-5.2
    for model_id in ("gpt-5.2", "gpt-5.2-chat-latest"):
        register(
            Responses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                supports_schema=True,
                supports_tools=True,
            ),
            AsyncResponses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                supports_schema=True,
                supports_tools=True,
            ),
        )
        # "gpt-5.2-pro" is Responses API only

    # GPT-5.4
    for model_id in (
        "gpt-5.4",
        "gpt-5.4-2026-03-05",
        "gpt-5.4-mini",
        "gpt-5.4-mini-2026-03-17",
        "gpt-5.4-nano",
        "gpt-5.4-nano-2026-03-17",
    ):
        register(
            Responses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                image_detail_original=True,
                supports_schema=True,
                supports_tools=True,
            ),
            AsyncResponses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                image_detail_original=True,
                supports_schema=True,
                supports_tools=True,
            ),
        )
    # GPT-5.5 — routes through the Responses API by default; pass
    # ``-o chat_completions 1`` to fall back to /v1/chat/completions.
    for model_id in (
        "gpt-5.5",
        "gpt-5.5-2026-04-23",
    ):
        register(
            Responses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                image_detail_original=True,
                supports_schema=True,
                supports_tools=True,
            ),
            AsyncResponses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                image_detail_original=True,
                supports_schema=True,
                supports_tools=True,
            ),
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
        reasoning = extra_model.get("reasoning")
        kwargs = {}
        if extra_model.get("can_stream") is False:
            kwargs["can_stream"] = False
        if extra_model.get("supports_schema") is True:
            kwargs["supports_schema"] = True
        if extra_model.get("supports_tools") is True:
            kwargs["supports_tools"] = True
        if extra_model.get("vision") is True:
            kwargs["vision"] = True
        if extra_model.get("audio") is True:
            kwargs["audio"] = True
        if extra_model.get("completion"):
            klass = Completion
            async_klass = None
        elif extra_model.get("responses"):
            klass = Responses
            async_klass = AsyncResponses
        else:
            klass = Chat
            async_klass = AsyncChat
        model_kwargs = dict(
            model_id=model_id,
            model_name=model_name,
            api_base=api_base,
            api_type=api_type,
            api_version=api_version,
            api_engine=api_engine,
            headers=headers,
            reasoning=reasoning,
            **kwargs,
        )
        chat_model = klass(**model_kwargs)
        async_model = async_klass(**model_kwargs) if async_klass else None
        if api_base:
            chat_model.needs_key = None
            if async_model:
                async_model.needs_key = None
        if extra_model.get("api_key_name"):
            chat_model.needs_key = extra_model["api_key_name"]
            if async_model:
                async_model.needs_key = extra_model["api_key_name"]
        register(
            chat_model,
            async_model,
            aliases=aliases,
        )


@hookimpl
def register_embedding_models(register):
    register(
        OpenAIEmbeddingModel("text-embedding-ada-002", "text-embedding-ada-002"),
        aliases=(
            "ada",
            "ada-002",
        ),
    )
    register(
        OpenAIEmbeddingModel("text-embedding-3-small", "text-embedding-3-small"),
        aliases=("3-small",),
    )
    register(
        OpenAIEmbeddingModel("text-embedding-3-large", "text-embedding-3-large"),
        aliases=("3-large",),
    )
    # With varying dimensions
    register(
        OpenAIEmbeddingModel(
            "text-embedding-3-small-512", "text-embedding-3-small", 512
        ),
        aliases=("3-small-512",),
    )
    register(
        OpenAIEmbeddingModel(
            "text-embedding-3-large-256", "text-embedding-3-large", 256
        ),
        aliases=("3-large-256",),
    )
    register(
        OpenAIEmbeddingModel(
            "text-embedding-3-large-1024", "text-embedding-3-large", 1024
        ),
        aliases=("3-large-1024",),
    )


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
        from llm import get_key

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
                created_str = datetime.datetime.fromtimestamp(
                    model["created"], datetime.timezone.utc
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


class ReasoningEffortEnum(str, Enum):
    none = "none"
    minimal = "minimal"
    low = "low"
    medium = "medium"
    high = "high"
    xhigh = "xhigh"


class VerbosityEnum(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ImageDetailEnum(str, Enum):
    low = "low"
    high = "high"
    auto = "auto"


class ImageDetailWithOriginalEnum(str, Enum):
    low = "low"
    high = "high"
    original = "original"
    auto = "auto"


def enum_values_sentence(enum_class):
    values = [item.value for item in enum_class]
    if len(values) == 1:
        return values[0]
    return "{}, and {}".format(", ".join(values[:-1]), values[-1])


def build_options_class(
    *,
    reasoning=False,
    verbosity=False,
    image_detail_original=False,
    chat_completions=False,
):
    fields = {
        "json_object": (
            Optional[bool],
            Field(
                description="Output a valid JSON object {...}. Prompt must mention JSON.",
                default=None,
            ),
        )
    }
    if chat_completions:
        fields["chat_completions"] = (
            Optional[bool],
            Field(
                description=(
                    "Force the use of the older /v1/chat/completions endpoint "
                    "instead of /v1/responses. Most callers should leave this "
                    "off; set to true to fall back to the Chat Completions code "
                    "path for compatibility."
                ),
                default=None,
            ),
        )
    image_detail_enum = (
        ImageDetailWithOriginalEnum if image_detail_original else ImageDetailEnum
    )
    image_detail_values = enum_values_sentence(image_detail_enum)
    fields["image_detail"] = (
        Optional[image_detail_enum],
        Field(
            description=(
                "Controls the detail level for image attachments. Supported values are "
                f"{image_detail_values}."
            ),
            default=None,
        ),
    )
    if reasoning:
        fields["reasoning_effort"] = (
            Optional[ReasoningEffortEnum],
            Field(
                description=(
                    "Constraints effort on reasoning for reasoning models. Currently "
                    "supported values are low, medium, and high. Reducing reasoning "
                    "effort can result in faster responses and fewer tokens used on "
                    "reasoning in a response."
                ),
                default=None,
            ),
        )
    if verbosity:
        fields["verbosity"] = (
            Optional[VerbosityEnum],
            Field(
                description=(
                    "Controls how verbose the model's response should be. Supported "
                    "values are low, medium, and high."
                ),
                default=None,
            ),
        )
    return create_model("Options", __base__=SharedOptions, **fields)


def _attachment(attachment, image_detail=None):
    url = attachment.url
    base64_content = ""
    if not url or attachment.resolve_type().startswith("audio/"):
        base64_content = attachment.base64_content()
        url = f"data:{attachment.resolve_type()};base64,{base64_content}"
    if attachment.resolve_type() == "application/pdf":
        if not base64_content:
            base64_content = attachment.base64_content()
        return {
            "type": "file",
            "file": {
                "filename": f"{attachment.id()}.pdf",
                "file_data": f"data:application/pdf;base64,{base64_content}",
            },
        }
    if attachment.resolve_type().startswith("image/"):
        image_url = {"url": url}
        if image_detail:
            image_url["detail"] = image_detail
        return {"type": "image_url", "image_url": image_url}
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
        reasoning=False,
        verbosity=False,
        image_detail_original=False,
        supports_schema=False,
        supports_tools=False,
        allows_system_prompt=True,
    ):
        self.model_id = model_id
        self.key = key
        self.supports_schema = supports_schema
        self.supports_tools = supports_tools
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

        if reasoning or verbosity or image_detail_original:
            self.Options = build_options_class(
                reasoning=reasoning,
                verbosity=verbosity,
                image_detail_original=image_detail_original,
            )

        if vision:
            self.attachment_types.update(
                {
                    "image/png",
                    "image/jpeg",
                    "image/webp",
                    "image/gif",
                    "application/pdf",
                }
            )

        if audio:
            self.attachment_types.update(
                {
                    "audio/wav",
                    "audio/mpeg",
                }
            )

    def __str__(self) -> str:
        return "OpenAI Chat: {}".format(self.model_id)

    def _append_llm_message(self, out, message, current_system, image_detail=None):
        """Translate one llm.Message into one (or more) OpenAI message
        dicts and append them to ``out``.

        Returns the (possibly updated) current_system value so the caller
        can avoid re-emitting an unchanged system prompt.
        """
        from llm.parts import (
            AttachmentPart,
            TextPart,
            ToolCallPart,
            ToolResultPart,
        )

        text_bits = []
        attachment_items = []
        tool_calls = []
        tool_results = []

        for part in message.parts:
            if isinstance(part, TextPart):
                text_bits.append(part.text)
            elif isinstance(part, AttachmentPart) and part.attachment:
                attachment_items.append(
                    _attachment(part.attachment, image_detail=image_detail)
                )
            elif isinstance(part, ToolCallPart):
                tool_calls.append(
                    {
                        "type": "function",
                        "id": part.tool_call_id,
                        "function": {
                            "name": part.name,
                            "arguments": json.dumps(part.arguments),
                        },
                    }
                )
            elif isinstance(part, ToolResultPart):
                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": part.tool_call_id,
                        "content": part.output,
                    }
                )

        # Role "tool" emits one OpenAI "tool" message per ToolResultPart.
        if message.role == "tool":
            out.extend(tool_results)
            return current_system

        # System dedup: skip if this text is already the active system prompt.
        if message.role == "system":
            text = "".join(text_bits)
            if text == current_system:
                return current_system
            current_system = text

        if attachment_items:
            content = []
            if text_bits:
                content.append({"type": "text", "text": "".join(text_bits)})
            content.extend(attachment_items)
            entry = {"role": message.role, "content": content}
        else:
            entry = {
                "role": message.role,
                "content": "".join(text_bits) if text_bits else None,
            }

        if tool_calls:
            entry["tool_calls"] = tool_calls
            # OpenAI expects content=null when only tool_calls are present.
            if not text_bits:
                entry["content"] = None
        elif entry["content"] is None and message.role != "assistant":
            # For user/system, an empty message is pointless — drop it.
            return current_system

        out.append(entry)
        return current_system

    def build_messages(self, prompt, conversation, image_detail=None):
        """Translate prompt.messages into OpenAI's wire format."""
        messages: List[Dict[str, Any]] = []
        if image_detail is not None:
            image_detail = image_detail.value
        current_system: Optional[str] = None
        for msg in prompt.messages:
            current_system = self._append_llm_message(
                messages, msg, current_system, image_detail=image_detail
            )
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

    def get_client(self, key, *, async_=False):
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
            kwargs["api_key"] = self.get_key(key)
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
        kwargs.pop("image_detail", None)
        kwargs.pop("chat_completions", None)
        if "max_tokens" not in kwargs and self.default_max_tokens is not None:
            kwargs["max_tokens"] = self.default_max_tokens
        if json_object:
            kwargs["response_format"] = {"type": "json_object"}
        if prompt.schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": prompt.schema},
            }
        if prompt.tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or None,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in prompt.tools
            ]
        if stream:
            kwargs["stream_options"] = {"include_usage": True}
        return kwargs


class Chat(_Shared, KeyModel):
    needs_key = "openai"
    key_env_var = "OPENAI_API_KEY"
    default_max_tokens = None

    Options = build_options_class()

    def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: Response,
        conversation: Optional[Conversation] = None,
        key: Optional[str] = None,
    ) -> Iterator[Union[str, StreamEvent]]:
        if prompt.system and not self.allows_system_prompt:
            raise NotImplementedError("Model does not support system prompts")
        messages = self.build_messages(
            prompt,
            conversation,
            image_detail=getattr(prompt.options, "image_detail", None),
        )
        kwargs = self.build_kwargs(prompt, stream)
        client = self.get_client(key)
        usage = None
        if stream:
            completion = client.chat.completions.create(
                model=self.model_name or self.model_id,
                messages=messages,
                stream=True,
                **kwargs,
            )
            chunks = []
            tool_calls = {}
            for chunk in completion:
                chunks.append(chunk)
                if chunk.usage:
                    usage = chunk.usage.model_dump()
                if chunk.choices and chunk.choices[0].delta:
                    for tool_call in chunk.choices[0].delta.tool_calls or []:
                        if tool_call.function.arguments is None:
                            tool_call.function.arguments = ""
                        idx = tool_call.index
                        if idx not in tool_calls:
                            tool_calls[idx] = tool_call
                            yield StreamEvent(
                                type="tool_call_name",
                                chunk=tool_call.function.name or "",
                                tool_call_id=tool_call.id,
                            )
                        else:
                            tool_calls[
                                idx
                            ].function.arguments += tool_call.function.arguments
                        if tool_call.function.arguments:
                            yield StreamEvent(
                                type="tool_call_args",
                                chunk=tool_call.function.arguments,
                                tool_call_id=tool_calls[idx].id,
                            )
                try:
                    content = chunk.choices[0].delta.content
                except IndexError:
                    content = None
                if content:
                    # Empty strings are noise (OpenAI's first chunk
                    # with role=assistant has content="").
                    yield StreamEvent(type="text", chunk=content)
            response.response_json = remove_dict_none_values(combine_chunks(chunks))
            if tool_calls:
                for value in tool_calls.values():
                    response.add_tool_call(
                        llm.ToolCall(
                            tool_call_id=value.id,
                            name=value.function.name,
                            arguments=json.loads(value.function.arguments),
                        )
                    )
        else:
            completion = client.chat.completions.create(
                model=self.model_name or self.model_id,
                messages=messages,
                stream=False,
                **kwargs,
            )
            usage = completion.usage.model_dump()
            response.response_json = remove_dict_none_values(completion.model_dump())
            for tool_call in completion.choices[0].message.tool_calls or []:
                response.add_tool_call(
                    llm.ToolCall(
                        tool_call_id=tool_call.id,
                        name=tool_call.function.name,
                        arguments=json.loads(tool_call.function.arguments),
                    )
                )
                yield StreamEvent(
                    type="tool_call_name",
                    chunk=tool_call.function.name or "",
                    tool_call_id=tool_call.id,
                )
                yield StreamEvent(
                    type="tool_call_args",
                    chunk=tool_call.function.arguments or "",
                    tool_call_id=tool_call.id,
                )
            if completion.choices[0].message.content is not None:
                yield StreamEvent(
                    type="text",
                    chunk=completion.choices[0].message.content,
                )
        self.set_usage(response, usage)
        if usage and (usage.get("completion_tokens_details") or {}).get(
            "reasoning_tokens"
        ):
            yield StreamEvent(type="reasoning", chunk="", redacted=True)
        response._prompt_json = redact_data({"messages": messages})


class AsyncChat(_Shared, AsyncKeyModel):
    needs_key = "openai"
    key_env_var = "OPENAI_API_KEY"
    default_max_tokens = None

    Options = build_options_class()

    async def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: AsyncResponse,
        conversation: Optional[AsyncConversation] = None,
        key: Optional[str] = None,
    ) -> AsyncGenerator[Union[str, StreamEvent], None]:
        if prompt.system and not self.allows_system_prompt:
            raise NotImplementedError("Model does not support system prompts")
        messages = self.build_messages(
            prompt,
            conversation,
            image_detail=getattr(prompt.options, "image_detail", None),
        )
        kwargs = self.build_kwargs(prompt, stream)
        client = self.get_client(key, async_=True)
        usage = None
        if stream:
            completion = await client.chat.completions.create(
                model=self.model_name or self.model_id,
                messages=messages,
                stream=True,
                **kwargs,
            )
            chunks = []
            tool_calls = {}
            async for chunk in completion:
                if chunk.usage:
                    usage = chunk.usage.model_dump()
                chunks.append(chunk)
                if chunk.choices and chunk.choices[0].delta:
                    for tool_call in chunk.choices[0].delta.tool_calls or []:
                        if tool_call.function.arguments is None:
                            tool_call.function.arguments = ""
                        idx = tool_call.index
                        if idx not in tool_calls:
                            tool_calls[idx] = tool_call
                            yield StreamEvent(
                                type="tool_call_name",
                                chunk=tool_call.function.name or "",
                                tool_call_id=tool_call.id,
                            )
                        else:
                            tool_calls[
                                idx
                            ].function.arguments += tool_call.function.arguments
                        if tool_call.function.arguments:
                            yield StreamEvent(
                                type="tool_call_args",
                                chunk=tool_call.function.arguments,
                                tool_call_id=tool_calls[idx].id,
                            )
                try:
                    content = chunk.choices[0].delta.content
                except IndexError:
                    content = None
                if content:
                    yield StreamEvent(type="text", chunk=content)
            if tool_calls:
                for value in tool_calls.values():
                    response.add_tool_call(
                        llm.ToolCall(
                            tool_call_id=value.id,
                            name=value.function.name,
                            arguments=json.loads(value.function.arguments),
                        )
                    )
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
            for tool_call in completion.choices[0].message.tool_calls or []:
                response.add_tool_call(
                    llm.ToolCall(
                        tool_call_id=tool_call.id,
                        name=tool_call.function.name,
                        arguments=json.loads(tool_call.function.arguments),
                    )
                )
                yield StreamEvent(
                    type="tool_call_name",
                    chunk=tool_call.function.name or "",
                    tool_call_id=tool_call.id,
                )
                yield StreamEvent(
                    type="tool_call_args",
                    chunk=tool_call.function.arguments or "",
                    tool_call_id=tool_call.id,
                )
            if completion.choices[0].message.content is not None:
                yield StreamEvent(
                    type="text",
                    chunk=completion.choices[0].message.content,
                )
        self.set_usage(response, usage)
        if usage and (usage.get("completion_tokens_details") or {}).get(
            "reasoning_tokens"
        ):
            yield StreamEvent(type="reasoning", chunk="", redacted=True)
        response._prompt_json = redact_data({"messages": messages})


def _responses_attachment(attachment, image_detail=None):
    """Translate an llm Attachment into a Responses-API content part."""
    url = attachment.url
    base64_content = ""
    if not url or attachment.resolve_type().startswith("audio/"):
        base64_content = attachment.base64_content()
        url = f"data:{attachment.resolve_type()};base64,{base64_content}"
    if attachment.resolve_type() == "application/pdf":
        if not base64_content:
            base64_content = attachment.base64_content()
        return {
            "type": "input_file",
            "filename": f"{attachment.id()}.pdf",
            "file_data": f"data:application/pdf;base64,{base64_content}",
        }
    if attachment.resolve_type().startswith("image/"):
        item = {"type": "input_image", "image_url": url}
        if image_detail:
            item["detail"] = image_detail
        return item
    # Audio is not yet supported on the Responses input shape we use; fall
    # back to image_url for unknown types so we don't silently drop content.
    return {"type": "input_image", "image_url": url}


class _SharedResponses(_Shared):
    """Mixin that translates llm.Prompt into Responses API parameters."""

    def __str__(self) -> str:
        return "OpenAI Responses: {}".format(self.model_id)

    def _delegate_chat_kwargs(self):
        """Return constructor kwargs that mirror this Responses model so we
        can build a sibling Chat / AsyncChat instance for the
        ``-o chat_completions 1`` opt-out path."""
        return dict(
            model_id=self.model_id,
            key=self.key,
            model_name=self.model_name,
            api_base=self.api_base,
            api_type=self.api_type,
            api_version=self.api_version,
            api_engine=self.api_engine,
            headers=self.headers,
            can_stream=self.can_stream,
            vision=self.vision,
            reasoning=self._reasoning,
            verbosity=self._verbosity,
            image_detail_original=self._image_detail_original,
            supports_schema=self.supports_schema,
            supports_tools=self.supports_tools,
            allows_system_prompt=self.allows_system_prompt,
        )

    def _build_responses_input(self, prompt, image_detail=None):
        """Translate prompt.messages into a (input_items, instructions) tuple
        for the Responses API.

        The most recent system Message is hoisted into ``instructions``;
        earlier system messages are dropped (mirroring the way the Chat
        path collapses repeated identical system prompts).
        """
        from llm.parts import (
            AttachmentPart,
            ReasoningPart,
            TextPart,
            ToolCallPart,
            ToolResultPart,
        )

        items: List[Dict[str, Any]] = []
        instructions: Optional[str] = None

        for msg in prompt.messages:
            if msg.role == "system":
                text = "".join(p.text for p in msg.parts if isinstance(p, TextPart))
                if text:
                    instructions = text
                continue

            text_bits: List[str] = []
            attachment_items: List[Dict[str, Any]] = []
            tool_call_items: List[Dict[str, Any]] = []
            tool_result_items: List[Dict[str, Any]] = []
            reasoning_items: List[Dict[str, Any]] = []

            for part in msg.parts:
                if isinstance(part, TextPart):
                    text_bits.append(part.text)
                elif isinstance(part, AttachmentPart) and part.attachment:
                    attachment_items.append(
                        _responses_attachment(
                            part.attachment, image_detail=image_detail
                        )
                    )
                elif isinstance(part, ToolCallPart):
                    tool_call_items.append(
                        {
                            "type": "function_call",
                            "call_id": part.tool_call_id,
                            "name": part.name,
                            "arguments": json.dumps(part.arguments),
                        }
                    )
                elif isinstance(part, ToolResultPart):
                    tool_result_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": part.tool_call_id,
                            "output": part.output,
                        }
                    )
                elif isinstance(part, ReasoningPart):
                    pm = (part.provider_metadata or {}).get("openai") or {}
                    enc = pm.get("encrypted_content")
                    rid = pm.get("id")
                    if enc or rid:
                        # Round-trip a previous reasoning item so the model
                        # can pick up where it left off mid-tool-call.
                        item: Dict[str, Any] = {"type": "reasoning"}
                        if rid:
                            item["id"] = rid
                        if enc:
                            item["encrypted_content"] = enc
                        if pm.get("summary"):
                            item["summary"] = pm["summary"]
                        else:
                            item["summary"] = []
                        reasoning_items.append(item)

            # Reasoning items must precede the assistant message / function
            # call they belonged to.
            items.extend(reasoning_items)

            if msg.role == "tool":
                items.extend(tool_result_items)
                continue

            if msg.role == "user":
                if attachment_items:
                    content: List[Dict[str, Any]] = []
                    if text_bits:
                        content.append(
                            {"type": "input_text", "text": "".join(text_bits)}
                        )
                    content.extend(attachment_items)
                    items.append({"role": "user", "content": content})
                elif text_bits:
                    items.append({"role": "user", "content": "".join(text_bits)})
            elif msg.role == "assistant":
                if text_bits:
                    items.append({"role": "assistant", "content": "".join(text_bits)})
                items.extend(tool_call_items)

        return items, instructions

    def _build_responses_kwargs(self, prompt, stream):
        """Build the keyword arguments for client.responses.create()."""
        opts = dict(not_nulls(prompt.options))
        # Strip options that are either internal to llm or not accepted by
        # the Responses API.
        opts.pop("json_object", None)
        opts.pop("chat_completions", None)
        opts.pop("image_detail", None)
        max_tokens = opts.pop("max_tokens", None)
        reasoning_effort = opts.pop("reasoning_effort", None)
        verbosity = opts.pop("verbosity", None)
        temperature = opts.pop("temperature", None)
        top_p = opts.pop("top_p", None)
        seed = opts.pop("seed", None)

        kwargs: Dict[str, Any] = {}
        if max_tokens is None and self.default_max_tokens is not None:
            max_tokens = self.default_max_tokens
        if max_tokens is not None:
            kwargs["max_output_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if seed is not None:
            kwargs["seed"] = seed
        if self._reasoning:
            reasoning = {}
            if not getattr(prompt, "hide_reasoning", False):
                reasoning["summary"] = "auto"
            if reasoning_effort:
                reasoning["effort"] = reasoning_effort
            if reasoning:
                kwargs["reasoning"] = reasoning

        text: Dict[str, Any] = {}
        if verbosity:
            text["verbosity"] = verbosity
        if prompt.options.json_object:
            text["format"] = {"type": "json_object"}
        if prompt.schema:
            # ``strict: False`` mirrors the looser behaviour of the
            # /v1/chat/completions json_schema response_format - required
            # because the Responses API otherwise insists on
            # ``additionalProperties: false`` everywhere.
            text["format"] = {
                "type": "json_schema",
                "name": "output",
                "schema": prompt.schema,
                "strict": False,
            }
        if text:
            kwargs["text"] = text

        if prompt.tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description or None,
                    "parameters": tool.input_schema,
                }
                for tool in prompt.tools
            ]

        # Pass anything we did not consume through verbatim - this lets
        # extras like ``parallel_tool_calls`` flow into the API.
        kwargs.update(opts)
        return kwargs

    def _set_usage_responses(self, response, usage):
        if not usage:
            return
        input_tokens = usage.get("input_tokens", 0) or 0
        output_tokens = usage.get("output_tokens", 0) or 0
        details = {}
        for key in ("input_tokens_details", "output_tokens_details"):
            value = usage.get(key)
            if value:
                details[key] = value
        response.set_usage(
            input=input_tokens, output=output_tokens, details=details or None
        )

    def _reasoning_text_from_item(self, item):
        bits = []
        for attr in ("summary", "content"):
            for part in getattr(item, attr, None) or []:
                if isinstance(part, dict):
                    text = part.get("text")
                else:
                    text = getattr(part, "text", None)
                if text:
                    bits.append(text)
        return "".join(bits)

    def _reasoning_event(self, item, *, include_text=True):
        """Build a redacted-reasoning StreamEvent that carries the opaque
        ``id`` and ``encrypted_content`` from a Responses-API reasoning
        item. Echoing this metadata back on the next request via
        ``_build_responses_input`` lets the model pick up its prior chain
        of thought - critical for tool-using reasoning models, since
        without it the model loses ~3% on SWE-bench (per OpenAI)."""
        rid = getattr(item, "id", None)
        enc = getattr(item, "encrypted_content", None)
        summary = getattr(item, "summary", None)
        text = self._reasoning_text_from_item(item) if include_text else ""
        meta: Dict[str, Any] = {}
        if rid:
            meta["id"] = rid
        if enc:
            meta["encrypted_content"] = enc
        if summary:
            # ``summary`` is a list of {type:"summary_text", text:"..."}
            # objects when reasoning summaries are enabled.
            try:
                meta["summary"] = [
                    s.model_dump() if hasattr(s, "model_dump") else dict(s)
                    for s in summary
                ]
            except Exception:
                meta["summary"] = list(summary)
        return StreamEvent(
            type="reasoning",
            chunk=text,
            redacted=include_text and not text,
            provider_metadata={"openai": meta} if meta else None,
        )


class Responses(_SharedResponses, KeyModel):
    needs_key = "openai"
    key_env_var = "OPENAI_API_KEY"
    default_max_tokens = None

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
        reasoning=False,
        verbosity=False,
        image_detail_original=False,
        supports_schema=False,
        supports_tools=False,
        allows_system_prompt=True,
    ):
        super().__init__(
            model_id,
            key=key,
            model_name=model_name,
            api_base=api_base,
            api_type=api_type,
            api_version=api_version,
            api_engine=api_engine,
            headers=headers,
            can_stream=can_stream,
            vision=vision,
            audio=audio,
            reasoning=reasoning,
            verbosity=verbosity,
            image_detail_original=image_detail_original,
            supports_schema=supports_schema,
            supports_tools=supports_tools,
            allows_system_prompt=allows_system_prompt,
        )
        self._reasoning = reasoning
        self._verbosity = verbosity
        self._image_detail_original = image_detail_original
        # Override the Options class so that ``-o chat_completions 1`` is
        # always available on Responses-routed models.
        self.Options = build_options_class(
            reasoning=reasoning,
            verbosity=verbosity,
            image_detail_original=image_detail_original,
            chat_completions=True,
        )

    def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: Response,
        conversation: Optional[Conversation] = None,
        key: Optional[str] = None,
    ) -> Iterator[Union[str, StreamEvent]]:
        if getattr(prompt.options, "chat_completions", None):
            chat = Chat(**self._delegate_chat_kwargs())
            yield from chat.execute(prompt, stream, response, conversation, key)
            return

        if prompt.system and not self.allows_system_prompt:
            raise NotImplementedError("Model does not support system prompts")

        image_detail = getattr(prompt.options, "image_detail", None)
        if image_detail is not None:
            image_detail = image_detail.value
        input_items, instructions = self._build_responses_input(
            prompt, image_detail=image_detail
        )
        kwargs = self._build_responses_kwargs(prompt, stream)
        if instructions is not None:
            kwargs["instructions"] = instructions
        kwargs["store"] = False
        if self._reasoning:
            kwargs["include"] = ["reasoning.encrypted_content"]

        client = self.get_client(key)
        usage = None
        had_reasoning = False
        if stream:
            stream_obj = client.responses.create(
                model=self.model_name or self.model_id,
                input=input_items,
                stream=True,
                **kwargs,
            )
            tool_call_meta: Dict[str, Dict[str, str]] = {}
            final_response_dict: Optional[Dict[str, Any]] = None
            reasoning_items_with_streamed_text = set()
            for event in stream_obj:
                etype = getattr(event, "type", None)
                if etype == "response.output_item.added":
                    item = event.item
                    if item.type == "function_call":
                        tool_call_meta[item.id] = {
                            "id": item.id,
                            "call_id": item.call_id,
                            "name": item.name,
                        }
                        yield StreamEvent(
                            type="tool_call_name",
                            chunk=item.name or "",
                            tool_call_id=item.call_id,
                        )
                elif etype == "response.output_text.delta":
                    yield StreamEvent(type="text", chunk=event.delta or "")
                elif etype == "response.function_call_arguments.delta":
                    item_id = getattr(event, "item_id", None)
                    meta = tool_call_meta.get(item_id) if item_id else None
                    call_id = meta["call_id"] if meta else None
                    yield StreamEvent(
                        type="tool_call_args",
                        chunk=event.delta or "",
                        tool_call_id=call_id,
                    )
                elif etype in (
                    "response.reasoning_summary_text.delta",
                    "response.reasoning_text.delta",
                ):
                    item_id = getattr(event, "item_id", None)
                    if item_id:
                        reasoning_items_with_streamed_text.add(item_id)
                    yield StreamEvent(type="reasoning", chunk=event.delta or "")
                elif etype in (
                    "response.reasoning_summary_text.done",
                    "response.reasoning_text.done",
                ):
                    item_id = getattr(event, "item_id", None)
                    if item_id not in reasoning_items_with_streamed_text:
                        text = getattr(event, "text", None) or ""
                        if text:
                            if item_id:
                                reasoning_items_with_streamed_text.add(item_id)
                            yield StreamEvent(type="reasoning", chunk=text)
                elif etype == "response.output_item.done":
                    item = event.item
                    if item.type == "reasoning":
                        had_reasoning = True
                        item_id = getattr(item, "id", None)
                        yield self._reasoning_event(
                            item,
                            include_text=(
                                item_id not in reasoning_items_with_streamed_text
                            ),
                        )
                    elif item.type == "function_call":
                        try:
                            args = json.loads(item.arguments) if item.arguments else {}
                        except json.JSONDecodeError:
                            args = {"_raw": item.arguments}
                        response.add_tool_call(
                            llm.ToolCall(
                                tool_call_id=item.call_id,
                                name=item.name,
                                arguments=args,
                            )
                        )
                elif etype == "response.completed":
                    final_response_dict = event.response.model_dump()
                    if final_response_dict.get("usage"):
                        usage = final_response_dict["usage"]
            if final_response_dict is not None:
                response.response_json = remove_dict_none_values(final_response_dict)
        else:
            completion = client.responses.create(
                model=self.model_name or self.model_id,
                input=input_items,
                stream=False,
                **kwargs,
            )
            dumped = completion.model_dump()
            response.response_json = remove_dict_none_values(dumped)
            usage = dumped.get("usage")
            for item in completion.output:
                if item.type == "reasoning":
                    had_reasoning = True
                    yield self._reasoning_event(item)
                elif item.type == "function_call":
                    try:
                        args = json.loads(item.arguments) if item.arguments else {}
                    except json.JSONDecodeError:
                        args = {"_raw": item.arguments}
                    response.add_tool_call(
                        llm.ToolCall(
                            tool_call_id=item.call_id,
                            name=item.name,
                            arguments=args,
                        )
                    )
                    yield StreamEvent(
                        type="tool_call_name",
                        chunk=item.name or "",
                        tool_call_id=item.call_id,
                    )
                    yield StreamEvent(
                        type="tool_call_args",
                        chunk=item.arguments or "",
                        tool_call_id=item.call_id,
                    )
                elif item.type == "message":
                    for content in item.content or []:
                        ctype = getattr(content, "type", None)
                        if ctype == "output_text" and content.text:
                            yield StreamEvent(type="text", chunk=content.text)

        self._set_usage_responses(response, usage)
        # Fallback: usage said reasoning happened but the API gave us no
        # reasoning items to harvest encrypted_content from. Emit the
        # opaque "reasoning happened" marker for UI / token accounting.
        if (
            not had_reasoning
            and usage
            and ((usage.get("output_tokens_details") or {}).get("reasoning_tokens"))
        ):
            yield StreamEvent(type="reasoning", chunk="", redacted=True)
        response._prompt_json = redact_data(
            {"input": input_items, "instructions": instructions}
        )


class AsyncResponses(_SharedResponses, AsyncKeyModel):
    needs_key = "openai"
    key_env_var = "OPENAI_API_KEY"
    default_max_tokens = None

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
        reasoning=False,
        verbosity=False,
        image_detail_original=False,
        supports_schema=False,
        supports_tools=False,
        allows_system_prompt=True,
    ):
        super().__init__(
            model_id,
            key=key,
            model_name=model_name,
            api_base=api_base,
            api_type=api_type,
            api_version=api_version,
            api_engine=api_engine,
            headers=headers,
            can_stream=can_stream,
            vision=vision,
            audio=audio,
            reasoning=reasoning,
            verbosity=verbosity,
            image_detail_original=image_detail_original,
            supports_schema=supports_schema,
            supports_tools=supports_tools,
            allows_system_prompt=allows_system_prompt,
        )
        self._reasoning = reasoning
        self._verbosity = verbosity
        self._image_detail_original = image_detail_original
        self.Options = build_options_class(
            reasoning=reasoning,
            verbosity=verbosity,
            image_detail_original=image_detail_original,
            chat_completions=True,
        )

    async def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: AsyncResponse,
        conversation: Optional[AsyncConversation] = None,
        key: Optional[str] = None,
    ) -> AsyncGenerator[Union[str, StreamEvent], None]:
        if getattr(prompt.options, "chat_completions", None):
            chat = AsyncChat(**self._delegate_chat_kwargs())
            async for event in chat.execute(
                prompt, stream, response, conversation, key
            ):
                yield event
            return

        if prompt.system and not self.allows_system_prompt:
            raise NotImplementedError("Model does not support system prompts")

        image_detail = getattr(prompt.options, "image_detail", None)
        if image_detail is not None:
            image_detail = image_detail.value
        input_items, instructions = self._build_responses_input(
            prompt, image_detail=image_detail
        )
        kwargs = self._build_responses_kwargs(prompt, stream)
        if instructions is not None:
            kwargs["instructions"] = instructions
        kwargs["store"] = False
        if self._reasoning:
            kwargs["include"] = ["reasoning.encrypted_content"]

        client = self.get_client(key, async_=True)
        usage = None
        had_reasoning = False
        if stream:
            stream_obj = await client.responses.create(
                model=self.model_name or self.model_id,
                input=input_items,
                stream=True,
                **kwargs,
            )
            tool_call_meta: Dict[str, Dict[str, str]] = {}
            final_response_dict: Optional[Dict[str, Any]] = None
            reasoning_items_with_streamed_text = set()
            async for event in stream_obj:
                etype = getattr(event, "type", None)
                if etype == "response.output_item.added":
                    item = event.item
                    if item.type == "function_call":
                        tool_call_meta[item.id] = {
                            "id": item.id,
                            "call_id": item.call_id,
                            "name": item.name,
                        }
                        yield StreamEvent(
                            type="tool_call_name",
                            chunk=item.name or "",
                            tool_call_id=item.call_id,
                        )
                elif etype == "response.output_text.delta":
                    yield StreamEvent(type="text", chunk=event.delta or "")
                elif etype == "response.function_call_arguments.delta":
                    item_id = getattr(event, "item_id", None)
                    meta = tool_call_meta.get(item_id) if item_id else None
                    call_id = meta["call_id"] if meta else None
                    yield StreamEvent(
                        type="tool_call_args",
                        chunk=event.delta or "",
                        tool_call_id=call_id,
                    )
                elif etype in (
                    "response.reasoning_summary_text.delta",
                    "response.reasoning_text.delta",
                ):
                    item_id = getattr(event, "item_id", None)
                    if item_id:
                        reasoning_items_with_streamed_text.add(item_id)
                    yield StreamEvent(type="reasoning", chunk=event.delta or "")
                elif etype in (
                    "response.reasoning_summary_text.done",
                    "response.reasoning_text.done",
                ):
                    item_id = getattr(event, "item_id", None)
                    if item_id not in reasoning_items_with_streamed_text:
                        text = getattr(event, "text", None) or ""
                        if text:
                            if item_id:
                                reasoning_items_with_streamed_text.add(item_id)
                            yield StreamEvent(type="reasoning", chunk=text)
                elif etype == "response.output_item.done":
                    item = event.item
                    if item.type == "reasoning":
                        had_reasoning = True
                        item_id = getattr(item, "id", None)
                        yield self._reasoning_event(
                            item,
                            include_text=(
                                item_id not in reasoning_items_with_streamed_text
                            ),
                        )
                    elif item.type == "function_call":
                        try:
                            args = json.loads(item.arguments) if item.arguments else {}
                        except json.JSONDecodeError:
                            args = {"_raw": item.arguments}
                        response.add_tool_call(
                            llm.ToolCall(
                                tool_call_id=item.call_id,
                                name=item.name,
                                arguments=args,
                            )
                        )
                elif etype == "response.completed":
                    final_response_dict = event.response.model_dump()
                    if final_response_dict.get("usage"):
                        usage = final_response_dict["usage"]
            if final_response_dict is not None:
                response.response_json = remove_dict_none_values(final_response_dict)
        else:
            completion = await client.responses.create(
                model=self.model_name or self.model_id,
                input=input_items,
                stream=False,
                **kwargs,
            )
            dumped = completion.model_dump()
            response.response_json = remove_dict_none_values(dumped)
            usage = dumped.get("usage")
            for item in completion.output:
                if item.type == "reasoning":
                    had_reasoning = True
                    yield self._reasoning_event(item)
                elif item.type == "function_call":
                    try:
                        args = json.loads(item.arguments) if item.arguments else {}
                    except json.JSONDecodeError:
                        args = {"_raw": item.arguments}
                    response.add_tool_call(
                        llm.ToolCall(
                            tool_call_id=item.call_id,
                            name=item.name,
                            arguments=args,
                        )
                    )
                    yield StreamEvent(
                        type="tool_call_name",
                        chunk=item.name or "",
                        tool_call_id=item.call_id,
                    )
                    yield StreamEvent(
                        type="tool_call_args",
                        chunk=item.arguments or "",
                        tool_call_id=item.call_id,
                    )
                elif item.type == "message":
                    for content in item.content or []:
                        ctype = getattr(content, "type", None)
                        if ctype == "output_text" and content.text:
                            yield StreamEvent(type="text", chunk=content.text)

        self._set_usage_responses(response, usage)
        if (
            not had_reasoning
            and usage
            and ((usage.get("output_tokens_details") or {}).get("reasoning_tokens"))
        ):
            yield StreamEvent(type="reasoning", chunk="", redacted=True)
        response._prompt_json = redact_data(
            {"input": input_items, "instructions": instructions}
        )


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

    def __str__(self) -> str:
        return "OpenAI Completion: {}".format(self.model_id)

    def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: Response,
        conversation: Optional[Conversation] = None,
        key: Optional[str] = None,
    ) -> Iterator[Union[str, StreamEvent]]:
        if prompt.system:
            raise NotImplementedError(
                "System prompts are not supported for OpenAI completion models"
            )
        messages = []
        if conversation is not None:
            for prev_response in conversation.responses:
                messages.append(prev_response.prompt.prompt)
                messages.append(cast(Response, prev_response).text())
        messages.append(prompt.prompt)
        kwargs = self.build_kwargs(prompt, stream)
        client = self.get_client(key)
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
            usage = item.usage.model_dump()
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
    if chunks:
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
