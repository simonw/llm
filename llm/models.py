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
    TYPE_CHECKING,
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
    cast,
    get_type_hints,
)
from .serialization import ResponseDict

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
    hide_reasoning: bool

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
        messages=None,
        hide_reasoning=False,
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
        self.hide_reasoning = hide_reasoning
        # Explicit messages= list, if the caller supplied one. Copied so
        # later mutation by the caller doesn't alter the Prompt.
        self._explicit_messages = list(messages) if messages is not None else None

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
    def messages(self):
        """Canonical list of Message objects for this prompt.

        **Invariant:** this property returns exactly what the model
        was (or will be) sent for this turn — the full chain including
        any prior conversation history.

        - If ``messages=`` was passed explicitly, it is authoritative:
          returned verbatim. Other kwargs (``prompt=``, ``system=``,
          ``attachments=``, ``tool_results=``) are ignored for the
          messages list (they remain available via ``prompt.prompt``,
          ``prompt.system``, etc., for adapters that still read them).
        - Otherwise the list is synthesized from the legacy kwargs
          (system, tool_results, prompt, attachments), producing just
          the current turn — prior history is not folded in, because
          no conversation context is reachable here.

        Conversation.prompt / AsyncConversation.prompt / reply() all
        pre-compute the full chain and pass it as ``messages=``, so
        ``response.prompt.messages`` after those paths is the full
        chain.
        """
        from .parts import (
            AttachmentPart,
            Message,
            TextPart,
            ToolResultPart,
        )

        if self._explicit_messages is not None:
            return list(self._explicit_messages)

        result: List["Message"] = []

        if self.system:
            result.append(Message(role="system", parts=[TextPart(text=self.system)]))

        if self.tool_results:
            result.append(
                Message(
                    role="tool",
                    parts=[
                        ToolResultPart(
                            name=tr.name,
                            output=tr.output,
                            tool_call_id=tr.tool_call_id,
                        )
                        for tr in self.tool_results
                    ],
                )
            )

        user_parts: List[Any] = []
        if self.prompt:
            user_parts.append(TextPart(text=self.prompt))
        for att in self.attachments:
            user_parts.append(AttachmentPart(attachment=att))
        if user_parts:
            result.append(Message(role="user", parts=user_parts))

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


def _merge_options(options: Optional[dict], kwargs: dict) -> dict:
    if not options:
        return kwargs
    overlap = set(options) & set(kwargs)
    if overlap:
        raise TypeError(
            "Got values for these options both in options= and as keyword "
            "arguments: {}".format(sorted(overlap))
        )
    return {**options, **kwargs}


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

    def _build_full_chain(
        self,
        prompt: Optional[str],
        attachments,
        tool_results,
        explicit_messages,
    ) -> List[Any]:
        """Build the full message chain for the next turn.

        Uses the last response's stored prompt chain to recover prior
        history, then appends the new turn's content (explicit messages
        first, or synthesized from prompt/attachments/tool_results).

        Returns the list that should be passed as ``messages=`` to the
        Prompt constructor so that ``response.prompt.messages`` equals
        exactly what the model sees.

        If ``explicit_messages`` is provided, the caller has opted out
        of history reconstruction and the list is used as-is.
        """
        from .parts import (
            AttachmentPart,
            Message,
            TextPart,
            ToolResultPart,
        )

        if explicit_messages is not None:
            return list(explicit_messages)

        chain: List[Any] = []
        if self.responses:
            last = self.responses[-1]
            # last.prompt.messages already contains the full input chain
            # under the invariant, so use the last response only and then
            # append that response's structured output.
            chain.extend(last.prompt.messages)
            chain.extend(last._messages_now())

        # Append the new turn's input
        if tool_results:
            chain.append(
                Message(
                    role="tool",
                    parts=[
                        ToolResultPart(
                            name=tr.name,
                            output=tr.output,
                            tool_call_id=tr.tool_call_id,
                        )
                        for tr in tool_results
                    ],
                )
            )

        user_parts: List[Any] = []
        if prompt:
            user_parts.append(TextPart(text=prompt))
        for att in attachments or []:
            user_parts.append(AttachmentPart(attachment=att))
        if user_parts:
            chain.append(Message(role="user", parts=user_parts))

        return chain


@dataclass
class Conversation(_BaseConversation):
    before_call: Optional[BeforeCallSync] = None
    after_call: Optional[AfterCallSync] = None

    def prompt(
        self,
        prompt: Optional[str] = None,
        *,
        fragments: Optional[List[Union[str, Fragment]]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        system_fragments: Optional[List[Union[str, Fragment]]] = None,
        messages: Optional[List[Any]] = None,
        stream: bool = True,
        key: Optional[str] = None,
        options: Optional[dict] = None,
        hide_reasoning: bool = False,
        **kwargs,
    ) -> "Response":
        merged = _merge_options(options, kwargs)
        # Build the authoritative chain so response.prompt.messages
        # equals exactly what the model sees for this turn.
        chain = self._build_full_chain(
            prompt=prompt,
            attachments=attachments,
            tool_results=tool_results,
            explicit_messages=messages,
        )
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
                messages=chain,
                options=self.model.Options(**merged),
                hide_reasoning=hide_reasoning,
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
        messages: Optional[List[Any]] = None,
        stream: bool = True,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        chain_limit: Optional[int] = None,
        before_call: Optional[BeforeCallSync] = None,
        after_call: Optional[AfterCallSync] = None,
        key: Optional[str] = None,
        options: Optional[dict] = None,
        hide_reasoning: bool = False,
    ) -> "ChainResponse":
        self.model._validate_attachments(attachments)
        # Parity with Conversation.prompt: pre-bake the full chain so
        # response.prompt.messages is authoritative for the first turn
        # of the chain loop. Subsequent tool-result turns extend the
        # chain via _chain_for_tool_results.
        chain_messages = self._build_full_chain(
            prompt=prompt,
            attachments=attachments,
            tool_results=tool_results,
            explicit_messages=messages,
        )
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
                messages=chain_messages,
                model=self.model,
                options=self.model.Options(**(options or {})),
                hide_reasoning=hide_reasoning,
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
        messages: Optional[List[Any]] = None,
        stream: bool = True,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        chain_limit: Optional[int] = None,
        before_call: Optional[BeforeCallAsync] = None,
        after_call: Optional[AfterCallAsync] = None,
        key: Optional[str] = None,
        options: Optional[dict] = None,
        hide_reasoning: bool = False,
    ) -> "AsyncChainResponse":
        self.model._validate_attachments(attachments)
        chain_messages = self._build_full_chain(
            prompt=prompt,
            attachments=attachments,
            tool_results=tool_results,
            explicit_messages=messages,
        )
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
                messages=chain_messages,
                model=self.model,
                options=self.model.Options(**(options or {})),
                hide_reasoning=hide_reasoning,
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
        fragments: Optional[List[str]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        system_fragments: Optional[List[str]] = None,
        messages: Optional[List[Any]] = None,
        stream: bool = True,
        key: Optional[str] = None,
        options: Optional[dict] = None,
        hide_reasoning: bool = False,
        **kwargs,
    ) -> "AsyncResponse":
        merged = _merge_options(options, kwargs)
        chain = self._build_full_chain(
            prompt=prompt,
            attachments=attachments,
            tool_results=tool_results,
            explicit_messages=messages,
        )
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
                messages=chain,
                options=self.model.Options(**merged),
                hide_reasoning=hide_reasoning,
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
        self.model = model
        self.stream = stream
        self._key = key
        self._chunks: List[str] = []
        # Every StreamEvent ever yielded by execute(), in order. Plain
        # str yields are wrapped as text events (with part_index resolved
        # by _resolve_part_index) so this buffer is the single source of
        # truth for replay and for assembling response.messages.
        self._stream_events: List[Any] = []
        # Auto-allocator state for resolving StreamEvent.part_index=None.
        # Plugins yield events with part_index=None (the default) and
        # the framework assigns concrete integers based on context:
        # consecutive same-family text/reasoning events concatenate,
        # tool calls group by tool_call_id, and tool_result is always
        # its own part. _auto_index_max tracks the highest index seen
        # (explicit or allocated); _auto_last_index / _auto_last_family
        # remember the previously-resolved event so same-family runs
        # share an index; _auto_tool_id_to_index maps known tool ids to
        # their assigned index for parallel-tool-call grouping.
        self._auto_index_max: int = -1
        self._auto_last_index: Optional[int] = None
        self._auto_last_family: Optional[str] = None
        self._auto_tool_id_to_index: Dict[str, int] = {}
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

    def _messages_now(self) -> List[Any]:
        """Assemble messages assuming the response is already drained.

        Public ``messages()`` forces / awaits first, then delegates here.
        Internal sync paths (``_response_to_dict``,
        ``_chain_for_tool_results``) call this directly so they don't
        have to await on async responses.
        """
        from .parts import Message

        loaded = getattr(self, "_loaded_messages", None)
        if loaded is not None:
            return list(loaded)
        parts = self._build_parts()
        if not parts:
            return []
        return [Message(role="assistant", parts=parts)]

    @staticmethod
    def _event_family(event_type: str) -> str:
        if event_type in ("tool_call_name", "tool_call_args"):
            return "tool_call"
        return event_type

    def _resolve_part_index(self, event):
        """Mutate event.part_index in place when the plugin left it None.

        Resolution rules: consecutive same-family text/reasoning events
        share an index; tool-call events are grouped by tool_call_id;
        tool_result always allocates a fresh index. Explicit indices
        pass through but update the allocator's bookkeeping so future
        None resolutions avoid collisions.
        """
        fam = self._event_family(event.type)

        if event.part_index is not None:
            if event.part_index > self._auto_index_max:
                self._auto_index_max = event.part_index
            if (
                event.type in ("tool_call_name", "tool_call_args")
                and event.tool_call_id
            ):
                self._auto_tool_id_to_index[event.tool_call_id] = event.part_index
            self._auto_last_index = event.part_index
            self._auto_last_family = fam
            return

        if event.type in ("tool_call_name", "tool_call_args"):
            if event.tool_call_id:
                existing = self._auto_tool_id_to_index.get(event.tool_call_id)
                if existing is not None:
                    event.part_index = existing
                    self._auto_last_index = existing
                    self._auto_last_family = "tool_call"
                    return
                self._auto_index_max += 1
                new_idx = self._auto_index_max
                self._auto_tool_id_to_index[event.tool_call_id] = new_idx
                event.part_index = new_idx
                self._auto_last_index = new_idx
                self._auto_last_family = "tool_call"
                return
            # No tool_call_id — providers like Gemini omit the id on
            # parallel tool calls. tool_call_args events glue onto the
            # most recent tool-call index; a fresh tool_call_name
            # always starts a new part (otherwise N parallel tool calls
            # collapse into one with concatenated names and args).
            if (
                event.type == "tool_call_args"
                and self._auto_last_family == "tool_call"
                and self._auto_last_index is not None
            ):
                event.part_index = self._auto_last_index
                return
            self._auto_index_max += 1
            new_idx = self._auto_index_max
            event.part_index = new_idx
            self._auto_last_index = new_idx
            self._auto_last_family = "tool_call"
            return

        if event.type == "tool_result":
            self._auto_index_max += 1
            new_idx = self._auto_index_max
            event.part_index = new_idx
            self._auto_last_index = new_idx
            self._auto_last_family = "tool_result"
            return

        # text / reasoning: same family as previous → reuse, else new.
        if self._auto_last_family == fam and self._auto_last_index is not None:
            event.part_index = self._auto_last_index
            return
        self._auto_index_max += 1
        new_idx = self._auto_index_max
        event.part_index = new_idx
        self._auto_last_index = new_idx
        self._auto_last_family = fam

    def _process_chunk(self, chunk):
        """Normalize a chunk from execute() into a StreamEvent and return
        the text str (or None) that __iter__ should yield.

        Plain str yields from legacy plugins are wrapped as text events
        with an auto-allocated part_index. Side effects: populates
        self._stream_events and self._chunks.
        """
        from .parts import StreamEvent

        if isinstance(chunk, StreamEvent):
            self._resolve_part_index(chunk)
            self._stream_events.append(chunk)
            if chunk.type == "text":
                self._chunks.append(chunk.chunk)
                return chunk.chunk
            return None
        # Legacy plain-str plugin.
        event = StreamEvent(type="text", chunk=chunk)
        self._resolve_part_index(event)
        self._stream_events.append(event)
        self._chunks.append(chunk)
        return chunk

    def _build_parts(self) -> List[Any]:
        """Assemble Part objects from the accumulated stream events.

        Events sharing a part_index group into one Part. Mixing
        families (text vs tool_call vs reasoning vs tool_result) at the
        same index is a plugin bug — raises ValueError instead of
        silently dropping content.

        Fallback: when no stream events were recorded (response was
        rehydrated from SQLite via ``from_row``), synthesize a
        TextPart from ``self._chunks`` plus any ``self._tool_calls``
        restored by the row loader. Reasoning signatures are not
        recoverable from SQLite in this fallback — use
        ``response.to_dict()`` / ``Response.from_dict()`` for
        structure-preserving persistence.
        """
        from .parts import (
            ReasoningPart,
            TextPart,
            ToolCallPart,
            ToolResultPart,
        )

        if not self._stream_events:
            # Rehydrated-from-SQLite path: assemble from _chunks +
            # _tool_calls so response.messages isn't empty after
            # from_row, and Conversation.prompt-built chains include
            # the assistant turn on follow-up calls.
            fallback_parts: List[Any] = []
            text = "".join(self._chunks)
            if text:
                fallback_parts.append(TextPart(text=text))
            for tc in self._tool_calls:
                fallback_parts.append(
                    ToolCallPart(
                        name=tc.name,
                        arguments=tc.arguments or {},
                        tool_call_id=tc.tool_call_id,
                    )
                )
            return fallback_parts

        # Group events by their (resolved) part_index, preserving the
        # order in which each index was first seen. Then build one Part
        # per group. This handles non-adjacent same-index events (e.g.
        # text → tool_call → text where the plugin pinned both text
        # bursts to part_index=0) by merging them into one Part.
        groups: Dict[int, List[Any]] = {}
        order: List[int] = []
        for event in self._stream_events:
            pi = event.part_index
            if pi not in groups:
                groups[pi] = []
                order.append(pi)
            groups[pi].append(event)

        parts: List[Any] = []
        for pi in order:
            evs = groups[pi]
            fam_first = self._event_family(evs[0].type)
            for e in evs:
                if self._event_family(e.type) != fam_first:
                    raise ValueError(
                        f"StreamEvent type {e.type!r} is incompatible with "
                        f"prior type at part_index={pi}. "
                        "Allocate a new part_index for a different content type."
                    )

            pm_merged: Optional[Dict[str, Any]] = None
            for e in evs:
                if e.provider_metadata:
                    merged = dict(pm_merged) if pm_merged else {}
                    for k, v in e.provider_metadata.items():
                        merged[k] = v
                    pm_merged = merged

            if fam_first == "text":
                text = "".join(e.chunk for e in evs)
                if text:
                    parts.append(TextPart(text=text, provider_metadata=pm_merged))
            elif fam_first == "reasoning":
                text = "".join(e.chunk for e in evs)
                redacted = any(e.redacted for e in evs)
                if text or redacted:
                    parts.append(
                        ReasoningPart(
                            text=text,
                            redacted=redacted,
                            provider_metadata=pm_merged,
                        )
                    )
            elif fam_first == "tool_call":
                tool_name = "".join(e.chunk for e in evs if e.type == "tool_call_name")
                args_str = "".join(e.chunk for e in evs if e.type == "tool_call_args")
                try:
                    arguments = json.loads(args_str) if args_str else {}
                except json.JSONDecodeError:
                    arguments = {"_raw": args_str}
                tool_call_id = next(
                    (e.tool_call_id for e in evs if e.tool_call_id), None
                )
                server_executed = any(e.server_executed for e in evs)
                parts.append(
                    ToolCallPart(
                        name=tool_name,
                        arguments=arguments,
                        tool_call_id=tool_call_id,
                        server_executed=server_executed,
                        provider_metadata=pm_merged,
                    )
                )
            elif fam_first == "tool_result":
                tool_result_name = next((e.tool_name for e in evs if e.tool_name), "")
                tool_call_id = next(
                    (e.tool_call_id for e in evs if e.tool_call_id), None
                )
                server_executed = any(e.server_executed for e in evs)
                parts.append(
                    ToolResultPart(
                        name=tool_result_name,
                        output="".join(e.chunk for e in evs),
                        tool_call_id=tool_call_id,
                        server_executed=server_executed,
                        provider_metadata=pm_merged,
                    )
                )

        # Merge in any tool calls registered via add_tool_call() that the
        # plugin didn't also emit as StreamEvents. Dedup by tool_call_id so
        # plugins using both APIs in tandem don't double-count.
        seen_ids = {
            p.tool_call_id
            for p in parts
            if isinstance(p, ToolCallPart) and p.tool_call_id is not None
        }
        for tc in self._tool_calls:
            if tc.tool_call_id is not None and tc.tool_call_id in seen_ids:
                continue
            parts.append(
                ToolCallPart(
                    name=tc.name,
                    arguments=tc.arguments or {},
                    tool_call_id=tc.tool_call_id,
                )
            )

        # Hoist redacted reasoning Parts to the start of the assembled
        # message. Plugins typically emit them late (when usage arrives
        # in the final chunk), but UIs render reasoning before content,
        # so the framework reorders. Relative order among redacted
        # Parts is preserved.
        redacted_parts = [
            p for p in parts if isinstance(p, ReasoningPart) and p.redacted
        ]
        if redacted_parts:
            other_parts = [
                p for p in parts if not (isinstance(p, ReasoningPart) and p.redacted)
            ]
            parts = redacted_parts + other_parts

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
        # Concatenate visible reasoning text from the assembled
        # ReasoningPart entries; redacted markers contribute nothing.
        from .parts import ReasoningPart

        reasoning_text = "".join(
            p.text
            for m in self._messages_now()
            for p in m.parts
            if isinstance(p, ReasoningPart) and p.text
        )
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
            "reasoning": reasoning_text or None,
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


def _response_to_dict(response: "_BaseResponse") -> ResponseDict:
    """Shared serializer for Response.to_dict / AsyncResponse.to_dict.

    The output is a JSON-safe dict — store it anywhere (file, Redis,
    Postgres, HTTP body) and round-trip via Response.from_dict or
    AsyncResponse.from_dict.
    """
    options = {
        key: value
        for key, value in dict(response.prompt.options).items()
        if value is not None
    }
    payload: Dict[str, Any] = {
        "model": response.model.model_id,
        "prompt": {
            "messages": [m.to_dict() for m in response.prompt.messages],
        },
        "messages": [m.to_dict() for m in response._messages_now()],
    }
    if options:
        payload["prompt"]["options"] = options
    if response.prompt._system:
        payload["prompt"]["system"] = response.prompt._system
    # Optional audit fields — helpful for debugging, not needed for reply().
    if response.id:
        payload["id"] = response.id
    if response._done:
        if response.input_tokens is not None or response.output_tokens is not None:
            usage: Dict[str, Any] = {}
            if response.input_tokens is not None:
                usage["input"] = response.input_tokens
            if response.output_tokens is not None:
                usage["output"] = response.output_tokens
            if response.token_details is not None:
                usage["details"] = response.token_details
            payload["usage"] = usage
        if response._start_utcnow is not None:
            payload["datetime_utc"] = response._start_utcnow.isoformat()
    return cast(ResponseDict, payload)


def _response_from_dict(
    data: ResponseDict,
    cls,
    *,
    model=None,
    async_: bool = False,
) -> "_BaseResponse":
    """Shared deserializer for Response.from_dict / AsyncResponse.from_dict."""
    from .parts import Message

    if model is None:
        from llm import get_async_model, get_model

        getter = get_async_model if async_ else get_model
        model = getter(data["model"])

    prompt_data = data.get("prompt", {})
    input_messages = [Message.from_dict(m) for m in prompt_data.get("messages", [])]
    output_messages = [Message.from_dict(m) for m in data.get("messages", [])]

    options_kwargs = prompt_data.get("options") or {}
    system = prompt_data.get("system")

    prompt = Prompt(
        None,
        model=model,
        messages=input_messages,
        system=system,
        options=model.Options(**options_kwargs),
    )
    response = cls(prompt, model=model, stream=False)
    # Preserve id for audit continuity.
    if "id" in data:
        response.id = data["id"]
    # Rebuild chunks from the assistant's text parts so response.text()
    # works without re-running the assembler.
    from .parts import TextPart

    response._chunks = [
        p.text
        for m in output_messages
        for p in m.parts
        if isinstance(p, TextPart) and p.text
    ]
    # Stash the structured output so response.messages returns the
    # full picture (reasoning, tool calls, signatures) without needing
    # a StreamEvent replay.
    response._loaded_messages = output_messages
    response._done = True
    # Restore usage if present.
    usage = data.get("usage")
    if usage:
        response.input_tokens = usage.get("input")
        response.output_tokens = usage.get("output")
        response.token_details = usage.get("details")
    return response


class Response(_BaseResponse):
    "Sync response from a model."

    model: "Model"
    conversation: Optional["Conversation"] = None

    def reply(
        self,
        prompt: Optional[str] = None,
        *,
        messages: Optional[List[Any]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        options: Optional[dict] = None,
        **kwargs,
    ) -> "Response":
        """Continue the conversation from this response.

        Builds the next turn's chain as
        ``self.prompt.messages + self.messages + [tool_message] +
        [user(prompt)] + messages`` and calls
        ``self.model.prompt(messages=chain, ...)``.

        If this response made tool calls and ``tool_results=`` is not
        passed, ``reply()`` runs ``self.execute_tool_calls()``
        automatically and threads the results into the chain. Pass an
        explicit ``tool_results=`` list (e.g. results you mutated, or
        synthetic ones for testing) to skip auto-execution.
        """
        from .parts import Message, TextPart, ToolResultPart

        self._force()
        if tool_results is None and self._tool_calls:
            tool_results = self.execute_tool_calls()
        # Forward original tools so the next turn can call them again
        # (mirrors Conversation.prompt's `tools or self.tools` rule).
        if "tools" not in kwargs and self.prompt.tools:
            kwargs["tools"] = self.prompt.tools
        chain: List[Any] = list(self.prompt.messages) + list(self._messages_now())
        if tool_results:
            chain.append(
                Message(
                    role="tool",
                    parts=[
                        ToolResultPart(
                            name=tr.name,
                            output=tr.output,
                            tool_call_id=tr.tool_call_id,
                        )
                        for tr in tool_results
                    ],
                )
            )
        if prompt:
            chain.append(Message(role="user", parts=[TextPart(text=prompt)]))
        if messages:
            chain.extend(messages)
        return self.model.prompt(messages=chain, options=options, **kwargs)

    def to_dict(self) -> ResponseDict:
        """Serialize this response for JSON persistence.

        Captures exactly what is needed to continue the conversation:
        model id, the input chain that was sent
        (``response.prompt.messages``), the structured assistant output
        (``response.messages``), and any explicit options. Pair with
        :meth:`Response.from_dict` to rehydrate and
        :meth:`Response.reply` to continue.

        Returns :class:`~llm.serialization.ResponseDict`.
        """
        return _response_to_dict(self)

    @classmethod
    def from_dict(
        cls,
        data: ResponseDict,
        *,
        model: Optional["Model"] = None,
    ) -> "Response":
        """Rehydrate a Response from a ``to_dict()`` payload.

        The returned Response is in the ``_done`` state with
        ``response.text()`` and ``response.messages`` populated.
        ``model`` overrides the stored model id (useful for continuing
        on a different model).
        """
        return cast(
            "Response", _response_from_dict(data, cls, model=model, async_=False)
        )

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

    def _iter_events(self):
        """Drive self.model.execute() once and yield each raw chunk it
        produces. Callers normalize chunks through _process_chunk.
        """
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
            yield chunk

    def __iter__(self) -> Iterator[str]:
        self._start = time.monotonic()
        self._start_utcnow = datetime.datetime.now(datetime.timezone.utc)
        if self._done:
            yield from self._chunks
            return

        for chunk in self._iter_events():
            text = self._process_chunk(chunk)
            if text is not None:
                yield text

        if self.conversation:
            self.conversation.responses.append(self)
        self._end = time.monotonic()
        self._done = True
        self._on_done()

    def stream_events(self):
        """Yield StreamEvent objects as the model produces them.

        Whichever of __iter__ and stream_events runs first during live
        streaming consumes the underlying generator. After completion,
        both work — each replays from its own buffer.
        """
        if self._done:
            yield from self._stream_events
            return

        self._start = time.monotonic()
        self._start_utcnow = datetime.datetime.now(datetime.timezone.utc)
        for chunk in self._iter_events():
            # _process_chunk appends to self._stream_events; use it as
            # the canonical source for what to yield so the replay path
            # matches the live path byte-for-byte.
            self._process_chunk(chunk)
            yield self._stream_events[-1]

        if self.conversation:
            self.conversation.responses.append(self)
        self._end = time.monotonic()
        self._done = True
        self._on_done()

    def messages(self) -> List[Any]:
        """List of Message objects produced by this response.

        Almost always a single assistant Message; multiple messages are
        possible for providers that emit multi-message responses during
        server-side tool execution.

        Forces execution if the response has not yet been drained, so
        ``response.messages()`` is safe to call without a prior
        ``response.text()`` / iteration.

        Responses rehydrated via ``Response.from_dict`` short-circuit
        and return the stored messages directly.
        """
        self._force()
        return self._messages_now()

    def __repr__(self):
        text = "... not yet done ..."
        if self._done:
            text = "".join(self._chunks)
        return "<Response prompt='{}' text='{}'>".format(self.prompt.prompt, text)


class AsyncResponse(_BaseResponse):
    "Async response from a model."

    model: "AsyncModel"
    conversation: Optional["AsyncConversation"] = None

    async def reply(
        self,
        prompt: Optional[str] = None,
        *,
        messages: Optional[List[Any]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        options: Optional[dict] = None,
        **kwargs,
    ) -> "AsyncResponse":
        """Async counterpart of Response.reply(). Requires this response
        to have been awaited (so self.messages is available).

        Awaitable so the auto-execute path can ``await
        self.execute_tool_calls()``. See ``Response.reply`` for the
        ``tool_results=`` semantics.
        """
        from .parts import Message, TextPart, ToolResultPart

        if not self._done:
            raise ValueError(
                "Response not yet awaited — call `await response` before reply()"
            )
        if tool_results is None and self._tool_calls:
            tool_results = await self.execute_tool_calls()
        if "tools" not in kwargs and self.prompt.tools:
            kwargs["tools"] = self.prompt.tools
        chain: List[Any] = list(self.prompt.messages) + list(self._messages_now())
        if tool_results:
            chain.append(
                Message(
                    role="tool",
                    parts=[
                        ToolResultPart(
                            name=tr.name,
                            output=tr.output,
                            tool_call_id=tr.tool_call_id,
                        )
                        for tr in tool_results
                    ],
                )
            )
        if prompt:
            chain.append(Message(role="user", parts=[TextPart(text=prompt)]))
        if messages:
            chain.extend(messages)
        return self.model.prompt(messages=chain, options=options, **kwargs)

    def to_dict(self) -> ResponseDict:
        """Async counterpart of Response.to_dict(). Requires awaiting."""
        if not self._done:
            raise ValueError(
                "Response not yet awaited — call `await response` before to_dict()"
            )
        return _response_to_dict(self)

    @classmethod
    def from_dict(
        cls,
        data: ResponseDict,
        *,
        model: Optional["AsyncModel"] = None,
    ) -> "AsyncResponse":
        """Async counterpart of Response.from_dict()."""
        return cast(
            "AsyncResponse", _response_from_dict(data, cls, model=model, async_=True)
        )

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

    def _ensure_async_generator(self):
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

    async def _async_finalize(self):
        if self.conversation:
            self.conversation.responses.append(self)
        self._end = time.monotonic()
        self._done = True
        if hasattr(self, "_generator"):
            del self._generator
        await self._on_done()

    async def __anext__(self) -> str:
        if self._done:
            if hasattr(self, "_iter_chunks") and self._iter_chunks:
                return self._iter_chunks.pop(0)
            raise StopAsyncIteration

        self._ensure_async_generator()
        # Skip non-text events — iteration yields only text. Loop until
        # we find a text chunk or the generator is exhausted.
        while True:
            try:
                chunk = await self._generator.__anext__()
            except StopAsyncIteration:
                await self._async_finalize()
                raise
            assert chunk is not None
            text = self._process_chunk(chunk)
            if text is not None:
                return text

    async def astream_events(self):
        """Yield StreamEvent objects as the model produces them (async)."""
        if self._done:
            for event in self._stream_events:
                yield event
            return

        self._start = time.monotonic()
        self._start_utcnow = datetime.datetime.now(datetime.timezone.utc)
        self._ensure_async_generator()
        try:
            while True:
                try:
                    chunk = await self._generator.__anext__()
                except StopAsyncIteration:
                    await self._async_finalize()
                    return
                assert chunk is not None
                self._process_chunk(chunk)
                yield self._stream_events[-1]
        finally:
            pass

    async def messages(self) -> List[Any]:
        """List of Message objects produced by this response.

        Awaits ``self._force()`` so ``await response.messages()`` is
        safe to call without first awaiting ``response.text()`` or
        iterating the stream. Responses rehydrated via
        ``AsyncResponse.from_dict`` short-circuit and return the
        stored messages.
        """
        await self._force()
        return self._messages_now()

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


def _chain_for_tool_results(prior_response, tool_results, attachments) -> List[Any]:
    """Build the message chain for a tool-result turn in a chain loop.

    Takes the prior response's full input chain + its structured
    output, then appends a tool-role message carrying the new
    ToolResult outputs. Attachments (e.g. images returned by tools)
    are folded into a subsequent user-role message.

    This is what gives ``response.prompt.messages`` on the tool-
    result turn the complete history for the next provider call —
    including any reasoning signatures or thoughtSignatures from the
    prior turn.
    """
    from .parts import (
        AttachmentPart,
        Message,
        ToolResultPart,
    )

    chain: List[Any] = list(prior_response.prompt.messages) + list(
        prior_response._messages_now()
    )
    if tool_results:
        chain.append(
            Message(
                role="tool",
                parts=[
                    ToolResultPart(
                        name=tr.name,
                        output=tr.output,
                        tool_call_id=tr.tool_call_id,
                    )
                    for tr in tool_results
                ],
            )
        )
    # Attachments that came back from tools ride on a trailing user
    # message (mimics the legacy attachments=[] kwarg behavior).
    if attachments:
        chain.append(
            Message(
                role="user",
                parts=[AttachmentPart(attachment=a) for a in attachments],
            )
        )
    return chain


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
                # Pre-bake the full chain for the tool-result turn so
                # response.prompt.messages is what gets sent — carries
                # thoughtSignatures, thinking signatures, and everything
                # else the model needs for the next call.
                next_chain = _chain_for_tool_results(
                    current_response, tool_results, attachments
                )
                current_response = Response(
                    Prompt(
                        "",  # Next prompt text is empty; tool_results drive it
                        self.model,
                        tools=current_response.prompt.tools,
                        tool_results=tool_results,
                        messages=next_chain,
                        # Carry system + system_fragments forward so
                        # stateless-per-turn adapters (OpenAI and
                        # friends that read prompt.system directly)
                        # keep seeing the system prompt on every call
                        # of the chain loop.
                        system=self.prompt._system,
                        system_fragments=self.prompt.system_fragments,
                        options=self.prompt.options,
                        attachments=attachments,
                        hide_reasoning=current_response.prompt.hide_reasoning,
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
        "Yield StreamEvents from every response in the chain."
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
                # Pre-bake chain so prompt.messages carries full history
                # + any thinking/tool-call signatures from prior turn.
                next_chain = _chain_for_tool_results(
                    current_response, tool_results, attachments
                )
                prompt = Prompt(
                    "",
                    self.model,
                    tools=current_response.prompt.tools,
                    tool_results=tool_results,
                    messages=next_chain,
                    # Carry system + system_fragments forward — same
                    # reasoning as the sync path.
                    system=self.prompt._system,
                    system_fragments=self.prompt.system_fragments,
                    options=self.prompt.options,
                    attachments=attachments,
                    hide_reasoning=current_response.prompt.hide_reasoning,
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
        "Yield StreamEvents from every response in the chain."
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
        fragments: Optional[List[Union[str, Fragment]]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        system_fragments: Optional[List[Union[str, Fragment]]] = None,
        messages: Optional[List[Any]] = None,
        stream: bool = True,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        options: Optional[dict] = None,
        hide_reasoning: bool = False,
        **kwargs,
    ) -> Response:
        key_value = kwargs.pop("key", None)
        merged = _merge_options(options, kwargs)
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
                messages=messages,
                model=self,
                options=self.Options(**merged),
                hide_reasoning=hide_reasoning,
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
        messages: Optional[List[Any]] = None,
        stream: bool = True,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        before_call: Optional[BeforeCallSync] = None,
        after_call: Optional[AfterCallSync] = None,
        key: Optional[str] = None,
        options: Optional[dict] = None,
        hide_reasoning: bool = False,
    ) -> ChainResponse:
        return self.conversation().chain(
            prompt=prompt,
            fragments=fragments,
            attachments=attachments,
            system=system,
            system_fragments=system_fragments,
            messages=messages,
            stream=stream,
            schema=schema,
            tools=tools,
            tool_results=tool_results,
            before_call=before_call,
            after_call=after_call,
            key=key,
            options=options,
            hide_reasoning=hide_reasoning,
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
        fragments: Optional[List[Union[str, Fragment]]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        system_fragments: Optional[List[Union[str, Fragment]]] = None,
        messages: Optional[List[Any]] = None,
        stream: bool = True,
        options: Optional[dict] = None,
        hide_reasoning: bool = False,
        **kwargs,
    ) -> AsyncResponse:
        key_value = kwargs.pop("key", None)
        merged = _merge_options(options, kwargs)
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
                messages=messages,
                model=self,
                options=self.Options(**merged),
                hide_reasoning=hide_reasoning,
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
        messages: Optional[List[Any]] = None,
        stream: bool = True,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        tools: Optional[List[ToolDef]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        before_call: Optional[BeforeCallAsync] = None,
        after_call: Optional[AfterCallAsync] = None,
        key: Optional[str] = None,
        options: Optional[dict] = None,
        hide_reasoning: bool = False,
    ) -> AsyncChainResponse:
        return self.conversation().chain(
            prompt=prompt,
            fragments=fragments,
            attachments=attachments,
            system=system,
            system_fragments=system_fragments,
            messages=messages,
            stream=stream,
            schema=schema,
            tools=tools,
            tool_results=tool_results,
            before_call=before_call,
            after_call=after_call,
            key=key,
            options=options,
            hide_reasoning=hide_reasoning,
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
