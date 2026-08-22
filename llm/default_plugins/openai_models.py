import datetime
import json
import os
import sys
from collections.abc import AsyncGenerator, Iterable, Iterator
from enum import Enum
from typing import Any, ClassVar, Literal

import click
import httpx2
import openai
import sqlite_utils
import yaml
from pydantic import Field, ValidationError, create_model, field_validator

import llm
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
from llm.models import _partition_tools
from llm.parts import StreamEvent
from llm.utils import (
    dicts_to_table_string,
    logging_client,
    remove_dict_none_values,
    simplify_usage_dict,
)


@hookimpl
def register_models(register):
    # GPT-4o
    register(
        Chat(
            "gpt-4o",
            vision=True,
            service_tier=True,
            supports_schema=True,
            supports_tools=True,
        ),
        AsyncChat(
            "gpt-4o",
            vision=True,
            service_tier=True,
            supports_schema=True,
            supports_tools=True,
        ),
        aliases=("4o",),
    )
    register(
        Chat(
            "gpt-4o-mini",
            vision=True,
            service_tier=True,
            supports_schema=True,
            supports_tools=True,
        ),
        AsyncChat(
            "gpt-4o-mini",
            vision=True,
            service_tier=True,
            supports_schema=True,
            supports_tools=True,
        ),
        aliases=("4o-mini",),
    )
    # GPT-4.1
    for model_id in ("gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano"):
        register(
            Chat(
                model_id,
                vision=True,
                service_tier=True,
                supports_schema=True,
                supports_tools=True,
            ),
            AsyncChat(
                model_id,
                vision=True,
                service_tier=True,
                supports_schema=True,
                supports_tools=True,
            ),
            aliases=(model_id.replace("gpt-", ""),),
        )
    # 3.5 and 4
    register(
        Chat("gpt-3.5-turbo", service_tier=True),
        AsyncChat("gpt-3.5-turbo", service_tier=True),
        aliases=("3.5", "chatgpt"),
    )
    register(
        Chat("gpt-3.5-turbo-16k", service_tier=True),
        AsyncChat("gpt-3.5-turbo-16k", service_tier=True),
        aliases=("chatgpt-16k", "3.5-16k"),
    )
    register(
        Chat("gpt-4", service_tier=True),
        AsyncChat("gpt-4", service_tier=True),
        aliases=("4", "gpt4"),
    )
    # GPT-4 Turbo models
    register(
        Chat("gpt-4-turbo-2024-04-09", service_tier=True),
        AsyncChat("gpt-4-turbo-2024-04-09", service_tier=True),
    )
    register(
        Chat("gpt-4-turbo", service_tier=True),
        AsyncChat("gpt-4-turbo", service_tier=True),
        aliases=("gpt-4-turbo-preview", "4-turbo", "4t"),
    )
    # o1
    for model_id in ("o1", "o1-2024-12-17"):
        register(
            Responses(
                model_id,
                vision=True,
                can_stream=False,
                reasoning=True,
                service_tier=True,
                supports_schema=True,
                supports_tools=True,
            ),
            AsyncResponses(
                model_id,
                vision=True,
                can_stream=False,
                reasoning=True,
                service_tier=True,
                supports_schema=True,
                supports_tools=True,
            ),
        )

    register(
        Responses(
            "o3-mini",
            reasoning=True,
            service_tier=True,
            supports_schema=True,
            supports_tools=True,
        ),
        AsyncResponses(
            "o3-mini",
            reasoning=True,
            service_tier=True,
            supports_schema=True,
            supports_tools=True,
        ),
    )
    register(
        Responses(
            "o3",
            vision=True,
            reasoning=True,
            service_tier=True,
            supports_schema=True,
            supports_tools=True,
        ),
        AsyncResponses(
            "o3",
            vision=True,
            reasoning=True,
            service_tier=True,
            supports_schema=True,
            supports_tools=True,
        ),
    )
    register(
        Responses(
            "o4-mini",
            vision=True,
            reasoning=True,
            service_tier=True,
            supports_schema=True,
            supports_tools=True,
        ),
        AsyncResponses(
            "o4-mini",
            vision=True,
            reasoning=True,
            service_tier=True,
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
                service_tier=True,
                supports_schema=True,
                supports_tools=True,
            ),
            AsyncResponses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                service_tier=True,
                supports_schema=True,
                supports_tools=True,
            ),
        )
    # GPT-5.1
    register(
        Responses(
            "gpt-5.1",
            vision=True,
            reasoning=True,
            verbosity=True,
            service_tier=True,
            supports_schema=True,
            supports_tools=True,
        ),
        AsyncResponses(
            "gpt-5.1",
            vision=True,
            reasoning=True,
            verbosity=True,
            service_tier=True,
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
                service_tier=True,
                supports_schema=True,
                supports_tools=True,
            ),
            AsyncResponses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                service_tier=True,
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
                service_tier=True,
                supports_schema=True,
                supports_tools=True,
            ),
            AsyncResponses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                image_detail_original=True,
                service_tier=True,
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
                service_tier=True,
                supports_schema=True,
                supports_tools=True,
            ),
            AsyncResponses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                image_detail_original=True,
                service_tier=True,
                supports_schema=True,
                supports_tools=True,
            ),
        )

    # GPT-5.6
    for model_id in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
        register(
            Responses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                image_detail_original=True,
                service_tier=True,
                supports_schema=True,
                supports_tools=True,
            ),
            AsyncResponses(
                model_id,
                vision=True,
                reasoning=True,
                verbosity=True,
                image_detail_original=True,
                service_tier=True,
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
        if extra_model.get("service_tier") is True:
            kwargs["service_tier"] = True
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

    def embed_batch(
        self, items: Iterable[str | bytes], *, key: str | None = None
    ) -> Iterator[list[float]]:
        kwargs = {
            "input": items,
            "model": self.openai_model_id,
        }
        if self.dimensions:
            kwargs["dimensions"] = self.dimensions
        client = openai.OpenAI(api_key=key)
        results = client.embeddings.create(**kwargs).data
        return ([float(r) for r in result.embedding] for result in results)


@hookimpl
def register_commands(cli):
    from llm.cli import (
        AttachmentType,
        attachment_types_callback,
        schema_option,
        tool_options,
    )

    @cli.group(name="openai")
    def openai_():
        "Commands for working with OpenAI and OpenAI-compatible APIs"

    @openai_.command()
    @click.argument("url")
    @click.argument("prompt", required=False)
    @click.option(
        "model_id",
        "-m",
        "--model",
        help="Model ID (required unless --models or provided by template)",
    )
    @click.option("-s", "--system", help="System prompt to use")
    @click.option("-t", "--template", help="Template to use")
    @click.option(
        "param",
        "-p",
        "--param",
        multiple=True,
        type=(str, str),
        help="Parameters for template",
    )
    @click.option(
        "options",
        "-o",
        "--option",
        type=(str, str),
        multiple=True,
        help="key/value options for the model",
    )
    @schema_option
    @click.option(
        "--schema-multi",
        help="JSON schema to use for multiple results",
    )
    @click.option(
        "attachments",
        "-a",
        "--attachment",
        type=AttachmentType(),
        multiple=True,
        help="Attachment path or URL or -",
    )
    @click.option(
        "attachment_types",
        "--at",
        "--attachment-type",
        type=(str, str),
        multiple=True,
        callback=attachment_types_callback,
        help="\b\nAttachment with explicit mimetype,\n--at image.jpg image/jpeg",
    )
    @tool_options
    @click.option("--key", help="API key or stored key alias to send")
    @click.option(
        "headers",
        "-H",
        "--header",
        type=(str, str),
        multiple=True,
        help="Additional HTTP header",
    )
    @click.option(
        "use_responses",
        "--responses",
        is_flag=True,
        help="Use the Responses API instead of Chat Completions",
    )
    @click.option(
        "force_chat",
        "--chat",
        is_flag=True,
        help="Start an interactive chat",
    )
    @click.option(
        "list_models",
        "--models",
        is_flag=True,
        help="List model IDs from the endpoint and exit",
    )
    @click.option("--no-stream", is_flag=True, help="Do not stream output")
    @click.option("-R", "--hide-reasoning", is_flag=True, help="Hide reasoning output")
    def endpoint(
        url,
        prompt,
        model_id,
        system,
        template,
        param,
        options,
        schema_input,
        schema_multi,
        attachments,
        attachment_types,
        tools,
        python_tools,
        tools_debug,
        tools_approve,
        chain_limit,
        key,
        headers,
        use_responses,
        force_chat,
        list_models,
        no_stream,
        hide_reasoning,
    ):
        """
        Run against an OpenAI-compatible endpoint without logging.

        PROMPT or stdin is executed once. If neither is provided, wait for
        input on stdin. Use --chat to start an interactive chat. Templates run
        once by default; use --chat to apply one interactively. Use --models
        to list the available model IDs without running a prompt.
        """
        from llm.cli import (
            AttachmentError,
            LoadTemplateError,
            _apply_template,
            _merge_template_attachments,
            _merge_template_options,
            _merge_template_tools,
            _run_chat,
            _tool_chain_kwargs,
            display_stream_events,
            load_template,
            logs_db_path,
            migrate,
            multi_schema,
            render_errors,
            resolve_schema_input,
        )

        if list_models and prompt is not None:
            raise click.ClickException("--models cannot be used with a prompt")
        if list_models and template:
            raise click.ClickException("--models cannot be used with --template")
        if list_models and (tools or python_tools):
            raise click.ClickException("--models cannot be used with tools")
        if list_models and (schema_input or schema_multi):
            raise click.ClickException("--models cannot be used with schemas")
        if force_chat and prompt is not None:
            raise click.ClickException("--chat cannot be used with a prompt")

        if schema_multi:
            schema_input = schema_multi
        schema = None
        if schema_input:
            # Never create logs.db for this unlogged command. An existing
            # database can resolve stored schema IDs; all other schema input
            # is resolved using a temporary in-memory database.
            log_path = logs_db_path()
            if log_path.exists():
                schema_db = sqlite_utils.Database(log_path)
            else:
                schema_db = sqlite_utils.Database(memory=True)
            migrate(schema_db)
            schema = resolve_schema_input(schema_db, schema_input, load_template)
            if schema_multi:
                schema = multi_schema(schema)

        template_obj = None
        params = dict(param)
        if template:
            try:
                template_obj = load_template(template)
                attachments, attachment_types = _merge_template_attachments(
                    template_obj, attachments, attachment_types
                )
            except (AttachmentError, LoadTemplateError) as ex:
                raise click.ClickException(str(ex))
            if not model_id and template_obj.model:
                model_id = template_obj.model
            if template_obj.schema_object and not schema:
                schema = template_obj.schema_object
            if template_obj.options:
                options = _merge_template_options(template_obj, options)
            tools, python_tools = _merge_template_tools(
                template_obj, tools, python_tools
            )

        if not list_models and not model_id:
            raise click.ClickException(
                "--model is required unless --models or a template model is used"
            )

        model_class = Responses if use_responses else Chat
        model_kwargs = {
            "model_id": model_id or "",
            "model_name": model_id or "",
            "api_base": url,
            "headers": dict(headers),
            "vision": True,
            "audio": not use_responses,
            # Optimistically expose capabilities that have no effect until
            # the user explicitly exercises them.
            "reasoning": True,
            "verbosity": True,
            "image_detail_original": True,
            "supports_schema": True,
            "supports_tools": True,
        }
        if use_responses:
            model_kwargs["reasoning_summary"] = False
        model = model_class(**model_kwargs)

        # A configured api_base never receives the user's default OpenAI key.
        # Match that safety property here: only send credentials when --key
        # was explicitly provided for this invocation.
        if not key:
            model.needs_key = None

        try:
            validated_options = {
                option_name: option_value
                for option_name, option_value in model.Options(**dict(options))
                if option_value is not None
            }
        except ValidationError as ex:
            raise click.ClickException(render_errors(ex.errors()))

        prompt_kwargs = {
            "options": validated_options,
            "schema": schema,
            "stream": not no_stream,
            "hide_reasoning": hide_reasoning,
        }
        if key:
            prompt_kwargs["key"] = key

        tool_kwargs = _tool_chain_kwargs(
            tools,
            python_tools,
            tools_debug,
            tools_approve,
            chain_limit,
            model=model,
        )
        resolved_attachments = [*attachments, *attachment_types]
        try:
            if list_models:
                available_models = model.get_client(key).models.list()
                error = getattr(available_models, "error", None)
                if error:
                    if isinstance(error, dict):
                        error = error.get("message") or json.dumps(error)
                    raise click.ClickException(str(error))
                for available_model in available_models:
                    click.echo(available_model.id)
                return

            if force_chat:
                conversation = model.conversation()

                def transform_chat_prompt(chat_prompt):
                    nonlocal system
                    if template_obj:
                        chat_prompt, system = _apply_template(
                            template_obj, chat_prompt, params, system
                        )
                    return chat_prompt

                def execute_chat_prompt(chat_prompt, _fragments, turn_attachments):
                    nonlocal system
                    prompt_method = (
                        conversation.chain if tool_kwargs else conversation.prompt
                    )
                    response = prompt_method(
                        chat_prompt,
                        system=system,
                        attachments=turn_attachments,
                        **prompt_kwargs,
                        **tool_kwargs,
                    )
                    system = None
                    return response

                _run_chat(
                    f"{model_id} at {url}",
                    execute_chat_prompt,
                    initial_attachments=resolved_attachments,
                    transform_prompt=transform_chat_prompt,
                    show_reasoning=not hide_reasoning,
                )
                return

            if not sys.stdin.isatty():
                stdin_prompt = sys.stdin.read()
                if stdin_prompt:
                    prompt = " ".join(
                        part for part in (stdin_prompt, prompt) if part is not None
                    )
            elif (
                prompt is None
                and not resolved_attachments
                and not schema
                and (template_obj is None or "input" in template_obj.vars())
            ):
                # Match `llm prompt`: wait for stdin until EOF instead of
                # implicitly starting an interactive chat.
                prompt = sys.stdin.read()
            if template_obj:
                prompt, system = _apply_template(template_obj, prompt, params, system)
            if prompt is None and not (resolved_attachments or schema):
                raise click.ClickException(
                    "A prompt is required when stdin is not interactive"
                )
            if tool_kwargs:
                response = model.conversation().chain(
                    prompt,
                    system=system,
                    attachments=resolved_attachments,
                    **prompt_kwargs,
                    **tool_kwargs,
                )
            else:
                response = model.prompt(
                    prompt,
                    system=system,
                    attachments=resolved_attachments,
                    **prompt_kwargs,
                )
            display_stream_events(
                response.stream_events(),
                show_reasoning=not hide_reasoning,
            )
            click.echo()
        except (click.Abort, click.ClickException):
            raise
        except (ValueError, NotImplementedError) as ex:
            raise click.ClickException(str(ex))
        except Exception as ex:
            if getattr(sys, "_called_from_test", False) or os.environ.get(
                "LLM_RAISE_ERRORS"
            ):
                raise
            raise click.ClickException(str(ex))

    @openai_.command()
    @click.option("json_", "--json", is_flag=True, help="Output as JSON")
    @click.option("--key", help="OpenAI API key")
    def models(json_, key):
        "List models available to you from the OpenAI API"
        from llm import get_key

        api_key = get_key(key, "openai", "OPENAI_API_KEY")
        response = httpx2.get(
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
            done = dicts_to_table_string(["id", "owned_by", "created"], to_print)
            print("\n".join(done))


class SharedOptions(llm.Options):
    temperature: float | None = Field(
        description=(
            "What sampling temperature to use, between 0 and 2. Higher values like "
            "0.8 will make the output more random, while lower values like 0.2 will "
            "make it more focused and deterministic."
        ),
        ge=0,
        le=2,
        default=None,
    )
    max_tokens: int | None = Field(
        description="Maximum number of tokens to generate.", default=None
    )
    top_p: float | None = Field(
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
    frequency_penalty: float | None = Field(
        description=(
            "Number between -2.0 and 2.0. Positive values penalize new tokens based "
            "on their existing frequency in the text so far, decreasing the model's "
            "likelihood to repeat the same line verbatim."
        ),
        ge=-2,
        le=2,
        default=None,
    )
    presence_penalty: float | None = Field(
        description=(
            "Number between -2.0 and 2.0. Positive values penalize new tokens based "
            "on whether they appear in the text so far, increasing the model's "
            "likelihood to talk about new topics."
        ),
        ge=-2,
        le=2,
        default=None,
    )
    stop: str | None = Field(
        description=("A string where the API will stop generating further tokens."),
        default=None,
    )
    logit_bias: dict | str | None = Field(
        description=(
            "Modify the likelihood of specified tokens appearing in the completion. "
            'Pass a JSON string like \'{"1712":-100, "892":-100, "1489":-100}\''
        ),
        default=None,
    )
    seed: int | None = Field(
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
    max = "max"


class ReasoningSummaryEnum(str, Enum):
    auto = "auto"
    concise = "concise"
    detailed = "detailed"


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
    reasoning_summary=False,
    verbosity=False,
    image_detail_original=False,
    chat_completions=False,
    service_tier=False,
):
    fields = {
        "json_object": (
            bool | None,
            Field(
                description="Output a valid JSON object {...}. Prompt must mention JSON.",
                default=None,
            ),
        )
    }
    if chat_completions:
        fields["chat_completions"] = (
            bool | None,
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
        image_detail_enum | None,
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
            ReasoningEffortEnum | None,
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
    if reasoning_summary:
        reasoning_summary_values = enum_values_sentence(ReasoningSummaryEnum)
        fields["reasoning_summary"] = (
            ReasoningSummaryEnum | None,
            Field(
                description=(
                    "Requests a summary of the model's reasoning. Supported values "
                    f"are {reasoning_summary_values}."
                ),
                default=None,
            ),
        )
    if verbosity:
        fields["verbosity"] = (
            VerbosityEnum | None,
            Field(
                description=(
                    "Controls how verbose the model's response should be. Supported "
                    "values are low, medium, and high."
                ),
                default=None,
            ),
        )
    if service_tier:
        fields["service_tier"] = (
            str | None,
            Field(
                description=(
                    "The processing tier to use for this request - for example "
                    "'fast' for Fast mode (faster responses at a higher price) "
                    "or 'flex' for slower, cheaper processing on models that "
                    "support those tiers."
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
    # NEVER remove or change an existing entry - only ever append new
    # ones.
    json_replacements: ClassVar[dict] = {
        "completion_tokens_details_0": {
            "accepted_prediction_tokens": 0,
            "audio_tokens": 0,
            "reasoning_tokens": 0,
            "rejected_prediction_tokens": 0,
        },
        "prompt_tokens_details_0": {
            "audio_tokens": 0,
            "cached_tokens": 0,
        },
    }

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
        service_tier=False,
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

        if reasoning or verbosity or image_detail_original or service_tier:
            self.Options = build_options_class(
                reasoning=reasoning,
                verbosity=verbosity,
                image_detail_original=image_detail_original,
                service_tier=service_tier,
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
        return f"OpenAI Chat: {self.model_id}"

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
        messages: list[dict[str, Any]] = []
        if image_detail is not None:
            image_detail = image_detail.value
        current_system: str | None = None
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
        # Responses models reuse their Options object when explicitly routed
        # through the Chat Completions compatibility path.
        kwargs.pop("reasoning_summary", None)
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
        conversation: Conversation | None = None,
        key: str | None = None,
    ) -> Iterator[str | StreamEvent]:
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
                            arguments=json.loads(value.function.arguments or "{}"),
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
                        arguments=json.loads(tool_call.function.arguments or "{}"),
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
        conversation: AsyncConversation | None = None,
        key: str | None = None,
    ) -> AsyncGenerator[str | StreamEvent, None]:
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
                            arguments=json.loads(value.function.arguments or "{}"),
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
                        arguments=json.loads(tool_call.function.arguments or "{}"),
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


class WebSearch(llm.ServerSideTool):
    """Search the web using OpenAI's hosted search tool.

    Configure domain filters, approximate location, result context, live web
    access and image search through constructor arguments. Set
    ``include_sources`` to retain every consulted URL or ``include_results``
    to retain raw results such as image search results.
    """

    name = "web_search"
    _search_context_sizes = frozenset({"low", "medium", "high"})
    _return_token_budgets = frozenset({"default", "unlimited"})
    _search_content_types = frozenset({"text", "image"})

    def __init__(
        self,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
        user_location: dict | None = None,
        search_context_size: Literal["low", "medium", "high"] | None = None,
        external_web_access: bool | None = None,
        return_token_budget: Literal["default", "unlimited"] | None = None,
        search_content_types: list[Literal["text", "image"]] | None = None,
        image_settings: dict | None = None,
        include_sources: bool = False,
        include_results: bool = False,
    ):
        super().__init__()
        self.allowed_domains = self._validate_domains(
            "allowed_domains", allowed_domains
        )
        self.blocked_domains = self._validate_domains(
            "blocked_domains", blocked_domains
        )
        if (
            search_context_size is not None
            and search_context_size not in self._search_context_sizes
        ):
            raise ValueError("search_context_size must be one of: low, medium or high")
        if external_web_access is not None and not isinstance(
            external_web_access, bool
        ):
            raise TypeError("external_web_access must be a boolean")
        if (
            return_token_budget is not None
            and return_token_budget not in self._return_token_budgets
        ):
            raise ValueError("return_token_budget must be default or unlimited")
        if search_content_types is not None:
            if not isinstance(search_content_types, list):
                raise TypeError("search_content_types must be a list")
            invalid_content_types = set(search_content_types).difference(
                self._search_content_types
            )
            if invalid_content_types:
                raise ValueError("search_content_types must contain text and/or image")
        if user_location is not None:
            if not isinstance(user_location, dict):
                raise TypeError("user_location must be a dictionary")
            user_location = dict(user_location)
            user_location.setdefault("type", "approximate")
            if user_location["type"] != "approximate":
                raise ValueError("user_location type must be approximate")
        if image_settings is not None:
            if not isinstance(image_settings, dict):
                raise TypeError("image_settings must be a dictionary")
            image_settings = dict(image_settings)
            max_results = image_settings.get("max_results")
            if max_results is not None and (
                isinstance(max_results, bool)
                or not isinstance(max_results, int)
                or max_results < 1
            ):
                raise ValueError(
                    "image_settings max_results must be a positive integer"
                )
            caption = image_settings.get("caption")
            if caption is not None and not isinstance(caption, bool):
                raise TypeError("image_settings caption must be a boolean")
        if not isinstance(include_sources, bool):
            raise TypeError("include_sources must be a boolean")
        if not isinstance(include_results, bool):
            raise TypeError("include_results must be a boolean")
        self.user_location = user_location
        self.search_context_size = search_context_size
        self.external_web_access = external_web_access
        self.return_token_budget = return_token_budget
        self.search_content_types = (
            list(search_content_types) if search_content_types is not None else None
        )
        self.image_settings = image_settings
        self.include_sources = include_sources
        self.include_results = include_results

    @staticmethod
    def _validate_domains(name, domains):
        if domains is None:
            return None
        if not isinstance(domains, list):
            raise TypeError(f"{name} must be a list")
        if len(domains) > 100:
            raise ValueError(f"{name} cannot contain more than 100 domains")
        for domain in domains:
            if not isinstance(domain, str) or not domain:
                raise TypeError(f"{name} entries must be non-empty strings")
            if domain.lower().startswith(("http://", "https://")):
                raise ValueError(f"{name} entries must omit the URL scheme")
        return list(domains)

    def tool_spec(self, model):
        spec = {"type": "web_search"}
        if self.allowed_domains is not None or self.blocked_domains is not None:
            filters = {}
            if self.allowed_domains is not None:
                filters["allowed_domains"] = list(self.allowed_domains)
            if self.blocked_domains is not None:
                filters["blocked_domains"] = list(self.blocked_domains)
            spec["filters"] = filters
        for key in (
            "user_location",
            "search_context_size",
            "external_web_access",
            "return_token_budget",
            "search_content_types",
            "image_settings",
        ):
            value = getattr(self, key)
            if value is not None:
                if isinstance(value, dict):
                    value = dict(value)
                elif isinstance(value, list):
                    value = list(value)
                spec[key] = value
        return spec

    def prepare_request(self, model, kwargs):
        if not self.include_sources and not self.include_results:
            return
        include = kwargs.setdefault("include", [])
        if self.include_sources and "web_search_call.action.sources" not in include:
            include.append("web_search_call.action.sources")
        if self.include_results and "web_search_call.results" not in include:
            include.append("web_search_call.results")


class CodeInterpreter(llm.ServerSideTool):
    """Run Python in an OpenAI-managed container.

    With no ``container`` argument OpenAI creates or reuses an automatic
    container. ``memory_limit`` and ``file_ids`` configure that automatic
    container. Pass an existing ``cntr_`` ID as ``container`` to use it
    explicitly instead.
    """

    name = "code_interpreter"
    _memory_limits = frozenset({"1g", "4g", "16g", "64g"})

    def __init__(
        self,
        container: str | None = None,
        memory_limit: Literal["1g", "4g", "16g", "64g"] | None = None,
        file_ids: list[str] | None = None,
    ):
        super().__init__()
        if container is not None and not isinstance(container, str):
            raise TypeError("container must be a string container ID")
        if memory_limit is not None and memory_limit not in self._memory_limits:
            raise ValueError("memory_limit must be one of: 1g, 4g, 16g or 64g")
        if container is not None and (memory_limit is not None or file_ids is not None):
            raise ValueError(
                "container cannot be combined with memory_limit or file_ids"
            )
        self.container = container
        self.memory_limit = memory_limit
        self.file_ids = list(file_ids) if file_ids is not None else None

    def tool_spec(self, model):
        if self.container is not None:
            return {"type": "code_interpreter", "container": self.container}
        container = {"type": "auto"}
        if self.memory_limit is not None:
            container["memory_limit"] = self.memory_limit
        if self.file_ids is not None:
            container["file_ids"] = list(self.file_ids)
        return {"type": "code_interpreter", "container": container}

    def prepare_request(self, model, kwargs):
        include = kwargs.setdefault("include", [])
        if "code_interpreter_call.outputs" not in include:
            include.append("code_interpreter_call.outputs")


class _SharedResponses(_Shared):
    """Mixin that translates llm.Prompt into Responses API parameters."""

    @property
    def supported_server_side_tools(self):
        return (WebSearch, CodeInterpreter, llm.ServerSideTool)

    # Recurring boilerplate in Responses API payloads. Same contract as
    # _Shared.json_replacements, which this replaces for Responses
    # models: NEVER remove or change an existing entry - only ever
    # append new ones.
    json_replacements: ClassVar[dict] = {
        "tool_usage_0": {
            "image_gen": {
                "input_tokens": 0,
                "input_tokens_details": {
                    "image_tokens": 0,
                    "text_tokens": 0,
                },
                "output_tokens": 0,
                "output_tokens_details": {
                    "image_tokens": 0,
                    "text_tokens": 0,
                },
                "total_tokens": 0,
            },
            "web_search": {"num_requests": 0},
        },
        "input_tokens_details_0": {
            "cached_tokens": 0,
            "cache_write_tokens": 0,
        },
        "reasoning_settings_0": {
            "effort": "medium",
            "summary": "detailed",
            "context": "all_turns",
            "mode": "standard",
        },
        "reasoning_settings_1": {
            "effort": "medium",
            "summary": "detailed",
            "context": "current_turn",
            "mode": "standard",
        },
        # The default text block on non-schema replies
        "text_format_0": {"format": {"type": "text"}, "verbosity": "medium"},
        # The static envelope of a Responses payload
        "response_env_0": {
            "object": "response",
            "parallel_tool_calls": True,
            "temperature": 1.0,
            "tool_choice": "auto",
            "top_p": 1.0,
            "background": False,
            "service_tier": "default",
            "status": "completed",
            "top_logprobs": 0,
            "truncation": "disabled",
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
            "store": False,
            "tools": [],
        },
        "message_completed": {
            "role": "assistant",
            "status": "completed",
            "type": "message",
            "phase": "final_answer",
        },
    }

    def __str__(self) -> str:
        return f"OpenAI Responses: {self.model_id}"

    def _delegate_chat_kwargs(self):
        """Return constructor kwargs that mirror this Responses model so we
        can build a sibling Chat / AsyncChat instance for the
        ``-o chat_completions 1`` opt-out path."""
        return {
            "model_id": self.model_id,
            "key": self.key,
            "model_name": self.model_name,
            "api_base": self.api_base,
            "api_type": self.api_type,
            "api_version": self.api_version,
            "api_engine": self.api_engine,
            "headers": self.headers,
            "can_stream": self.can_stream,
            "vision": self.vision,
            "reasoning": self._reasoning,
            "verbosity": self._verbosity,
            "image_detail_original": self._image_detail_original,
            "service_tier": self._service_tier,
            "supports_schema": self.supports_schema,
            "supports_tools": self.supports_tools,
            "allows_system_prompt": self.allows_system_prompt,
        }

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

        items: list[dict[str, Any]] = []
        instructions: str | None = None

        for msg in prompt.messages:
            if msg.role == "system":
                text = "".join(p.text for p in msg.parts if isinstance(p, TextPart))
                if text:
                    instructions = text
                continue

            text_bits: list[str] = []
            attachment_items: list[dict[str, Any]] = []
            tool_call_items: list[dict[str, Any]] = []
            tool_result_items: list[dict[str, Any]] = []
            reasoning_items: list[dict[str, Any]] = []

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
                    if part.server_executed:
                        # Server-side tool calls (web_search,
                        # code_interpreter) ran inside OpenAI's
                        # infrastructure - they must not be replayed as
                        # client function_call items.
                        continue
                    tool_call_items.append(
                        {
                            "type": "function_call",
                            "call_id": part.tool_call_id,
                            "name": part.name,
                            "arguments": json.dumps(part.arguments),
                        }
                    )
                elif isinstance(part, ToolResultPart):
                    if part.server_executed:
                        continue
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
                        item: dict[str, Any] = {"type": "reasoning"}
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
                    content: list[dict[str, Any]] = []
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
        reasoning_summary = opts.pop("reasoning_summary", None)
        verbosity = opts.pop("verbosity", None)
        temperature = opts.pop("temperature", None)
        top_p = opts.pop("top_p", None)
        seed = opts.pop("seed", None)

        kwargs: dict[str, Any] = {}
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
                if reasoning_summary is not None:
                    reasoning["summary"] = reasoning_summary
                elif self._reasoning_summary:
                    reasoning["summary"] = "auto"
            if reasoning_effort:
                reasoning["effort"] = reasoning_effort
            if reasoning:
                kwargs["reasoning"] = reasoning

        text: dict[str, Any] = {}
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
            _partition_tools(self, prompt.tools)
            kwargs["tools"] = [
                (
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": tool.description or None,
                        "parameters": tool.input_schema,
                    }
                    if isinstance(tool, llm.Tool)
                    else tool.tool_spec(self)
                )
                for tool in prompt.tools
            ]

        # Pass anything we did not consume through verbatim - this lets
        # extras like ``parallel_tool_calls`` flow into the API.
        kwargs.update(opts)
        return kwargs

    def _finalize_responses_kwargs(self, prompt, stream, instructions=None):
        """Build complete request kwargs, then run server-tool hooks in order."""
        kwargs = self._build_responses_kwargs(prompt, stream)
        if instructions is not None:
            kwargs["instructions"] = instructions
        kwargs["store"] = False
        if self._reasoning and (
            self._reasoning_summary
            or getattr(prompt.options, "reasoning_summary", None)
            or getattr(prompt.options, "reasoning_effort", None)
        ):
            include = kwargs.setdefault("include", [])
            if "reasoning.encrypted_content" not in include:
                include.append("reasoning.encrypted_content")
        _, server_side_tools = _partition_tools(self, prompt.tools)
        for tool in server_side_tools:
            tool.prepare_request(self, kwargs)
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
        meta: dict[str, Any] = {}
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
            except Exception:  # noqa: BLE001
                meta["summary"] = list(summary)
        return StreamEvent(
            type="reasoning",
            chunk=text,
            redacted=include_text and not text,
            provider_metadata={"openai": meta} if meta else None,
        )

    def _reasoning_refresh_events(self, response_json, done_events):
        """Metadata-only reasoning events rebuilt from the final payload.

        While streaming, reasoning metadata is first harvested from the
        ``response.output_item.done`` event, but the ``response.completed``
        payload carries a *different* ciphertext of the same reasoning -
        OpenAI encrypts per event. Re-emitting the metadata from the
        final payload, aimed at the already-resolved part_index, makes
        the stored part and ``response_json`` agree on one blob (which
        also lets the log store condense the payload against the part).

        ``done_events`` maps reasoning item id to the StreamEvent
        yielded at ``output_item.done``; the framework has resolved
        ``part_index`` on it by the time the stream ends.
        """
        events = []
        for item in response_json.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "reasoning":
                continue
            prior = done_events.get(item.get("id"))
            if prior is None or prior.part_index is None:
                continue
            meta = {
                key: item[key]
                for key in ("id", "encrypted_content", "summary")
                if item.get(key)
            }
            if meta:
                events.append(
                    StreamEvent(
                        type="reasoning",
                        chunk="",
                        part_index=prior.part_index,
                        provider_metadata={"openai": meta},
                        message_index=prior.message_index,
                    )
                )
        return events

    def _server_tool_events(self, item, message_index):
        """StreamEvents for a server-side tool call output item
        (web_search_call / code_interpreter_call), or [] for other
        item types. The call and its result both carry
        ``server_executed=True`` so they are recorded in the message
        parts without entering the locally-executable tool call list.
        """
        item_type = getattr(item, "type", None)
        item_id = getattr(item, "id", None)
        events: list[StreamEvent] = []
        if item_type == "web_search_call":
            action = getattr(item, "action", None)
            if hasattr(action, "model_dump"):
                action = action.model_dump()
            events.append(
                StreamEvent(
                    type="tool_call_name",
                    chunk="web_search",
                    tool_call_id=item_id,
                    server_executed=True,
                    message_index=message_index,
                )
            )
            events.append(
                StreamEvent(
                    type="tool_call_args",
                    chunk=json.dumps(action or {}),
                    tool_call_id=item_id,
                    server_executed=True,
                    message_index=message_index,
                )
            )
            results = getattr(item, "results", None) or []
            results = [
                result.model_dump() if hasattr(result, "model_dump") else result
                for result in results
            ]
            events.append(
                StreamEvent(
                    type="tool_result",
                    chunk=(
                        json.dumps(results)
                        if results
                        else (getattr(item, "status", None) or "completed")
                    ),
                    tool_call_id=item_id,
                    server_executed=True,
                    tool_name="web_search",
                    message_index=message_index,
                )
            )
        elif item_type == "code_interpreter_call":
            code = getattr(item, "code", None) or ""
            events.append(
                StreamEvent(
                    type="tool_call_name",
                    chunk="code_interpreter",
                    tool_call_id=item_id,
                    server_executed=True,
                    message_index=message_index,
                )
            )
            events.append(
                StreamEvent(
                    type="tool_call_args",
                    chunk=json.dumps({"code": code}),
                    tool_call_id=item_id,
                    server_executed=True,
                    message_index=message_index,
                )
            )
            output_bits = []
            for output in getattr(item, "outputs", None) or []:
                if hasattr(output, "model_dump"):
                    output = output.model_dump()
                if isinstance(output, dict):
                    text = output.get("logs") or output.get("url")
                    if text:
                        output_bits.append(text)
            events.append(
                StreamEvent(
                    type="tool_result",
                    chunk="\n".join(output_bits)
                    or (getattr(item, "status", None) or "completed"),
                    tool_call_id=item_id,
                    server_executed=True,
                    tool_name="code_interpreter",
                    message_index=message_index,
                )
            )
        return events

    def _refresh_server_tool_events(self, output, done_events):
        """Replace streamed server-tool payloads with their final values.

        OpenAI can return incomplete sources, results or outputs on a
        ``response.output_item.done`` event and then provide the complete
        item on ``response.completed``. The response stores yielded
        StreamEvent objects by reference, so updating their chunks here
        corrects the assembled Parts without emitting duplicate events.
        """
        for item in output or []:
            item_id = getattr(item, "id", None)
            prior_events = done_events.get(item_id)
            if not prior_events:
                continue
            final_events = {
                event.type: event
                for event in self._server_tool_events(
                    item, prior_events[0].message_index
                )
            }
            for prior_event in prior_events:
                final_event = final_events.get(prior_event.type)
                if final_event is not None:
                    prior_event.chunk = final_event.chunk

    def _non_streaming_output_events(self, output, response):
        """Translate a non-streaming Responses ``output`` item list into
        StreamEvents. Returns ``(events, had_reasoning)``.

        Each ``message`` item after the first starts a new
        ``message_index``, so server-side tool execution that
        interleaves multiple message items assembles into multiple
        assistant Messages. Items between two message items (tool
        calls, reasoning) group with the preceding message.
        """
        events: list[StreamEvent] = []
        had_reasoning = False
        message_index = 0
        seen_message = False
        for item in output:
            if item.type == "message" and seen_message:
                message_index += 1
            if item.type == "reasoning":
                had_reasoning = True
                event = self._reasoning_event(item)
                event.message_index = message_index
                events.append(event)
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
                events.append(
                    StreamEvent(
                        type="tool_call_name",
                        chunk=item.name or "",
                        tool_call_id=item.call_id,
                        message_index=message_index,
                    )
                )
                events.append(
                    StreamEvent(
                        type="tool_call_args",
                        chunk=item.arguments or "",
                        tool_call_id=item.call_id,
                        message_index=message_index,
                    )
                )
            elif item.type == "message":
                seen_message = True
                for content in item.content or []:
                    ctype = getattr(content, "type", None)
                    if ctype == "output_text" and content.text:
                        events.append(
                            StreamEvent(
                                type="text",
                                chunk=content.text,
                                message_index=message_index,
                            )
                        )
            else:
                events.extend(self._server_tool_events(item, message_index))
        return events, had_reasoning


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
        service_tier=False,
        supports_schema=False,
        supports_tools=False,
        allows_system_prompt=True,
        reasoning_summary=True,
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
            service_tier=service_tier,
            supports_schema=supports_schema,
            supports_tools=supports_tools,
            allows_system_prompt=allows_system_prompt,
        )
        self._reasoning = reasoning
        self._reasoning_summary = reasoning_summary
        self._verbosity = verbosity
        self._image_detail_original = image_detail_original
        self._service_tier = service_tier
        # Override the Options class so that ``-o chat_completions 1`` is
        # always available on Responses-routed models.
        self.Options = build_options_class(
            reasoning=reasoning,
            reasoning_summary=reasoning,
            verbosity=verbosity,
            image_detail_original=image_detail_original,
            chat_completions=True,
            service_tier=service_tier,
        )

    def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: Response,
        conversation: Conversation | None = None,
        key: str | None = None,
    ) -> Iterator[str | StreamEvent]:
        if getattr(prompt.options, "chat_completions", None):
            chat = Chat(**self._delegate_chat_kwargs())
            _partition_tools(chat, prompt.tools)
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
        kwargs = self._finalize_responses_kwargs(prompt, stream, instructions)

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
            tool_call_meta: dict[str, dict[str, str]] = {}
            final_response_dict: dict[str, Any] | None = None
            reasoning_items_with_streamed_text = set()
            reasoning_done_events: dict[str, StreamEvent] = {}
            server_tool_done_events: dict[str, list[StreamEvent]] = {}
            message_index = 0
            seen_message = False
            for event in stream_obj:
                etype = getattr(event, "type", None)
                if etype == "response.output_item.added":
                    item = event.item
                    if item.type == "message":
                        if seen_message:
                            message_index += 1
                        seen_message = True
                    elif item.type == "function_call":
                        tool_call_meta[item.id] = {
                            "id": item.id,
                            "call_id": item.call_id,
                            "name": item.name,
                        }
                        yield StreamEvent(
                            type="tool_call_name",
                            chunk=item.name or "",
                            tool_call_id=item.call_id,
                            message_index=message_index,
                        )
                elif etype == "response.output_text.delta":
                    yield StreamEvent(
                        type="text",
                        chunk=event.delta or "",
                        message_index=message_index,
                    )
                elif etype == "response.function_call_arguments.delta":
                    item_id = getattr(event, "item_id", None)
                    meta = tool_call_meta.get(item_id) if item_id else None
                    call_id = meta["call_id"] if meta else None
                    yield StreamEvent(
                        type="tool_call_args",
                        chunk=event.delta or "",
                        tool_call_id=call_id,
                        message_index=message_index,
                    )
                elif etype in (
                    "response.reasoning_summary_text.delta",
                    "response.reasoning_text.delta",
                ):
                    item_id = getattr(event, "item_id", None)
                    if item_id:
                        reasoning_items_with_streamed_text.add(item_id)
                    yield StreamEvent(
                        type="reasoning",
                        chunk=event.delta or "",
                        message_index=message_index,
                    )
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
                            yield StreamEvent(
                                type="reasoning",
                                chunk=text,
                                message_index=message_index,
                            )
                elif etype == "response.output_item.done":
                    item = event.item
                    if item.type == "reasoning":
                        had_reasoning = True
                        item_id = getattr(item, "id", None)
                        reasoning_event = self._reasoning_event(
                            item,
                            include_text=(
                                item_id not in reasoning_items_with_streamed_text
                            ),
                        )
                        reasoning_event.message_index = message_index
                        if item_id:
                            # Retained so the refresh after
                            # response.completed can target the part
                            # this event resolved to.
                            reasoning_done_events[item_id] = reasoning_event
                        yield reasoning_event
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
                    else:
                        server_events = self._server_tool_events(item, message_index)
                        item_id = getattr(item, "id", None)
                        if item_id and server_events:
                            server_tool_done_events[item_id] = server_events
                        yield from server_events
                elif etype == "response.completed":
                    self._refresh_server_tool_events(
                        event.response.output, server_tool_done_events
                    )
                    final_response_dict = event.response.model_dump(warnings=False)
                    if final_response_dict.get("usage"):
                        usage = final_response_dict["usage"]
            if final_response_dict is not None:
                response.response_json = remove_dict_none_values(final_response_dict)
                yield from self._reasoning_refresh_events(
                    response.response_json, reasoning_done_events
                )
        else:
            completion = client.responses.create(
                model=self.model_name or self.model_id,
                input=input_items,
                stream=False,
                **kwargs,
            )
            dumped = completion.model_dump(warnings=False)
            response.response_json = remove_dict_none_values(dumped)
            usage = dumped.get("usage")
            events, had_reasoning = self._non_streaming_output_events(
                completion.output, response
            )
            yield from events

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
        service_tier=False,
        supports_schema=False,
        supports_tools=False,
        allows_system_prompt=True,
        reasoning_summary=True,
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
            service_tier=service_tier,
            supports_schema=supports_schema,
            supports_tools=supports_tools,
            allows_system_prompt=allows_system_prompt,
        )
        self._reasoning = reasoning
        self._reasoning_summary = reasoning_summary
        self._verbosity = verbosity
        self._image_detail_original = image_detail_original
        self._service_tier = service_tier
        self.Options = build_options_class(
            reasoning=reasoning,
            reasoning_summary=reasoning,
            verbosity=verbosity,
            image_detail_original=image_detail_original,
            chat_completions=True,
            service_tier=service_tier,
        )

    async def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: AsyncResponse,
        conversation: AsyncConversation | None = None,
        key: str | None = None,
    ) -> AsyncGenerator[str | StreamEvent, None]:
        if getattr(prompt.options, "chat_completions", None):
            chat = AsyncChat(**self._delegate_chat_kwargs())
            _partition_tools(chat, prompt.tools)
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
        kwargs = self._finalize_responses_kwargs(prompt, stream, instructions)

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
            tool_call_meta: dict[str, dict[str, str]] = {}
            final_response_dict: dict[str, Any] | None = None
            reasoning_items_with_streamed_text = set()
            reasoning_done_events: dict[str, StreamEvent] = {}
            server_tool_done_events: dict[str, list[StreamEvent]] = {}
            message_index = 0
            seen_message = False
            async for event in stream_obj:
                etype = getattr(event, "type", None)
                if etype == "response.output_item.added":
                    item = event.item
                    if item.type == "message":
                        if seen_message:
                            message_index += 1
                        seen_message = True
                    elif item.type == "function_call":
                        tool_call_meta[item.id] = {
                            "id": item.id,
                            "call_id": item.call_id,
                            "name": item.name,
                        }
                        yield StreamEvent(
                            type="tool_call_name",
                            chunk=item.name or "",
                            tool_call_id=item.call_id,
                            message_index=message_index,
                        )
                elif etype == "response.output_text.delta":
                    yield StreamEvent(
                        type="text",
                        chunk=event.delta or "",
                        message_index=message_index,
                    )
                elif etype == "response.function_call_arguments.delta":
                    item_id = getattr(event, "item_id", None)
                    meta = tool_call_meta.get(item_id) if item_id else None
                    call_id = meta["call_id"] if meta else None
                    yield StreamEvent(
                        type="tool_call_args",
                        chunk=event.delta or "",
                        tool_call_id=call_id,
                        message_index=message_index,
                    )
                elif etype in (
                    "response.reasoning_summary_text.delta",
                    "response.reasoning_text.delta",
                ):
                    item_id = getattr(event, "item_id", None)
                    if item_id:
                        reasoning_items_with_streamed_text.add(item_id)
                    yield StreamEvent(
                        type="reasoning",
                        chunk=event.delta or "",
                        message_index=message_index,
                    )
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
                            yield StreamEvent(
                                type="reasoning",
                                chunk=text,
                                message_index=message_index,
                            )
                elif etype == "response.output_item.done":
                    item = event.item
                    if item.type == "reasoning":
                        had_reasoning = True
                        item_id = getattr(item, "id", None)
                        reasoning_event = self._reasoning_event(
                            item,
                            include_text=(
                                item_id not in reasoning_items_with_streamed_text
                            ),
                        )
                        reasoning_event.message_index = message_index
                        if item_id:
                            # Retained so the refresh after
                            # response.completed can target the part
                            # this event resolved to.
                            reasoning_done_events[item_id] = reasoning_event
                        yield reasoning_event
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
                    else:
                        server_events = self._server_tool_events(item, message_index)
                        item_id = getattr(item, "id", None)
                        if item_id and server_events:
                            server_tool_done_events[item_id] = server_events
                        for server_event in server_events:
                            yield server_event
                elif etype == "response.completed":
                    self._refresh_server_tool_events(
                        event.response.output, server_tool_done_events
                    )
                    final_response_dict = event.response.model_dump(warnings=False)
                    if final_response_dict.get("usage"):
                        usage = final_response_dict["usage"]
            if final_response_dict is not None:
                response.response_json = remove_dict_none_values(final_response_dict)
                for refresh in self._reasoning_refresh_events(
                    response.response_json, reasoning_done_events
                ):
                    yield refresh
        else:
            completion = await client.responses.create(
                model=self.model_name or self.model_id,
                input=input_items,
                stream=False,
                **kwargs,
            )
            dumped = completion.model_dump(warnings=False)
            response.response_json = remove_dict_none_values(dumped)
            usage = dumped.get("usage")
            events, had_reasoning = self._non_streaming_output_events(
                completion.output, response
            )
            for event in events:
                yield event

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
        logprobs: int | None = Field(
            description="Include the log probabilities of most likely N per token",
            default=None,
            le=5,
        )

    def __init__(self, *args, default_max_tokens=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_max_tokens = default_max_tokens

    def __str__(self) -> str:
        return f"OpenAI Completion: {self.model_id}"

    def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: Response,
        conversation: Conversation | None = None,
        key: str | None = None,
    ) -> Iterator[str | StreamEvent]:
        if prompt.system:
            raise NotImplementedError(
                "System prompts are not supported for OpenAI completion models"
            )
        from llm.parts import TextPart

        # prompt.messages carries the full history - including history
        # reloaded from storage, which conversation.responses does not.
        messages = []
        for message in prompt.messages:
            if message.role not in ("user", "assistant"):
                continue
            text = "".join(
                part.text
                for part in message.parts
                if isinstance(part, TextPart) and part.text
            )
            if text:
                messages.append(text)
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


def combine_chunks(chunks: list) -> dict:
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
