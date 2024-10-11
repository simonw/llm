import enum
from typing import Annotated, Union
import json
import os
import functools

import pytest
from pytest_httpx import IteratorStream
from click.testing import CliRunner

from llm.tool import Tool
from llm.cli import cli
from llm.default_plugins import file_tools


def test_no_parameters():
    @Tool
    def tool() -> str:
        "tool description"
        return "output"

    assert tool.schema == {
        "type": "function",
        "function": {"name": "tool", "description": "tool description"},
    }
    assert tool("{}") == "output"


def test_missing_description():
    with pytest.raises(ValueError, match=" description"):

        @Tool
        def tool() -> str:
            return "output"


def test_invalid_return():
    with pytest.raises(ValueError, match=" return"):

        @Tool
        def tool() -> int:
            "tool description"


def test_missing_annotated():
    with pytest.raises(ValueError, match=" annotated"):

        @Tool
        def tool(a: int) -> str:
            "tool description"


def test_missing_annotated_description():
    with pytest.raises(TypeError, match=" at least two arguments"):

        @Tool
        def tool(a: Annotated[int]) -> str:
            "tool description"


def test_unsupported_parameters():
    with pytest.raises(TypeError, match=" parameter type"):

        @Tool
        def tool(a: Annotated[object, "a desc"]) -> str:
            "tool description"


def test_call():
    @Tool
    def tool(a: Annotated[int, "a desc"]) -> str:
        "tool description"
        return "output"

    assert tool(json.dumps({"a": 1})) == "output"

    assert "exception" in tool("{}")
    assert "exception" in tool(json.dumps({"a": 1, "b": 2}))


def test_annotated_parameters():
    @Tool
    def tool(
        a: Annotated[bool, "a desc"],
        b: Annotated[int, "b desc"] = 1,
        c: Annotated[Union[str, None], "c desc"] = "2",
    ) -> str:
        "tool description"
        return "output"

    assert tool.schema == {
        "type": "function",
        "function": {
            "name": "tool",
            "description": "tool description",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"description": "a desc", "type": "boolean"},
                    "b": {"description": "b desc", "type": "integer"},
                    "c": {"description": "c desc", "type": "string"},
                },
                "required": ["a"],
                "additionalProperties": False,
            },
        },
    }
    assert tool(json.dumps({"a": True})) == "output"


def test_enum_parameters():
    class MyEnum(enum.Enum):
        A = "a"
        B = "b"

    @Tool
    def tool(
        a: Annotated[MyEnum, "a enum desc"],
        b: Annotated[int, "b desc"] = 1,
    ) -> str:
        "tool description"
        return "output"

    assert tool.schema == {
        "type": "function",
        "function": {
            "name": "tool",
            "description": "tool description",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {
                        "description": "a enum desc",
                        "type": "string",
                        "enum": ["a", "b"],
                    },
                    "b": {"description": "b desc", "type": "integer"},
                },
                "required": ["a"],
                "additionalProperties": False,
            },
        },
    }
    assert tool(json.dumps({"a": MyEnum.A.value})) == "output"


def test_list_parameters():
    @Tool
    def tool(
        a: Annotated[list, "a enum desc"],
        b: Annotated[list[int], "b desc"],
        c: Annotated[list[str], "c desc"],
    ) -> str:
        "tool description"
        return "output"

    assert tool.schema == {
        "type": "function",
        "function": {
            "name": "tool",
            "description": "tool description",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"description": "a enum desc", "type": "array"},
                    "b": {
                        "description": "b desc",
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                    "c": {
                        "description": "c desc",
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["a", "b", "c"],
                "additionalProperties": False,
            },
        },
    }
    assert tool(json.dumps({"a": [], "b": [1], "c": ["s"]})) == "output"


def test_unsupported_list_parameters():
    with pytest.raises(TypeError, match=" parameter type"):

        @Tool
        def tool(
            a: Annotated[list[Union[str, int]], "a enum desc"],
        ) -> str:
            "tool description"
            return "output"


def test_object_tool():
    class MyTool:
        "tool description"

        __name__ = "tool"

        def __call__(
            self,
            a: Annotated[bool, "a desc"],
            b: Annotated[int, "b desc"] = 1,
        ) -> str:
            return "output"

    tool = Tool(MyTool())

    assert tool.schema == {
        "type": "function",
        "function": {
            "name": "tool",
            "description": "tool description",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"description": "a desc", "type": "boolean"},
                    "b": {"description": "b desc", "type": "integer"},
                },
                "required": ["a"],
                "additionalProperties": False,
            },
        },
    }
    assert tool(json.dumps({"a": True, "b": 3})) == "output"


def stream_tool_call(datafile):
    with open(datafile) as f:
        for line in f:
            yield f"{line}\n\n".encode("utf-8")


@pytest.fixture
def read_files_mock(monkeypatch):
    def mock_read_files(filenames):
        return "some license text"

    monkeypatch.setattr(
        file_tools,
        "read_files",
        functools.update_wrapper(mock_read_files, file_tools.read_files),
    )


def test_tool_completion_stream(httpx_mock, read_files_mock, logs_db):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        stream=IteratorStream(
            stream_tool_call(
                os.path.join(os.path.dirname(__file__), "fixtures/stream_tool_call.txt")
            )
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        stream=IteratorStream(
            stream_tool_call(
                os.path.join(
                    os.path.dirname(__file__), "fixtures/stream_tool_call_result.txt"
                )
            )
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(
        cli,
        [
            "--enable-tools",
            "-m",
            "4o-mini",
            "--key",
            "x",
            "Summarize this file LICENSE.txt",
        ],
    )
    assert result.exit_code == 0
    assert result.output == (
        'The file LICENSE.txt states that software distributed under this License is provided "AS IS," '
        "without any warranties or conditions, either express or implied. "
        "It emphasizes that the user should refer to the License for specific permissions and "
        "limitations regarding the software.\n"
    )
    rows = list(logs_db["responses"].rows_where(select="response_json"))
    assert (
        len(json.loads(rows[0]["response_json"])) == 2
    )  # two response_jsons for tools


def test_tool_completion_nostream(httpx_mock, read_files_mock, logs_db):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        json={
            "id": "chatcmpl-AGWNZTKcKeVOqSmRraGyzeEnOzs4O",
            "object": "chat.completion",
            "created": 1728501077,
            "model": "gpt-4o-mini-2024-07-18",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_SSoLPi8JuIZ1WDygNI5CSCkx",
                                "type": "function",
                                "function": {
                                    "name": "read_files",
                                    "arguments": '{"filenames":["LICENSE.txt"]}',
                                },
                            }
                        ],
                        "refusal": None,
                    },
                    "logprobs": None,
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 74,
                "completion_tokens": 17,
                "total_tokens": 91,
                "prompt_tokens_details": {"cached_tokens": 0},
                "completion_tokens_details": {"reasoning_tokens": 0},
            },
            "system_fingerprint": "fp_74ba47b4ac",
        },
        headers={"Content-Type": "application/json"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        json={
            "id": "chatcmpl-AGWNa4MUDJ7q6pm2KZqutUqPWlQnX",
            "object": "chat.completion",
            "created": 1728501078,
            "model": "gpt-4o-mini-2024-07-18",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": 'The LICENSE.txt file states that the software is distributed "AS IS," without any warranties or conditions, either express or implied. It advises the reader to refer to the License for specific terms regarding permissions and limitations.',
                        "refusal": None,
                    },
                    "logprobs": None,
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 174,
                "completion_tokens": 43,
                "total_tokens": 217,
                "prompt_tokens_details": {"cached_tokens": 0},
                "completion_tokens_details": {"reasoning_tokens": 0},
            },
            "system_fingerprint": "fp_f85bea6784",
        },
        headers={"Content-Type": "application/json"},
    )
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(
        cli,
        [
            "--no-stream",
            "--enable-tools",
            "-m",
            "4o-mini",
            "--key",
            "x",
            "Summarize this file LICENSE.txt",
        ],
    )
    assert result.exit_code == 0
    assert result.output == (
        'The LICENSE.txt file states that the software is distributed "AS IS," '
        "without any warranties or conditions, either express or implied. "
        "It advises the reader to refer to the License for specific terms regarding "
        "permissions and limitations.\n"
    )
    rows = list(logs_db["responses"].rows_where(select="response_json"))
    assert (
        len(json.loads(rows[0]["response_json"])) == 2
    )  # two response_jsons for tools
