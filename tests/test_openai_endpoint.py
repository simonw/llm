import base64
import json

from click.testing import CliRunner
from pytest_httpx import IteratorStream

from llm.cli import cli


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
        "stream": False,
        "temperature": 0.4,
    }


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
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "Hello from Responses\n"
    assert not (user_path / "logs.db").exists()
    assert json.loads(httpx_mock.get_requests()[0].content) == {
        "input": [{"role": "user", "content": "Hello"}],
        "model": "test-model",
        "store": False,
        "stream": False,
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
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "A remote image\n"
    assert not (user_path / "logs.db").exists()
    assert json.loads(httpx_mock.get_requests()[0].content)["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Describe this"},
                {
                    "type": "input_image",
                    "image_url": "https://images.example.test/test.jpg",
                },
            ],
        }
    ]


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
    assert json.loads(requests[1].content)["messages"] == [
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
