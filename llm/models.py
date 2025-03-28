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
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Set,
    Union,
)
from .utils import (
    ensure_fragment,
    make_schema_id,
    mimetype_from_path,
    mimetype_from_string,
    token_usage_string,
)
from abc import ABC, abstractmethod
import json
from pydantic import BaseModel, ConfigDict
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
class Prompt:
    _prompt: Optional[str]
    model: "Model"
    fragments: Optional[List[str]]
    attachments: Optional[List[Attachment]]
    _system: Optional[str]
    system_fragments: Optional[List[str]]
    prompt_json: Optional[str]
    schema: Optional[Union[Dict, type[BaseModel]]]
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


@dataclass
class _BaseConversation:
    model: "_BaseModel"
    id: str = field(default_factory=lambda: str(ULID()).lower())
    name: Optional[str] = None
    responses: List["_BaseResponse"] = field(default_factory=list)

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
    def prompt(
        self,
        prompt: Optional[str] = None,
        *,
        fragments: Optional[List[str]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
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

    prompt: "Prompt"
    stream: bool
    conversation: Optional["_BaseConversation"] = None
    _key: Optional[str] = None

    def __init__(
        self,
        prompt: Prompt,
        model: "_BaseModel",
        stream: bool,
        conversation: Optional[_BaseConversation] = None,
        key: Optional[str] = None,
    ):
        self.prompt = prompt
        self._prompt_json = None
        self.model = model
        self.stream = stream
        self._key = key
        self._chunks: List[str] = []
        self._done = False
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

        response_id = str(ULID()).lower()
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
                callback = callback(self)
            if asyncio.iscoroutine(callback):
                await callback

    async def _on_done(self):
        for callback in self.done_callbacks:
            if callable(callback):
                callback = callback(self)
            if asyncio.iscoroutine(callback):
                await callback

    def __aiter__(self):
        self._start = time.monotonic()
        self._start_utcnow = datetime.datetime.now(datetime.timezone.utc)
        return self

    async def __anext__(self) -> str:
        if self._done:
            if not self._chunks:
                raise StopAsyncIteration
            chunk = self._chunks.pop(0)
            if not self._chunks:
                raise StopAsyncIteration
            return chunk

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
            self._chunks.append(chunk)
            return chunk
        except StopAsyncIteration:
            if self.conversation:
                self.conversation.responses.append(self)
            self._end = time.monotonic()
            self._done = True
            await self._on_done()
            raise

    async def _force(self):
        if not self._done:
            async for _ in self:
                pass
        return self

    def text_or_raise(self) -> str:
        if not self._done:
            raise ValueError("Response not yet awaited")
        return "".join(self._chunks)

    async def text(self) -> str:
        await self._force()
        return "".join(self._chunks)

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
        response = Response(
            self.prompt,
            self.model,
            self.stream,
            conversation=self.conversation,
        )
        response._chunks = self._chunks
        response._done = True
        response._end = self._end
        response._start = self._start
        response._start_utcnow = self._start_utcnow
        response.input_tokens = self.input_tokens
        response.output_tokens = self.output_tokens
        response.token_details = self.token_details
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
        key = get_key(
            explicit_key=explicit_key,
            key_alias=self.needs_key,
            env_var=self.key_env_var,
        )
        if key:
            return key

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
    def conversation(self) -> Conversation:
        return Conversation(model=self)

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
        **options,
    ) -> Response:
        key = options.pop("key", None)
        self._validate_attachments(attachments)
        return Response(
            Prompt(
                prompt,
                fragments=fragments,
                attachments=attachments,
                system=system,
                schema=schema,
                system_fragments=system_fragments,
                model=self,
                options=self.Options(**options),
            ),
            self,
            stream,
            key=key,
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
    def conversation(self) -> AsyncConversation:
        return AsyncConversation(model=self)

    def prompt(
        self,
        prompt: Optional[str] = None,
        *,
        fragments: Optional[List[str]] = None,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        schema: Optional[Union[dict, type[BaseModel]]] = None,
        system_fragments: Optional[List[str]] = None,
        stream: bool = True,
        **options,
    ) -> AsyncResponse:
        key = options.pop("key", None)
        self._validate_attachments(attachments)
        return AsyncResponse(
            Prompt(
                prompt,
                fragments=fragments,
                attachments=attachments,
                system=system,
                schema=schema,
                system_fragments=system_fragments,
                model=self,
                options=self.Options(**options),
            ),
            self,
            stream,
            key=key,
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
        yield ""


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
        yield ""


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
        batch_size = self.batch_size if batch_size is None else batch_size
        if (not self.supports_binary) or (not self.supports_text):

            def checking_iter(items):
                for item in items:
                    self._check(item)
                    yield item

            iter_items = checking_iter(items)
        if batch_size is None:
            yield from self.embed_batch(iter_items)
            return
        while True:
            batch_items = list(islice(iter_items, batch_size))
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
        query = query.lower()
        all_strings: List[str] = []
        all_strings.extend(self.aliases)
        if self.model:
            all_strings.append(str(self.model))
        if self.async_model:
            all_strings.append(str(self.async_model.model_id))
        return any(query in alias.lower() for alias in all_strings)


@dataclass
class EmbeddingModelWithAliases:
    model: EmbeddingModel
    aliases: Set[str]

    def matches(self, query: str) -> bool:
        query = query.lower()
        all_strings: List[str] = []
        all_strings.extend(self.aliases)
        all_strings.append(str(self.model))
        return any(query in alias.lower() for alias in all_strings)


def _conversation_name(text):
    # Collapse whitespace, including newlines
    text = re.sub(r"\s+", " ", text)
    if len(text) <= CONVERSATION_NAME_LENGTH:
        return text
    return text[: CONVERSATION_NAME_LENGTH - 1] + "…"
