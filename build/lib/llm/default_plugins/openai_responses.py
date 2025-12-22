"""
OpenAI Responses API models - the default OpenAI models in LLM.

These use OpenAI's newer Responses API (client.responses.create())
which supports reasoning models, built-in tools, and other advanced features.

For the legacy Chat Completions API, use models with the openai/chat/ prefix.
"""

import json
from enum import Enum
import llm
from llm import (
    AsyncKeyModel,
    KeyModel,
    hookimpl,
    Options,
    Prompt,
    Response,
    Conversation,
)
from llm.utils import simplify_usage_dict
import openai
from pydantic import Field, create_model
from typing import AsyncGenerator, Iterator, Optional


@hookimpl
def register_models(register):
    # GPT-4o models
    register(
        ResponsesModel("gpt-4o", vision=True),
        AsyncResponsesModel("gpt-4o", vision=True),
        aliases=("4o",),
    )
    register(
        ResponsesModel("chatgpt-4o-latest", vision=True),
        AsyncResponsesModel("chatgpt-4o-latest", vision=True),
        aliases=("chatgpt-4o",),
    )
    register(
        ResponsesModel("gpt-4o-mini", vision=True),
        AsyncResponsesModel("gpt-4o-mini", vision=True),
        aliases=("4o-mini",),
    )

    # GPT-4.1 models
    for model_id in ("gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano"):
        register(
            ResponsesModel(model_id, vision=True),
            AsyncResponsesModel(model_id, vision=True),
            aliases=(model_id.replace("gpt-", ""),),
        )

    # GPT-4.5 models
    register(
        ResponsesModel("gpt-4.5-preview", vision=True),
        AsyncResponsesModel("gpt-4.5-preview", vision=True),
        aliases=("gpt-4.5",),
    )
    register(
        ResponsesModel("gpt-4.5-preview-2025-02-27", vision=True),
        AsyncResponsesModel("gpt-4.5-preview-2025-02-27", vision=True),
    )

    # o1 models
    register(
        ResponsesModel("o1", vision=True, reasoning=True),
        AsyncResponsesModel("o1", vision=True, reasoning=True),
    )
    register(
        ResponsesModel("o1-pro", vision=True, reasoning=True, streaming=False),
        AsyncResponsesModel("o1-pro", vision=True, reasoning=True, streaming=False),
    )
    register(
        ResponsesModel("o1-mini", reasoning=True, schemas=False),
        AsyncResponsesModel("o1-mini", reasoning=True, schemas=False),
    )

    # o3 models
    register(
        ResponsesModel("o3-mini", reasoning=True),
        AsyncResponsesModel("o3-mini", reasoning=True),
    )
    register(
        ResponsesModel("o3", vision=True, reasoning=True, streaming=False),
        AsyncResponsesModel("o3", vision=True, reasoning=True, streaming=False),
    )
    register(
        ResponsesModel("o3-pro", vision=True, reasoning=True),
        AsyncResponsesModel("o3-pro", vision=True, reasoning=True),
    )

    # o4 models
    register(
        ResponsesModel("o4-mini", vision=True, reasoning=True),
        AsyncResponsesModel("o4-mini", vision=True, reasoning=True),
    )

    # GPT-5 models
    for model_id in (
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-5-2025-08-07",
        "gpt-5-mini-2025-08-07",
        "gpt-5-nano-2025-08-07",
        "gpt-5-codex",
        "gpt-5-pro",
        "gpt-5-pro-2025-10-06",
    ):
        register(
            ResponsesModel(model_id, vision=True, reasoning=True),
            AsyncResponsesModel(model_id, vision=True, reasoning=True),
        )


class TruncationEnum(str, Enum):
    auto = "auto"
    disabled = "disabled"


class ImageDetailEnum(str, Enum):
    low = "low"
    high = "high"
    auto = "auto"


class ReasoningEffortEnum(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class BaseOptions(Options):
    max_output_tokens: Optional[int] = Field(
        description=(
            "An upper bound for the number of tokens that can be generated for a "
            "response, including visible output tokens and reasoning tokens."
        ),
        ge=0,
        default=None,
    )
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
    store: Optional[bool] = Field(
        description=(
            "Whether to store the generated model response for later retrieval via API."
        ),
        default=None,
    )
    truncation: Optional[TruncationEnum] = Field(
        description=(
            "The truncation strategy to use for the model response. If 'auto' and the "
            "context of this response and previous ones exceeds the model's context "
            "window size, the model will truncate the response to fit the context "
            "window by dropping input items in the middle of the conversation."
        ),
        default=None,
    )


class VisionOptions(Options):
    image_detail: Optional[ImageDetailEnum] = Field(
        description=(
            "low = fixed tokens per image. high = more tokens for larger images. "
            "auto = model decides. Default is low."
        ),
        default=None,
    )


class ReasoningOptions(Options):
    reasoning_effort: Optional[ReasoningEffortEnum] = Field(
        description=(
            "Constraints effort on reasoning for reasoning models. Currently supported "
            "values are low, medium, and high. Reducing reasoning effort can result in "
            "faster responses and fewer tokens used on reasoning in a response."
        ),
        default=None,
    )


class _SharedResponses:
    needs_key = "openai"
    key_env_var = "OPENAI_API_KEY"

    def __init__(
        self, model_name, vision=False, streaming=True, schemas=True, reasoning=False
    ):
        self.model_id = "openai/" + model_name
        streaming_suffix = "-streaming"
        if model_name.endswith(streaming_suffix):
            model_name = model_name[: -len(streaming_suffix)]
        self.model_name = model_name
        self.can_stream = streaming
        self.supports_schema = schemas
        options = [BaseOptions]
        self.vision = vision
        if vision:
            self.attachment_types = {
                "image/png",
                "image/jpeg",
                "image/webp",
                "image/gif",
                "application/pdf",
            }
            options.append(VisionOptions)
        if reasoning:
            options.append(ReasoningOptions)
        self.Options = combine_options(*options)
        self.supports_tools = True

    def __str__(self):
        return f"OpenAI: {self.model_id}"

    def set_usage(self, response, usage):
        if not usage:
            return
        if not isinstance(usage, dict):
            usage = usage.model_dump()
        input_tokens = usage.pop("input_tokens")
        output_tokens = usage.pop("output_tokens")
        usage.pop("total_tokens")
        response.set_usage(
            input=input_tokens, output=output_tokens, details=simplify_usage_dict(usage)
        )

    def _build_messages(self, prompt, conversation):
        messages = []
        current_system = None
        image_detail = None
        if self.vision:
            image_detail = prompt.options.image_detail or "low"
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
                            {"type": "input_text", "text": prev_response.prompt.prompt}
                        )
                    for attachment in prev_response.attachments:
                        attachment_message.append(_attachment(attachment, image_detail))
                    messages.append({"role": "user", "content": attachment_message})
                else:
                    messages.append(
                        {"role": "user", "content": prev_response.prompt.prompt}
                    )
                for tool_result in getattr(prev_response.prompt, "tool_results", []):
                    if not tool_result.tool_call_id:
                        continue
                    messages.append(
                        {
                            "type": "function_call_output",
                            "call_id": tool_result.tool_call_id,
                            "output": tool_result.output,
                        }
                    )
                prev_text = prev_response.text_or_raise()
                if prev_text:
                    messages.append({"role": "assistant", "content": prev_text})
                tool_calls = prev_response.tool_calls_or_raise()
                if tool_calls:
                    for tool_call in tool_calls:
                        messages.append(
                            {
                                "type": "function_call",
                                "call_id": tool_call.tool_call_id,
                                "name": tool_call.name,
                                "arguments": json.dumps(tool_call.arguments),
                            }
                        )
        if prompt.system and prompt.system != current_system:
            messages.append({"role": "system", "content": prompt.system})
        if not prompt.attachments:
            messages.append({"role": "user", "content": prompt.prompt or ""})
        else:
            attachment_message = []
            if prompt.prompt:
                attachment_message.append({"type": "input_text", "text": prompt.prompt})
            for attachment in prompt.attachments:
                attachment_message.append(_attachment(attachment, image_detail))
            messages.append({"role": "user", "content": attachment_message})
        for tool_result in getattr(prompt, "tool_results", []):
            if not tool_result.tool_call_id:
                continue
            messages.append(
                {
                    "type": "function_call_output",
                    "call_id": tool_result.tool_call_id,
                    "output": tool_result.output,
                }
            )
        return messages

    def _build_kwargs(self, prompt, conversation):
        messages = self._build_messages(prompt, conversation)
        kwargs = {"model": self.model_name, "input": messages}
        for option in (
            "max_output_tokens",
            "temperature",
            "top_p",
            "store",
            "truncation",
        ):
            value = getattr(prompt.options, option, None)
            if value is not None:
                kwargs[option] = value

        if prompt.tools:
            tool_defs = []
            for tool in prompt.tools:
                if not getattr(tool, "name", None):
                    continue
                parameters = tool.input_schema or {
                    "type": "object",
                    "properties": {},
                }
                tool_defs.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": tool.description or None,
                        "parameters": parameters,
                        "strict": False,
                    }
                )
            if tool_defs:
                kwargs["tools"] = tool_defs
        if self.supports_schema and prompt.schema:
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "output",
                    "schema": additional_properties_false(prompt.schema),
                }
            }
        return kwargs

    def _update_tool_call_from_event(self, event, _tc_buf):
        """
        Accumulate streaming tool-call args by tool_call_id.
        _tc_buf is a dict[id] -> {"name": str, "arguments": str}
        """
        et = getattr(event, "type", None)
        # Python SDK surfaces rich objects; also support dict fallbacks:
        obj = getattr(event, "to_dict", None)
        if callable(obj):
            payload = event.to_dict()
        else:
            payload = getattr(event, "__dict__", {}) or {}

        # The SDK emits specific typed events for tool-calls; normalize:
        # Expected shapes (SDK may differ slightly by version):
        # - response.tool_call.delta   => { "id", "type":"function", "name"?, "arguments_delta" }
        # - response.tool_call.completed => { "id", "type":"function", "name", "arguments" }
        # Keep this resilient by checking common fields.
        item = payload.get("response", payload.get("data", payload))
        tool = item.get("tool_call") if isinstance(item, dict) else None
        if not tool and "tool_call" in payload:
            tool = payload["tool_call"]

        # Some SDKs put fields at top-level for tool events:
        if (
            tool is None
            and ("tool_call_id" in payload or "id" in payload)
            and (
                "arguments_delta" in payload
                or "arguments" in payload
                or "name" in payload
            )
        ):
            tool = payload

        if not tool:
            return None

        tool_id = tool.get("id") or tool.get("tool_call_id")
        if not tool_id:
            return None

        entry = _tc_buf.setdefault(tool_id, {"name": None, "arguments": ""})

        # Name may arrive early or only at completion:
        if tool.get("name"):
            entry["name"] = tool["name"]

        # Streaming deltas:
        if "arguments_delta" in tool and tool["arguments_delta"]:
            entry["arguments"] += tool["arguments_delta"]

        # Completion:
        if (
            "arguments" in tool
            and tool["arguments"]
            and not tool.get("arguments_delta")
        ):
            entry["arguments"] = tool["arguments"]
            return tool_id  # signal completion for this id

        return None

    def _finalize_streaming_tool_calls(self, response, _tc_buf):
        # Called when we know streaming has finished or when a tool_call completed event fires.
        for tool_id, data in list(_tc_buf.items()):
            if data.get("name") and data.get("arguments") is not None:
                self._add_tool_call(
                    response,
                    tool_id,
                    data.get("name"),
                    data.get("arguments"),
                )
                del _tc_buf[tool_id]

    def _add_tool_call(self, response, tool_id, name, arguments):
        try:
            parsed_arguments = json.loads(arguments or "{}")
        except Exception:
            parsed_arguments = arguments or ""
        response.add_tool_call(
            llm.ToolCall(
                tool_call_id=tool_id,
                name=name or "unknown_tool",
                arguments=parsed_arguments,
            )
        )

    def _add_tool_calls_from_output(self, response, output):
        if not output:
            return
        for item in output:
            if hasattr(item, "model_dump"):
                data = item.model_dump()
            elif isinstance(item, dict):
                data = item
            else:
                data = getattr(item, "__dict__", {}) or {}

            itype = data.get("type")
            if itype not in {"tool_call", "function_call"}:
                continue

            tool_id = (
                data.get("call_id")
                or data.get("id")
                or data.get("tool_call_id")
                or f"call_{len(output)}"
            )
            name = data.get("name") or "unknown_tool"
            arguments = data.get("arguments") or "{}"
            self._add_tool_call(response, tool_id, name, arguments)

    def _handle_event(self, event, response, _tc_buf=None):
        et = getattr(event, "type", None)
        if et == "response.output_text.delta":
            return event.delta

        # Accumulate tool-call pieces if provided
        if _tc_buf is not None and et and "tool_call" in et:
            completed_id = self._update_tool_call_from_event(event, _tc_buf)
            if completed_id:
                # finalize this single tool call immediately
                entry = _tc_buf.pop(completed_id)
                self._finalize_streaming_tool_calls(response, {completed_id: entry})

        if et == "response.completed":
            response.response_json = event.response.model_dump()
            self.set_usage(response, event.response.usage)
            self._add_tool_calls_from_output(
                response, getattr(event.response, "output", None)
            )
            # finalize any remaining buffered tool-calls
            if _tc_buf:
                self._finalize_streaming_tool_calls(response, _tc_buf)
            return None

    def _finish_non_streaming_response(self, response, client_response):
        response.response_json = client_response.model_dump()
        self.set_usage(response, client_response.usage)
        self._add_tool_calls_from_output(
            response, getattr(client_response, "output", None)
        )


class ResponsesModel(_SharedResponses, KeyModel):
    def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: Response,
        conversation: Optional[Conversation],
        key: Optional[str],
    ) -> Iterator[str]:
        client = openai.OpenAI(api_key=self.get_key(key))
        kwargs = self._build_kwargs(prompt, conversation)
        kwargs["stream"] = stream
        if stream:
            # Buffer for assembling tool-call deltas across events
            _tc_buf = {}
            for event in client.responses.create(**kwargs):
                delta = self._handle_event(event, response, _tc_buf)
                if delta is not None:
                    yield delta
        else:
            client_response = client.responses.create(**kwargs)
            text = getattr(client_response, "output_text", None)
            if text:
                yield text
            self._finish_non_streaming_response(response, client_response)


class AsyncResponsesModel(_SharedResponses, AsyncKeyModel):
    async def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: Response,
        conversation: Optional[Conversation],
        key: Optional[str],
    ) -> AsyncGenerator[str, None]:
        client = openai.AsyncOpenAI(api_key=self.get_key(key))
        kwargs = self._build_kwargs(prompt, conversation)
        kwargs["stream"] = stream
        if stream:
            _tc_buf = {}
            async for event in await client.responses.create(**kwargs):
                delta = self._handle_event(event, response, _tc_buf)
                if delta is not None:
                    yield delta
        else:
            client_response = await client.responses.create(**kwargs)
            text = getattr(client_response, "output_text", None)
            if text:
                yield text
            self._finish_non_streaming_response(response, client_response)


def _attachment(attachment, image_detail):
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
        return {"type": "input_image", "image_url": url, "detail": image_detail}
    else:
        format_ = "wav" if attachment.resolve_type() == "audio/wav" else "mp3"
        return {
            "type": "input_audio",
            "input_audio": {
                "data": base64_content,
                "format": format_,
            },
        }


def combine_options(*mixins):
    # reversed() here makes --options display order correct
    return create_model("CombinedOptions", __base__=tuple(reversed(mixins)))


def additional_properties_false(input_dict: dict) -> dict:
    """
    Recursively process a dictionary and add 'additionalProperties': False
    to any dictionary that has a 'properties' key.

    Args:
        input_dict (dict): The input dictionary to process

    Returns:
        dict: A new dictionary with 'additionalProperties': False added where needed
    """
    result = {}
    for key, value in input_dict.items():
        if isinstance(value, dict):
            result[key] = additional_properties_false(value)
        elif isinstance(value, list):
            result[key] = [
                additional_properties_false(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value

    if "properties" in input_dict:
        result["additionalProperties"] = False

    return result
