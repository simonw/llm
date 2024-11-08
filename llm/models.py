import base64
from dataclasses import dataclass, field
import datetime
from .errors import NeedsKeyException
import hashlib
import httpx
from itertools import islice
import re
import time
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Union
from .utils import mimetype_from_path, mimetype_from_string
from abc import ABC, abstractmethod
import json
from pydantic import BaseModel
from ulid import ULID

CONVERSATION_NAME_LENGTH = 32


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
    prompt: str
    model: "Model"
    attachments: Optional[List[Attachment]]
    system: Optional[str]
    prompt_json: Optional[str]
    options: "Options"

    def __init__(
        self,
        prompt,
        model,
        *,
        attachments=None,
        system=None,
        prompt_json=None,
        options=None
    ):
        self.prompt = prompt
        self.model = model
        self.attachments = list(attachments or [])
        self.system = system
        self.prompt_json = prompt_json
        self.options = options or {}


@dataclass
class Conversation:
    model: "Model"
    id: str = field(default_factory=lambda: str(ULID()).lower())
    name: Optional[str] = None
    responses: List["Response"] = field(default_factory=list)

    def prompt(
        self,
        prompt: Optional[str],
        *,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        stream: bool = True,
        **options
    ):
        return Response(
            Prompt(
                prompt,
                model=self.model,
                attachments=attachments,
                system=system,
                options=self.model.Options(**options),
            ),
            self.model,
            stream,
            conversation=self,
        )

    @classmethod
    def from_row(cls, row):
        from llm import get_model

        return cls(
            model=get_model(row["model"]),
            id=row["id"],
            name=row["name"],
        )


class Response(ABC):
    def __init__(
        self,
        prompt: Prompt,
        model: "Model",
        stream: bool,
        conversation: Optional[Conversation] = None,
    ):
        self.prompt = prompt
        self._prompt_json = None
        self.model = model
        self.stream = stream
        self._chunks: List[str] = []
        self._done = False
        self.response_json = None
        self.conversation = conversation
        self.attachments: List[Attachment] = []

    def __iter__(self) -> Iterator[str]:
        self._start = time.monotonic()
        self._start_utcnow = datetime.datetime.utcnow()
        if self._done:
            yield from self._chunks
        for chunk in self.model.execute(
            self.prompt,
            stream=self.stream,
            response=self,
            conversation=self.conversation,
        ):
            yield chunk
            self._chunks.append(chunk)
        if self.conversation:
            self.conversation.responses.append(self)
        self._end = time.monotonic()
        self._done = True

    def _force(self):
        if not self._done:
            list(self)

    def __str__(self) -> str:
        return self.text()

    def text(self) -> str:
        self._force()
        return "".join(self._chunks)

    def json(self) -> Optional[Dict[str, Any]]:
        self._force()
        return self.response_json

    def duration_ms(self) -> int:
        self._force()
        return int((self._end - self._start) * 1000)

    def datetime_utc(self) -> str:
        self._force()
        return self._start_utcnow.isoformat()

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
        response_id = str(ULID()).lower()
        response = {
            "id": response_id,
            "model": self.model.model_id,
            "prompt": self.prompt.prompt,
            "system": self.prompt.system,
            "prompt_json": self._prompt_json,
            "options_json": {
                key: value
                for key, value in dict(self.prompt.options).items()
                if value is not None
            },
            "response": self.text(),
            "response_json": self.json(),
            "conversation_id": conversation.id,
            "duration_ms": self.duration_ms(),
            "datetime_utc": self.datetime_utc(),
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

    @classmethod
    def fake(
        cls,
        model: "Model",
        prompt: str,
        *attachments: List[Attachment],
        system: str,
        response: str
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

    @classmethod
    def from_row(cls, db, row):
        from llm import get_model

        model = get_model(row["model"])

        response = cls(
            model=model,
            prompt=Prompt(
                prompt=row["prompt"],
                model=model,
                attachments=[],
                system=row["system"],
                options=model.Options(**json.loads(row["options_json"])),
            ),
            stream=False,
        )
        response.id = row["id"]
        response._prompt_json = json.loads(row["prompt_json"] or "null")
        response.response_json = json.loads(row["response_json"] or "null")
        response._done = True
        response._chunks = [row["response"]]
        # Attachments
        response.attachments = [
            Attachment.from_row(arow)
            for arow in db.query(
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

    def __repr__(self):
        return "<Response prompt='{}' text='{}'>".format(
            self.prompt.prompt, self.text()
        )


class Options(BaseModel):
    # Note: using pydantic v1 style Configs,
    # these are also compatible with pydantic v2
    class Config:
        extra = "forbid"


_Options = Options


class _get_key_mixin:
    def get_key(self):
        from llm import get_key

        if self.needs_key is None:
            # This model doesn't use an API key
            return None

        if self.key is not None:
            # Someone already set model.key='...'
            return self.key

        # Attempt to load a key using llm.get_key()
        key = get_key(
            explicit_key=None, key_alias=self.needs_key, env_var=self.key_env_var
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


class Model(ABC, _get_key_mixin):
    model_id: str

    # API key handling
    key: Optional[str] = None
    needs_key: Optional[str] = None
    key_env_var: Optional[str] = None

    # Model characteristics
    can_stream: bool = False
    attachment_types: Set = set()

    class Options(_Options):
        pass

    def conversation(self):
        return Conversation(model=self)

    @abstractmethod
    def execute(
        self,
        prompt: Prompt,
        stream: bool,
        response: Response,
        conversation: Optional[Conversation],
    ) -> Iterator[str]:
        """
        Execute a prompt and yield chunks of text, or yield a single big chunk.
        Any additional useful information about the execution should be assigned to the response.
        """
        pass

    def prompt(
        self,
        prompt: str,
        *,
        attachments: Optional[List[Attachment]] = None,
        system: Optional[str] = None,
        stream: bool = True,
        **options
    ):
        # Validate attachments
        if attachments and not self.attachment_types:
            raise ValueError(
                "This model does not support attachments, but some were provided"
            )
        for attachment in attachments or []:
            attachment_type = attachment.resolve_type()
            if attachment_type not in self.attachment_types:
                raise ValueError(
                    "This model does not support attachments of type '{}', only {}".format(
                        attachment_type, ", ".join(self.attachment_types)
                    )
                )
        return self.response(
            Prompt(
                prompt,
                attachments=attachments,
                system=system,
                model=self,
                options=self.Options(**options),
            ),
            stream=stream,
        )

    def response(self, prompt: Prompt, stream: bool = True) -> Response:
        return Response(prompt, self, stream)

    def __str__(self) -> str:
        return "{}: {}".format(self.__class__.__name__, self.model_id)

    def __repr__(self):
        return "<Model '{}'>".format(self.model_id)


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


@dataclass
class ModelWithAliases:
    model: Model
    aliases: Set[str]


@dataclass
class EmbeddingModelWithAliases:
    model: EmbeddingModel
    aliases: Set[str]


def _conversation_name(text):
    # Collapse whitespace, including newlines
    text = re.sub(r"\s+", " ", text)
    if len(text) <= CONVERSATION_NAME_LENGTH:
        return text
    return text[: CONVERSATION_NAME_LENGTH - 1] + "…"
