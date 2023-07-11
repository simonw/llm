from dataclasses import dataclass, asdict, field
import datetime
from .errors import NeedsKeyException
import time
from typing import Any, Dict, Iterator, List, Optional, Set
from abc import ABC, abstractmethod
import os
from pydantic import ConfigDict, BaseModel
from ulid import ULID


@dataclass
class Prompt:
    prompt: str
    model: "Model"
    system: Optional[str]
    prompt_json: Optional[str]
    options: "Options"

    def __init__(self, prompt, model, system=None, prompt_json=None, options=None):
        self.prompt = prompt
        self.model = model
        self.system = system
        self.prompt_json = prompt_json
        self.options = options or {}


class OptionsError(Exception):
    pass


@dataclass
class LogMessage:
    model: str  # Actually the model.model_id string
    prompt: str  # Simplified string version of prompt
    system: Optional[str]  # Simplified string of system prompt
    prompt_json: Optional[Dict[str, Any]]  # Detailed JSON of prompt
    options_json: Dict[str, Any]  # Any options e.g. temperature
    response: str  # Simplified string version of response
    response_json: Optional[Dict[str, Any]]  # Detailed JSON of response
    reply_to_id: Optional[int]  # ID of message this is a reply to
    chat_id: Optional[
        int
    ]  # ID of chat this is a part of (ID of first message in thread)


@dataclass
class Conversation:
    model: "Model"
    id: str = field(default_factory=lambda: str(ULID()).lower())
    name: Optional[str] = None
    responses: List["Response"] = field(default_factory=list)

    def prompt(
        self,
        prompt: Optional[str],
        system: Optional[str] = None,
        stream: bool = True,
        **options
    ):
        return Response(
            Prompt(
                prompt,
                system=system,
                model=self.model,
                options=self.model.Options(**options),
            ),
            self.model,
            stream,
            conversation=self,
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
        self._response_json = None
        self.conversation = conversation

    def __iter__(self) -> Iterator[str]:
        self._start = time.monotonic()
        self._start_utcnow = datetime.datetime.utcnow()
        if self._done:
            return self._chunks
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

    def text(self) -> str:
        self._force()
        return "".join(self._chunks)

    def json(self) -> Optional[Dict[str, Any]]:
        self._force()
        return self._response_json

    def duration_ms(self) -> int:
        self._force()
        return int((self._end - self._start) * 1000)

    def datetime_utc(self) -> str:
        self._force()
        return self._start_utcnow.isoformat()

    def log_message(self) -> LogMessage:
        return LogMessage(
            model=self.prompt.model.model_id,
            prompt=self.prompt.prompt,
            system=self.prompt.system,
            prompt_json=self._prompt_json,
            options_json={
                key: value
                for key, value in self.prompt.options.model_dump().items()
                if value is not None
            },
            response=self.text(),
            response_json=self.json(),
            reply_to_id=None,  # TODO
            chat_id=None,  # TODO
        )

    def log_to_db(self, db):
        message = self.log_message()
        message_dict = asdict(message)
        message_dict["duration_ms"] = self.duration_ms()
        message_dict["datetime_utc"] = self.datetime_utc()
        db["logs"].insert(message_dict, pk="id")


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")


_Options = Options


class Model(ABC):
    model_id: str
    key: Optional[str] = None
    needs_key: Optional[str] = None
    key_env_var: Optional[str] = None
    can_stream: bool = False

    class Options(_Options):
        pass

    def get_key(self):
        if self.needs_key is None:
            return None
        if self.key is not None:
            return self.key
        if self.key_env_var is not None:
            key = os.environ.get(self.key_env_var)
            if key:
                return key

        message = "No key found - add one using 'llm keys set {}'".format(
            self.needs_key
        )
        if self.key_env_var:
            message += " or set the {} environment variable".format(self.key_env_var)
        raise NeedsKeyException(message)

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
        prompt: Optional[str],
        system: Optional[str] = None,
        stream: bool = True,
        **options
    ):
        return self.response(
            Prompt(prompt, system=system, model=self, options=self.Options(**options)),
            stream=stream,
        )

    def response(self, prompt: Prompt, stream: bool = True) -> Response:
        return Response(prompt, self, stream)

    def __str__(self) -> str:
        return "{}: {}".format(self.__class__.__name__, self.model_id)


@dataclass
class ModelWithAliases:
    model: Model
    aliases: Set[str]
