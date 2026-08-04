import base64
import json

import sqlite_utils
from click.testing import CliRunner
from pytest_httpx import IteratorStream

from llm.cli import cli
from llm.migrations import migrate


def _add_chat_response(httpx_mock, url, text):
    httpx_mock.add_response(
        method="POST",
        url=f"{url}/chat/completions",
        json={
            "id": "chatcmpl_test",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 2,
                "total_tokens": 5,
            },
        },
        headers={"Content-Type": "application/json"},
    )


def _add_chat_tool_call_response(httpx_mock, url, name, arguments):
    httpx_mock.add_response(
        method="POST",
        url=f"{url}/chat/completions",
        json={
            "id": "chatcmpl_tool_test",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_test",
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(arguments),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 2,
                "total_tokens": 5,
            },
        },
        headers={"Content-Type": "application/json"},
    )


def _responses_payload(text):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": "test-model",
        "output": [
            {
                "type": "message",
                "id": "msg_test",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 3,
            "output_tokens": 2,
            "total_tokens": 5,
        },
        "status": "completed",
    }


def _responses_tool_call_payload(name, arguments):
    return {
        "id": "resp_tool_test",
        "object": "response",
        "created_at": 1,
        "model": "test-model",
        "output": [
            {
                "type": "function_call",
                "id": "fc_test",
                "call_id": "call_test",
                "name": name,
                "arguments": json.dumps(arguments),
                "status": "completed",
            }
        ],
        "usage": {
            "input_tokens": 3,
            "output_tokens": 2,
            "total_tokens": 5,
        },
        "status": "completed",
    }


def _chat_stream_events():
    for delta, finish_reason in (
        ({"role": "assistant", "content": ""}, None),
        ({"content": "Hello"}, None),
        ({"content": " streamed"}, None),
        ({}, "stop"),
    ):
        yield "data: {}\n\n".format(
            json.dumps(
                {
                    "id": "chatcmpl_stream_test",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "finish_reason": finish_reason,
                        }
                    ],
                }
            )
        ).encode("utf-8")
    yield b"data: [DONE]\n\n"


def test_endpoint_chat_completions_does_not_log_or_leak_default_key(
    httpx_mock, user_path, monkeypatch
):
    base_url = "https://example.test/v1"
    _add_chat_response(httpx_mock, base_url, "Hello from the endpoint")
    monkeypatch.setenv("OPENAI_API_KEY", "real-default-openai-key")

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "Hello",
            "-m",
            "test-model",
            "--no-stream",
            "-H",
            "X-Test",
            "one",
            "-o",
            "reasoning_effort",
            "low",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "Hello from the endpoint\n"
    assert not (user_path / "logs.db").exists()

    request = httpx_mock.get_requests()[0]
    assert request.headers["Authorization"] == "Bearer DUMMY_KEY"
    assert request.headers["X-Test"] == "one"
    assert json.loads(request.content) == {
        "messages": [{"role": "user", "content": "Hello"}],
        "model": "test-model",
        "reasoning_effort": "low",
        "stream": False,
    }


def test_endpoint_chat_completions_attachment(httpx_mock, user_path, tmp_path):
    base_url = "https://attachments.example.test/v1"
    _add_chat_response(httpx_mock, base_url, "A test image")
    image_bytes = b"\x89PNG\r\n\x1a\nendpoint attachment"
    image_path = tmp_path / "image.png"
    image_path.write_bytes(image_bytes)

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "Describe this",
            "-m",
            "test-model",
            "--no-stream",
            "-a",
            str(image_path),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "A test image\n"
    assert not (user_path / "logs.db").exists()
    assert json.loads(httpx_mock.get_requests()[0].content)["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,{}".format(
                            base64.b64encode(image_bytes).decode("ascii")
                        )
                    },
                },
            ],
        }
    ]


def test_endpoint_template(httpx_mock, user_path, templates_path):
    base_url = "https://templates.example.test/v1"
    _add_chat_response(httpx_mock, base_url, "Template response")
    (templates_path / "endpoint.yaml").write_text(
        """
model: template-model
system: You are $persona
prompt: "Question: $input"
options:
  temperature: 0.4
schema_object:
  type: object
  properties:
    answer:
      type: string
  required:
  - answer
attachment_types:
- type: image/jpeg
  value: https://images.example.test/template.jpg
""".strip(),
        "utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "Where?",
            "--template",
            "endpoint",
            "--schema",
            '{"type": "object"}',
            "--param",
            "persona",
            "concise",
            "--no-stream",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "Template response\n"
    assert not (user_path / "logs.db").exists()
    assert json.loads(httpx_mock.get_requests()[0].content) == {
        "messages": [
            {"role": "system", "content": "You are concise"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Question: Where?"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "https://images.example.test/template.jpg"
                        },
                    },
                ],
            },
        ],
        "model": "template-model",
        # CLI --schema takes precedence over template schema_object
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "output",
                "schema": {"type": "object"},
            },
        },
        "stream": False,
        "temperature": 0.4,
    }


def test_endpoint_template_schema_object_used_when_no_cli_schema(
    httpx_mock, user_path, templates_path
):
    base_url = "https://templates2.example.test/v1"
    _add_chat_response(httpx_mock, base_url, "Template response 2")
    (templates_path / "schemaonly.yaml").write_text(
        """
model: schema-model
schema_object:
  type: object
  properties:
    answer:
      type: string
  required:
  - answer
""".strip(),
        "utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "test question",
            "--template",
            "schemaonly",
            "--no-stream",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    request_body = json.loads(httpx_mock.get_requests()[0].content)
    assert request_body["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "output",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
    }


def test_endpoint_schema(httpx_mock, user_path):
    base_url = "https://schema.example.test/v1"
    _add_chat_response(httpx_mock, base_url, '{"name": "Cleo", "age": 10}')

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "Invent a dog",
            "-m",
            "test-model",
            "--schema",
            "name, age int",
            "--no-stream",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert not (user_path / "logs.db").exists()
    request_body = json.loads(httpx_mock.get_requests()[0].content)
    assert request_body["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "output",
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                },
                "required": ["name", "age"],
            },
        },
    }


def test_endpoint_schema_by_id_from_existing_logs_database(httpx_mock, user_path):
    base_url = "https://schema-id.example.test/v1"
    _add_chat_response(httpx_mock, base_url, '{"name": "Cleo"}')
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    db = sqlite_utils.Database(str(user_path / "logs.db"))
    migrate(db)
    db["schemas"].insert({"id": "dog-schema", "content": json.dumps(schema)})
    assert (user_path / "logs.db").exists()

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "Invent a dog",
            "-m",
            "test-model",
            "--schema",
            "dog-schema",
            "--no-stream",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    request_body = json.loads(httpx_mock.get_requests()[0].content)
    assert request_body["response_format"]["json_schema"]["schema"] == schema
    assert db["responses"].count == 0


def test_endpoint_invalid_schema_id_does_not_create_logs_database(user_path):
    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            "https://schema-id.example.test/v1",
            "Invent a dog",
            "-m",
            "test-model",
            "--schema",
            "missing-schema",
            "--no-stream",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 2
    assert "Invalid schema" in result.output
    assert not (user_path / "logs.db").exists()


def test_endpoint_static_template_runs_once_on_terminal(
    httpx_mock, user_path, templates_path, monkeypatch
):
    base_url = "https://terminal-template.example.test/v1"
    _add_chat_response(httpx_mock, base_url, "Five pelicans")
    (templates_path / "pelican.yaml").write_text(
        "prompt: List five pelican names\n", "utf-8"
    )
    monkeypatch.setattr("click.testing._NamedTextIOWrapper.isatty", lambda self: True)

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "-m",
            "test-model",
            "-t",
            "pelican",
            "--no-stream",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "Five pelicans\n"
    assert not (user_path / "logs.db").exists()
    assert json.loads(httpx_mock.get_requests()[0].content)["messages"] == [
        {"role": "user", "content": "List five pelican names"}
    ]


def test_endpoint_tools_and_functions(httpx_mock, user_path):
    base_url = "https://tools.example.test/v1"
    _add_chat_tool_call_response(httpx_mock, base_url, "multiply", {"a": 6, "b": 7})
    _add_chat_response(httpx_mock, base_url, "The answer is 42")

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "What is 6 * 7?",
            "-m",
            "test-model",
            "--no-stream",
            "-T",
            "llm_version",
            "--functions",
            (
                "def multiply(a: int, b: int) -> int:\n"
                '    "Multiply two numbers."\n'
                "    return a * b\n"
            ),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "The answer is 42\n"
    assert not (user_path / "logs.db").exists()

    requests = [json.loads(request.content) for request in httpx_mock.get_requests()]
    assert len(requests) == 2
    assert {tool["function"]["name"] for tool in requests[0]["tools"]} == {
        "llm_version",
        "multiply",
    }
    assert requests[1]["messages"] == [
        {"role": "user", "content": "What is 6 * 7?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_test",
                    "type": "function",
                    "function": {
                        "name": "multiply",
                        "arguments": '{"a": 6, "b": 7}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "content": "42",
            "tool_call_id": "call_test",
        },
    ]


def test_endpoint_streams_by_default(httpx_mock, user_path):
    base_url = "https://stream.example.test/v1"
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/chat/completions",
        stream=IteratorStream(_chat_stream_events()),
        headers={"Content-Type": "text/event-stream"},
    )

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "Hello",
            "-m",
            "test-model",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "Hello streamed\n"
    assert not (user_path / "logs.db").exists()
    request_body = json.loads(httpx_mock.get_requests()[0].content)
    assert request_body["stream"] is True
    assert request_body["stream_options"] == {"include_usage": True}


def test_endpoint_uses_explicit_key(httpx_mock, user_path):
    base_url = "https://example.test/v1"
    _add_chat_response(httpx_mock, base_url, "Authenticated")

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "Hello",
            "-m",
            "test-model",
            "--no-stream",
            "--key",
            "endpoint-key",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert httpx_mock.get_requests()[0].headers["Authorization"] == (
        "Bearer endpoint-key"
    )
    assert not (user_path / "logs.db").exists()


def test_endpoint_lists_models_without_model_or_logging(
    httpx_mock, user_path, monkeypatch
):
    base_url = "https://models.example.test/v1"
    monkeypatch.setenv("OPENAI_API_KEY", "real-default-openai-key")
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/models",
        json={
            "object": "list",
            "data": [
                {
                    "id": "first-model",
                    "object": "model",
                    "created": 1,
                    "owned_by": "example",
                },
                {
                    "id": "second-model",
                    "object": "model",
                    "created": 2,
                    "owned_by": "example",
                },
            ],
        },
        headers={"Content-Type": "application/json"},
    )

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "--models",
            "-H",
            "X-Test",
            "one",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "first-model\nsecond-model\n"
    assert not (user_path / "logs.db").exists()
    request = httpx_mock.get_requests()[0]
    assert request.headers["Authorization"] == "Bearer DUMMY_KEY"
    assert request.headers["X-Test"] == "one"


def test_endpoint_models_surfaces_error_from_successful_response(httpx_mock, user_path):
    base_url = "https://models-error.example.test"
    httpx_mock.add_response(
        method="GET",
        url=f"{base_url}/models",
        json={"error": "Unexpected endpoint or method. (GET /models)"},
        headers={"Content-Type": "application/json"},
    )

    result = CliRunner().invoke(
        cli,
        ["openai", "endpoint", base_url, "--models"],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert result.output == "Error: Unexpected endpoint or method. (GET /models)\n"
    assert not (user_path / "logs.db").exists()


def test_endpoint_responses_api(httpx_mock, user_path):
    base_url = "https://responses.example.test/v1"
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/responses",
        json=_responses_payload("Hello from Responses"),
        headers={"Content-Type": "application/json"},
    )

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "Hello",
            "-m",
            "test-model",
            "--responses",
            "--no-stream",
            "-o",
            "verbosity",
            "low",
            "-o",
            "reasoning_effort",
            "low",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "Hello from Responses\n"
    assert not (user_path / "logs.db").exists()
    assert json.loads(httpx_mock.get_requests()[0].content) == {
        "input": [{"role": "user", "content": "Hello"}],
        "include": ["reasoning.encrypted_content"],
        "model": "test-model",
        "reasoning": {"effort": "low"},
        "store": False,
        "stream": False,
        "text": {"verbosity": "low"},
    }


def test_endpoint_responses_api_attachment(httpx_mock, user_path):
    base_url = "https://responses-attachments.example.test/v1"
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/responses",
        json=_responses_payload("A remote image"),
        headers={"Content-Type": "application/json"},
    )

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "Describe this",
            "-m",
            "test-model",
            "--responses",
            "--no-stream",
            "--at",
            "https://images.example.test/test.jpg",
            "image/jpeg",
            "-o",
            "image_detail",
            "original",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "A remote image\n"
    assert not (user_path / "logs.db").exists()
    request_body = json.loads(httpx_mock.get_requests()[0].content)
    assert "include" not in request_body
    assert "reasoning" not in request_body
    assert request_body["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Describe this"},
                {
                    "type": "input_image",
                    "image_url": "https://images.example.test/test.jpg",
                    "detail": "original",
                },
            ],
        }
    ]


def test_endpoint_responses_api_schema_multi(httpx_mock, user_path):
    base_url = "https://responses-schema.example.test/v1"
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/responses",
        json=_responses_payload('{"items": [{"name": "Cleo", "age": 10}]}'),
        headers={"Content-Type": "application/json"},
    )

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "Invent a dog",
            "-m",
            "test-model",
            "--responses",
            "--schema-multi",
            "name, age int",
            "--no-stream",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert not (user_path / "logs.db").exists()
    request_body = json.loads(httpx_mock.get_requests()[0].content)
    assert request_body["text"]["format"] == {
        "type": "json_schema",
        "name": "output",
        "schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "age": {"type": "integer"},
                        },
                        "required": ["name", "age"],
                    },
                }
            },
            "required": ["items"],
        },
        "strict": False,
    }


def test_endpoint_responses_api_tools(httpx_mock, user_path):
    base_url = "https://responses-tools.example.test/v1"
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/responses",
        json=_responses_tool_call_payload("multiply", {"a": 6, "b": 7}),
        headers={"Content-Type": "application/json"},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/responses",
        json=_responses_payload("The answer is 42"),
        headers={"Content-Type": "application/json"},
    )

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "What is 6 * 7?",
            "-m",
            "test-model",
            "--responses",
            "--no-stream",
            "--functions",
            (
                "def multiply(a: int, b: int) -> int:\n"
                '    "Multiply two numbers."\n'
                "    return a * b\n"
            ),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "The answer is 42\n"
    assert not (user_path / "logs.db").exists()

    requests = [json.loads(request.content) for request in httpx_mock.get_requests()]
    assert requests[0]["tools"][0]["name"] == "multiply"
    assert requests[1]["input"] == [
        {"role": "user", "content": "What is 6 * 7?"},
        {
            "type": "function_call",
            "call_id": "call_test",
            "name": "multiply",
            "arguments": '{"a": 6, "b": 7}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_test",
            "output": "42",
        },
    ]


def test_endpoint_responses_api_raw_server_side_tool(httpx_mock, user_path):
    base_url = "https://raw-tools.example.test/v1"
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/responses",
        json=_responses_payload("Search complete"),
        headers={"Content-Type": "application/json"},
    )
    tool_spec = {
        "type": "openrouter:web_search",
        "parameters": {"engine": "exa", "max_results": 2, "max_uses": 1},
    }

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "Search for the latest news",
            "-m",
            "test-model",
            "--responses",
            "--no-stream",
            "-T",
            f"ServerSideTool(spec={json.dumps(tool_spec)})",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "Search complete\n"
    assert not (user_path / "logs.db").exists()
    request_body = json.loads(httpx_mock.get_requests()[0].content)
    assert request_body["tools"] == [tool_spec]


def test_endpoint_reads_one_off_prompt_from_stdin(httpx_mock, user_path):
    base_url = "https://stdin.example.test/v1"
    _add_chat_response(httpx_mock, base_url, "From stdin")

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "-m",
            "test-model",
            "--no-stream",
        ],
        input="Hello from stdin",
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    request_body = json.loads(httpx_mock.get_requests()[0].content)
    assert request_body["messages"] == [{"role": "user", "content": "Hello from stdin"}]
    assert not (user_path / "logs.db").exists()


def test_endpoint_without_prompt_waits_for_stdin(httpx_mock, user_path, monkeypatch):
    base_url = "https://terminal-stdin.example.test/v1"
    _add_chat_response(httpx_mock, base_url, "From awaited stdin")
    monkeypatch.setattr("click.testing._NamedTextIOWrapper.isatty", lambda self: True)

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "-m",
            "test-model",
            "--no-stream",
        ],
        input="Hello after waiting for stdin",
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "From awaited stdin\n"
    request_body = json.loads(httpx_mock.get_requests()[0].content)
    assert request_body["messages"] == [
        {"role": "user", "content": "Hello after waiting for stdin"}
    ]
    assert not (user_path / "logs.db").exists()


def test_endpoint_interactive_chat_preserves_history(
    httpx_mock, user_path, templates_path
):
    base_url = "https://chat.example.test/v1"
    _add_chat_response(httpx_mock, base_url, "First answer")
    _add_chat_response(httpx_mock, base_url, "Second answer")
    (templates_path / "endpoint-chat.yaml").write_text(
        'prompt: "Question: $input"\n', "utf-8"
    )

    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            base_url,
            "-m",
            "test-model",
            "--chat",
            "--no-stream",
            "--system",
            "Be brief",
            "--template",
            "endpoint-chat",
            "--functions",
            (
                "def lookup(value: str) -> str:\n"
                '    "Look up a value."\n'
                "    return value\n"
            ),
            "--at",
            "https://images.example.test/context.jpg",
            "image/jpeg",
        ],
        input="First question\nSecond question\nquit\n",
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "First answer" in result.output
    assert "Second answer" in result.output
    assert not (user_path / "logs.db").exists()

    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    request_bodies = [json.loads(request.content) for request in requests]
    assert all(
        body["tools"][0]["function"]["name"] == "lookup" for body in request_bodies
    )
    assert request_bodies[1]["messages"] == [
        {"role": "system", "content": "Be brief"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Question: First question"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "https://images.example.test/context.jpg",
                    },
                },
            ],
        },
        {"role": "assistant", "content": "First answer"},
        {"role": "user", "content": "Question: Second question"},
    ]
