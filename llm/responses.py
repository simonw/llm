"""
OpenResponses API client implementation for LLM.

This module provides sync and async model classes that implement the
OpenResponses API specification using httpx as the transport layer.
"""

from __future__ import annotations

import json
from typing import (
    Any,
    AsyncGenerator,
    Dict,
    Iterator,
    List,
    Optional,
    Union,
    cast,
)

import httpx
from pydantic import BaseModel, ConfigDict, Field

from llm import AsyncKeyModel, KeyModel, Prompt
from llm.models import (
    AsyncConversation,
    AsyncResponse,
    Conversation,
    Response,
    ToolCall,
    _Options,
)


class ResponsesAPIError(Exception):
    """Base exception for OpenResponses API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class ResponsesAuthenticationError(ResponsesAPIError):
    """Raised when authentication fails (401)."""

    def __init__(self, message: str):
        super().__init__(message, status_code=401)


class ResponsesRateLimitError(ResponsesAPIError):
    """Raised when rate limit is exceeded (429)."""

    def __init__(self, message: str):
        super().__init__(message, status_code=429)


class ResponsesInvalidRequestError(ResponsesAPIError):
    """Raised for invalid requests (400)."""

    def __init__(self, message: str):
        super().__init__(message, status_code=400)


class InputTokensDetails(BaseModel):
    """Details about input token usage."""

    cached_tokens: int = 0


class OutputTokensDetails(BaseModel):
    """Details about output token usage."""

    reasoning_tokens: int = 0


class Usage(BaseModel):
    """Token usage statistics."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_tokens_details: Optional[InputTokensDetails] = None
    output_tokens_details: Optional[OutputTokensDetails] = None


class OutputTextContent(BaseModel):
    """Text content in an output message."""

    type: str = "output_text"
    text: str
    annotations: List[Any] = Field(default_factory=list)


class FunctionCallContent(BaseModel):
    """Function call content in an output item."""

    type: str = "function_call"
    id: str
    status: str
    call_id: Optional[str] = None
    name: str
    arguments: str = ""


class OutputItem(BaseModel):
    """An output item from the model (message or function call)."""

    model_config = ConfigDict(extra="allow")

    type: str
    id: Optional[str] = None
    status: Optional[str] = None
    role: Optional[str] = None
    content: Optional[List[Any]] = None
    call_id: Optional[str] = None
    name: Optional[str] = None
    arguments: Optional[str] = None


class TextFormat(BaseModel):
    """Text format configuration."""

    type: str = "text"


class TextField(BaseModel):
    """Text field configuration."""

    model_config = ConfigDict(extra="allow")

    format: Optional[TextFormat] = None


class ResponseResource(BaseModel):
    """The complete response object from the Responses API."""

    model_config = ConfigDict(extra="allow")

    id: str
    object: str = "response"
    created_at: int
    completed_at: Optional[int] = None
    status: str
    model: str
    incomplete_details: Optional[Any] = None
    previous_response_id: Optional[str] = None
    next_response_ids: List[str] = Field(default_factory=list)
    instructions: Optional[Union[str, List[Any]]] = None
    input: List[Any] = Field(default_factory=list)
    output: List[OutputItem] = Field(default_factory=list)
    error: Optional[Any] = None
    tools: List[Any] = Field(default_factory=list)
    tool_choice: Optional[Any] = None
    truncation: Optional[str] = None
    parallel_tool_calls: bool = True
    text: Optional[TextField] = None
    top_p: Optional[float] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    top_logprobs: Optional[int] = None
    temperature: Optional[float] = None
    reasoning: Optional[Any] = None
    user: Optional[str] = None
    usage: Optional[Usage] = None
    cost_token: Optional[str] = None
    max_output_tokens: Optional[int] = None
    max_tool_calls: Optional[int] = None
    store: bool = False
    background: bool = False
    service_tier: Optional[str] = None
    context_edits: List[Any] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None
    safety_identifier: Optional[str] = None
    prompt_cache_key: Optional[str] = None
    prompt_cache_retention: Optional[str] = None
    conversation: Optional[Any] = None
    billing: Optional[Any] = None


class ResponseStreamEvent(BaseModel):
    """Base class for streaming events."""

    model_config = ConfigDict(extra="allow")

    type: str
    sequence_number: int


class ResponseCreatedEvent(ResponseStreamEvent):
    """Event emitted when response is created."""

    type: str = "response.created"
    response: ResponseResource


class ResponseInProgressEvent(ResponseStreamEvent):
    """Event emitted when response is in progress."""

    type: str = "response.in_progress"
    response: ResponseResource


class ResponseCompletedEvent(ResponseStreamEvent):
    """Event emitted when response is completed."""

    type: str = "response.completed"
    response: ResponseResource


class ResponseFailedEvent(ResponseStreamEvent):
    """Event emitted when response fails."""

    type: str = "response.failed"
    response: ResponseResource


class ResponseOutputItemAddedEvent(ResponseStreamEvent):
    """Event emitted when an output item is added."""

    type: str = "response.output_item.added"
    output_index: int
    item: OutputItem


class ResponseOutputItemDoneEvent(ResponseStreamEvent):
    """Event emitted when an output item is done."""

    type: str = "response.output_item.done"
    output_index: int
    item: OutputItem


class ResponseContentPartAddedEvent(ResponseStreamEvent):
    """Event emitted when a content part is added."""

    type: str = "response.content_part.added"
    item_id: str
    output_index: int
    content_index: int
    part: Any


class ResponseContentPartDoneEvent(ResponseStreamEvent):
    """Event emitted when a content part is done."""

    type: str = "response.content_part.done"
    item_id: str
    output_index: int
    content_index: int
    part: Any


class ResponseOutputTextDeltaEvent(ResponseStreamEvent):
    """Event emitted when text is incrementally added."""

    type: str = "response.output_text.delta"
    item_id: str
    output_index: int
    content_index: int
    delta: str
    logprobs: List[Any] = Field(default_factory=list)
    obfuscation: Optional[str] = None


class ResponseOutputTextDoneEvent(ResponseStreamEvent):
    """Event emitted when text output is complete."""

    type: str = "response.output_text.done"
    item_id: str
    output_index: int
    content_index: int
    text: str


class ResponseFunctionCallArgumentsDeltaEvent(ResponseStreamEvent):
    """Event emitted when function call arguments are incrementally added."""

    type: str = "response.function_call_arguments.delta"
    item_id: str
    output_index: int
    delta: str
    obfuscation: Optional[str] = None


class ResponseFunctionCallArgumentsDoneEvent(ResponseStreamEvent):
    """Event emitted when function call arguments are complete."""

    type: str = "response.function_call_arguments.done"
    item_id: str
    output_index: int
    arguments: str


EVENT_TYPE_MAP = {
    "response.created": ResponseCreatedEvent,
    "response.in_progress": ResponseInProgressEvent,
    "response.completed": ResponseCompletedEvent,
    "response.failed": ResponseFailedEvent,
    "response.output_item.added": ResponseOutputItemAddedEvent,
    "response.output_item.done": ResponseOutputItemDoneEvent,
    "response.content_part.added": ResponseContentPartAddedEvent,
    "response.content_part.done": ResponseContentPartDoneEvent,
    "response.output_text.delta": ResponseOutputTextDeltaEvent,
    "response.output_text.done": ResponseOutputTextDoneEvent,
    "response.function_call_arguments.delta": ResponseFunctionCallArgumentsDeltaEvent,
    "response.function_call_arguments.done": ResponseFunctionCallArgumentsDoneEvent,
}


def parse_sse_event(line: str) -> Optional[ResponseStreamEvent]:
    """
    Parse a single SSE line and return the appropriate event object.

    Args:
        line: A single line from the SSE stream.

    Returns:
        A ResponseStreamEvent subclass instance, or None for empty/comment lines.

    Raises:
        json.JSONDecodeError: If the JSON data is invalid.
    """
    line = line.strip()

    if not line:
        return None

    if line.startswith(":"):
        return None

    if line.startswith("data:"):
        data = line[5:].strip()

        if data == "[DONE]":
            return None

        event_data = json.loads(data)
        event_type = event_data.get("type", "")

        event_class = EVENT_TYPE_MAP.get(event_type, ResponseStreamEvent)
        return event_class(**event_data)

    return None


class ResponsesOptions(_Options):
    """Options for OpenResponses API models."""

    temperature: Optional[float] = Field(
        description="Sampling temperature between 0 and 2.",
        ge=0,
        le=2,
        default=None,
    )
    max_output_tokens: Optional[int] = Field(
        description="Maximum number of tokens to generate.",
        ge=1,
        default=None,
    )
    top_p: Optional[float] = Field(
        description="Nucleus sampling parameter between 0 and 1.",
        ge=0,
        le=1,
        default=None,
    )
    frequency_penalty: Optional[float] = Field(
        description="Frequency penalty between -2 and 2.",
        ge=-2,
        le=2,
        default=None,
    )
    presence_penalty: Optional[float] = Field(
        description="Presence penalty between -2 and 2.",
        ge=-2,
        le=2,
        default=None,
    )


class _SharedResponses:
    """Shared implementation for sync and async responses models."""

    model_id: str
    api_base: str
    can_stream: bool = True
    supports_schema: bool = False
    supports_tools: bool = True

    def __init__(
        self,
        model_id: str,
        api_base: Optional[str] = None,
        key: Optional[str] = None,
    ):
        self.model_id = model_id
        self.api_base = api_base or "https://api.openai.com/v1"
        self.key = key

    def __str__(self) -> str:
        return f"OpenResponses: {self.model_id}"

    def _build_request_body(
        self,
        prompt: Prompt,
        stream: bool,
        conversation: Optional[Union[Conversation, AsyncConversation]],
    ) -> Dict[str, Any]:
        """Build the request body for the API call."""
        body: Dict[str, Any] = {
            "model": self.model_id,
            "stream": stream,
        }

        input_items = []

        if prompt.system:
            input_items.append(
                {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": prompt.system}],
                }
            )

        if conversation is not None:
            for prev_response in conversation.responses:
                if prev_response.prompt.prompt:
                    input_items.append(
                        {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": prev_response.prompt.prompt,
                                }
                            ],
                        }
                    )
                resp = cast(Response, prev_response)
                response_text = resp.text()
                if response_text:
                    input_items.append(
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": response_text}],
                        }
                    )

        if prompt.prompt:
            input_items.append(
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt.prompt}],
                }
            )

        if input_items:
            body["input"] = input_items

        options = prompt.options
        if options:
            if hasattr(options, "temperature") and options.temperature is not None:
                body["temperature"] = options.temperature
            if (
                hasattr(options, "max_output_tokens")
                and options.max_output_tokens is not None
            ):
                body["max_output_tokens"] = options.max_output_tokens
            if hasattr(options, "top_p") and options.top_p is not None:
                body["top_p"] = options.top_p
            if (
                hasattr(options, "frequency_penalty")
                and options.frequency_penalty is not None
            ):
                body["frequency_penalty"] = options.frequency_penalty
            if (
                hasattr(options, "presence_penalty")
                and options.presence_penalty is not None
            ):
                body["presence_penalty"] = options.presence_penalty

        if prompt.tools:
            tools = []
            for tool in prompt.tools:
                tools.append(
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    }
                )
            body["tools"] = tools

        if prompt.schema:
            schema_dict = prompt.schema
            if hasattr(prompt.schema, "model_json_schema"):
                schema_dict = prompt.schema.model_json_schema()
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "response",
                        "schema": schema_dict,
                    },
                }
            }

        return body

    def _build_input_items(
        self, conversation_messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert conversation messages to input items format."""
        input_items = []
        for msg in conversation_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                role = "developer"

            if role == "assistant":
                input_items.append(
                    {
                        "type": "message",
                        "role": role,
                        "content": [{"type": "output_text", "text": content}],
                    }
                )
            else:
                input_items.append(
                    {
                        "type": "message",
                        "role": role,
                        "content": [{"type": "input_text", "text": content}],
                    }
                )

        return input_items

    def _get_headers(self, key: str) -> Dict[str, str]:
        """Get request headers."""
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Handle error responses from the API."""
        try:
            error_data = response.json()
            message = error_data.get("error", {}).get("message", response.text)
        except (json.JSONDecodeError, KeyError):
            message = response.text

        if response.status_code == 401:
            raise ResponsesAuthenticationError(message)
        elif response.status_code == 429:
            raise ResponsesRateLimitError(message)
        elif response.status_code == 400:
            raise ResponsesInvalidRequestError(message)
        else:
            raise ResponsesAPIError(message, status_code=response.status_code)

    def _extract_text_from_response(self, response_resource: ResponseResource) -> str:
        """Extract text content from a response resource."""
        text_parts = []
        for output_item in response_resource.output:
            if output_item.type == "message" and output_item.content:
                for content in output_item.content:
                    if (
                        isinstance(content, dict)
                        and content.get("type") == "output_text"
                    ):
                        text_parts.append(content.get("text", ""))
                    elif hasattr(content, "type") and content.type == "output_text":
                        text_parts.append(content.text)
        return "".join(text_parts)

    def _set_usage_from_response(
        self,
        response: Union[Response, AsyncResponse],
        response_resource: ResponseResource,
    ) -> None:
        """Set usage information on the llm response object."""
        if response_resource.usage:
            response.set_usage(
                input=response_resource.usage.input_tokens,
                output=response_resource.usage.output_tokens,
            )

    def _extract_tool_calls_from_response(
        self,
        response: Union[Response, AsyncResponse],
        response_resource: ResponseResource,
    ) -> None:
        """Extract and add tool calls from response resource."""
        for output_item in response_resource.output:
            if output_item.type == "function_call":
                tool_call = ToolCall(
                    name=output_item.name or "",
                    arguments=json.loads(output_item.arguments or "{}"),
                    tool_call_id=output_item.call_id,
                )
                response.add_tool_call(tool_call)


class ResponsesModel(_SharedResponses, KeyModel):
    """Synchronous model for OpenResponses API."""

    needs_key = "openresponses"
    key_env_var = "OPENRESPONSES_API_KEY"

    class Options(ResponsesOptions):
        pass

    def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: Response,
        conversation: Optional[Conversation],
        key: Optional[str] = None,
    ) -> Iterator[str]:
        """Execute the model and yield text chunks."""
        api_key = key or self.key or self.get_key(key)
        if not api_key:
            raise ResponsesAuthenticationError("No API key provided")
        body = self._build_request_body(prompt, stream, conversation)
        headers = self._get_headers(api_key)
        url = f"{self.api_base}/responses"

        with httpx.Client() as client:
            if stream:
                yield from self._execute_streaming(client, url, headers, body, response)
            else:
                yield from self._execute_non_streaming(
                    client, url, headers, body, response
                )

    def _execute_non_streaming(
        self,
        client: httpx.Client,
        url: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
        response: Response,
    ) -> Iterator[str]:
        """Execute non-streaming request."""
        http_response = client.post(url, headers=headers, json=body)

        if http_response.status_code != 200:
            self._handle_error_response(http_response)

        response_resource = ResponseResource(**http_response.json())
        response.response_json = http_response.json()

        self._set_usage_from_response(response, response_resource)
        self._extract_tool_calls_from_response(response, response_resource)

        text = self._extract_text_from_response(response_resource)
        if text:
            yield text

    def _execute_streaming(
        self,
        client: httpx.Client,
        url: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
        response: Response,
    ) -> Iterator[str]:
        """Execute streaming request."""
        with client.stream("POST", url, headers=headers, json=body) as http_response:
            if http_response.status_code != 200:
                http_response.read()
                self._handle_error_response(http_response)

            for line in http_response.iter_lines():
                if not line:
                    continue

                event = parse_sse_event(line)
                if event is None:
                    continue

                if isinstance(event, ResponseOutputTextDeltaEvent):
                    yield event.delta

                elif isinstance(event, ResponseCompletedEvent):
                    response.response_json = event.response.model_dump()
                    self._set_usage_from_response(response, event.response)
                    self._extract_tool_calls_from_response(response, event.response)


class AsyncResponsesModel(_SharedResponses, AsyncKeyModel):
    """Asynchronous model for OpenResponses API."""

    needs_key = "openresponses"
    key_env_var = "OPENRESPONSES_API_KEY"

    class Options(ResponsesOptions):
        pass

    async def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: AsyncResponse,
        conversation: Optional[AsyncConversation],
        key: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Execute the model and yield text chunks asynchronously."""
        api_key = key or self.key or self.get_key(key)
        if not api_key:
            raise ResponsesAuthenticationError("No API key provided")
        body = self._build_request_body(prompt, stream, conversation)
        headers = self._get_headers(api_key)
        url = f"{self.api_base}/responses"

        async with httpx.AsyncClient() as client:
            if stream:
                async for chunk in self._execute_streaming_async(
                    client, url, headers, body, response
                ):
                    yield chunk
            else:
                async for chunk in self._execute_non_streaming_async(
                    client, url, headers, body, response
                ):
                    yield chunk

    async def _execute_non_streaming_async(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
        response: AsyncResponse,
    ) -> AsyncGenerator[str, None]:
        """Execute non-streaming request asynchronously."""
        http_response = await client.post(url, headers=headers, json=body)

        if http_response.status_code != 200:
            self._handle_error_response(http_response)

        response_resource = ResponseResource(**http_response.json())
        response.response_json = http_response.json()

        self._set_usage_from_response(response, response_resource)
        self._extract_tool_calls_from_response(response, response_resource)

        text = self._extract_text_from_response(response_resource)
        if text:
            yield text

    async def _execute_streaming_async(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
        response: AsyncResponse,
    ) -> AsyncGenerator[str, None]:
        """Execute streaming request asynchronously."""
        async with client.stream(
            "POST", url, headers=headers, json=body
        ) as http_response:
            if http_response.status_code != 200:
                await http_response.aread()
                self._handle_error_response(http_response)

            async for line in http_response.aiter_lines():
                if not line:
                    continue

                event = parse_sse_event(line)
                if event is None:
                    continue

                if isinstance(event, ResponseOutputTextDeltaEvent):
                    yield event.delta

                elif isinstance(event, ResponseCompletedEvent):
                    response.response_json = event.response.model_dump()
                    self._set_usage_from_response(response, event.response)
                    self._extract_tool_calls_from_response(response, event.response)
