import asyncio
import base64
from condense_json import condense_json
from dataclasses import dataclass, field
import datetime
from .errors import NeedsKeyException
import hashlib
import httpx
from itertools import islice
from pathlib import Path
import re
import time
from types import MethodType
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
    TYPE_CHECKING,
    Union,
    get_type_hints,
)

if TYPE_CHECKING:
    from .parts import StreamEvent
from .utils import (
    ensure_fragment,
    ensure_tool,
    make_schema_id,
    mimetype_from_path,
    mimetype_from_string,
    token_usage_string,
    monotonic_ulid,
    Fragment,
)
from abc import ABC, abstractmethod
import inspect
import json
from pydantic import BaseModel, ConfigDict, create_model

CONVERSATION_NAME_LENGTH = 32


@dataclass
class Usage:
    "Token usage information from a model response."

    input: Optional[int] = None
    output: Optional[int] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class Attachment:
    "An attachment (image, audio, etc) to include with a prompt."

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
                self._id = hashlib.sha256(Path(self.path).read_bytes()).hexdigest()
            else:
                self._id = hashlib.sha256(
                    json.dumps({"url": self.url}).encode("utf-8")
                ).hexdigest()
        return self._id

    def resolve_type(self):
        "Return the content type, guessing from content if not specified."
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
        "Return the binary content, reading from path or URL if needed."
        content = self.content
        if not content:
            if self.path:
                content = Path(self.path).read_bytes()
            elif self.url:
                response = httpx.get(self.url)
                response.raise_for_status()
                content = response.content
        return content

    def base64_content(self):
        "Return the content as a base64-encoded string."
        return base64.b64encode(self.content_bytes()).decode("utf-8")

    def __repr__(self):
        info = [f"<Attachment: {self.id()}"]
        if self.type:
            info.append(f'type="{self.type}"')
        if self.path:
            info.append(f'path="{self.path}"')
        if self.url:
            info.append(f'url="{self.url}"')
        if self.content:
            info.append(f"content={len(self.content)} bytes")
        return " ".join(info) + ">"

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
    "A tool that can be called by a model."

    name: str
    description: Optional[str] = None
    input_schema: Dict = field(default_factory=dict)
    implementation: Optional[Callable] = None
    plugin: Optional[str] = None  # plugin tool came from, e.g. 'llm_tools_sqlite'

    def __post_init__(self):
        # Convert Pydantic model to JSON schema if needed
        self.input_schema = _ensure_dict_schema(self.input_schema)

    def hash(self):
        """Hash for tool based on its name, description and input schema (preserving key order)"""
        to_hash = {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
        if self.plugin:
            to_hash["plugin"] = self.plugin
        return hashlib.sha256(json.dumps(to_hash).encode("utf-8")).hexdigest()

    @classmethod
    def function(cls, function, name=None, description=None):
        """
        Turn a Python function into a Tool object by:
         - Extracting the function name
         - Using the function docstring for the Tool description
         - Building a Pydantic model for inputs by inspecting the function signature
         - Building a Pydantic model for the return value by using the function's return annotation
        """
        if not name and function.__name__ == "<lambda>":
            raise ValueError(
                "Cannot create a Tool from a lambda function without providing name="
            )

        return cls(
            name=name or function.__name__,
            description=description or function.__doc__ or None,
            input_schema=_get_arguments_input_schema(function, name),
            implementation=function,
        )


def _get_arguments_input_schema(function, name):
    signature = inspect.signature(function)
    type_hints = get_type_hints(function)
    fields = {}
    for param_name, param in signature.parameters.items():
        if param_name == "self":
            continue
        # Determine the type annotation (default to string if missing)
        annotated_type = type_hints.get(param_name, str)

        # Handle default value if present; if there's no default, use '...'
        if param.default is inspect.Parameter.empty:
            fields[param_name] = (annotated_type, ...)
        else:
            fields[param_name] = (annotated_type, param.default)

    return create_model(f"{name}InputSchema", **fields)


class Toolbox:
    name: Optional[str] = None
    instance_id: Optional[int] = None
    _blocked = (
        "tools",
        "add_tool",
        "method_tools",
        "__init_subclass__",
        "prepare",
        "prepare_async",
    )
    _extra_tools: List[Tool] = []
    _config: Dict[str, Any] = {}
    _prepared: bool = False
    _async_prepared: bool = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        original_init = cls.__init__

        def wrapped_init(self, *args, **kwargs):
            # Track args/kwargs passed to constructor in self._config
            # so we can serialize them to a database entry later on
            sig = inspect.signature(original_init)
            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()

            self._config = {
                name: value
                for name, value in bound.arguments.items()
                if name != "self"
                and sig.parameters[name].kind
                not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            }
            self._extra_tools = []

            original_init(self, *args, **kwargs)

        cls.__init__ = wrapped_init

    @classmethod
    def method_tools(cls) -> List[Tool]:
        tools = []
        for method_name in dir(cls):
            if method_name.startswith("_") or method_name in cls._blocked:
                continue
            method = getattr(cls, method_name)
            if callable(method):
                tool = Tool.function(
                    method,
                    name="{}_{}".format(cls.__name__, method_name),
                )
                tools.append(tool)
        return tools

    def tools(self) -> Iterable[Tool]:
        "Returns an llm.Tool() for each class method, plus any extras registered with add_tool()"
        # method_tools() returns unbound methods, we need bound methods here:
        for name in dir(self):
            if name.startswith("_") or name in self._blocked:
                continue
            attr = getattr(self, name)
            if callable(attr):
                tool = Tool.function(attr, name=f"{self.__class__.__name__}_{name}")
                tool.plugin = getattr(self, "plugin", None)
                yield tool
        yield from self._extra_tools

    def add_tool(
        self, tool_or_function: Union[Tool, Callable[..., Any]], pass_self: bool = False
    ):
        "Add a tool to this toolbox"

        def _upgrade(fn):
            if pass_self:
                return MethodType(fn, self)
            return fn

        if isinstance(tool_or_function, Tool):
            self._extra_tools.append(tool_or_function)
        elif callable(tool_or_function):
            self._extra_tools.append(Tool.function(_upgrade(tool_or_function)))
        else:
            raise ValueError("Tool must be an instance of Tool or a callable function")

    def prepare(self):
        """
        Over-ride this to perform setup (and .add_tool() calls) before the toolbox is used.
        Implement a similar prepare_async() method for async setup.
        """
        pass

    async def prepare_async(self):
        """
        Over-ride this to perform async setup (and .add_tool() calls) before the toolbox is used.
        """
        pass


@dataclass
class ToolCall:
    "A request by the model to call a tool."

    name: str
    arguments: dict
    tool_call_id: Optional[str] = None


@dataclass
class ToolResult:
    "The result of executing a tool call."

    name: str
    output: str
    attachments: List[Attachment] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    instance: Optional[Toolbox] = None
    exception: Optional[Exception] = None


@dataclass
class ToolOutput:
    "Tool functions can return output with extra attachments"

    output: Optional[Union[str, dict, list, bool, int, float]] = None
    attachments: List[Attachment] = field(default_factory=list)


ToolDef = Union[Tool, Toolbox, Callable[..., Any]]
BeforeCallSync = Callable[[Optional[Tool], ToolCall], None]
AfterCallSync = Callable[[Tool, ToolCall, ToolResult], None]
BeforeCallAsync = Callable[[Optional[Tool], ToolCall], Union[None, Awaitable[None]]]
AfterCallAsync = Callable[[Tool, ToolCall, ToolResult], Union[None, Awaitable[None]]]


class CancelToolCall(Exception):
    pass


@dataclass
class Prompt:
    "The prompt being sent to the model."

    _prompt: Optional[str]
    model: "Model"
    fragments: Optional[List[Union[str, Fragment]]]
    attachments: Optional[List[Attachment]]
    _system: Optional[str]
    system_fragments: Optional[List[Union[str, Fragment]]]
    prompt_json: Optional[str]
    schema: Optional[Union[Dict, type[BaseModel]]]
    tools: List[Tool]
    tool_results: List[ToolResult]
    options: "Options"
    _parts: Optional[List[Any]]  # List of Part objects
    _explicit_messages: Optional[List[Any]]  # messages= passed explicitly

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
        parts=None,
        messages=None,
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
        self._parts = parts
        self._explicit_messages = list(messages) if messages else None

    @property
    def prompt(self):
        "The text of the prompt, with any fragments concatenated."
        return "\n".join(self.fragments + ([self._prompt] if self._prompt else []))

    @property
    def system(self):
        "The system prompt, with any system fragments concatenated."
        bits = [
            bit.strip()
            for bit in (self.system_fragments + [self._system or ""])
            if bit.strip()
        ]
        return "\n\n".join(bits)

    @property
    def parts(self):
        """Return the list of input Part objects for this prompt.

        Synthesized from prompt=, system=, attachments=, and parts= parameters.
        """
        from .parts import TextPart, AttachmentPart

        result = []

        # Start with any explicitly provided parts
        if self._parts:
            result.extend(self._parts)

        # Add system prompt as a system-role TextPart
        system_text = self.system
        if system_text:
            result.insert(0, TextPart(role="system", text=system_text))

        # Add prompt text as a user-role TextPart
        prompt_text = self.prompt
        if prompt_text:
            result.append(TextPart(role="user", text=prompt_text))

        # Add attachments as user-role AttachmentParts
        for attachment in self.attachments:
            result.append(AttachmentPart(role="user", attachment=attachment))

        return result

    @property
    def messages(self):
        """Canonical list of Message objects for this prompt.

        If messages= was explicitly passed, that list is returned verbatim.
        Otherwise synthesized from system=, parts=, prompt=, attachments=,
        and tool_results=.
        """
        from .parts import (
            AttachmentPart,
            Message,
            TextPart,
            ToolCallPart,
            ToolResultPart,
            normalize_parts,
        )

        if self._explicit_messages is not None:
            return list(self._explicit_messages)

        result: List[Message] = []

        if self.system:
            result.append(
                Message(
                    role="system",
                    parts=[TextPart(role="system", text=self.system)],
                )
            )

        # Group explicitly-provided parts= by role into Messages.
        if self._parts:
            current_role = None
            current_parts: List[Any] = []
            for part in normalize_parts(self._parts, role="user"):
                role = getattr(part, "role", "user") or "user"
                if isinstance(part, ToolCallPart):
                    role = "assistant"
                elif isinstance(part, ToolResultPart):
                    role = "tool"
                if role != current_role and current_parts:
                    result.append(Message(role=current_role, parts=current_parts))
                    current_parts = []
                current_role = role
                current_parts.append(part)
            if current_parts:
                result.append(Message(role=current_role, parts=current_parts))

        # Tool results from the legacy tool_results= parameter.
        if self.tool_results:
            result.append(
                Message(
                    role="tool",
                    parts=[
                        ToolResultPart(
                            role="tool",
                            name=tr.name,
                            output=tr.output,
                            tool_call_id=tr.tool_call_id,
                        )
                        for tr in self.tool_results
                    ],
                )
            )

        # Current user turn: prompt text and/or attachments.
        user_parts: List[Any] = []
        if self.prompt:
            user_parts.append(TextPart(role="user", text=self.prompt))
        for att in self.attachments:
            user_parts.append(AttachmentPart(role="user", attachment=att))
        if user_parts:
            result.append(Message(role="user", parts=user_parts))

        return result


def _parts_to_messages(parts: List[Any]) -> List[Any]:
    """Group a flat list of Part objects into Message objects by consecutive role.

    Output parts from a model response typically all share role='assistant',
    producing a single Message. Server-executed tool_result parts (role='tool')
    embedded among assistant parts produce a separate Message per role boundary.
    """
    from .parts import Message

    result: List[Any] = []
    current_role: str = "assistant"
    current_parts: List[Any] = []
    for part in parts:
        role = getattr(part, "role", "assistant") or "assistant"
        if role != current_role and current_parts:
            result.append(Message(role=current_role, parts=current_parts))
            current_parts = []
        current_role = role
        current_parts.append(part)
    if current_parts:
        result.append(Message(role=current_role, parts=current_parts))
    return result


def _wrap_tools(tools: List[ToolDef]) -> List[Tool]:
    wrapped_tools = []
    for tool in tools:
        if isinstance(tool, Tool):
            wrapped_tools.append(tool)
        elif isinstance(tool, Toolbox):
            wrapped_tools.extend(tool.tools())
        elif callable(tool):
            wrapped_tools.append(Tool.function(tool))
        else:
            raise ValueError(f"Invalid tool: {tool}")
    return wrapped_tools


@dataclass
class _BaseConversation:
    model: "_BaseModel"
    id: str = field(default_factory=lambda: str(monotonic_ulid()).lower())
    name: Optional[str] = None
    responses: List["_BaseResponse"] = field(default_factory=list)
    tools: Optional[List[ToolDef]] = None
    chain_limit: Optional[int] = None

    @classmethod
    @abstractmethod
    def from_row(cls, row: Any) -> "_BaseConversation":
        raise NotImplementedError


@dataclass
class Conversation(_BaseConversation):
    before_call: Optional[BeforeCallSync] = None
    after_call: Optional[AfterCallSync] = None

    def prompt(
        self,
        prompt: Optional[str] = None,
        *,
        parts: Optional[List[Any]] = None,
        messages: Optional[List[Any]] = None,
        fragments: Optional[List[Union[str, Fragment]]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        system_fragments: Optional[List[Union[str, Fragment]]] = None,
        stream: bool = True,
        key: Optional[str] = None,
        **options,
    ) -> "Response":
        return Response(
            Prompt(
                prompt,
                parts=parts,
                messages=messages,
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
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        chain_limit: Optional[int] = None,
        before_call: Optional[BeforeCallSync] = None,
        after_call: Optional[AfterCallSync] = None,
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
            before_call=before_call or self.before_call,
            after_call=after_call or self.after_call,
            chain_limit=chain_limit if chain_limit is not None else self.chain_limit,
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
    before_call: Optional[BeforeCallAsync] = None
    after_call: Optional[AfterCallAsync] = None

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
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        chain_limit: Optional[int] = None,
        before_call: Optional[BeforeCallAsync] = None,
        after_call: Optional[AfterCallAsync] = None,
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
            before_call=before_call or self.before_call,
            after_call=after_call or self.after_call,
            chain_limit=chain_limit if chain_limit is not None else self.chain_limit,
        )

    def prompt(
        self,
        prompt: Optional[str] = None,
        *,
        parts: Optional[List[Any]] = None,
        messages: Optional[List[Any]] = None,
        fragments: Optional[List[str]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        system_fragments: Optional[List[str]] = None,
        stream: bool = True,
        key: Optional[str] = None,
        **options,
    ) -> "AsyncResponse":
        return AsyncResponse(
            Prompt(
                prompt,
                parts=parts,
                messages=messages,
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

    def to_sync_conversation(self):
        return Conversation(
            model=self.model,
            id=self.id,
            name=self.name,
            responses=[],  # Because we only use this in logging
            tools=self.tools,
            chain_limit=self.chain_limit,
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
    resolved_model: Optional[str] = None
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
        self.id = str(monotonic_ulid()).lower()
        self.prompt = prompt
        self._prompt_json = None
        self._reasoning_token_count: int = 0
        self.model = model
        self.stream = stream
        self._key = key
        self._chunks: List[str] = []
        self._stream_events: List[Any] = []  # StreamEvent objects
        self._has_stream_events = False  # True if any StreamEvents were yielded
        self._done = False
        self._tool_calls: List[ToolCall] = []
        self.response_json: Optional[Dict[str, Any]] = None
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

    def _process_chunk(self, chunk):
        """Process a chunk from execute(), handling str or StreamEvent.

        Returns the text str to yield to __iter__ callers, or None if the
        chunk should be filtered (e.g. reasoning, tool_call events).
        """
        from .parts import StreamEvent

        if isinstance(chunk, StreamEvent):
            self._has_stream_events = True
            self._stream_events.append(chunk)
            if chunk.type == "text":
                self._chunks.append(chunk.chunk)
                return chunk.chunk
            return None
        else:
            # Plain str — backward compat
            self._chunks.append(chunk)
            return chunk

    def _build_parts(self):
        """Assemble Part objects from accumulated _stream_events."""
        from .parts import (
            TextPart,
            ReasoningPart,
            ToolCallPart,
            ToolResultPart,
        )

        if not self._has_stream_events:
            # No StreamEvents were used — synthesize from plain text chunks
            text = "".join(self._chunks)
            if text:
                return [TextPart(role="assistant", text=text)]
            return []

        parts = []
        current_index = None
        current_type = None
        buffer = []

        def finalize():
            if current_type is None:
                return
            pm = provider_metadata_buf[0] if provider_metadata_buf else None
            if current_type == "text":
                text = "".join(buffer)
                if text:
                    parts.append(
                        TextPart(role="assistant", text=text, provider_metadata=pm)
                    )
            elif current_type == "reasoning":
                text = "".join(buffer)
                if text:
                    parts.append(
                        ReasoningPart(role="assistant", text=text, provider_metadata=pm)
                    )
            elif current_type in ("tool_call_name", "tool_call_args"):
                # Finalize tool call from accumulated name/args
                name = tool_name_buf[0] if tool_name_buf else ""
                args_str = "".join(tool_args_buf)
                try:
                    arguments = json.loads(args_str) if args_str else {}
                except json.JSONDecodeError:
                    arguments = {"_raw": args_str}
                parts.append(
                    ToolCallPart(
                        role="assistant",
                        name=name,
                        arguments=arguments,
                        tool_call_id=tool_call_id_buf[0] if tool_call_id_buf else None,
                        server_executed=(
                            server_executed_buf[0] if server_executed_buf else False
                        ),
                        provider_metadata=pm,
                    )
                )
            elif current_type == "tool_result":
                output = "".join(buffer)
                parts.append(
                    ToolResultPart(
                        role="tool",
                        name=tool_name_buf[0] if tool_name_buf else "",
                        output=output,
                        tool_call_id=tool_call_id_buf[0] if tool_call_id_buf else None,
                        server_executed=(
                            server_executed_buf[0] if server_executed_buf else False
                        ),
                        provider_metadata=pm,
                    )
                )

        tool_name_buf = []
        tool_args_buf = []
        tool_call_id_buf = []
        server_executed_buf = []
        provider_metadata_buf: List[Any] = []

        # Types compatible within a single part_index share the same "family".
        # An event type switching families at the same part_index is a bug in
        # the plugin — raise rather than silently drop the earlier content.
        def _family(t: str) -> str:
            if t in ("tool_call_name", "tool_call_args"):
                return "tool_call"
            return t

        for event in self._stream_events:
            if event.part_index != current_index:
                finalize()
                current_index = event.part_index
                current_type = event.type
                buffer = []
                tool_name_buf = []
                tool_args_buf = []
                tool_call_id_buf = []
                server_executed_buf = []
                provider_metadata_buf = []
            elif current_type is not None and _family(event.type) != _family(
                current_type
            ):
                raise ValueError(
                    f"StreamEvent type {event.type!r} is incompatible with "
                    f"prior type {current_type!r} at part_index={event.part_index}. "
                    f"Allocate a new part_index for a different content type."
                )

            if event.type == "text":
                current_type = "text"
                buffer.append(event.chunk)
            elif event.type == "reasoning":
                current_type = "reasoning"
                buffer.append(event.chunk)
            elif event.type == "tool_call_name":
                current_type = "tool_call_name"
                tool_name_buf.append(event.chunk)
                if event.tool_call_id:
                    tool_call_id_buf = [event.tool_call_id]
                if event.server_executed:
                    server_executed_buf = [True]
            elif event.type == "tool_call_args":
                current_type = "tool_call_args"
                tool_args_buf.append(event.chunk)
                if event.tool_call_id and not tool_call_id_buf:
                    tool_call_id_buf = [event.tool_call_id]
                if event.server_executed and not server_executed_buf:
                    server_executed_buf = [True]
            elif event.type == "tool_result":
                current_type = "tool_result"
                buffer.append(event.chunk)
                if event.tool_call_id and not tool_call_id_buf:
                    tool_call_id_buf = [event.tool_call_id]
                if event.server_executed and not server_executed_buf:
                    server_executed_buf = [True]
                if event.tool_name:
                    tool_name_buf = [event.tool_name]

            # Merge provider_metadata across events for this part (last wins,
            # deep-merged by top-level namespace key).
            if event.provider_metadata:
                merged = dict(provider_metadata_buf[0]) if provider_metadata_buf else {}
                for k, v in event.provider_metadata.items():
                    merged[k] = v
                provider_metadata_buf = [merged]

        finalize()

        # Add redacted reasoning part if the model reported reasoning token usage
        reasoning_token_count = getattr(self, "_reasoning_token_count", 0)
        if reasoning_token_count:
            parts.insert(
                0,
                ReasoningPart(
                    role="assistant",
                    text="",
                    redacted=True,
                    token_count=reasoning_token_count,
                ),
            )

        return parts

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

    def set_resolved_model(self, model_id: str):
        self.resolved_model = model_id

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
                plugin=tool_row["plugin"],
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

        # Load parts from the parts table if it exists
        if "parts" in db.table_names():
            response._loaded_parts = cls._load_parts_from_db(db, row["id"])
        else:
            response._loaded_parts = None

        return response

    @staticmethod
    def _load_parts_from_db(db, response_id):
        from .parts import (
            TextPart,
            ReasoningPart,
            ToolCallPart,
            ToolResultPart,
        )

        parts_rows = list(
            db.execute(
                'SELECT * FROM parts WHERE response_id = ? AND direction = ? ORDER BY "order"',
                [response_id, "output"],
            ).fetchall()
        )
        if not parts_rows:
            return None

        columns = [
            desc[0] for desc in db.execute("SELECT * FROM parts LIMIT 0").description
        ]
        parts = []
        for row_tuple in parts_rows:
            r = dict(zip(columns, row_tuple))
            part_type = r["part_type"]
            role = r["role"]
            content = r.get("content")
            content_json = r.get("content_json")

            data = json.loads(content_json) if content_json else {}
            pm = data.get("provider_metadata")
            if part_type == "text":
                parts.append(
                    TextPart(role=role, text=content or "", provider_metadata=pm)
                )
            elif part_type == "reasoning":
                parts.append(
                    ReasoningPart(
                        role=role,
                        text=content or "",
                        redacted=data.get("redacted", False),
                        token_count=data.get("token_count"),
                        provider_metadata=pm,
                    )
                )
            elif part_type == "tool_call":
                parts.append(
                    ToolCallPart(
                        role=role,
                        name=data.get("name", ""),
                        arguments=data.get("arguments", {}),
                        tool_call_id=r.get("tool_call_id"),
                        server_executed=bool(r.get("server_executed")),
                        provider_metadata=pm,
                    )
                )
            elif part_type == "tool_result":
                parts.append(
                    ToolResultPart(
                        role=role,
                        name=data.get("name", ""),
                        output=content or "",
                        tool_call_id=r.get("tool_call_id"),
                        server_executed=bool(r.get("server_executed")),
                        exception=data.get("exception"),
                        provider_metadata=pm,
                    )
                )
        return parts

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
            "resolved_model": self.resolved_model,
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
            instance_id = None
            if tool_result.instance:
                try:
                    if not tool_result.instance.instance_id:
                        tool_result.instance.instance_id = (
                            db["tool_instances"]
                            .insert(
                                {
                                    "plugin": tool.plugin,
                                    "name": tool.name.split("_")[0],
                                    "arguments": json.dumps(
                                        tool_result.instance._config
                                    ),
                                }
                            )
                            .last_pk
                        )
                    instance_id = tool_result.instance.instance_id
                except AttributeError:
                    pass
            tool_result_id = (
                db["tool_results"]
                .insert(
                    {
                        "response_id": response_id,
                        "tool_id": tool_ids_by_name.get(tool_result.name) or None,
                        "name": tool_result.name,
                        "output": tool_result.output,
                        "tool_call_id": tool_result.tool_call_id,
                        "instance_id": instance_id,
                        "exception": (
                            (
                                "{}: {}".format(
                                    tool_result.exception.__class__.__name__,
                                    str(tool_result.exception),
                                )
                            )
                            if tool_result.exception
                            else None
                        ),
                    }
                )
                .last_pk
            )
            # Persist attachments for tool results
            for index, attachment in enumerate(tool_result.attachments):
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
                db["tool_results_attachments"].insert(
                    {
                        "tool_result_id": tool_result_id,
                        "attachment_id": attachment_id,
                        "order": index,
                    },
                )

        # Persist parts (input and output) to the parts table
        if "parts" in db.table_names():
            self._log_parts_to_db(db, response_id)

    def _log_parts_to_db(self, db, response_id):
        from .parts import (
            TextPart,
            ReasoningPart,
            ToolCallPart,
            ToolResultPart,
            AttachmentPart,
        )

        order = 0

        # Write input parts
        for part in self.prompt.parts:
            row = {
                "response_id": response_id,
                "direction": "input",
                "role": part.role,
                "order": order,
            }
            pm = getattr(part, "provider_metadata", None)
            if isinstance(part, TextPart):
                row["part_type"] = "text"
                row["content"] = part.text
                if pm:
                    row["content_json"] = json.dumps({"provider_metadata": pm})
            elif isinstance(part, ReasoningPart):
                row["part_type"] = "reasoning"
                row["content"] = part.text
                extra: Dict[str, Any] = {}
                if part.redacted or part.token_count:
                    extra["redacted"] = part.redacted
                    extra["token_count"] = part.token_count
                if pm:
                    extra["provider_metadata"] = pm
                if extra:
                    row["content_json"] = json.dumps(extra)
            elif isinstance(part, AttachmentPart):
                row["part_type"] = "attachment"
                if part.attachment:
                    att_data = {}
                    if part.attachment.type:
                        att_data["type"] = part.attachment.type
                    if part.attachment.url:
                        att_data["url"] = part.attachment.url
                    if part.attachment.path:
                        att_data["path"] = part.attachment.path
                    if pm:
                        att_data["provider_metadata"] = pm
                    row["content_json"] = json.dumps(att_data)
            else:
                row["part_type"] = "unknown"
                row["content_json"] = json.dumps(part.to_dict())
            db["parts"].insert(row)
            order += 1

        # Write output parts
        for part in self.parts:
            row = {
                "response_id": response_id,
                "direction": "output",
                "role": part.role,
                "order": order,
            }
            pm = getattr(part, "provider_metadata", None)
            if isinstance(part, TextPart):
                row["part_type"] = "text"
                row["content"] = part.text
                if pm:
                    row["content_json"] = json.dumps({"provider_metadata": pm})
            elif isinstance(part, ReasoningPart):
                row["part_type"] = "reasoning"
                row["content"] = part.text
                extra2: Dict[str, Any] = {}
                if part.redacted or part.token_count:
                    extra2["redacted"] = part.redacted
                    extra2["token_count"] = part.token_count
                if pm:
                    extra2["provider_metadata"] = pm
                if extra2:
                    row["content_json"] = json.dumps(extra2)
            elif isinstance(part, ToolCallPart):
                row["part_type"] = "tool_call"
                tc_data: Dict[str, Any] = {
                    "name": part.name,
                    "arguments": part.arguments,
                }
                if pm:
                    tc_data["provider_metadata"] = pm
                row["content_json"] = json.dumps(tc_data)
                row["tool_call_id"] = part.tool_call_id
                row["server_executed"] = 1 if part.server_executed else 0
            elif isinstance(part, ToolResultPart):
                row["part_type"] = "tool_result"
                row["content"] = part.output
                tr_data: Dict[str, Any] = {
                    "name": part.name,
                    "exception": part.exception,
                }
                if pm:
                    tr_data["provider_metadata"] = pm
                row["content_json"] = json.dumps(tr_data)
                row["tool_call_id"] = part.tool_call_id
                row["server_executed"] = 1 if part.server_executed else 0
            else:
                row["part_type"] = "unknown"
                row["content_json"] = json.dumps(part.to_dict())
            db["parts"].insert(row)
            order += 1


class Response(_BaseResponse):
    "Sync response from a model."

    model: "Model"
    conversation: Optional["Conversation"] = None

    def on_done(self, callback):
        "Register a callback to be called when the response is complete."
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
        "Return the full text of the response, executing the prompt if needed."
        self._force()
        return "".join(self._chunks)

    def text_or_raise(self) -> str:
        return self.text()

    def execute_tool_calls(
        self,
        *,
        before_call: Optional[BeforeCallSync] = None,
        after_call: Optional[AfterCallSync] = None,
    ) -> List[ToolResult]:
        tool_results = []
        tools_by_name = {tool.name: tool for tool in self.prompt.tools}

        # Run prepare() on all Toolbox instances that need it
        instances_to_prepare: list[Toolbox] = []
        for tool_to_prep in tools_by_name.values():
            inst = _get_instance(tool_to_prep.implementation)
            if isinstance(inst, Toolbox) and not getattr(inst, "_prepared", False):
                instances_to_prepare.append(inst)

        for inst in instances_to_prepare:
            inst.prepare()
            inst._prepared = True

        for tool_call in self.tool_calls():
            tool: Optional[Tool] = tools_by_name.get(tool_call.name)
            # Tool could be None if the tool was not found in the prompt tools,
            # but we still call the before_call method:
            if before_call:
                try:
                    cb_result = before_call(tool, tool_call)
                    if inspect.isawaitable(cb_result):
                        raise TypeError(
                            "Asynchronous 'before_call' callback provided to a synchronous tool execution context. "
                            "Please use an async chain/response or a synchronous callback."
                        )
                except CancelToolCall as ex:
                    tool_results.append(
                        ToolResult(
                            name=tool_call.name,
                            output="Cancelled: " + str(ex),
                            tool_call_id=tool_call.tool_call_id,
                            exception=ex,
                        )
                    )
                    continue

            if tool is None:
                msg = 'tool "{}" does not exist'.format(tool_call.name)
                tool_results.append(
                    ToolResult(
                        name=tool_call.name,
                        output="Error: " + msg,
                        tool_call_id=tool_call.tool_call_id,
                        exception=KeyError(msg),
                    )
                )
                continue

            if not tool.implementation:
                raise ValueError(
                    "No implementation available for tool: {}".format(tool_call.name)
                )

            attachments = []
            exception = None

            try:
                if inspect.iscoroutinefunction(tool.implementation):
                    result = asyncio.run(tool.implementation(**tool_call.arguments))
                else:
                    result = tool.implementation(**tool_call.arguments)

                if isinstance(result, ToolOutput):
                    attachments = result.attachments
                    result = result.output

                if not isinstance(result, str):
                    result = json.dumps(result, default=repr)
            except Exception as ex:
                result = f"Error: {ex}"
                exception = ex

            tool_result_obj = ToolResult(
                name=tool_call.name,
                output=result,
                attachments=attachments,
                tool_call_id=tool_call.tool_call_id,
                instance=_get_instance(tool.implementation),
                exception=exception,
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
        "Return the list of tool calls made during this response."
        self._force()
        return self._tool_calls

    def tool_calls_or_raise(self) -> List[ToolCall]:
        return self.tool_calls()

    def json(self) -> Optional[Dict[str, Any]]:
        "Return the raw JSON response from the model, if available."
        self._force()
        return self.response_json

    def duration_ms(self) -> int:
        self._force()
        return int(((self._end or 0) - (self._start or 0)) * 1000)

    def datetime_utc(self) -> str:
        self._force()
        return self._start_utcnow.isoformat() if self._start_utcnow else ""

    def usage(self) -> Usage:
        "Return token usage information for this response."
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
            generator = self.model.execute(
                self.prompt,
                stream=self.stream,
                response=self,
                conversation=self.conversation,
            )
        elif isinstance(self.model, KeyModel):
            generator = self.model.execute(
                self.prompt,
                stream=self.stream,
                response=self,
                conversation=self.conversation,
                key=self.model.get_key(self._key),
            )
        else:
            raise Exception("self.model must be a Model or KeyModel")

        for chunk in generator:
            assert chunk is not None
            text = self._process_chunk(chunk)
            if text is not None:
                yield text

        if self.conversation:
            self.conversation.responses.append(self)
        self._end = time.monotonic()
        self._done = True
        self._on_done()

    def stream_events(self):
        "Yield StreamEvents for this response."
        from .parts import StreamEvent

        if self._done:
            if self._has_stream_events:
                yield from self._stream_events
            else:
                # Synthesize text events from plain chunks
                text = "".join(self._chunks)
                if text:
                    yield StreamEvent(type="text", chunk=text, part_index=0)
            return

        # Live streaming - process chunks and yield all events
        self._start = time.monotonic()
        self._start_utcnow = datetime.datetime.now(datetime.timezone.utc)

        if isinstance(self.model, Model):
            generator = self.model.execute(
                self.prompt,
                stream=self.stream,
                response=self,
                conversation=self.conversation,
            )
        elif isinstance(self.model, KeyModel):
            generator = self.model.execute(
                self.prompt,
                stream=self.stream,
                response=self,
                conversation=self.conversation,
                key=self.model.get_key(self._key),
            )
        else:
            raise Exception("self.model must be a Model or KeyModel")

        for chunk in generator:
            assert chunk is not None
            if isinstance(chunk, StreamEvent):
                self._has_stream_events = True
                self._stream_events.append(chunk)
                if chunk.type == "text":
                    self._chunks.append(chunk.chunk)
                yield chunk
            else:
                self._chunks.append(chunk)
                yield StreamEvent(type="text", chunk=chunk, part_index=0)

        if self.conversation:
            self.conversation.responses.append(self)
        self._end = time.monotonic()
        self._done = True
        self._on_done()

    @property
    def parts(self):
        "Return the list of Part objects for this response."
        if hasattr(self, "_loaded_parts") and self._loaded_parts is not None:
            return self._loaded_parts
        self._force()
        return self._build_parts()

    @property
    def messages(self):
        "Return the list of Message objects for this response."
        return _parts_to_messages(self.parts)

    def __repr__(self):
        text = "... not yet done ..."
        if self._done:
            text = "".join(self._chunks)
        return "<Response prompt='{}' text='{}'>".format(self.prompt.prompt, text)


class AsyncResponse(_BaseResponse):
    "Async response from a model."

    model: "AsyncModel"
    conversation: Optional["AsyncConversation"] = None

    @classmethod
    def from_row(cls, db, row, _async=False):
        return super().from_row(db, row, _async=True)

    async def on_done(self, callback):
        "Register a callback to be called when the response is complete."
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
        before_call: Optional[BeforeCallAsync] = None,
        after_call: Optional[AfterCallAsync] = None,
    ) -> List[ToolResult]:
        tool_calls_list = await self.tool_calls()
        tools_by_name = {tool.name: tool for tool in self.prompt.tools}

        # Run async prepare_async() on all Toolbox instances that need it
        instances_to_prepare: list[Toolbox] = []
        for tool_to_prep in tools_by_name.values():
            inst = _get_instance(tool_to_prep.implementation)
            if isinstance(inst, Toolbox) and not getattr(
                inst, "_async_prepared", False
            ):
                instances_to_prepare.append(inst)

        for inst in instances_to_prepare:
            await inst.prepare_async()
            inst._async_prepared = True

        indexed_results: List[tuple[int, ToolResult]] = []
        async_tasks: List[asyncio.Task] = []

        for idx, tc in enumerate(tool_calls_list):
            tool: Optional[Tool] = tools_by_name.get(tc.name)
            exception: Optional[Exception] = None

            if tool is None:
                output = f'Error: tool "{tc.name}" does not exist'
                exception = KeyError(tc.name)
            elif not tool.implementation:
                output = f'Error: tool "{tc.name}" has no implementation'
                exception = KeyError(tc.name)
            elif inspect.iscoroutinefunction(tool.implementation):

                async def run_async(tc=tc, tool=tool, idx=idx):
                    # before_call inside the task
                    if before_call:
                        try:
                            cb = before_call(tool, tc)
                            if inspect.isawaitable(cb):
                                await cb
                        except CancelToolCall as ex:
                            return idx, ToolResult(
                                name=tc.name,
                                output="Cancelled: " + str(ex),
                                tool_call_id=tc.tool_call_id,
                                exception=ex,
                            )

                    exception = None
                    attachments = []

                    try:
                        result = await tool.implementation(**tc.arguments)
                        if isinstance(result, ToolOutput):
                            attachments.extend(result.attachments)
                            result = result.output
                        output = (
                            result
                            if isinstance(result, str)
                            else json.dumps(result, default=repr)
                        )
                    except Exception as ex:
                        output = f"Error: {ex}"
                        exception = ex

                    tr = ToolResult(
                        name=tc.name,
                        output=output,
                        attachments=attachments,
                        tool_call_id=tc.tool_call_id,
                        instance=_get_instance(tool.implementation),
                        exception=exception,
                    )

                    # after_call inside the task
                    if tool is not None and after_call:
                        cb2 = after_call(tool, tc, tr)
                        if inspect.isawaitable(cb2):
                            await cb2

                    return idx, tr

                async_tasks.append(asyncio.create_task(run_async()))

            else:
                # Sync implementation: do hooks and call inline
                if before_call:
                    try:
                        cb = before_call(tool, tc)
                        if inspect.isawaitable(cb):
                            await cb
                    except CancelToolCall as ex:
                        indexed_results.append(
                            (
                                idx,
                                ToolResult(
                                    name=tc.name,
                                    output="Cancelled: " + str(ex),
                                    tool_call_id=tc.tool_call_id,
                                    exception=ex,
                                ),
                            )
                        )
                        continue

                exception = None
                attachments = []

                if tool is None:
                    output = f'Error: tool "{tc.name}" does not exist'
                    exception = KeyError(tc.name)
                else:
                    try:
                        res = tool.implementation(**tc.arguments)
                        if inspect.isawaitable(res):
                            res = await res
                        if isinstance(res, ToolOutput):
                            attachments.extend(res.attachments)
                            res = res.output
                        output = (
                            res
                            if isinstance(res, str)
                            else json.dumps(res, default=repr)
                        )
                    except Exception as ex:
                        output = f"Error: {ex}"
                        exception = ex

                    tr = ToolResult(
                        name=tc.name,
                        output=output,
                        attachments=attachments,
                        tool_call_id=tc.tool_call_id,
                        instance=_get_instance(tool.implementation),
                        exception=exception,
                    )

                    if tool is not None and after_call:
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

    def _ensure_generator(self):
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

    async def __anext__(self) -> str:
        if self._done:
            if hasattr(self, "_iter_chunks") and self._iter_chunks:
                return self._iter_chunks.pop(0)
            raise StopAsyncIteration

        self._ensure_generator()

        try:
            while True:
                chunk = await self._generator.__anext__()
                assert chunk is not None
                text = self._process_chunk(chunk)
                if text is not None:
                    return text
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
        "Return the full text of the response, executing the prompt if needed."
        await self._force()
        return "".join(self._chunks)

    async def tool_calls(self) -> List[ToolCall]:
        "Return the list of tool calls made during this response."
        await self._force()
        return self._tool_calls

    def tool_calls_or_raise(self) -> List[ToolCall]:
        if not self._done:
            raise ValueError("Response not yet awaited")
        return self._tool_calls

    async def json(self) -> Optional[Dict[str, Any]]:
        "Return the raw JSON response from the model, if available."
        await self._force()
        return self.response_json

    async def duration_ms(self) -> int:
        await self._force()
        return int(((self._end or 0) - (self._start or 0)) * 1000)

    async def datetime_utc(self) -> str:
        await self._force()
        return self._start_utcnow.isoformat() if self._start_utcnow else ""

    async def usage(self) -> Usage:
        "Return token usage information for this response."
        await self._force()
        return Usage(
            input=self.input_tokens,
            output=self.output_tokens,
            details=self.token_details,
        )

    async def astream_events(self):
        "Yield StreamEvents for this response (async)."
        from .parts import StreamEvent

        if self._done:
            if self._has_stream_events:
                for event in self._stream_events:
                    yield event
            else:
                text = "".join(self._chunks)
                if text:
                    yield StreamEvent(type="text", chunk=text, part_index=0)
            return

        # Live streaming
        self._start = time.monotonic()
        self._start_utcnow = datetime.datetime.now(datetime.timezone.utc)
        self._ensure_generator()

        try:
            while True:
                chunk = await self._generator.__anext__()
                assert chunk is not None
                if isinstance(chunk, StreamEvent):
                    self._has_stream_events = True
                    self._stream_events.append(chunk)
                    if chunk.type == "text":
                        self._chunks.append(chunk.chunk)
                    yield chunk
                else:
                    self._chunks.append(chunk)
                    yield StreamEvent(type="text", chunk=chunk, part_index=0)
        except StopAsyncIteration:
            if self.conversation:
                self.conversation.responses.append(self)
            self._end = time.monotonic()
            self._done = True
            if hasattr(self, "_generator"):
                del self._generator
            await self._on_done()

    @property
    def parts(self):
        "Return the list of Part objects for this response."
        if hasattr(self, "_loaded_parts") and self._loaded_parts is not None:
            return self._loaded_parts
        if not self._done:
            raise ValueError("Response not yet awaited - use 'await response' first")
        return self._build_parts()

    @property
    def messages(self):
        "Return the list of Message objects for this response."
        return _parts_to_messages(self.parts)

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
                self.conversation.to_sync_conversation() if self.conversation else None
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
        response.resolved_model = self.resolved_model
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
        chain_limit: Optional[int] = 10,
        before_call: Optional[Union[BeforeCallSync, BeforeCallAsync]] = None,
        after_call: Optional[Union[AfterCallSync, AfterCallAsync]] = None,
    ):
        self.prompt = prompt
        self.model = model
        self.stream = stream
        self._key = key
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
    before_call: Optional[BeforeCallSync] = None
    after_call: Optional[AfterCallSync] = None

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
            attachments = []
            for tool_result in tool_results:
                attachments.extend(tool_result.attachments)
            if tool_results:
                current_response = Response(
                    Prompt(
                        "",  # Next prompt is empty, tools drive it
                        self.model,
                        tools=current_response.prompt.tools,
                        tool_results=tool_results,
                        options=self.prompt.options,
                        attachments=attachments,
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

    def stream_events(self):
        "Yield StreamEvents from all responses in the chain."
        for response_item in self.responses():
            yield from response_item.stream_events()

    def text(self) -> str:
        return "".join(self)


class AsyncChainResponse(_BaseChainResponse):
    _responses: List["AsyncResponse"]
    before_call: Optional[BeforeCallAsync] = None
    after_call: Optional[AfterCallAsync] = None

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
                attachments = []
                for tool_result in tool_results:
                    attachments.extend(tool_result.attachments)
                prompt = Prompt(
                    "",
                    self.model,
                    tools=current_response.prompt.tools,
                    tool_results=tool_results,
                    options=self.prompt.options,
                    attachments=attachments,
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

    async def astream_events(self):
        "Yield StreamEvents from all responses in the chain."
        async for response_item in self.responses():
            async for event in response_item.astream_events():
                yield event

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
    def conversation(
        self,
        tools: Optional[List[ToolDef]] = None,
        before_call: Optional[BeforeCallSync] = None,
        after_call: Optional[AfterCallSync] = None,
        chain_limit: Optional[int] = None,
    ) -> Conversation:
        return Conversation(
            model=self,
            tools=tools,
            before_call=before_call,
            after_call=after_call,
            chain_limit=chain_limit,
        )

    def prompt(
        self,
        prompt: Optional[str] = None,
        *,
        parts: Optional[List[Any]] = None,
        messages: Optional[List[Any]] = None,
        fragments: Optional[List[Union[str, Fragment]]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        system_fragments: Optional[List[Union[str, Fragment]]] = None,
        stream: bool = True,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        **options,
    ) -> Response:
        key_value = options.pop("key", None)
        self._validate_attachments(attachments)
        return Response(
            Prompt(
                prompt,
                parts=parts,
                messages=messages,
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
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        before_call: Optional[BeforeCallSync] = None,
        after_call: Optional[AfterCallSync] = None,
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
    ) -> Iterator[Union[str, "StreamEvent"]]:
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
    ) -> Iterator[Union[str, "StreamEvent"]]:
        pass


class _AsyncModel(_BaseModel):
    def conversation(
        self,
        tools: Optional[List[ToolDef]] = None,
        before_call: Optional[BeforeCallAsync] = None,
        after_call: Optional[AfterCallAsync] = None,
        chain_limit: Optional[int] = None,
    ) -> AsyncConversation:
        return AsyncConversation(
            model=self,
            tools=tools,
            before_call=before_call,
            after_call=after_call,
            chain_limit=chain_limit,
        )

    def prompt(
        self,
        prompt: Optional[str] = None,
        *,
        parts: Optional[List[Any]] = None,
        messages: Optional[List[Any]] = None,
        fragments: Optional[List[Union[str, Fragment]]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        system_fragments: Optional[List[Union[str, Fragment]]] = None,
        stream: bool = True,
        **options,
    ) -> AsyncResponse:
        key_value = options.pop("key", None)
        self._validate_attachments(attachments)
        return AsyncResponse(
            Prompt(
                prompt,
                parts=parts,
                messages=messages,
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
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        before_call: Optional[BeforeCallAsync] = None,
        after_call: Optional[AfterCallAsync] = None,
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
    ) -> AsyncGenerator[Union[str, "StreamEvent"], None]:
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
    ) -> AsyncGenerator[Union[str, "StreamEvent"], None]:
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
    "A model with its optional async counterpart and aliases."

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


def _ensure_dict_schema(schema):
    """Convert a Pydantic model to a JSON schema dict if needed."""
    if schema and not isinstance(schema, dict) and issubclass(schema, BaseModel):
        schema_dict = schema.model_json_schema()
        _remove_titles_recursively(schema_dict)
        return schema_dict
    return schema


def _remove_titles_recursively(obj):
    """Recursively remove all 'title' fields from a nested dictionary."""
    if isinstance(obj, dict):
        # Remove title if present
        obj.pop("title", None)

        # Recursively process all values
        for value in obj.values():
            _remove_titles_recursively(value)
    elif isinstance(obj, list):
        # Process each item in lists
        for item in obj:
            _remove_titles_recursively(item)


def _get_instance(implementation):
    if hasattr(implementation, "__self__"):
        return implementation.__self__
    return None
