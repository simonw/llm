import asyncio
import base64
from condense_json import condense_json
from dataclasses import dataclass, field
import datetime
from .errors import NeedsKeyException
import hashlib
import httpx
from itertools import islice
import re
import time
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Set,
    Union,
    get_type_hints,
)
from .utils import (
    ensure_fragment,
    ensure_tool,
    make_schema_id,
    mimetype_from_path,
    mimetype_from_string,
    token_usage_string,
)
from abc import ABC, abstractmethod
import inspect
import json
from pydantic import BaseModel, ConfigDict, create_model
from ulid import ULID

CONVERSATION_NAME_LENGTH = 32


@dataclass
class Usage:
    input: Optional[int] = None
    output: Optional[int] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class Attachment:
    type: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    content: Optional[bytes] = None
    _id: Optional[str] = None

    def id(self):
        # Hash of the binary content, or of '{"url": "https://..."}' for URL attachments
        if self._id is None:
            if self.content:
                self._id = hashlib.sha256(self.content).hexdigest()
            elif self.path:
                self._id = hashlib.sha256(open(self.path, "rb").read()).hexdigest()
            else:
                self._id = hashlib.sha256(
                    json.dumps({"url": self.url}).encode("utf-8")
                ).hexdigest()
        return self._id

    def resolve_type(self):
        if self.type:
            return self.type
        # Derive it from path or url or content
        if self.path:
            return mimetype_from_path(self.path)
        if self.url:
            response = httpx.head(self.url)
            response.raise_for_status()
            return response.headers.get("content-type")
        if self.content:
            return mimetype_from_string(self.content)
        raise ValueError("Attachment has no type and no content to derive it from")

    def content_bytes(self):
        content = self.content
        if not content:
            if self.path:
                content = open(self.path, "rb").read()
            elif self.url:
                response = httpx.get(self.url)
                response.raise_for_status()
                content = response.content
        return content

    def base64_content(self):
        return base64.b64encode(self.content_bytes()).decode("utf-8")

    @classmethod
    def from_row(cls, row):
        return cls(
            _id=row["id"],
            type=row["type"],
            path=row["path"],
            url=row["url"],
            content=row["content"],
        )


@dataclass
class Tool:
    name: str
    description: Optional[str] = None
    input_schema: Dict = field(default_factory=dict)
    implementation: Optional[Callable] = None

    def __post_init__(self):
        # Convert Pydantic model to JSON schema if needed
        self.input_schema = self._ensure_dict_schema(self.input_schema)

    def _ensure_dict_schema(self, schema):
        """Convert a Pydantic model to a JSON schema dict if needed."""
        if schema and not isinstance(schema, dict) and issubclass(schema, BaseModel):
            schema_dict = schema.model_json_schema()
            # Strip annoying "title" fields which are just the "name" in title case
            schema_dict.pop("title", None)
            for value in schema_dict.get("properties", {}).values():
                value.pop("title", None)
            return schema_dict
        return schema

    def hash(self):
        """Hash for tool based on its name, description and input schema (preserving key order)"""
        to_hash = {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
        return hashlib.sha256(json.dumps(to_hash).encode("utf-8")).hexdigest()

    @classmethod
    def function(cls, function, name=None):
        """
        Turn a Python function into a Tool object by:
         - Extracting the function name
         - Using the function docstring for the Tool description
         - Building a Pydantic model for inputs by inspecting the function signature
         - Building a Pydantic model for the return value by using the function's return annotation
        """
        signature = inspect.signature(function)
        type_hints = get_type_hints(function)

        if not name and function.__name__ == "<lambda>":
            raise ValueError(
                "Cannot create a Tool from a lambda function without providing name="
            )

        fields = {}
        for param_name, param in signature.parameters.items():
            # Determine the type annotation (default to string if missing)
            annotated_type = type_hints.get(param_name, str)

            # Handle default value if present; if there's no default, use '...'
            if param.default is inspect.Parameter.empty:
                fields[param_name] = (annotated_type, ...)
            else:
                fields[param_name] = (annotated_type, param.default)

        input_schema = create_model(f"{function.__name__}InputSchema", **fields)

        return cls(
            name=name or function.__name__,
            description=function.__doc__ or None,
            input_schema=input_schema,
            implementation=function,
        )


ToolDef = Union[Tool, Callable[..., Any]]


@dataclass
class ToolCall:
    name: str
    arguments: dict
    tool_call_id: Optional[str] = None


@dataclass
class ToolResult:
    name: str
    output: str
    tool_call_id: Optional[str] = None


class CancelToolCall(Exception):
    pass


@dataclass
class Prompt:
    _prompt: Optional[str]
    model: "Model"
    fragments: Optional[List[str]]
    attachments: Optional[List[Attachment]]
    _system: Optional[str]
    system_fragments: Optional[List[str]]
    prompt_json: Optional[str]
    schema: Optional[Union[Dict, type[BaseModel]]]
    tools: List[Tool]
    tool_results: List[ToolResult]
    options: "Options"

    def __init__(
        self,
        prompt,
        model,
        *,
        fragments=None,
        attachments=None,
        system=None,
        system_fragments=None,
        prompt_json=None,
        options=None,
        schema=None,
        tools=None,
        tool_results=None,
    ):
        self._prompt = prompt
        self.model = model
        self.attachments = list(attachments or [])
        self.fragments = fragments or []
        self._system = system
        self.system_fragments = system_fragments or []
        self.prompt_json = prompt_json
        if schema and not isinstance(schema, dict) and issubclass(schema, BaseModel):
            schema = schema.model_json_schema()
        self.schema = schema
        self.tools = _wrap_tools(tools or [])
        self.tool_results = tool_results or []
        self.options = options or {}

    @property
    def prompt(self):
        return "\n".join(self.fragments + ([self._prompt] if self._prompt else []))

    @property
    def system(self):
        bits = [
            bit.strip()
            for bit in (self.system_fragments + [self._system or ""])
            if bit.strip()
        ]
        return "\n\n".join(bits)


def _wrap_tools(tools: List[ToolDef]) -> List[Tool]:
    wrapped_tools = []
    for tool in tools:
        if isinstance(tool, Tool):
            wrapped_tools.append(tool)
        elif callable(tool):
            wrapped_tools.append(Tool.function(tool))
        else:
            raise ValueError(f"Invalid tool: {tool}")
    return wrapped_tools


@dataclass
class _BaseConversation:
    model: "_BaseModel"
    id: str = field(default_factory=lambda: str(ULID()).lower())
    name: Optional[str] = None
    responses: List["_BaseResponse"] = field(default_factory=list)
    tools: Optional[List[Tool]] = None

    @classmethod
    @abstractmethod
    def from_row(cls, row: Any) -> "_BaseConversation":
        raise NotImplementedError


@dataclass
class Conversation(_BaseConversation):
    def prompt(
        self,
        prompt: Optional[str] = None,
        *,
        fragments: Optional[List[str]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[Tool]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        system_fragments: Optional[List[str]] = None,
        stream: bool = True,
        key: Optional[str] = None,
        **options,
    ) -> "Response":
        return Response(
            Prompt(
                prompt,
                model=self.model,
                fragments=fragments,
                attachments=attachments,
                system=system,
                schema=schema,
                tools=tools or self.tools,
                tool_results=tool_results,
                system_fragments=system_fragments,
                options=self.model.Options(**options),
            ),
            self.model,
            stream,
            conversation=self,
            key=key,
        )

    def chain(
        self,
        prompt: Optional[str] = None,
        *,
        fragments: Optional[List[str]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        system_fragments: Optional[List[str]] = None,
        stream: bool = True,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[Tool]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        chain_limit: Optional[int] = None,
        before_call: Optional[Callable[[Tool, ToolCall], None]] = None,
        after_call: Optional[Callable[[Tool, ToolCall, ToolResult], None]] = None,
        details: bool = False,
        key: Optional[str] = None,
        options: Optional[dict] = None,
    ) -> "ChainResponse":
        self.model._validate_attachments(attachments)
        return ChainResponse(
            Prompt(
                prompt,
                fragments=fragments,
                attachments=attachments,
                system=system,
                schema=schema,
                tools=tools or self.tools,
                tool_results=tool_results,
                system_fragments=system_fragments,
                model=self.model,
                options=self.model.Options(**(options or {})),
            ),
            model=self.model,
            stream=stream,
            conversation=self,
            key=key,
            details=details,
            before_call=before_call,
            after_call=after_call,
            chain_limit=chain_limit,
        )

    @classmethod
    def from_row(cls, row):
        from llm import get_model

        return cls(
            model=get_model(row["model"]),
            id=row["id"],
            name=row["name"],
        )

    def __repr__(self):
        count = len(self.responses)
        s = "s" if count == 1 else ""
        return f"<{self.__class__.__name__}: {self.id} - {count} response{s}"


@dataclass
class AsyncConversation(_BaseConversation):
    def chain(
        self,
        prompt: Optional[str] = None,
        *,
        fragments: Optional[List[str]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        system_fragments: Optional[List[str]] = None,
        stream: bool = True,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[Tool]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        chain_limit: Optional[int] = None,
        before_call: Optional[
            Callable[[Tool, ToolCall], Union[None, Awaitable[None]]]
        ] = None,
        after_call: Optional[
            Callable[[Tool, ToolCall, ToolResult], Union[None, Awaitable[None]]]
        ] = None,
        details: bool = False,
        key: Optional[str] = None,
        options: Optional[dict] = None,
    ) -> "AsyncChainResponse":
        self.model._validate_attachments(attachments)
        return AsyncChainResponse(
            Prompt(
                prompt,
                fragments=fragments,
                attachments=attachments,
                system=system,
                schema=schema,
                tools=tools or self.tools,
                tool_results=tool_results,
                system_fragments=system_fragments,
                model=self.model,
                options=self.model.Options(**(options or {})),
            ),
            model=self.model,
            stream=stream,
            conversation=self,
            key=key,
            details=details,
            before_call=before_call,
            after_call=after_call,
            chain_limit=chain_limit,
        )

    def prompt(
        self,
        prompt: Optional[str] = None,
        *,
        fragments: Optional[List[str]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[Tool]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        system_fragments: Optional[List[str]] = None,
        stream: bool = True,
        key: Optional[str] = None,
        **options,
    ) -> "AsyncResponse":
        return AsyncResponse(
            Prompt(
                prompt,
                model=self.model,
                fragments=fragments,
                attachments=attachments,
                system=system,
                schema=schema,
                tools=tools,
                tool_results=tool_results,
                system_fragments=system_fragments,
                options=self.model.Options(**options),
            ),
            self.model,
            stream,
            conversation=self,
            key=key,
        )

    @classmethod
    def from_row(cls, row):
        from llm import get_async_model

        return cls(
            model=get_async_model(row["model"]),
            id=row["id"],
            name=row["name"],
        )

    def __repr__(self):
        count = len(self.responses)
        s = "s" if count == 1 else ""
        return f"<{self.__class__.__name__}: {self.id} - {count} response{s}"


FRAGMENT_SQL = """
select
    'prompt' as fragment_type,
    fragments.content,
    pf."order" as ord
from prompt_fragments pf
join fragments on pf.fragment_id = fragments.id
where pf.response_id = :response_id
union all
select
    'system' as fragment_type,
    fragments.content,
    sf."order" as ord
from system_fragments sf
join fragments on sf.fragment_id = fragments.id
where sf.response_id = :response_id
order by fragment_type desc, ord asc;
"""


class _BaseResponse:
    """Base response class shared between sync and async responses"""

    id: str
    prompt: "Prompt"
    stream: bool
    conversation: Optional["_BaseConversation"] = None
    _key: Optional[str] = None
    _tool_calls: List[ToolCall] = []

    def __init__(
        self,
        prompt: Prompt,
        model: "_BaseModel",
        stream: bool,
        conversation: Optional[_BaseConversation] = None,
        key: Optional[str] = None,
    ):
        self.id = str(ULID()).lower()
        self.prompt = prompt
        self._prompt_json = None
        self.model = model
        self.stream = stream
        self._key = key
        self._chunks: List[str] = []
        self._done = False
        self._tool_calls: List[ToolCall] = []
        self.response_json = None
        self.conversation = conversation
        self.attachments: List[Attachment] = []
        self._start: Optional[float] = None
        self._end: Optional[float] = None
        self._start_utcnow: Optional[datetime.datetime] = None
        self.input_tokens: Optional[int] = None
        self.output_tokens: Optional[int] = None
        self.token_details: Optional[dict] = None
        self.done_callbacks: List[Callable] = []

        if self.prompt.schema and not self.model.supports_schema:
            raise ValueError(f"{self.model} does not support schemas")

        if self.prompt.tools and not self.model.supports_tools:
            raise ValueError(f"{self.model} does not support tools")

    def add_tool_call(self, tool_call: ToolCall):
        self._tool_calls.append(tool_call)

    def set_usage(
        self,
        *,
        input: Optional[int] = None,
        output: Optional[int] = None,
        details: Optional[dict] = None,
    ):
        self.input_tokens = input
        self.output_tokens = output
        self.token_details = details

    @classmethod
    def from_row(cls, db, row, _async=False):
        from llm import get_model, get_async_model

        if _async:
            model = get_async_model(row["model"])
        else:
            model = get_model(row["model"])

        # Schema
        schema = None
        if row["schema_id"]:
            schema = json.loads(db["schemas"].get(row["schema_id"])["content"])

        # Tool definitions and results for prompt
        tools = [
            Tool(
                name=tool_row["name"],
                description=tool_row["description"],
                input_schema=json.loads(tool_row["input_schema"]),
                # In this case we don't have a reference to the actual Python code
                # but that's OK, we should not need it for prompts deserialized from DB
                implementation=None,
            )
            for tool_row in db.query(
                """
                select tools.* from tools
                join tool_responses on tools.id = tool_responses.tool_id
                where tool_responses.response_id = ?
            """,
                [row["id"]],
            )
        ]
        tool_results = [
            ToolResult(
                name=tool_results_row["name"],
                output=tool_results_row["output"],
                tool_call_id=tool_results_row["tool_call_id"],
            )
            for tool_results_row in db.query(
                """
                select * from tool_results
                where response_id = ?
            """,
                [row["id"]],
            )
        ]

        all_fragments = list(db.query(FRAGMENT_SQL, {"response_id": row["id"]}))
        fragments = [
            row["content"] for row in all_fragments if row["fragment_type"] == "prompt"
        ]
        system_fragments = [
            row["content"] for row in all_fragments if row["fragment_type"] == "system"
        ]
        response = cls(
            model=model,
            prompt=Prompt(
                prompt=row["prompt"],
                model=model,
                fragments=fragments,
                attachments=[],
                system=row["system"],
                schema=schema,
                tools=tools,
                tool_results=tool_results,
                system_fragments=system_fragments,
                options=model.Options(**json.loads(row["options_json"])),
            ),
            stream=False,
        )
        prompt_json = json.loads(row["prompt_json"] or "null")
        response.id = row["id"]
        response._prompt_json = prompt_json
        response.response_json = json.loads(row["response_json"] or "null")
        response._done = True
        response._chunks = [row["response"]]
        # Attachments
        response.attachments = [
            Attachment.from_row(attachment_row)
            for attachment_row in db.query(
                """
                select attachments.* from attachments
                join prompt_attachments on attachments.id = prompt_attachments.attachment_id
                where prompt_attachments.response_id = ?
                order by prompt_attachments."order"
            """,
                [row["id"]],
            )
        ]
        # Tool calls
        response._tool_calls = [
            ToolCall(
                name=tool_row["name"],
                arguments=json.loads(tool_row["arguments"]),
                tool_call_id=tool_row["tool_call_id"],
            )
            for tool_row in db.query(
                """
                select * from tool_calls
                where response_id = ?
                order by tool_call_id
            """,
                [row["id"]],
            )
        ]

        return response

    def token_usage(self) -> str:
        return token_usage_string(
            self.input_tokens, self.output_tokens, self.token_details
        )

    def log_to_db(self, db):
        conversation = self.conversation
        if not conversation:
            conversation = Conversation(model=self.model)
        db["conversations"].insert(
            {
                "id": conversation.id,
                "name": _conversation_name(
                    self.prompt.prompt or self.prompt.system or ""
                ),
                "model": conversation.model.model_id,
            },
            ignore=True,
        )
        schema_id = None
        if self.prompt.schema:
            schema_id, schema_json = make_schema_id(self.prompt.schema)
            db["schemas"].insert({"id": schema_id, "content": schema_json}, ignore=True)

        response_id = self.id
        replacements = {}
        # Include replacements from previous responses
        for previous_response in conversation.responses[:-1]:
            for fragment in (previous_response.prompt.fragments or []) + (
                previous_response.prompt.system_fragments or []
            ):
                fragment_id = ensure_fragment(db, fragment)
                replacements[f"f:{fragment_id}"] = fragment
                replacements[f"r:{previous_response.id}"] = (
                    previous_response.text_or_raise()
                )

        for i, fragment in enumerate(self.prompt.fragments):
            fragment_id = ensure_fragment(db, fragment)
            replacements[f"f{fragment_id}"] = fragment
            db["prompt_fragments"].insert(
                {
                    "response_id": response_id,
                    "fragment_id": fragment_id,
                    "order": i,
                },
            )
        for i, fragment in enumerate(self.prompt.system_fragments):
            fragment_id = ensure_fragment(db, fragment)
            replacements[f"f{fragment_id}"] = fragment
            db["system_fragments"].insert(
                {
                    "response_id": response_id,
                    "fragment_id": fragment_id,
                    "order": i,
                },
            )

        response_text = self.text_or_raise()
        replacements[f"r:{response_id}"] = response_text
        json_data = self.json()

        response = {
            "id": response_id,
            "model": self.model.model_id,
            "prompt": self.prompt._prompt,
            "system": self.prompt._system,
            "prompt_json": condense_json(self._prompt_json, replacements),
            "options_json": {
                key: value
                for key, value in dict(self.prompt.options).items()
                if value is not None
            },
            "response": response_text,
            "response_json": condense_json(json_data, replacements),
            "conversation_id": conversation.id,
            "duration_ms": self.duration_ms(),
            "datetime_utc": self.datetime_utc(),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "token_details": (
                json.dumps(self.token_details) if self.token_details else None
            ),
            "schema_id": schema_id,
        }
        db["responses"].insert(response)

        # Persist any attachments - loop through with index
        for index, attachment in enumerate(self.prompt.attachments):
            attachment_id = attachment.id()
            db["attachments"].insert(
                {
                    "id": attachment_id,
                    "type": attachment.resolve_type(),
                    "path": attachment.path,
                    "url": attachment.url,
                    "content": attachment.content,
                },
                replace=True,
            )
            db["prompt_attachments"].insert(
                {
                    "response_id": response_id,
                    "attachment_id": attachment_id,
                    "order": index,
                },
            )

        # Persist any tools, tool calls and tool results
        tool_ids_by_name = {}
        for tool in self.prompt.tools:
            tool_id = ensure_tool(db, tool)
            tool_ids_by_name[tool.name] = tool_id
            db["tool_responses"].insert(
                {
                    "tool_id": tool_id,
                    "response_id": response_id,
                }
            )
        for tool_call in self.tool_calls():  # TODO Should  be _or_raise()
            db["tool_calls"].insert(
                {
                    "response_id": response_id,
                    "tool_id": tool_ids_by_name.get(tool_call.name) or None,
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments),
                    "tool_call_id": tool_call.tool_call_id,
                }
            )
        for tool_result in self.prompt.tool_results:
            db["tool_results"].insert(
                {
                    "response_id": response_id,
                    "tool_id": tool_ids_by_name.get(tool_result.name) or None,
                    "name": tool_result.name,
                    "output": tool_result.output,
                    "tool_call_id": tool_result.tool_call_id,
                }
            )


class Response(_BaseResponse):
    model: "Model"
    conversation: Optional["Conversation"] = None

    def on_done(self, callback):
        if not self._done:
            self.done_callbacks.append(callback)
        else:
            callback(self)

    def _on_done(self):
        for callback in self.done_callbacks:
            callback(self)

    def __str__(self) -> str:
        return self.text()

    def _force(self):
        if not self._done:
            list(self)

    def text(self) -> str:
        self._force()
        return "".join(self._chunks)

    def text_or_raise(self) -> str:
        return self.text()

    def execute_tool_calls(
        self,
        *,
        before_call: Optional[
            Callable[[Tool, ToolCall], Union[None, Awaitable[None]]]
        ] = None,
        after_call: Optional[
            Callable[[Tool, ToolCall, ToolResult], Union[None, Awaitable[None]]]
        ] = None,
    ) -> List[ToolResult]:
        tool_results = []
        tools_by_name = {tool.name: tool for tool in self.prompt.tools}
        for tool_call in self.tool_calls():
            tool = tools_by_name.get(tool_call.name)
            if tool is None:
                raise CancelToolCall("Unknown tool: {}".format(tool_call.name))

            if before_call:
                # This may raise CancelToolCall:
                cb_result = before_call(tool, tool_call)
                if inspect.isawaitable(cb_result):
                    raise TypeError(
                        "Asynchronous 'before_call' callback provided to a synchronous tool execution context. "
                        "Please use an async chain/response or a synchronous callback."
                    )

            if not tool.implementation:
                raise CancelToolCall(
                    "No implementation available for tool: {}".format(tool_call.name)
                )

            try:
                if asyncio.iscoroutinefunction(tool.implementation):
                    result = asyncio.run(tool.implementation(**tool_call.arguments))
                else:
                    result = tool.implementation(**tool_call.arguments)

                if not isinstance(result, str):
                    result = json.dumps(result, default=repr)
            except Exception as ex:
                result = f"Error: {ex}"

            tool_result_obj = ToolResult(
                name=tool_call.name,
                output=result,
                tool_call_id=tool_call.tool_call_id,
            )

            if after_call:
                cb_result = after_call(tool, tool_call, tool_result_obj)
                if inspect.isawaitable(cb_result):
                    raise TypeError(
                        "Asynchronous 'after_call' callback provided to a synchronous tool execution context. "
                        "Please use an async chain/response or a synchronous callback."
                    )
            tool_results.append(tool_result_obj)
        return tool_results

    def tool_calls(self) -> List[ToolCall]:
        self._force()
        return self._tool_calls

    def tool_calls_or_raise(self) -> List[ToolCall]:
        return self.tool_calls()

    def json(self) -> Optional[Dict[str, Any]]:
        self._force()
        return self.response_json

    def duration_ms(self) -> int:
        self._force()
        return int(((self._end or 0) - (self._start or 0)) * 1000)

    def datetime_utc(self) -> str:
        self._force()
        return self._start_utcnow.isoformat() if self._start_utcnow else ""

    def usage(self) -> Usage:
        self._force()
        return Usage(
            input=self.input_tokens,
            output=self.output_tokens,
            details=self.token_details,
        )

    def __iter__(self) -> Iterator[str]:
        self._start = time.monotonic()
        self._start_utcnow = datetime.datetime.now(datetime.timezone.utc)
        if self._done:
            yield from self._chunks
            return

        if isinstance(self.model, Model):
            for chunk in self.model.execute(
                self.prompt,
                stream=self.stream,
                response=self,
                conversation=self.conversation,
            ):
                assert chunk is not None
                yield chunk
                self._chunks.append(chunk)
        elif isinstance(self.model, KeyModel):
            for chunk in self.model.execute(
                self.prompt,
                stream=self.stream,
                response=self,
                conversation=self.conversation,
                key=self.model.get_key(self._key),
            ):
                assert chunk is not None
                yield chunk
                self._chunks.append(chunk)
        else:
            raise Exception("self.model must be a Model or KeyModel")

        if self.conversation:
            self.conversation.responses.append(self)
        self._end = time.monotonic()
        self._done = True
        self._on_done()

    def __repr__(self):
        text = "... not yet done ..."
        if self._done:
            text = "".join(self._chunks)
        return "<Response prompt='{}' text='{}'>".format(self.prompt.prompt, text)


class AsyncResponse(_BaseResponse):
    model: "AsyncModel"
    conversation: Optional["AsyncConversation"] = None

    @classmethod
    def from_row(cls, db, row, _async=False):
        return super().from_row(db, row, _async=True)

    async def on_done(self, callback):
        if not self._done:
            self.done_callbacks.append(callback)
        else:
            if callable(callback):
                # Ensure we handle both sync and async callbacks correctly
                processed_callback = callback(self)
                if inspect.isawaitable(processed_callback):
                    await processed_callback
            elif inspect.isawaitable(callback):
                await callback

    async def _on_done(self):
        for callback_func in self.done_callbacks:
            if callable(callback_func):
                processed_callback = callback_func(self)
                if inspect.isawaitable(processed_callback):
                    await processed_callback
            elif inspect.isawaitable(callback_func):
                await callback_func

    async def execute_tool_calls(
        self,
        *,
        before_call: Optional[
            Callable[[Tool, ToolCall], Union[None, Awaitable[None]]]
        ] = None,
        after_call: Optional[
            Callable[[Tool, ToolCall, ToolResult], Union[None, Awaitable[None]]]
        ] = None,
    ) -> List[ToolResult]:
        tool_calls_list = await self.tool_calls()
        tools_by_name = {tool.name: tool for tool in self.prompt.tools}

        indexed_results: List[tuple[int, ToolResult]] = []
        async_tasks: List[asyncio.Task] = []

        for idx, tc in enumerate(tool_calls_list):
            tool = tools_by_name.get(tc.name)
            if tool is None:
                raise CancelToolCall(f"Unknown tool: {tc.name}")
            if not tool.implementation:
                raise CancelToolCall(f"No implementation for tool: {tc.name}")

            # If it's an async implementation, wrap it
            if inspect.iscoroutinefunction(tool.implementation):

                async def run_async(tc=tc, tool=tool, idx=idx):
                    # before_call inside the task
                    if before_call:
                        cb = before_call(tool, tc)
                        if inspect.isawaitable(cb):
                            await cb

                    try:
                        result = await tool.implementation(**tc.arguments)
                        output = (
                            result
                            if isinstance(result, str)
                            else json.dumps(result, default=repr)
                        )
                    except Exception as ex:
                        output = f"Error: {ex}"

                    tr = ToolResult(
                        name=tc.name,
                        output=output,
                        tool_call_id=tc.tool_call_id,
                    )

                    # after_call inside the task
                    if after_call:
                        cb2 = after_call(tool, tc, tr)
                        if inspect.isawaitable(cb2):
                            await cb2

                    return idx, tr

                async_tasks.append(asyncio.create_task(run_async()))

            else:
                # Sync implementation: do hooks and call inline
                if before_call:
                    cb = before_call(tool, tc)
                    if inspect.isawaitable(cb):
                        await cb

                try:
                    res = tool.implementation(**tc.arguments)
                    if inspect.isawaitable(res):
                        res = await res
                    output = (
                        res if isinstance(res, str) else json.dumps(res, default=repr)
                    )
                except Exception as ex:
                    output = f"Error: {ex}"

                tr = ToolResult(
                    name=tc.name,
                    output=output,
                    tool_call_id=tc.tool_call_id,
                )

                if after_call:
                    cb2 = after_call(tool, tc, tr)
                    if inspect.isawaitable(cb2):
                        await cb2

                indexed_results.append((idx, tr))

        # Await all async tasks in parallel
        if async_tasks:
            indexed_results.extend(await asyncio.gather(*async_tasks))

        # Reorder by original index
        indexed_results.sort(key=lambda x: x[0])
        return [tr for _, tr in indexed_results]

    def __aiter__(self):
        self._start = time.monotonic()
        self._start_utcnow = datetime.datetime.now(datetime.timezone.utc)
        if self._done:
            self._iter_chunks = list(self._chunks)  # Make a copy for iteration
        return self

    async def __anext__(self) -> str:
        if self._done:
            if hasattr(self, "_iter_chunks") and self._iter_chunks:
                return self._iter_chunks.pop(0)
            raise StopAsyncIteration

        if not hasattr(self, "_generator"):
            if isinstance(self.model, AsyncModel):
                self._generator = self.model.execute(
                    self.prompt,
                    stream=self.stream,
                    response=self,
                    conversation=self.conversation,
                )
            elif isinstance(self.model, AsyncKeyModel):
                self._generator = self.model.execute(
                    self.prompt,
                    stream=self.stream,
                    response=self,
                    conversation=self.conversation,
                    key=self.model.get_key(self._key),
                )
            else:
                raise ValueError("self.model must be an AsyncModel or AsyncKeyModel")

        try:
            chunk = await self._generator.__anext__()
            assert chunk is not None
            self._chunks.append(chunk)
            return chunk
        except StopAsyncIteration:
            if self.conversation:
                self.conversation.responses.append(self)
            self._end = time.monotonic()
            self._done = True
            if hasattr(self, "_generator"):
                del self._generator
            await self._on_done()
            raise

    async def _force(self):
        if not self._done:
            temp_chunks = []
            async for chunk in self:
                temp_chunks.append(chunk)
            # This should populate self._chunks
        return self

    def text_or_raise(self) -> str:
        if not self._done:
            raise ValueError("Response not yet awaited")
        return "".join(self._chunks)

    async def text(self) -> str:
        await self._force()
        return "".join(self._chunks)

    async def tool_calls(self) -> List[ToolCall]:
        await self._force()
        return self._tool_calls

    def tool_calls_or_raise(self) -> List[ToolCall]:
        if not self._done:
            raise ValueError("Response not yet awaited")
        return self._tool_calls

    async def json(self) -> Optional[Dict[str, Any]]:
        await self._force()
        return self.response_json

    async def duration_ms(self) -> int:
        await self._force()
        return int(((self._end or 0) - (self._start or 0)) * 1000)

    async def datetime_utc(self) -> str:
        await self._force()
        return self._start_utcnow.isoformat() if self._start_utcnow else ""

    async def usage(self) -> Usage:
        await self._force()
        return Usage(
            input=self.input_tokens,
            output=self.output_tokens,
            details=self.token_details,
        )

    def __await__(self):
        return self._force().__await__()

    async def to_sync_response(self) -> Response:
        await self._force()
        # This conversion might be tricky if the model is AsyncModel,
        # as Response expects a sync Model. For simplicity, we'll assume
        # the primary use case is data transfer after completion.
        # The model type on the new Response might need careful handling
        # if it's intended for further execution.
        # For now, let's assume self.model can be cast or is compatible.
        sync_model = self.model
        if not isinstance(self.model, (Model, KeyModel)):
            # This is a placeholder. A proper conversion or shared base might be needed
            # if the sync_response needs to be fully functional with its model.
            # For now, we pass the async model, which might limit what sync_response can do.
            pass

        response = Response(
            self.prompt,
            sync_model,  # This might need adjustment based on how Model/AsyncModel relate
            self.stream,
            # conversation type needs to be compatible too.
            conversation=(
                self.conversation.to_sync_conversation()
                if self.conversation
                and hasattr(self.conversation, "to_sync_conversation")
                else None
            ),
        )
        response.id = self.id
        response._chunks = list(self._chunks)  # Copy chunks
        response._done = self._done
        response._end = self._end
        response._start = self._start
        response._start_utcnow = self._start_utcnow
        response.input_tokens = self.input_tokens
        response.output_tokens = self.output_tokens
        response.token_details = self.token_details
        response._prompt_json = self._prompt_json
        response.response_json = self.response_json
        response._tool_calls = list(self._tool_calls)
        response.attachments = list(self.attachments)
        return response

    @classmethod
    def fake(
        cls,
        model: "AsyncModel",
        prompt: str,
        *attachments: List[Attachment],
        system: str,
        response: str,
    ):
        "Utility method to help with writing tests"
        response_obj = cls(
            model=model,
            prompt=Prompt(
                prompt,
                model=model,
                attachments=attachments,
                system=system,
            ),
            stream=False,
        )
        response_obj._done = True
        response_obj._chunks = [response]
        return response_obj

    def __repr__(self):
        text = "... not yet awaited ..."
        if self._done:
            text = "".join(self._chunks)
        return "<AsyncResponse prompt='{}' text='{}'>".format(self.prompt.prompt, text)


class _BaseChainResponse:
    prompt: "Prompt"
    stream: bool
    conversation: Optional["_BaseConversation"] = None
    _key: Optional[str] = None

    def __init__(
        self,
        prompt: Prompt,
        model: "_BaseModel",
        stream: bool,
        conversation: _BaseConversation,
        key: Optional[str] = None,
        details: bool = False,
        chain_limit: Optional[int] = 10,
        before_call: Optional[
            Callable[[Tool, ToolCall], Union[None, Awaitable[None]]]
        ] = None,
        after_call: Optional[
            Callable[[Tool, ToolCall, ToolResult], Union[None, Awaitable[None]]]
        ] = None,
    ):
        self.prompt = prompt
        self.model = model
        self.stream = stream
        self._key = key
        self._details = details
        self._responses: List[Any] = []
        self.conversation = conversation
        self.chain_limit = chain_limit
        self.before_call = before_call
        self.after_call = after_call

    def log_to_db(self, db):
        for response in self._responses:
            if isinstance(response, AsyncResponse):
                sync_response = asyncio.run(response.to_sync_response())
            elif isinstance(response, Response):
                sync_response = response
            else:
                assert False, "Should have been a Response or AsyncResponse"
            sync_response.log_to_db(db)


class ChainResponse(_BaseChainResponse):
    _responses: List["Response"]

    def responses(self) -> Iterator[Response]:
        prompt = self.prompt
        count = 0
        current_response: Optional[Response] = Response(
            prompt,
            self.model,
            self.stream,
            key=self._key,
            conversation=self.conversation,
        )
        while current_response:
            count += 1
            yield current_response
            self._responses.append(current_response)
            if self.chain_limit and count >= self.chain_limit:
                raise ValueError(f"Chain limit of {self.chain_limit} exceeded.")

            # This could raise llm.CancelToolCall:
            tool_results = current_response.execute_tool_calls(
                before_call=self.before_call, after_call=self.after_call
            )
            if tool_results:
                current_response = Response(
                    Prompt(
                        "",  # Next prompt is empty, tools drive it
                        self.model,
                        tools=current_response.prompt.tools,
                        tool_results=tool_results,
                        options=self.prompt.options,
                    ),
                    self.model,
                    stream=self.stream,
                    key=self._key,
                    conversation=self.conversation,
                )
            else:
                current_response = None
                break

    def __iter__(self) -> Iterator[str]:
        for response_item in self.responses():
            yield from response_item

    def text(self) -> str:
        return "".join(self)


class AsyncChainResponse(_BaseChainResponse):
    _responses: List["AsyncResponse"]

    async def responses(self) -> AsyncIterator[AsyncResponse]:
        prompt = self.prompt
        count = 0
        current_response: Optional[AsyncResponse] = AsyncResponse(
            prompt,
            self.model,
            self.stream,
            key=self._key,
            conversation=self.conversation,
        )
        while current_response:
            count += 1
            yield current_response
            self._responses.append(current_response)

            if self.chain_limit and count >= self.chain_limit:
                raise ValueError(f"Chain limit of {self.chain_limit} exceeded.")

            # This could raise llm.CancelToolCall:
            tool_results = await current_response.execute_tool_calls(
                before_call=self.before_call, after_call=self.after_call
            )
            if tool_results:
                prompt = Prompt(
                    "",
                    self.model,
                    tools=current_response.prompt.tools,
                    tool_results=tool_results,
                    options=self.prompt.options,
                )
                current_response = AsyncResponse(
                    prompt,
                    self.model,
                    stream=self.stream,
                    key=self._key,
                    conversation=self.conversation,
                )
            else:
                current_response = None
                break

    async def __aiter__(self) -> AsyncIterator[str]:
        async for response_item in self.responses():
            async for chunk in response_item:
                yield chunk

    async def text(self) -> str:
        all_chunks = []
        async for chunk in self:
            all_chunks.append(chunk)
        return "".join(all_chunks)


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")


_Options = Options


class _get_key_mixin:
    needs_key: Optional[str] = None
    key: Optional[str] = None
    key_env_var: Optional[str] = None

    def get_key(self, explicit_key: Optional[str] = None) -> Optional[str]:
        from llm import get_key

        if self.needs_key is None:
            # This model doesn't use an API key
            return None

        if self.key is not None:
            # Someone already set model.key='...'
            return self.key

        # Attempt to load a key using llm.get_key()
        key_value = get_key(
            explicit_key=explicit_key,
            key_alias=self.needs_key,
            env_var=self.key_env_var,
        )
        if key_value:
            return key_value

        # Show a useful error message
        message = "No key found - add one using 'llm keys set {}'".format(
            self.needs_key
        )
        if self.key_env_var:
            message += " or set the {} environment variable".format(self.key_env_var)
        raise NeedsKeyException(message)


class _BaseModel(ABC, _get_key_mixin):
    model_id: str
    can_stream: bool = False
    attachment_types: Set = set()

    supports_schema = False
    supports_tools = False

    class Options(_Options):
        pass

    def _validate_attachments(
        self, attachments: Optional[List[Attachment]] = None
    ) -> None:
        if attachments and not self.attachment_types:
            raise ValueError("This model does not support attachments")
        for attachment in attachments or []:
            attachment_type = attachment.resolve_type()
            if attachment_type not in self.attachment_types:
                raise ValueError(
                    f"This model does not support attachments of type '{attachment_type}', "
                    f"only {', '.join(self.attachment_types)}"
                )

    def __str__(self) -> str:
        return "{}{}: {}".format(
            self.__class__.__name__,
            " (async)" if isinstance(self, (AsyncModel, AsyncKeyModel)) else "",
            self.model_id,
        )

    def __repr__(self) -> str:
        return f"<{str(self)}>"


class _Model(_BaseModel):
    def conversation(self, tools: Optional[List[Tool]] = None) -> Conversation:
        return Conversation(model=self, tools=tools)

    def prompt(
        self,
        prompt: Optional[str] = None,
        *,
        fragments: Optional[List[str]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        system_fragments: Optional[List[str]] = None,
        stream: bool = True,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[Tool]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        **options,
    ) -> Response:
        key_value = options.pop("key", None)
        self._validate_attachments(attachments)
        return Response(
            Prompt(
                prompt,
                fragments=fragments,
                attachments=attachments,
                system=system,
                schema=schema,
                tools=tools,
                tool_results=tool_results,
                system_fragments=system_fragments,
                model=self,
                options=self.Options(**options),
            ),
            self,
            stream,
            key=key_value,
        )

    def chain(
        self,
        prompt: Optional[str] = None,
        *,
        fragments: Optional[List[str]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        system_fragments: Optional[List[str]] = None,
        stream: bool = True,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[Tool]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        before_call: Optional[Callable[[Tool, ToolCall], None]] = None,
        after_call: Optional[Callable[[Tool, ToolCall, ToolResult], None]] = None,
        details: bool = False,
        key: Optional[str] = None,
        options: Optional[dict] = None,
    ) -> ChainResponse:
        return self.conversation().chain(
            prompt=prompt,
            fragments=fragments,
            attachments=attachments,
            system=system,
            system_fragments=system_fragments,
            stream=stream,
            schema=schema,
            tools=tools,
            tool_results=tool_results,
            before_call=before_call,
            after_call=after_call,
            details=details,
            key=key,
            options=options,
        )


class Model(_Model):
    @abstractmethod
    def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: Response,
        conversation: Optional[Conversation],
    ) -> Iterator[str]:
        pass


class KeyModel(_Model):
    @abstractmethod
    def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: Response,
        conversation: Optional[Conversation],
        key: Optional[str],
    ) -> Iterator[str]:
        pass


class _AsyncModel(_BaseModel):
    def conversation(self, tools: Optional[List[Tool]] = None) -> AsyncConversation:
        return AsyncConversation(model=self, tools=tools)

    def prompt(
        self,
        prompt: Optional[str] = None,
        *,
        fragments: Optional[List[str]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[Tool]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        system_fragments: Optional[List[str]] = None,
        stream: bool = True,
        **options,
    ) -> AsyncResponse:
        key_value = options.pop("key", None)
        self._validate_attachments(attachments)
        return AsyncResponse(
            Prompt(
                prompt,
                fragments=fragments,
                attachments=attachments,
                system=system,
                schema=schema,
                tools=tools,
                tool_results=tool_results,
                system_fragments=system_fragments,
                model=self,
                options=self.Options(**options),
            ),
            self,
            stream,
            key=key_value,
        )

    def chain(
        self,
        prompt: Optional[str] = None,
        *,
        fragments: Optional[List[str]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        system_fragments: Optional[List[str]] = None,
        stream: bool = True,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[Tool]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        before_call: Optional[
            Callable[[Tool, ToolCall], Union[None, Awaitable[None]]]
        ] = None,
        after_call: Optional[
            Callable[[Tool, ToolCall, ToolResult], Union[None, Awaitable[None]]]
        ] = None,
        details: bool = False,
        key: Optional[str] = None,
        options: Optional[dict] = None,
    ) -> AsyncChainResponse:
        return self.conversation().chain(
            prompt=prompt,
            fragments=fragments,
            attachments=attachments,
            system=system,
            system_fragments=system_fragments,
            stream=stream,
            schema=schema,
            tools=tools,
            tool_results=tool_results,
            before_call=before_call,
            after_call=after_call,
            details=details,
            key=key,
            options=options,
        )


class AsyncModel(_AsyncModel):
    @abstractmethod
    async def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: AsyncResponse,
        conversation: Optional[AsyncConversation],
    ) -> AsyncGenerator[str, None]:
        if False:  # Ensure it's a generator type
            yield ""
        pass


class AsyncKeyModel(_AsyncModel):
    @abstractmethod
    async def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: AsyncResponse,
        conversation: Optional[AsyncConversation],
        key: Optional[str],
    ) -> AsyncGenerator[str, None]:
        if False:  # Ensure it's a generator type
            yield ""
        pass


class EmbeddingModel(ABC, _get_key_mixin):
    model_id: str
    key: Optional[str] = None
    needs_key: Optional[str] = None
    key_env_var: Optional[str] = None
    supports_text: bool = True
    supports_binary: bool = False
    batch_size: Optional[int] = None

    def _check(self, item: Union[str, bytes]):
        if not self.supports_binary and isinstance(item, bytes):
            raise ValueError(
                "This model does not support binary data, only text strings"
            )
        if not self.supports_text and isinstance(item, str):
            raise ValueError(
                "This model does not support text strings, only binary data"
            )

    def embed(self, item: Union[str, bytes]) -> List[float]:
        "Embed a single text string or binary blob, return a list of floats"
        self._check(item)
        return next(iter(self.embed_batch([item])))

    def embed_multi(
        self, items: Iterable[Union[str, bytes]], batch_size: Optional[int] = None
    ) -> Iterator[List[float]]:
        "Embed multiple items in batches according to the model batch_size"
        iter_items = iter(items)
        effective_batch_size = self.batch_size if batch_size is None else batch_size
        if (not self.supports_binary) or (not self.supports_text):

            def checking_iter(inner_items):
                for item_to_check in inner_items:
                    self._check(item_to_check)
                    yield item_to_check

            iter_items = checking_iter(items)
        if effective_batch_size is None:
            yield from self.embed_batch(iter_items)
            return
        while True:
            batch_items = list(islice(iter_items, effective_batch_size))
            if not batch_items:
                break
            yield from self.embed_batch(batch_items)

    @abstractmethod
    def embed_batch(self, items: Iterable[Union[str, bytes]]) -> Iterator[List[float]]:
        """
        Embed a batch of strings or blobs, return a list of lists of floats
        """
        pass

    def __str__(self) -> str:
        return "{}: {}".format(self.__class__.__name__, self.model_id)

    def __repr__(self) -> str:
        return f"<{str(self)}>"


@dataclass
class ModelWithAliases:
    model: Model
    async_model: AsyncModel
    aliases: Set[str]

    def matches(self, query: str) -> bool:
        query_lower = query.lower()
        all_strings: List[str] = []
        all_strings.extend(self.aliases)
        if self.model:
            all_strings.append(str(self.model))
        if self.async_model:
            all_strings.append(str(self.async_model.model_id))
        return any(query_lower in alias.lower() for alias in all_strings)


@dataclass
class EmbeddingModelWithAliases:
    model: EmbeddingModel
    aliases: Set[str]

    def matches(self, query: str) -> bool:
        query_lower = query.lower()
        all_strings: List[str] = []
        all_strings.extend(self.aliases)
        all_strings.append(str(self.model))
        return any(query_lower in alias.lower() for alias in all_strings)


def _conversation_name(text):
    # Collapse whitespace, including newlines
    text = re.sub(r"\s+", " ", text)
    if len(text) <= CONVERSATION_NAME_LENGTH:
        return text
    return text[: CONVERSATION_NAME_LENGTH - 1] + "…"
