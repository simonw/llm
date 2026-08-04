import asyncio
import base64
import dataclasses
import datetime
import functools
import hashlib
import re
import time
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
)
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from types import MethodType
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Optional,
    Union,
    cast,
    get_type_hints,
)

import httpx

from .errors import NeedsKeyException
from .serialization import ResponseDict

if TYPE_CHECKING:
    from .parts import StreamEvent
import inspect
import json
from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, create_model

from .utils import (
    Fragment,
    mimetype_from_path,
    mimetype_from_string,
    monotonic_ulid,
    token_usage_string,
)

CONVERSATION_NAME_LENGTH = 32


@dataclass
class Usage:
    "Token usage information from a model response."

    input: int | None = None
    output: int | None = None
    details: dict[str, Any] | None = None


@dataclass
class Attachment:
    "An attachment (image, audio, etc) to include with a prompt."

    type: str | None = None
    path: str | None = None
    url: str | None = None
    content: bytes | None = None
    _id: str | None = None

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
            with httpx.Client(follow_redirects=True, max_redirects=3) as client:
                response = client.head(self.url)
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
                with httpx.Client(follow_redirects=True, max_redirects=3) as client:
                    response = client.get(self.url)
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
    description: str | None = None
    input_schema: dict = field(default_factory=dict)
    implementation: Callable | None = None
    plugin: str | None = None  # plugin tool came from, e.g. 'llm_tools_sqlite'

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


class ServerSideTool:
    """A tool executed inside the provider's infrastructure.

    Instances are passed in ``tools=[...]`` alongside function tools. The
    framework transports and validates them but never executes them. Provider
    plugins subclass this class for their own tools; the base class can be
    instantiated directly with a raw provider tool specification.
    """

    name: ClassVar[str] = "server_side_tool"
    plugin: ClassVar[str | None] = None
    implementation: ClassVar[None] = None
    input_schema: ClassVar[dict] = {}

    def __init__(self, spec: dict | None = None):
        self.spec = spec
        self._config = {"spec": spec}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        original_init = cls.__init__

        @functools.wraps(original_init)
        def wrapped_init(self, *args, **kwargs):
            signature = inspect.signature(original_init)
            bound = signature.bind(self, *args, **kwargs)
            bound.apply_defaults()
            original_init(self, *args, **kwargs)
            self._config = {
                name: value
                for name, value in bound.arguments.items()
                if name != "self"
                and signature.parameters[name].kind
                not in (
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                )
            }

        cls.__init__ = wrapped_init

    @property
    def description(self) -> str | None:
        return inspect.getdoc(self.__class__)

    def tool_spec(self, model) -> dict:
        """Return this tool's provider-specific request specification."""
        if self.spec is None:
            raise TypeError(
                f"{self.__class__.__name__} does not define a raw provider tool spec"
            )
        return self.spec

    def prepare_request(self, model, kwargs: dict) -> None:
        """Add any other values this tool needs to provider request kwargs."""

    def hash(self):
        """Hash the definition separately from configured instances."""
        to_hash = {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "server_side": True,
        }
        if self.plugin:
            to_hash["plugin"] = self.plugin
        return hashlib.sha256(json.dumps(to_hash).encode("utf-8")).hexdigest()


def _get_arguments_input_schema(function, name):
    signature = inspect.signature(function)
    type_hints = get_type_hints(function)
    fields = {}
    for param_name, param in signature.parameters.items():
        if param_name in ("self", "llm_tool_call"):
            # llm_tool_call is reserved: populated with the ToolCall object
            # at execution time, never exposed to the model.
            continue
        # Determine the type annotation (default to string if missing)
        annotated_type = type_hints.get(param_name, str)

        # Handle default value if present; if there's no default, use '...'
        if param.default is inspect.Parameter.empty:
            fields[param_name] = (annotated_type, ...)
        else:
            fields[param_name] = (annotated_type, param.default)

    return create_model(f"{name}InputSchema", **fields)


def _accepts_llm_tool_call(implementation) -> bool:
    try:
        signature = inspect.signature(implementation)
    except (TypeError, ValueError):
        return False
    return "llm_tool_call" in signature.parameters


def _implementation_arguments(tool: "Tool", tool_call: "ToolCall") -> dict:
    """Arguments to invoke a tool implementation with.

    Implementations with an explicit ``llm_tool_call`` parameter receive
    the ToolCall object itself - a ``**kwargs`` catch-all does not count.
    """
    arguments = dict(tool_call.arguments)
    if _accepts_llm_tool_call(tool.implementation):
        arguments["llm_tool_call"] = tool_call
    return arguments


class Toolbox:
    name: str | None = None
    instance_id: int | None = None
    _blocked = (
        "tools",
        "add_tool",
        "method_tools",
        "__init_subclass__",
        "prepare",
        "prepare_async",
    )
    _extra_tools: ClassVar[list[Tool]] = []
    _config: ClassVar[dict[str, Any]] = {}
    _prepared: bool = False
    _async_prepared: bool = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        original_init = cls.__init__

        @functools.wraps(original_init)
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
    def method_tools(cls) -> list[Tool]:
        tools = []
        for method_name in dir(cls):
            if method_name.startswith("_") or method_name in cls._blocked:
                continue
            method = getattr(cls, method_name)
            if callable(method):
                tool = Tool.function(
                    method,
                    name=f"{cls.__name__}_{method_name}",
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
        self, tool_or_function: Tool | Callable[..., Any], pass_self: bool = False
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
            raise TypeError("Tool must be an instance of Tool or a callable function")

    def prepare(self):
        """
        Over-ride this to perform setup (and .add_tool() calls) before the toolbox is used.
        Implement a similar prepare_async() method for async setup.
        """

    async def prepare_async(self):
        """
        Over-ride this to perform async setup (and .add_tool() calls) before the toolbox is used.
        """


@dataclass
class ToolCall:
    "A request by the model to call a tool."

    name: str
    arguments: dict
    tool_call_id: str | None = None


def _ensure_tool_call_id(tool_call: ToolCall) -> ToolCall:
    # Generate a tool call ID if one has not yet been specified
    if tool_call.tool_call_id is not None:
        return tool_call
    return dataclasses.replace(
        tool_call,
        tool_call_id=f"tc_{str(monotonic_ulid()).lower()}",
    )


@dataclass
class ToolResult:
    "The result of executing a tool call."

    name: str
    output: str
    attachments: list[Attachment] = field(default_factory=list)
    tool_call_id: str | None = None
    instance: Toolbox | None = None
    exception: Exception | None = None


@dataclass
class ToolOutput:
    "Tool functions can return output with extra attachments"

    output: str | dict | list | bool | int | float | None = None
    attachments: list[Attachment] = field(default_factory=list)


ToolDef = Tool | Toolbox | ServerSideTool | Callable[..., Any]
BeforeCallSync = Callable[[Tool | None, ToolCall], None]
AfterCallSync = Callable[[Tool, ToolCall, ToolResult], None]
BeforeCallAsync = Callable[[Tool | None, ToolCall], None | Awaitable[None]]
AfterCallAsync = Callable[[Tool, ToolCall, ToolResult], None | Awaitable[None]]


class CancelToolCall(Exception):
    pass


class PauseChain(Exception):
    """Raise inside a tool implementation to pause the chain.

    Unlike other exceptions - which are converted into error ToolResults
    and sent back to the model - PauseChain propagates out of
    ``execute_tool_calls()`` and ``chain()``. Before it is re-raised the
    framework populates two attributes:

    - ``tool_call``: the ToolCall whose implementation paused
    - ``tool_results``: ToolResults of sibling calls in the same batch
      that completed

    Concurrent (async) sibling tool calls always run to completion
    before the exception propagates; sequential (sync) execution stops
    at the paused call, leaving later calls unexecuted so they can
    safely run when the chain is resumed. Resume by re-running the
    chain with a ``messages=`` history that ends in the unresolved tool
    calls.
    """

    def __init__(self, *args):
        super().__init__(*args)
        self.tool_call: ToolCall | None = None
        self.tool_results: list[ToolResult] = []


@dataclass
class Prompt:
    "The prompt being sent to the model."

    _prompt: str | None
    model: "Model"
    fragments: list[str | Fragment] | None
    attachments: list[Attachment] | None
    _system: str | None
    system_fragments: list[str | Fragment] | None
    prompt_json: str | None
    schema: dict | type[BaseModel] | None
    tools: list[Tool | ServerSideTool]
    tool_results: list[ToolResult]
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
        return _combine_system(self._system, self.system_fragments)

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

        result: list[Message] = []

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
                            exception=_format_tool_exception(tr.exception),
                            attachments=list(tr.attachments or []),
                        )
                        for tr in self.tool_results
                    ],
                )
            )

        user_parts: list[Any] = []
        if self.prompt:
            user_parts.append(TextPart(text=self.prompt))
        for att in self.attachments:
            user_parts.append(AttachmentPart(attachment=att))
        if user_parts:
            result.append(Message(role="user", parts=user_parts))

        return result


def _wrap_tools(tools: list[ToolDef]) -> list[Tool | ServerSideTool]:
    wrapped_tools = []
    for tool in tools:
        if isinstance(tool, (Tool, ServerSideTool)):
            wrapped_tools.append(tool)
        elif isinstance(tool, Toolbox):
            wrapped_tools.extend(tool.tools())
        elif callable(tool):
            wrapped_tools.append(Tool.function(tool))
        else:
            raise TypeError(f"Invalid tool: {tool}")
    return wrapped_tools


def _partition_tools(
    model: "_BaseModel", tools: Iterable[Tool | ServerSideTool]
) -> tuple[list[Tool], list[ServerSideTool]]:
    """Partition tools and reject server-side tools the model did not claim."""
    function_tools = []
    server_side_tools = []
    declared = tuple(model.supported_server_side_tools)
    for tool in tools:
        if isinstance(tool, ServerSideTool):
            # Declaring ServerSideTool itself claims only direct raw-spec
            # instances. Without this exact-type exception it would also
            # accidentally claim every provider-specific subclass.
            claimed = any(
                (
                    type(tool) is candidate
                    if candidate is ServerSideTool
                    else isinstance(tool, candidate)
                )
                for candidate in declared
            )
            if not claimed:
                raise ValueError(
                    f"Model '{model.model_id}' does not support server-side tool "
                    f"'{tool.name}'. Run: llm tools -m {model.model_id}"
                )
            server_side_tools.append(tool)
        else:
            function_tools.append(tool)
    return function_tools, server_side_tools


def _append_turn_input(
    chain: list[Any],
    prompt: str | None,
    fragments=None,
    attachments=None,
    tool_results=None,
) -> list[Any]:
    """Append a turn's new input to a message chain.

    A tool-role message for any tool results, then a user-role message
    built from fragments + prompt text + attachments. This is what makes
    ``messages=`` mean "authoritative history" without the other prompt
    arguments being silently dropped from the chain. Mutates and returns
    ``chain``.
    """
    from .parts import (
        AttachmentPart,
        Message,
        TextPart,
        ToolResultPart,
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
                        exception=_format_tool_exception(tr.exception),
                        attachments=list(tr.attachments or []),
                    )
                    for tr in tool_results
                ],
            )
        )

    user_parts: list[Any] = []
    # Fragments are concatenated into the prompt text before it is
    # sent, so they have to be in the chain too - prompt.messages is
    # meant to be exactly what the model sees. Matches Prompt.prompt.
    prompt_text = "\n".join(
        [str(fragment) for fragment in fragments or []] + ([prompt] if prompt else [])
    )
    if prompt_text:
        user_parts.append(TextPart(text=prompt_text))
    for att in attachments or []:
        user_parts.append(AttachmentPart(attachment=att))
    if user_parts:
        chain.append(Message(role="user", parts=user_parts))
    return chain


def _combine_system(system, system_fragments):
    "Concatenate the system prompt and any system fragments into one string."
    bits = [
        bit.strip()
        for bit in ((system_fragments or []) + [system or ""])
        if bit.strip()
    ]
    return "\n\n".join(bits)


def _merge_options(options: dict | None, kwargs: dict) -> dict:
    if not options:
        return kwargs
    overlap = set(options) & set(kwargs)
    if overlap:
        raise TypeError(
            "Got values for these options both in options= and as keyword "
            f"arguments: {sorted(overlap)}"
        )
    return {**options, **kwargs}


@dataclass
class _BaseConversation:
    model: "_BaseModel"
    id: str = field(default_factory=lambda: str(monotonic_ulid()).lower())
    name: str | None = None
    responses: list["_BaseResponse"] = field(default_factory=list)
    tools: list[ToolDef] | None = None
    chain_limit: int | None = None
    # History read back from storage, used as the chain for the next turn
    # when this conversation has not yet produced a response in this
    # process. Unlike a chain rebuilt from logged responses this is the
    # exact message list, so reasoning signatures and provider metadata
    # survive being reloaded.
    loaded_messages: list[Any] | None = None
    # Plugin and server-side tool names and configured specs (e.g.
    # 'Datasette({"url": ...})' or 'CodeInterpreter({"memory_limit":
    # "4g"})') recorded against this conversation's first turn in storage.
    # Read when the conversation was loaded from the message store, where
    # there are no rebuilt responses to copy prompt.tools from.
    loaded_tools: list[str] | None = None

    @classmethod
    @abstractmethod
    def from_row(cls, row: Any) -> "_BaseConversation":
        raise NotImplementedError

    def _record_response(self, response: "_BaseResponse") -> None:
        "Record a completed response as part of this conversation."
        self.responses.append(response)
        # History now comes from the live responses, so anything read
        # back from storage is superseded.
        self.loaded_messages = None

    def _build_full_chain(
        self,
        prompt: str | None,
        attachments,
        tool_results,
        explicit_messages,
        system=None,
        system_fragments=None,
        fragments=None,
    ) -> list[Any]:
        """Build the full message chain for the next turn.

        Uses the last response's stored prompt chain to recover prior
        history, then appends the new turn's content (explicit messages
        first, or synthesized from prompt/attachments/tool_results).

        Returns the list that should be passed as ``messages=`` to the
        Prompt constructor so that ``response.prompt.messages`` equals
        exactly what the model sees.

        If ``explicit_messages`` is provided, the caller has opted out
        of history reconstruction: the list is the authoritative history,
        and the new turn's input is appended to it.
        """
        from .parts import Message, TextPart

        if explicit_messages is not None:
            return _append_turn_input(
                list(explicit_messages),
                prompt,
                fragments,
                attachments,
                tool_results,
            )

        chain: list[Any] = []
        if self.loaded_messages:
            # Storage holds the exact chain, so prefer it over anything
            # rebuilt from logged responses. Cleared as soon as this
            # conversation produces a response of its own.
            chain.extend(self.loaded_messages)
        elif self.responses:
            last = self.responses[-1]
            # last.prompt.messages already contains the full input chain
            # under the invariant, so use the last response only and then
            # append that response's structured output.
            chain.extend(last.prompt.messages)
            chain.extend(last._messages_now())
        else:
            # Start with the system prompt as the first message so adapters
            # that build from prompt.messages see it. On later turns it
            # is already carried forward in last.prompt.messages.
            system_text = _combine_system(system, system_fragments)
            if system_text:
                chain.append(Message(role="system", parts=[TextPart(text=system_text)]))

        return _append_turn_input(chain, prompt, fragments, attachments, tool_results)


@dataclass
class Conversation(_BaseConversation):
    before_call: BeforeCallSync | None = None
    after_call: AfterCallSync | None = None

    def prompt(
        self,
        prompt: str | None = None,
        *,
        fragments: list[str | Fragment] | None = None,
        attachments: list[Attachment] | None = None,
        system: str | None = None,
        schema: dict | type[BaseModel] | None = None,
        tools: list[ToolDef] | None = None,
        tool_results: list[ToolResult] | None = None,
        system_fragments: list[str | Fragment] | None = None,
        messages: list[Any] | None = None,
        stream: bool = True,
        key: str | None = None,
        options: dict | None = None,
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
            system=system,
            system_fragments=system_fragments,
            fragments=fragments,
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
            before_call=self.before_call,
            after_call=self.after_call,
        )

    def chain(
        self,
        prompt: str | None = None,
        *,
        fragments: list[str] | None = None,
        attachments: list[Attachment] | None = None,
        system: str | None = None,
        system_fragments: list[str] | None = None,
        messages: list[Any] | None = None,
        stream: bool = True,
        schema: dict | type[BaseModel] | None = None,
        tools: list[ToolDef] | None = None,
        tool_results: list[ToolResult] | None = None,
        chain_limit: int | None = None,
        before_call: BeforeCallSync | None = None,
        after_call: AfterCallSync | None = None,
        key: str | None = None,
        options: dict | None = None,
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
            system=system,
            system_fragments=system_fragments,
            fragments=fragments,
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
    before_call: BeforeCallAsync | None = None
    after_call: AfterCallAsync | None = None

    def chain(
        self,
        prompt: str | None = None,
        *,
        fragments: list[str] | None = None,
        attachments: list[Attachment] | None = None,
        system: str | None = None,
        system_fragments: list[str] | None = None,
        messages: list[Any] | None = None,
        stream: bool = True,
        schema: dict | type[BaseModel] | None = None,
        tools: list[ToolDef] | None = None,
        tool_results: list[ToolResult] | None = None,
        chain_limit: int | None = None,
        before_call: BeforeCallAsync | None = None,
        after_call: AfterCallAsync | None = None,
        key: str | None = None,
        options: dict | None = None,
        hide_reasoning: bool = False,
    ) -> "AsyncChainResponse":
        self.model._validate_attachments(attachments)
        chain_messages = self._build_full_chain(
            prompt=prompt,
            attachments=attachments,
            tool_results=tool_results,
            explicit_messages=messages,
            system=system,
            system_fragments=system_fragments,
            fragments=fragments,
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
        prompt: str | None = None,
        *,
        fragments: list[str] | None = None,
        attachments: list[Attachment] | None = None,
        system: str | None = None,
        schema: dict | type[BaseModel] | None = None,
        tools: list[ToolDef] | None = None,
        tool_results: list[ToolResult] | None = None,
        system_fragments: list[str] | None = None,
        messages: list[Any] | None = None,
        stream: bool = True,
        key: str | None = None,
        options: dict | None = None,
        hide_reasoning: bool = False,
        **kwargs,
    ) -> "AsyncResponse":
        merged = _merge_options(options, kwargs)
        chain = self._build_full_chain(
            prompt=prompt,
            attachments=attachments,
            tool_results=tool_results,
            explicit_messages=messages,
            system=system,
            system_fragments=system_fragments,
            fragments=fragments,
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
            before_call=self.before_call,
            after_call=self.after_call,
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
    resolved_model: str | None = None
    conversation: Optional["_BaseConversation"] = None
    _key: str | None = None

    def __init__(
        self,
        prompt: Prompt,
        model: "_BaseModel",
        stream: bool,
        conversation: _BaseConversation | None = None,
        key: str | None = None,
        before_call: BeforeCallSync | BeforeCallAsync | None = None,
        after_call: AfterCallSync | AfterCallAsync | None = None,
    ):
        self.id = str(monotonic_ulid()).lower()
        self.prompt = prompt
        self._prompt_json = None
        self.model = model
        self.stream = stream
        self._key = key
        self.before_call = before_call
        self.after_call = after_call
        self._chunks: list[str] = []
        # Every StreamEvent ever yielded by execute(), in order. Plain
        # str yields are wrapped as text events (with part_index resolved
        # by _resolve_part_index) so this buffer is the single source of
        # truth for replay and for assembling response.messages.
        self._stream_events: list[Any] = []
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
        self._auto_last_index: int | None = None
        self._auto_last_family: str | None = None
        self._auto_tool_id_to_index: dict[str, int] = {}
        self._auto_last_message_index: int = 0
        self._done = False
        self._tool_calls: list[ToolCall] = []
        self.response_json: dict[str, Any] | None = None
        self.conversation = conversation
        self.attachments: list[Attachment] = []
        self._start: float | None = None
        self._end: float | None = None
        self._start_utcnow: datetime.datetime | None = None
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None
        self.token_details: dict | None = None
        self.done_callbacks: list[Callable] = []

        if self.prompt.schema and not self.model.supports_schema:
            raise ValueError(f"{self.model} does not support schemas")

        function_tools, _ = _partition_tools(self.model, self.prompt.tools)
        if function_tools and not self.model.supports_tools:
            raise ValueError(f"{self.model} does not support tools")

    def _messages_now(self) -> list[Any]:
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
        return [
            Message(role="assistant", parts=parts)
            for parts in self._build_message_parts()
        ]

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

        # A message_index change always starts a fresh part - text on
        # either side of a message boundary must not concatenate.
        if event.message_index != self._auto_last_message_index:
            self._auto_last_family = None
            self._auto_last_index = None
        self._auto_last_message_index = event.message_index

        if event.part_index is not None:
            self._auto_index_max = max(self._auto_index_max, event.part_index)
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

    def _build_parts(self) -> list[Any]:
        """All Parts from the accumulated stream events, flattened
        across message boundaries. See ``_build_message_parts``."""
        return [part for parts in self._build_message_parts() for part in parts]

    def _build_message_parts(self) -> list[list[Any]]:
        """Assemble Part objects from the accumulated stream events,
        grouped into one parts-list per assistant message.

        Most providers emit a single assistant message, so the result
        is usually a one-element list. Events carrying an explicit
        ``message_index`` (OpenAI Responses server-side tool execution
        interleaves multiple ``message`` output items in one response)
        split into one parts-list per distinct index, in first-seen
        order.

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
            fallback_parts: list[Any] = []
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
            return [fallback_parts] if fallback_parts else []

        # Group events by their (resolved) part_index, preserving the
        # order in which each index was first seen. Then build one Part
        # per group. This handles non-adjacent same-index events (e.g.
        # text → tool_call → text where the plugin pinned both text
        # bursts to part_index=0) by merging them into one Part. Each
        # group belongs to the message of its first event.
        groups: dict[int, list[Any]] = {}
        order: list[int] = []
        group_message: dict[int, int] = {}
        for event in self._stream_events:
            pi = event.part_index
            if pi not in groups:
                groups[pi] = []
                order.append(pi)
                group_message[pi] = event.message_index
            groups[pi].append(event)

        built: list[tuple[int, Any]] = []
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

            pm_merged: dict[str, Any] | None = None
            for e in evs:
                if e.provider_metadata:
                    merged = dict(pm_merged) if pm_merged else {}
                    for k, v in e.provider_metadata.items():
                        merged[k] = v
                    pm_merged = merged

            mi = group_message[pi]
            if fam_first == "text":
                text = "".join(e.chunk for e in evs)
                if text:
                    built.append((mi, TextPart(text=text, provider_metadata=pm_merged)))
            elif fam_first == "reasoning":
                text = "".join(e.chunk for e in evs)
                redacted = any(e.redacted for e in evs)
                if text or redacted:
                    built.append(
                        (
                            mi,
                            ReasoningPart(
                                text=text,
                                redacted=redacted,
                                provider_metadata=pm_merged,
                            ),
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
                built.append(
                    (
                        mi,
                        ToolCallPart(
                            name=tool_name,
                            arguments=arguments,
                            tool_call_id=tool_call_id,
                            server_executed=server_executed,
                            provider_metadata=pm_merged,
                        ),
                    )
                )
            elif fam_first == "tool_result":
                tool_result_name = next((e.tool_name for e in evs if e.tool_name), "")
                tool_call_id = next(
                    (e.tool_call_id for e in evs if e.tool_call_id), None
                )
                server_executed = any(e.server_executed for e in evs)
                built.append(
                    (
                        mi,
                        ToolResultPart(
                            name=tool_result_name,
                            output="".join(e.chunk for e in evs),
                            tool_call_id=tool_call_id,
                            server_executed=server_executed,
                            provider_metadata=pm_merged,
                        ),
                    )
                )

        # Split into per-message parts lists, message indexes in
        # first-seen order.
        message_order: list[int] = []
        by_message: dict[int, list[Any]] = {}
        for mi, part in built:
            if mi not in by_message:
                by_message[mi] = []
                message_order.append(mi)
            by_message[mi].append(part)
        messages_parts = [by_message[mi] for mi in message_order]
        if not messages_parts:
            messages_parts = [[]]

        # Merge in any tool calls registered via add_tool_call() that the
        # plugin didn't also emit as StreamEvents. Dedup by tool_call_id so
        # plugins using both APIs in tandem don't double-count. They join
        # the final message - matching the old append-at-end behavior.
        seen_ids = {
            p.tool_call_id
            for parts in messages_parts
            for p in parts
            if isinstance(p, ToolCallPart) and p.tool_call_id is not None
        }
        for tc in self._tool_calls:
            if tc.tool_call_id is not None and tc.tool_call_id in seen_ids:
                continue
            messages_parts[-1].append(
                ToolCallPart(
                    name=tc.name,
                    arguments=tc.arguments or {},
                    tool_call_id=tc.tool_call_id,
                )
            )

        # Hoist redacted reasoning Parts to the start of their message.
        # Plugins typically emit them late (when usage arrives in the
        # final chunk), but UIs render reasoning before content, so the
        # framework reorders. Relative order among redacted Parts is
        # preserved.
        for i, parts in enumerate(messages_parts):
            redacted_parts = [
                p for p in parts if isinstance(p, ReasoningPart) and p.redacted
            ]
            if redacted_parts:
                other_parts = [
                    p
                    for p in parts
                    if not (isinstance(p, ReasoningPart) and p.redacted)
                ]
                messages_parts[i] = redacted_parts + other_parts

        return [parts for parts in messages_parts if parts]

    def add_tool_call(self, tool_call: ToolCall):
        self._tool_calls.append(_ensure_tool_call_id(tool_call))

    def set_usage(
        self,
        *,
        input: int | None = None,
        output: int | None = None,
        details: dict | None = None,
    ):
        self.input_tokens = input
        self.output_tokens = output
        self.token_details = details

    def set_resolved_model(self, model_id: str):
        self.resolved_model = model_id

    @classmethod
    def from_row(cls, db, row, _async=False):
        from llm import get_async_model, get_model

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
        # Everything - thread, turn, messages, parts, fragments,
        # attachments, tools - is recorded in the content-addressed
        # tables. The legacy tables are no longer written; they hold
        # history logged by older versions and are still read.
        # This lives here rather than in the CLI because log_to_db()
        # is what plugins call.
        from .logs import LogStore

        LogStore(db).log(self)


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
    payload: dict[str, Any] = {
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
            usage: dict[str, Any] = {}
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
    # Rebuild _tool_calls from the restored parts so tool_calls() and
    # reply(tools=...) can execute serialized pending calls. Server-
    # executed calls stay out, matching add_tool_call() during live
    # streaming.
    from .parts import ToolCallPart

    response._tool_calls = [
        ToolCall(
            name=p.name,
            arguments=p.arguments or {},
            tool_call_id=p.tool_call_id,
        )
        for m in output_messages
        for p in m.parts
        if isinstance(p, ToolCallPart) and not p.server_executed
    ]
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
        prompt: str | None = None,
        *,
        messages: list[Any] | None = None,
        tool_results: list[ToolResult] | None = None,
        options: dict | None = None,
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
        from .parts import Message, TextPart

        self._force()
        # Forward original tools so the next turn can call them again
        # (mirrors Conversation.prompt's `tools or self.tools` rule).
        if "tools" not in kwargs and self.prompt.tools:
            kwargs["tools"] = self.prompt.tools
        if tool_results is None and self._tool_calls:
            tool_results = self.execute_tool_calls(tools=kwargs.get("tools"))
        chain: list[Any] = list(self.prompt.messages) + list(self._messages_now())
        if tool_results:
            tool_attachments: list[Attachment] = []
            for tr in tool_results:
                tool_attachments.extend(tr.attachments or [])
            _append_tool_results_to_chain(chain, tool_results, tool_attachments)
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
        self._force()
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
        before_call: BeforeCallSync | None = None,
        after_call: AfterCallSync | None = None,
        tool_calls_list: list[ToolCall] | None = None,
        tools: list[ToolDef] | None = None,
    ) -> list[ToolResult]:
        """Execute tool calls using this response's tools.

        By default executes ``self.tool_calls()``; pass
        ``tool_calls_list=`` to execute an explicit list instead (used
        when resuming a chain whose history ends in unresolved calls).
        Pass ``tools=`` to resolve implementations from an explicit
        list instead of ``self.prompt.tools`` (used when a rehydrated
        response has pending calls but no tool implementations).
        """
        tool_results = []
        effective_tools = _wrap_tools(tools) if tools is not None else self.prompt.tools
        tools_by_name = {
            tool.name: tool for tool in effective_tools if isinstance(tool, Tool)
        }
        if tool_calls_list is None:
            tool_calls_list = self.tool_calls()

        # Run prepare() on all Toolbox instances that need it
        instances_to_prepare: list[Toolbox] = []
        for tool_to_prep in tools_by_name.values():
            inst = _get_instance(tool_to_prep.implementation)
            if isinstance(inst, Toolbox) and not getattr(inst, "_prepared", False):
                instances_to_prepare.append(inst)

        for inst in instances_to_prepare:
            inst.prepare()
            inst._prepared = True

        for tool_call in tool_calls_list:
            tool: Tool | None = tools_by_name.get(tool_call.name)
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
                msg = f'tool "{tool_call.name}" does not exist'
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
                    f"No implementation available for tool: {tool_call.name}"
                )

            attachments = []
            exception = None

            try:
                implementation_arguments = _implementation_arguments(tool, tool_call)
                if inspect.iscoroutinefunction(tool.implementation):
                    result = asyncio.run(
                        tool.implementation(**implementation_arguments)
                    )
                else:
                    result = tool.implementation(**implementation_arguments)

                if isinstance(result, ToolOutput):
                    attachments = result.attachments
                    result = result.output

                if not isinstance(result, str):
                    result = json.dumps(result, default=repr)
            except PauseChain as ex:
                # Pause: propagate instead of converting to an error
                # result. Sequential execution stops here - later calls
                # never started, so they can safely run on resume.
                ex.tool_call = tool_call
                ex.tool_results = list(tool_results)
                raise
            except Exception as ex:  # noqa: BLE001
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

    def execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
        "Utility method for manually executing a tool call with callbacks"
        tool_call = _ensure_tool_call_id(tool_call)
        return self.execute_tool_calls(
            before_call=cast(BeforeCallSync | None, self.before_call),
            after_call=cast(AfterCallSync | None, self.after_call),
            tool_calls_list=[tool_call],
        )[0]

    def tool_calls(self) -> list[ToolCall]:
        "Return the list of tool calls made during this response."
        self._force()
        return self._tool_calls

    def tool_calls_or_raise(self) -> list[ToolCall]:
        return self.tool_calls()

    def json(self) -> dict[str, Any] | None:
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
            raise TypeError("self.model must be a Model or KeyModel")

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
            self.conversation._record_response(self)
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
            self.conversation._record_response(self)
        self._end = time.monotonic()
        self._done = True
        self._on_done()

    def messages(self) -> list[Any]:
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
        return f"<Response prompt='{self.prompt.prompt}' text='{text}'>"


class AsyncResponse(_BaseResponse):
    "Async response from a model."

    model: "AsyncModel"
    conversation: Optional["AsyncConversation"] = None

    async def reply(
        self,
        prompt: str | None = None,
        *,
        messages: list[Any] | None = None,
        tool_results: list[ToolResult] | None = None,
        options: dict | None = None,
        **kwargs,
    ) -> "AsyncResponse":
        """Async counterpart of Response.reply(). Requires this response
        to have been awaited (so self.messages is available).

        Awaitable so the auto-execute path can ``await
        self.execute_tool_calls()``. See ``Response.reply`` for the
        ``tool_results=`` semantics.
        """
        from .parts import Message, TextPart

        if not self._done:
            raise ValueError(
                "Response not yet awaited — call `await response` before reply()"
            )
        if "tools" not in kwargs and self.prompt.tools:
            kwargs["tools"] = self.prompt.tools
        if tool_results is None and self._tool_calls:
            tool_results = await self.execute_tool_calls(tools=kwargs.get("tools"))
        chain: list[Any] = list(self.prompt.messages) + list(self._messages_now())
        if tool_results:
            tool_attachments: list[Attachment] = []
            for tr in tool_results:
                tool_attachments.extend(tr.attachments or [])
            _append_tool_results_to_chain(chain, tool_results, tool_attachments)
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
        before_call: BeforeCallAsync | None = None,
        after_call: AfterCallAsync | None = None,
        tool_calls_list: list[ToolCall] | None = None,
        tools: list[ToolDef] | None = None,
    ) -> list[ToolResult]:
        """Execute tool calls using this response's tools.

        By default executes ``await self.tool_calls()``; pass
        ``tool_calls_list=`` to execute an explicit list instead (used
        when resuming a chain whose history ends in unresolved calls).
        Pass ``tools=`` to resolve implementations from an explicit
        list instead of ``self.prompt.tools`` (used when a rehydrated
        response has pending calls but no tool implementations).
        """
        if tool_calls_list is None:
            tool_calls_list = await self.tool_calls()
        effective_tools = _wrap_tools(tools) if tools is not None else self.prompt.tools
        tools_by_name = {
            tool.name: tool for tool in effective_tools if isinstance(tool, Tool)
        }

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

        indexed_results: list[tuple[int, ToolResult]] = []
        async_tasks: list[asyncio.Task] = []
        async_task_indexes: list[int] = []
        # Defined failure semantics: a pause or error in one call must not
        # orphan concurrently-running siblings. Pauses and hook failures
        # are collected here and raised only after every task that was
        # started has finished.
        paused: list[tuple[int, PauseChain]] = []
        failures: list[tuple[int, BaseException]] = []

        for idx, tc in enumerate(tool_calls_list):
            tool: Tool | None = tools_by_name.get(tc.name)
            exception: Exception | None = None

            if tool is None or not tool.implementation:
                # Mirror the sync executor: append an error ToolResult so
                # the provider still receives a result for every tool
                # call. before_call fires even though the tool is
                # unavailable.
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
                    except Exception as ex:  # noqa: BLE001
                        failures.append((idx, ex))
                        break
                reason = "does not exist" if tool is None else "has no implementation"
                msg = f'tool "{tc.name}" {reason}'
                indexed_results.append(
                    (
                        idx,
                        ToolResult(
                            name=tc.name,
                            output="Error: " + msg,
                            tool_call_id=tc.tool_call_id,
                            exception=KeyError(msg),
                        ),
                    )
                )
                continue

            if inspect.iscoroutinefunction(tool.implementation):

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
                        result = await tool.implementation(
                            **_implementation_arguments(tool, tc)
                        )
                        if isinstance(result, ToolOutput):
                            attachments.extend(result.attachments)
                            result = result.output
                        output = (
                            result
                            if isinstance(result, str)
                            else json.dumps(result, default=repr)
                        )
                    except PauseChain as ex:
                        # Propagates out of the task; collected after
                        # the gather so siblings finish first.
                        ex.tool_call = tc
                        raise
                    except Exception as ex:  # noqa: BLE001
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
                async_task_indexes.append(idx)

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
                    except Exception as ex:  # noqa: BLE001
                        failures.append((idx, ex))
                        break

                exception = None
                attachments = []

                try:
                    res = tool.implementation(**_implementation_arguments(tool, tc))
                    if inspect.isawaitable(res):
                        res = await res
                    if isinstance(res, ToolOutput):
                        attachments.extend(res.attachments)
                        res = res.output
                    output = (
                        res if isinstance(res, str) else json.dumps(res, default=repr)
                    )
                except PauseChain as ex:
                    # Inline execution stops here; later calls never
                    # start. Tasks already started are still awaited
                    # below before the pause propagates.
                    ex.tool_call = tc
                    paused.append((idx, ex))
                    break
                except Exception as ex:  # noqa: BLE001
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

                try:
                    if after_call:
                        cb2 = after_call(tool, tc, tr)
                        if inspect.isawaitable(cb2):
                            await cb2
                except Exception as ex:  # noqa: BLE001
                    failures.append((idx, ex))
                    break

                indexed_results.append((idx, tr))

        # Await every task that was started; return_exceptions so a pause
        # or hook failure in one task cannot orphan its siblings mid-flight.
        if async_tasks:
            outcomes = await asyncio.gather(*async_tasks, return_exceptions=True)
            for task_idx, outcome in zip(async_task_indexes, outcomes):
                if isinstance(outcome, PauseChain):
                    paused.append((task_idx, outcome))
                elif isinstance(outcome, BaseException):
                    failures.append((task_idx, outcome))
                else:
                    indexed_results.append(outcome)

        # Reorder by original index
        indexed_results.sort(key=lambda x: x[0])
        results = [tr for _, tr in indexed_results]

        # Hook failures are bugs: raise the first by call order.
        if failures:
            failures.sort(key=lambda item: item[0])
            raise failures[0][1]

        # Pauses propagate with the completed sibling results attached.
        if paused:
            paused.sort(key=lambda item: item[0])
            pause = paused[0][1]
            pause.tool_results = results
            raise pause

        return results

    async def execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
        "Asynchronous counterpart to :meth:`Response.execute_tool_call`."
        tool_call = _ensure_tool_call_id(tool_call)
        results = await self.execute_tool_calls(
            before_call=cast(BeforeCallAsync | None, self.before_call),
            after_call=cast(AfterCallAsync | None, self.after_call),
            tool_calls_list=[tool_call],
        )
        return results[0]

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
            self.conversation._record_response(self)
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

    async def messages(self) -> list[Any]:
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

    async def tool_calls(self) -> list[ToolCall]:
        "Return the list of tool calls made during this response."
        await self._force()
        return self._tool_calls

    def tool_calls_or_raise(self) -> list[ToolCall]:
        if not self._done:
            raise ValueError("Response not yet awaited")
        return self._tool_calls

    async def json(self) -> dict[str, Any] | None:
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
        # Without these the sync response falls back to assembling a bare
        # TextPart from _chunks, so reasoning, redacted markers and every
        # part's provider_metadata are lost. The CLI converts before
        # logging, so that loss would apply to every async response.
        response._stream_events = list(self._stream_events)
        response.attachments = list(self.attachments)
        response.resolved_model = self.resolved_model
        return response

    @classmethod
    def fake(
        cls,
        model: "AsyncModel",
        prompt: str,
        *attachments: list[Attachment],
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
        return f"<AsyncResponse prompt='{self.prompt.prompt}' text='{text}'>"


def _append_tool_results_to_chain(chain, tool_results, attachments) -> list[Any]:
    """Append a tool-role message carrying ToolResults to a message
    chain, plus a trailing user-role message for any attachments the
    tools returned (mimics the legacy attachments=[] kwarg behavior)."""
    from .parts import (
        AttachmentPart,
        Message,
        ToolResultPart,
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
                        exception=_format_tool_exception(tr.exception),
                    )
                    for tr in tool_results
                ],
            )
        )
    if attachments:
        chain.append(
            Message(
                role="user",
                parts=[AttachmentPart(attachment=a) for a in attachments],
            )
        )
    return chain


def _chain_for_tool_results(prior_response, tool_results, attachments) -> list[Any]:
    """Build the message chain for a tool-result turn in a chain loop.

    Takes the prior response's full input chain + its structured
    output, then appends a tool-role message carrying the new
    ToolResult outputs.

    This is what gives ``response.prompt.messages`` on the tool-
    result turn the complete history for the next provider call —
    including any reasoning signatures or thoughtSignatures from the
    prior turn.
    """
    chain: list[Any] = list(prior_response.prompt.messages) + list(
        prior_response._messages_now()
    )
    return _append_tool_results_to_chain(chain, tool_results, attachments)


def _trailing_pending_tool_calls(messages) -> list[ToolCall]:
    """Find unresolved tool calls at the end of a message history.

    Returns ToolCall objects from the last assistant message containing
    locally-executable tool_call parts, minus any that already have a
    matching tool_result in subsequent tool-role messages. Returns []
    when the history has moved on past those calls (a user/assistant/
    system message follows them) - resuming only makes sense when the
    calls are the latest thing that happened.

    Matching uses tool_call_id when present; id-less calls (histories
    persisted before ids were guaranteed) match results by name, one
    result consumed per call.
    """
    from .parts import ToolCallPart, ToolResultPart

    last_index = None
    call_parts: list[Any] = []
    for i, msg in enumerate(messages or []):
        parts = getattr(msg, "parts", None) or []
        calls = [
            p for p in parts if isinstance(p, ToolCallPart) and not p.server_executed
        ]
        if getattr(msg, "role", None) == "assistant" and calls:
            last_index = i
            call_parts = calls
    if last_index is None:
        return []

    results: list[Any] = []
    for msg in messages[last_index + 1 :]:
        role = getattr(msg, "role", None)
        if role == "tool":
            results.extend(
                p
                for p in (getattr(msg, "parts", None) or [])
                if isinstance(p, ToolResultPart)
            )
        else:
            # Conversation moved on past these calls
            return []

    matched_ids = {r.tool_call_id for r in results if r.tool_call_id}
    unmatched_names = [r.name for r in results if not r.tool_call_id]
    pending = []
    for part in call_parts:
        if part.tool_call_id:
            if part.tool_call_id in matched_ids:
                continue
        elif part.name in unmatched_names:
            unmatched_names.remove(part.name)
            continue
        pending.append(
            ToolCall(
                name=part.name,
                arguments=part.arguments or {},
                tool_call_id=part.tool_call_id,
            )
        )
    return pending


class _BaseChainResponse:
    prompt: "Prompt"
    stream: bool
    conversation: Optional["_BaseConversation"] = None
    _key: str | None = None

    def __init__(
        self,
        prompt: Prompt,
        model: "_BaseModel",
        stream: bool,
        conversation: _BaseConversation,
        key: str | None = None,
        chain_limit: int | None = 10,
        before_call: BeforeCallSync | BeforeCallAsync | None = None,
        after_call: AfterCallSync | AfterCallAsync | None = None,
    ):
        self.prompt = prompt
        self.model = model
        self.stream = stream
        self._key = key
        self._responses: list[Any] = []
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

    def _pending_tool_calls(self) -> list[ToolCall]:
        """Unresolved tool calls at the end of this chain's history.

        Non-empty when the supplied messages= end in an assistant
        message whose tool calls have no results yet - e.g. a chain
        that paused on PauseChain and is being resumed from persisted
        history."""
        if not self.prompt.tools:
            return []
        return _trailing_pending_tool_calls(self.prompt.messages)

    def _resume_prompt(self, tool_results: list[ToolResult]) -> Prompt:
        """The first prompt for a resumed chain: the original history
        plus a tool-role message carrying the freshly-executed results -
        the same shape as the chain loop's own tool-result turns."""
        prompt = self.prompt
        attachments = []
        for tool_result in tool_results:
            attachments.extend(tool_result.attachments)
        next_chain = _append_tool_results_to_chain(
            list(prompt.messages), tool_results, attachments
        )
        return Prompt(
            "",
            self.model,
            tools=prompt.tools,
            tool_results=tool_results,
            messages=next_chain,
            system=prompt._system,
            system_fragments=prompt.system_fragments,
            options=prompt.options,
            attachments=attachments,
            hide_reasoning=prompt.hide_reasoning,
        )


class ChainResponse(_BaseChainResponse):
    _responses: list["Response"]
    before_call: BeforeCallSync | None = None
    after_call: AfterCallSync | None = None

    def responses(self) -> Iterator[Response]:
        prompt = self.prompt
        count = 0
        initial_response = Response(
            prompt,
            self.model,
            self.stream,
            key=self._key,
            conversation=self.conversation,
            before_call=self.before_call,
            after_call=self.after_call,
        )
        # Resume: a history ending in unresolved tool calls means a
        # previous run stopped (paused or crashed) before executing
        # them. Execute those calls first - through the normal
        # before_call/after_call machinery - then start the loop on
        # the tool-result turn. This could raise llm.PauseChain.
        pending_tool_calls = self._pending_tool_calls()
        if pending_tool_calls:
            tool_results = initial_response.execute_tool_calls(
                before_call=self.before_call,
                after_call=self.after_call,
                tool_calls_list=pending_tool_calls,
            )
            initial_response = Response(
                self._resume_prompt(tool_results),
                self.model,
                self.stream,
                key=self._key,
                conversation=self.conversation,
                before_call=self.before_call,
                after_call=self.after_call,
            )
        current_response: Response | None = initial_response
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
                    before_call=self.before_call,
                    after_call=self.after_call,
                )
            else:
                current_response = None
                break

    def __iter__(self) -> Iterator[str]:
        # Rounds of a chain are separate model responses; joined with
        # nothing between them the text of one runs straight into the
        # next ("...have dragons.Now that I..."). Yield one space at
        # each boundary where neither side brings its own whitespace.
        # Display only: the separator never enters any response's
        # recorded events, so it is not stored or hashed.
        last_char = ""
        for response_item in self.responses():
            first_chunk = True
            for chunk in response_item:
                if not chunk:
                    continue
                if (
                    first_chunk
                    and last_char
                    and not last_char.isspace()
                    and not chunk[0].isspace()
                ):
                    yield " "
                first_chunk = False
                yield chunk
                last_char = chunk[-1]

    def stream_events(self):
        "Yield StreamEvents from every response in the chain."
        from .parts import StreamEvent

        # The same round-boundary separator as __iter__, synthesized at
        # the chain level so it is never part of a response's events.
        last_char = ""
        for response_item in self.responses():
            first_text = True
            for event in response_item.stream_events():
                if event.type == "text" and event.chunk:
                    if (
                        first_text
                        and last_char
                        and not last_char.isspace()
                        and not event.chunk[0].isspace()
                    ):
                        yield StreamEvent(type="text", chunk=" ")
                    first_text = False
                    last_char = event.chunk[-1]
                yield event

    def text(self) -> str:
        return "".join(self)


class AsyncChainResponse(_BaseChainResponse):
    _responses: list["AsyncResponse"]
    before_call: BeforeCallAsync | None = None
    after_call: AfterCallAsync | None = None

    async def responses(self) -> AsyncIterator[AsyncResponse]:
        prompt = self.prompt
        count = 0
        initial_response = AsyncResponse(
            prompt,
            self.model,
            self.stream,
            key=self._key,
            conversation=self.conversation,
            before_call=self.before_call,
            after_call=self.after_call,
        )
        # Resume: see ChainResponse.responses() - execute trailing
        # unresolved tool calls before the first provider call. This
        # could raise llm.PauseChain.
        pending_tool_calls = self._pending_tool_calls()
        if pending_tool_calls:
            tool_results = await initial_response.execute_tool_calls(
                before_call=self.before_call,
                after_call=self.after_call,
                tool_calls_list=pending_tool_calls,
            )
            initial_response = AsyncResponse(
                self._resume_prompt(tool_results),
                self.model,
                self.stream,
                key=self._key,
                conversation=self.conversation,
                before_call=self.before_call,
                after_call=self.after_call,
            )
        current_response: AsyncResponse | None = initial_response
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
                    before_call=self.before_call,
                    after_call=self.after_call,
                )
            else:
                current_response = None
                break

    async def __aiter__(self) -> AsyncIterator[str]:
        # Round-boundary separator - same reasoning as the sync chain.
        last_char = ""
        async for response_item in self.responses():
            first_chunk = True
            async for chunk in response_item:
                if not chunk:
                    continue
                if (
                    first_chunk
                    and last_char
                    and not last_char.isspace()
                    and not chunk[0].isspace()
                ):
                    yield " "
                first_chunk = False
                yield chunk
                last_char = chunk[-1]

    async def astream_events(self):
        "Yield StreamEvents from every response in the chain."
        from .parts import StreamEvent

        # Same round-boundary separator as __aiter__, synthesized at the
        # chain level so it is never part of a response's events.
        last_char = ""
        async for response_item in self.responses():
            first_text = True
            async for event in response_item.astream_events():
                if event.type == "text" and event.chunk:
                    if (
                        first_text
                        and last_char
                        and not last_char.isspace()
                        and not event.chunk[0].isspace()
                    ):
                        yield StreamEvent(type="text", chunk=" ")
                    first_text = False
                    last_char = event.chunk[-1]
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
    needs_key: str | None = None
    key: str | None = None
    key_env_var: str | None = None

    def get_key(self, explicit_key: str | None = None) -> str | None:
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
        message = f"No key found - add one using 'llm keys set {self.needs_key}'"
        if self.key_env_var:
            message += f" or set the {self.key_env_var} environment variable"
        raise NeedsKeyException(message)


class _BaseModel(ABC, _get_key_mixin):
    model_id: str
    can_stream: bool = False
    attachment_types: set[str] | frozenset[str] = frozenset()

    supports_schema = False
    supports_tools = False

    @property
    def supported_server_side_tools(self) -> tuple[type[ServerSideTool], ...]:
        """Server-side tool classes accepted by this model instance."""
        return ()

    class Options(_Options):
        pass

    def _validate_attachments(
        self, attachments: list[Attachment] | None = None
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
        return f"<{self!s}>"


class _Model(_BaseModel):
    def conversation(
        self,
        tools: list[ToolDef] | None = None,
        before_call: BeforeCallSync | None = None,
        after_call: AfterCallSync | None = None,
        chain_limit: int | None = None,
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
        prompt: str | None = None,
        *,
        fragments: list[str | Fragment] | None = None,
        attachments: list[Attachment] | None = None,
        system: str | None = None,
        system_fragments: list[str | Fragment] | None = None,
        messages: list[Any] | None = None,
        stream: bool = True,
        schema: dict | type[BaseModel] | None = None,
        tools: list[ToolDef] | None = None,
        tool_results: list[ToolResult] | None = None,
        options: dict | None = None,
        hide_reasoning: bool = False,
        **kwargs,
    ) -> Response:
        key_value = kwargs.pop("key", None)
        merged = _merge_options(options, kwargs)
        self._validate_attachments(attachments)
        if messages is not None:
            # messages= is the authoritative history; the other prompt
            # arguments are this turn's new input, folded in so that
            # response.prompt.messages stays exactly what the model sees.
            messages = _append_turn_input(
                list(messages), prompt, fragments, attachments, tool_results
            )
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
        prompt: str | None = None,
        *,
        fragments: list[str] | None = None,
        attachments: list[Attachment] | None = None,
        system: str | None = None,
        system_fragments: list[str] | None = None,
        messages: list[Any] | None = None,
        stream: bool = True,
        schema: dict | type[BaseModel] | None = None,
        tools: list[ToolDef] | None = None,
        tool_results: list[ToolResult] | None = None,
        before_call: BeforeCallSync | None = None,
        after_call: AfterCallSync | None = None,
        key: str | None = None,
        options: dict | None = None,
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
        conversation: Conversation | None,
    ) -> Iterator[Union[str, "StreamEvent"]]:
        pass


class KeyModel(_Model):
    @abstractmethod
    def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: Response,
        conversation: Conversation | None,
        key: str | None,
    ) -> Iterator[Union[str, "StreamEvent"]]:
        pass


class _AsyncModel(_BaseModel):
    def conversation(
        self,
        tools: list[ToolDef] | None = None,
        before_call: BeforeCallAsync | None = None,
        after_call: AfterCallAsync | None = None,
        chain_limit: int | None = None,
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
        prompt: str | None = None,
        *,
        fragments: list[str | Fragment] | None = None,
        attachments: list[Attachment] | None = None,
        system: str | None = None,
        schema: dict | type[BaseModel] | None = None,
        tools: list[ToolDef] | None = None,
        tool_results: list[ToolResult] | None = None,
        system_fragments: list[str | Fragment] | None = None,
        messages: list[Any] | None = None,
        stream: bool = True,
        options: dict | None = None,
        hide_reasoning: bool = False,
        **kwargs,
    ) -> AsyncResponse:
        key_value = kwargs.pop("key", None)
        merged = _merge_options(options, kwargs)
        self._validate_attachments(attachments)
        if messages is not None:
            # Same fold as Model.prompt: messages= is the history, the
            # other prompt arguments are this turn's new input.
            messages = _append_turn_input(
                list(messages), prompt, fragments, attachments, tool_results
            )
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
        prompt: str | None = None,
        *,
        fragments: list[str] | None = None,
        attachments: list[Attachment] | None = None,
        system: str | None = None,
        system_fragments: list[str] | None = None,
        messages: list[Any] | None = None,
        stream: bool = True,
        schema: dict | type[BaseModel] | None = None,
        tools: list[ToolDef] | None = None,
        tool_results: list[ToolResult] | None = None,
        before_call: BeforeCallAsync | None = None,
        after_call: AfterCallAsync | None = None,
        key: str | None = None,
        options: dict | None = None,
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
        conversation: AsyncConversation | None,
    ) -> AsyncGenerator[Union[str, "StreamEvent"], None]:
        if False:  # Ensure it's a generator type
            yield ""


class AsyncKeyModel(_AsyncModel):
    @abstractmethod
    async def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: AsyncResponse,
        conversation: AsyncConversation | None,
        key: str | None,
    ) -> AsyncGenerator[Union[str, "StreamEvent"], None]:
        if False:  # Ensure it's a generator type
            yield ""


class EmbeddingModel(ABC, _get_key_mixin):
    model_id: str
    key: str | None = None
    needs_key: str | None = None
    key_env_var: str | None = None
    supports_text: bool = True
    supports_binary: bool = False
    batch_size: int | None = None

    def _check(self, item: str | bytes):
        if not self.supports_binary and isinstance(item, bytes):
            raise ValueError(
                "This model does not support binary data, only text strings"
            )
        if not self.supports_text and isinstance(item, str):
            raise ValueError(
                "This model does not support text strings, only binary data"
            )

    def embed(self, item: str | bytes) -> list[float]:
        "Embed a single text string or binary blob, return a list of floats"
        self._check(item)
        return next(iter(self.embed_batch([item])))

    def embed_multi(
        self, items: Iterable[str | bytes], batch_size: int | None = None
    ) -> Iterator[list[float]]:
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
    def embed_batch(self, items: Iterable[str | bytes]) -> Iterator[list[float]]:
        """
        Embed a batch of strings or blobs, return a list of lists of floats
        """

    def __str__(self) -> str:
        return f"{self.__class__.__name__}: {self.model_id}"

    def __repr__(self) -> str:
        return f"<{self!s}>"


@dataclass
class ModelWithAliases:
    "A model with its optional async counterpart and aliases."

    model: Model
    async_model: AsyncModel
    aliases: set[str]

    def matches(self, query: str) -> bool:
        query_lower = query.lower()
        all_strings: list[str] = []
        all_strings.extend(self.aliases)
        if self.model:
            all_strings.append(str(self.model))
        if self.async_model:
            all_strings.append(str(self.async_model.model_id))
        return any(query_lower in alias.lower() for alias in all_strings)


@dataclass
class EmbeddingModelWithAliases:
    model: EmbeddingModel
    aliases: set[str]

    def matches(self, query: str) -> bool:
        query_lower = query.lower()
        all_strings: list[str] = []
        all_strings.extend(self.aliases)
        all_strings.append(str(self.model))
        return any(query_lower in alias.lower() for alias in all_strings)


def _format_tool_exception(exception) -> str | None:
    """Render a tool's exception the way it is recorded.

    ToolResult carries the exception object; ToolResultPart carries the
    rendered string, so the chain has to convert rather than drop it.
    """
    if exception is None:
        return None
    if isinstance(exception, str):
        return exception
    return f"{exception.__class__.__name__}: {exception!s}"


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
