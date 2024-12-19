import pytest
import sqlite_utils
import json
import llm
from llm.plugins import pm
from pydantic import Field
from pytest_httpx import IteratorStream
from typing import Optional


def pytest_configure(config):
    import sys

    sys._called_from_test = True


@pytest.fixture
def user_path(tmpdir):
    dir = tmpdir / "llm.datasette.io"
    dir.mkdir()
    return dir


@pytest.fixture
def logs_db(user_path):
    return sqlite_utils.Database(str(user_path / "logs.db"))


@pytest.fixture
def user_path_with_embeddings(user_path):
    path = str(user_path / "embeddings.db")
    db = sqlite_utils.Database(path)
    collection = llm.Collection("demo", db, model_id="embed-demo")
    collection.embed("1", "hello world")
    collection.embed("2", "goodbye world")


@pytest.fixture
def templates_path(user_path):
    dir = user_path / "templates"
    dir.mkdir()
    return dir


@pytest.fixture(autouse=True)
def env_setup(monkeypatch, user_path):
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))


class MockModel(llm.Model):
    model_id = "mock"
    attachment_types = {"image/png", "audio/wav"}

    class Options(llm.Options):
        max_tokens: Optional[int] = Field(
            description="Maximum number of tokens to generate.", default=None
        )

    def __init__(self):
        self.history = []
        self._queue = []

    def enqueue(self, messages):
        assert isinstance(messages, list)
        self._queue.append(messages)

    def execute(self, prompt, stream, response, conversation):
        self.history.append((prompt, stream, response, conversation))
        gathered = []
        while True:
            try:
                messages = self._queue.pop(0)
                for message in messages:
                    gathered.append(message)
                    yield message
                break
            except IndexError:
                break
        response.set_usage(input=len(prompt.prompt.split()), output=len(gathered))


class AsyncMockModel(llm.AsyncModel):
    model_id = "mock"

    def __init__(self):
        self.history = []
        self._queue = []

    def enqueue(self, messages):
        assert isinstance(messages, list)
        self._queue.append(messages)

    async def execute(self, prompt, stream, response, conversation):
        self.history.append((prompt, stream, response, conversation))
        gathered = []
        while True:
            try:
                messages = self._queue.pop(0)
                for message in messages:
                    gathered.append(message)
                    yield message
                break
            except IndexError:
                break
        response.set_usage(input=len(prompt.prompt.split()), output=len(gathered))


class EmbedDemo(llm.EmbeddingModel):
    model_id = "embed-demo"
    batch_size = 10
    supports_binary = True

    def __init__(self):
        self.embedded_content = []

    def embed_batch(self, texts):
        if not hasattr(self, "batch_count"):
            self.batch_count = 0
        self.batch_count += 1
        for text in texts:
            self.embedded_content.append(text)
            words = text.split()[:16]
            embedding = [len(word) for word in words]
            # Pad with 0 up to 16 words
            embedding += [0] * (16 - len(embedding))
            yield embedding


class EmbedBinaryOnly(EmbedDemo):
    model_id = "embed-binary-only"
    supports_text = False
    supports_binary = True


class EmbedTextOnly(EmbedDemo):
    model_id = "embed-text-only"
    supports_text = True
    supports_binary = False


@pytest.fixture
def embed_demo():
    return EmbedDemo()


@pytest.fixture
def mock_model():
    return MockModel()


@pytest.fixture
def async_mock_model():
    return AsyncMockModel()


@pytest.fixture(autouse=True)
def register_embed_demo_model(embed_demo, mock_model, async_mock_model):
    class MockModelsPlugin:
        __name__ = "MockModelsPlugin"

        @llm.hookimpl
        def register_embedding_models(self, register):
            register(embed_demo)
            register(EmbedBinaryOnly())
            register(EmbedTextOnly())

        @llm.hookimpl
        def register_models(self, register):
            register(mock_model, async_model=async_mock_model)

    pm.register(MockModelsPlugin(), name="undo-mock-models-plugin")
    try:
        yield
    finally:
        pm.unregister(name="undo-mock-models-plugin")


@pytest.fixture
def mocked_openai_chat(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "usage": {},
            "choices": [{"message": {"content": "Bob, Alice, Eve"}}],
        },
        headers={"Content-Type": "application/json"},
    )
    return httpx_mock


@pytest.fixture
def mocked_openai_chat_returning_fenced_code(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "usage": {},
            "choices": [
                {
                    "message": {
                        "content": "Code:\n\n````javascript\nfunction foo() {\n  return 'bar';\n}\n````\nDone.",
                    }
                }
            ],
        },
        headers={"Content-Type": "application/json"},
    )
    return httpx_mock


def stream_events():
    for delta, finish_reason in (
        ({"role": "assistant", "content": ""}, None),
        ({"content": "Hi"}, None),
        ({"content": "."}, None),
        ({}, "stop"),
    ):
        yield "data: {}\n\n".format(
            json.dumps(
                {
                    "id": "chat-1",
                    "object": "chat.completion.chunk",
                    "created": 1695096940,
                    "model": "gpt-3.5-turbo-0613",
                    "choices": [
                        {"index": 0, "delta": delta, "finish_reason": finish_reason}
                    ],
                }
            )
        ).encode("utf-8")
    yield "data: [DONE]\n\n".encode("utf-8")


@pytest.fixture
def mocked_openai_chat_stream(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        stream=IteratorStream(stream_events()),
        headers={"Content-Type": "text/event-stream"},
    )


@pytest.fixture
def mocked_openai_completion(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/completions",
        json={
            "id": "cmpl-uqkvlQyYK7bGYrRHQ0eXlWi7",
            "object": "text_completion",
            "created": 1589478378,
            "model": "gpt-3.5-turbo-instruct",
            "choices": [
                {
                    "text": "\n\nThis is indeed a test",
                    "index": 0,
                    "logprobs": None,
                    "finish_reason": "length",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        },
        headers={"Content-Type": "application/json"},
    )
    return httpx_mock


def stream_completion_events():
    choices_chunks = [
        [
            {
                "text": "\n\n",
                "index": 0,
                "logprobs": {
                    "tokens": ["\n\n"],
                    "token_logprobs": [-0.6],
                    "top_logprobs": [{"\n\n": -0.6, "\n": -1.9}],
                    "text_offset": [16],
                },
                "finish_reason": None,
            }
        ],
        [
            {
                "text": "Hi",
                "index": 0,
                "logprobs": {
                    "tokens": ["Hi"],
                    "token_logprobs": [-1.1],
                    "top_logprobs": [{"Hi": -1.1, "Hello": -0.7}],
                    "text_offset": [18],
                },
                "finish_reason": None,
            }
        ],
        [
            {
                "text": ".",
                "index": 0,
                "logprobs": {
                    "tokens": ["."],
                    "token_logprobs": [-1.1],
                    "top_logprobs": [{".": -1.1, "!": -0.9}],
                    "text_offset": [20],
                },
                "finish_reason": None,
            }
        ],
        [
            {
                "text": "",
                "index": 0,
                "logprobs": {
                    "tokens": [],
                    "token_logprobs": [],
                    "top_logprobs": [],
                    "text_offset": [],
                },
                "finish_reason": "stop",
            }
        ],
    ]

    for choices in choices_chunks:
        yield "data: {}\n\n".format(
            json.dumps(
                {
                    "id": "cmpl-80MdSaou7NnPuff5ZyRMysWBmgSPS",
                    "object": "text_completion",
                    "created": 1695097702,
                    "choices": choices,
                    "model": "gpt-3.5-turbo-instruct",
                }
            )
        ).encode("utf-8")
    yield "data: [DONE]\n\n".encode("utf-8")


@pytest.fixture
def mocked_openai_completion_logprobs_stream(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/completions",
        stream=IteratorStream(stream_completion_events()),
        headers={"Content-Type": "text/event-stream"},
    )
    return httpx_mock


@pytest.fixture
def mocked_openai_completion_logprobs(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/completions",
        json={
            "id": "cmpl-80MeBfKJutM0uMNJkRrebJLeP3bxL",
            "object": "text_completion",
            "created": 1695097747,
            "model": "gpt-3.5-turbo-instruct",
            "choices": [
                {
                    "text": "\n\nHi.",
                    "index": 0,
                    "logprobs": {
                        "tokens": ["\n\n", "Hi", "1"],
                        "token_logprobs": [-0.6, -1.1, -0.9],
                        "top_logprobs": [
                            {"\n\n": -0.6, "\n": -1.9},
                            {"Hi": -1.1, "Hello": -0.7},
                            {".": -0.9, "!": -1.1},
                        ],
                        "text_offset": [16, 18, 20],
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        },
        headers={"Content-Type": "application/json"},
    )
    return httpx_mock


@pytest.fixture
def mocked_localai(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://localai.localhost/chat/completions",
        json={
            "model": "orca",
            "usage": {},
            "choices": [{"message": {"content": "Bob, Alice, Eve"}}],
        },
        headers={"Content-Type": "application/json"},
    )
    httpx_mock.add_response(
        method="POST",
        url="http://localai.localhost/completions",
        json={
            "model": "completion-babbage",
            "usage": {},
            "choices": [{"text": "Hello"}],
        },
        headers={"Content-Type": "application/json"},
    )
    return httpx_mock


@pytest.fixture
def collection():
    collection = llm.Collection("test", model_id="embed-demo")
    collection.embed(1, "hello world")
    collection.embed(2, "goodbye world")
    return collection
