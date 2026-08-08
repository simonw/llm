import json

import pytest
import sqlite_utils
from click.testing import CliRunner

import llm
from llm.cli import cli
from llm.logs import LogStore


@pytest.fixture
def mocked_models(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="https://api.openai.com/v1/models",
        json={
            "data": [
                {
                    "id": "ada:2020-05-03",
                    "object": "model",
                    "created": 1588537600,
                    "owned_by": "openai",
                },
                {
                    "id": "babbage:2020-05-03",
                    "object": "model",
                    "created": 1588537600,
                    "owned_by": "openai",
                },
            ]
        },
        headers={"Content-Type": "application/json"},
    )
    return httpx_mock


def test_openai_models(mocked_models):
    runner = CliRunner()
    result = runner.invoke(cli, ["openai", "models", "--key", "x"])
    assert result.exit_code == 0
    assert result.output == (
        "id                    owned_by    created                  \n"
        "ada:2020-05-03        openai      2020-05-03T20:26:40+00:00\n"
        "babbage:2020-05-03    openai      2020-05-03T20:26:40+00:00\n"
    )


def test_openai_options_min_max():
    options = {
        "temperature": [0, 2],
        "top_p": [0, 1],
        "frequency_penalty": [-2, 2],
        "presence_penalty": [-2, 2],
    }
    runner = CliRunner()

    for option, [min_val, max_val] in options.items():
        result = runner.invoke(cli, ["-m", "chatgpt", "-o", option, "-10"])
        assert result.exit_code == 1
        assert f"greater than or equal to {min_val}" in result.output
        result2 = runner.invoke(cli, ["-m", "chatgpt", "-o", option, "10"])
        assert result2.exit_code == 1
        assert f"less than or equal to {max_val}" in result2.output


@pytest.mark.parametrize(
    "model_id",
    (
        "gpt-5",
        "gpt-5-mini",
        "gpt-5.1",
        "gpt-5.2",
        "gpt-5.4",
        "gpt-5.5",
    ),
)
def test_gpt5_models_support_verbosity_option(model_id):
    assert "verbosity" in llm.get_model(model_id).Options.model_fields
    assert "verbosity" in llm.get_async_model(model_id).Options.model_fields


@pytest.mark.parametrize("model_id", ("gpt-4o", "o3", "o4-mini"))
def test_non_gpt5_openai_chat_models_do_not_support_verbosity_option(model_id):
    assert "verbosity" not in llm.get_model(model_id).Options.model_fields
    assert "verbosity" not in llm.get_async_model(model_id).Options.model_fields


@pytest.mark.parametrize(
    "model_id",
    (
        "chatgpt-4o-latest",
        "gpt-4o-audio-preview",
        "gpt-4o-audio-preview-2024-12-17",
        "gpt-4o-audio-preview-2024-10-01",
        "gpt-4o-mini-audio-preview",
        "gpt-4o-mini-audio-preview-2024-12-17",
        "gpt-4-32k",
        "gpt-4-1106-preview",
        "gpt-4-0125-preview",
        "gpt-4.5-preview-2025-02-27",
        "gpt-4.5-preview",
        "o1-preview",
        "o1-mini",
        "gpt-5.1-chat-latest",
    ),
)
def test_deprecated_models_are_not_registered(model_id):
    with pytest.raises(llm.UnknownModelError):
        llm.get_model(model_id)
    with pytest.raises(llm.UnknownModelError):
        llm.get_async_model(model_id)


def test_gpt5_verbosity_option_is_sent_to_openai_chat_completions(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        json={
            "model": "gpt-5",
            "usage": {},
            "choices": [{"message": {"content": "Verbose enough"}}],
        },
        headers={"Content-Type": "application/json"},
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "-m",
            "gpt-5",
            "-o",
            "chat_completions",
            "1",
            "-o",
            "verbosity",
            "high",
            "--no-stream",
            "--key",
            "x",
            "Say hi",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert request_body["verbosity"] == "high"
    assert "text" not in request_body


def test_gpt5_verbosity_option_is_sent_to_openai_responses_by_default(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json={
            "id": "resp_test_1",
            "object": "response",
            "created_at": 1,
            "model": "gpt-5",
            "output": [
                {
                    "type": "message",
                    "id": "msg_1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Verbose enough",
                            "annotations": [],
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": 5,
                "output_tokens": 3,
                "total_tokens": 8,
            },
            "status": "completed",
        },
        headers={"Content-Type": "application/json"},
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "-m",
            "gpt-5",
            "-o",
            "verbosity",
            "high",
            "--no-stream",
            "--key",
            "x",
            "Say hi",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert request_body["text"]["verbosity"] == "high"
    assert request_body["include"] == ["reasoning.encrypted_content"]
    assert "verbosity" not in request_body


def test_gpt5_verbosity_option_validates_allowed_values():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["-m", "gpt-5", "-o", "verbosity", "extreme", "Say hi"],
    )
    assert result.exit_code == 1
    assert "Input should be 'low', 'medium' or 'high'" in result.output


def test_code_interpreter_cli_tool_is_resolved_from_model(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json={
            "id": "resp_code_interpreter_cli",
            "object": "response",
            "created_at": 1,
            "model": "gpt-5.6-luna",
            "output": [
                {
                    "type": "message",
                    "id": "msg_code_interpreter_cli",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Calculated",
                            "annotations": [],
                        }
                    ],
                }
            ],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "status": "completed",
        },
        headers={"Content-Type": "application/json"},
    )
    result = CliRunner().invoke(
        cli,
        [
            "-m",
            "gpt-5.6-luna",
            "-T",
            'CodeInterpreter(memory_limit="4g")',
            "--no-stream",
            "--no-log",
            "--key",
            "x",
            "Run this calculation",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.stdout == "Calculated\n"
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert request_body["tools"] == [
        {
            "type": "code_interpreter",
            "container": {"type": "auto", "memory_limit": "4g"},
        }
    ]
    assert "code_interpreter_call.outputs" in request_body["include"]


def test_code_interpreter_cli_tool_is_reused_on_continue(httpx_mock, user_path):
    def response_payload(response_id, text):
        return {
            "id": response_id,
            "object": "response",
            "created_at": 1,
            "model": "gpt-5.6-luna",
            "output": [
                {
                    "type": "message",
                    "id": f"msg_{response_id}",
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
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "status": "completed",
        }

    first_payload = response_payload("resp_code_interpreter_first", "Calculated")
    first_payload["output"] = [
        {
            "type": "message",
            "id": "msg_before_code",
            "role": "assistant",
            "status": "completed",
            "content": [
                {
                    "type": "output_text",
                    "text": "Running Python",
                    "annotations": [],
                }
            ],
        },
        {
            "type": "code_interpreter_call",
            "id": "ci_continue",
            "status": "completed",
            "container_id": "cntr_continue",
            "code": "print(6 * 7)",
            "outputs": [{"type": "logs", "logs": "42\n"}],
        },
        {
            "type": "message",
            "id": "msg_after_code",
            "role": "assistant",
            "status": "completed",
            "content": [
                {
                    "type": "output_text",
                    "text": "Calculated",
                    "annotations": [],
                }
            ],
        },
    ]
    for payload in (
        first_payload,
        response_payload("resp_code_interpreter_second", "Continued"),
    ):
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/responses",
            json=payload,
            headers={"Content-Type": "application/json"},
        )

    runner = CliRunner()
    first = runner.invoke(
        cli,
        [
            "-m",
            "gpt-5.6-luna",
            "-T",
            'CodeInterpreter(memory_limit="4g")',
            "--no-stream",
            "--key",
            "x",
            "Run this calculation",
        ],
        catch_exceptions=False,
    )
    second = runner.invoke(
        cli,
        ["Continue", "-c", "--no-stream", "--key", "x"],
        catch_exceptions=False,
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert second.output == "Continued\n"
    request_bodies = [
        json.loads(request.content) for request in httpx_mock.get_requests()
    ]
    expected_tool = {
        "type": "code_interpreter",
        "container": {"type": "auto", "memory_limit": "4g"},
    }
    assert request_bodies[0]["tools"] == [expected_tool]
    assert request_bodies[1]["tools"] == [expected_tool]
    assert request_bodies[1]["input"] == [
        {"role": "user", "content": "Run this calculation"},
        {"role": "assistant", "content": "Running Python"},
        {"role": "assistant", "content": "Calculated"},
        {"role": "user", "content": "Continue"},
    ]

    db = sqlite_utils.Database(str(user_path / "logs.db"))
    instance = next(iter(db["tool_instances"].rows))
    assert instance["name"] == "CodeInterpreter"
    assert json.loads(instance["arguments"])["memory_limit"] == "4g"
    assert {row["instance_id"] for row in db["turn_tools"].rows} == {instance["id"]}


def test_web_search_cli_tool_is_resolved_from_model(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json={
            "id": "resp_web_search_cli",
            "object": "response",
            "created_at": 1,
            "model": "gpt-5.6-luna",
            "output": [
                {
                    "type": "message",
                    "id": "msg_web_search_cli",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Search complete",
                            "annotations": [],
                        }
                    ],
                }
            ],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "status": "completed",
        },
        headers={"Content-Type": "application/json"},
    )
    result = CliRunner().invoke(
        cli,
        [
            "-m",
            "gpt-5.6-luna",
            "-T",
            'WebSearch(allowed_domains=["openai.com"], search_context_size="low", include_sources=true)',
            "--no-stream",
            "--no-log",
            "--key",
            "x",
            "Search for OpenAI news",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.stdout == "Search complete\n"
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert request_body["tools"] == [
        {
            "type": "web_search",
            "filters": {"allowed_domains": ["openai.com"]},
            "search_context_size": "low",
        }
    ]
    assert "web_search_call.action.sources" in request_body["include"]


def test_tools_list_for_model_includes_server_side_tools():
    runner = CliRunner()
    result = runner.invoke(cli, ["tools", "-m", "gpt-5.6-luna"])

    assert result.exit_code == 0
    assert (
        "Server-side tools for gpt-5.6-luna (executed by the provider):\n"
        in result.output
    )
    assert "CodeInterpreter(" in result.output
    assert "WebSearch(" in result.output
    assert "allowed_domains:" in result.output
    assert "memory_limit:" in result.output
    assert "Literal['1g', '4g', '16g', '64g']" in result.output
    assert "Run Python in an OpenAI-managed container." in result.output
    assert "ServerSideTool(spec: dict | None = None)" in result.output

    json_result = runner.invoke(cli, ["tools", "-m", "gpt-5.6-luna", "--json"])
    assert json_result.exit_code == 0
    server_side_tools = json.loads(json_result.output)["server_side_tools"]
    assert [tool["name"] for tool in server_side_tools] == [
        "WebSearch",
        "CodeInterpreter",
        "ServerSideTool",
    ]
    assert all(tool["server_side"] is True for tool in server_side_tools)
    assert server_side_tools[0]["signature"].startswith("(allowed_domains:")
    assert server_side_tools[0]["description"].startswith(
        "Search the web using OpenAI's hosted search tool."
    )


def test_tools_list_for_model_with_no_server_side_tools():
    runner = CliRunner()
    result = runner.invoke(cli, ["tools", "-m", "chatgpt"])

    assert result.exit_code == 0

    json_result = runner.invoke(cli, ["tools", "-m", "chatgpt", "--json"])
    assert json_result.exit_code == 0
    assert json.loads(json_result.output)["server_side_tools"] == []


def test_tools_list_rejects_unknown_model():
    result = CliRunner().invoke(cli, ["tools", "-m", "not-a-model"])

    assert result.exit_code == 1
    assert "Unknown model: not-a-model" in result.output


@pytest.mark.parametrize(
    "model_id,expected_description",
    (
        (
            "gpt-4o",
            "Controls the detail level for image attachments. Supported values are low, high, and auto.",
        ),
        (
            "gpt-5.4",
            "Controls the detail level for image attachments. Supported values are low, high, original, and auto.",
        ),
        (
            "gpt-5.5",
            "Controls the detail level for image attachments. Supported values are low, high, original, and auto.",
        ),
    ),
)
def test_openai_image_detail_option_description(model_id, expected_description):
    field = llm.get_model(model_id).Options.model_fields["image_detail"]
    assert field.description == expected_description


def test_openai_image_detail_option_is_sent_on_image_attachments(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "usage": {},
            "choices": [{"message": {"content": "Looks detailed"}}],
        },
        headers={"Content-Type": "application/json"},
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "-m",
            "gpt-4o",
            "-o",
            "image_detail",
            "high",
            "--at",
            "https://example.com/image.jpg",
            "image/jpeg",
            "--no-stream",
            "--key",
            "x",
            "Describe this",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    image_part = request_body["messages"][0]["content"][1]
    assert image_part == {
        "type": "image_url",
        "image_url": {
            "url": "https://example.com/image.jpg",
            "detail": "high",
        },
    }
    assert "image_detail" not in request_body


def test_openai_image_detail_original_is_sent_for_gpt54(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        json={
            "model": "gpt-5.4",
            "usage": {},
            "choices": [{"message": {"content": "Original detail"}}],
        },
        headers={"Content-Type": "application/json"},
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "-m",
            "gpt-5.4",
            "-o",
            "chat_completions",
            "1",
            "-o",
            "image_detail",
            "original",
            "--at",
            "https://example.com/image.jpg",
            "image/jpeg",
            "--no-stream",
            "--key",
            "x",
            "Describe this",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    image_part = request_body["messages"][0]["content"][1]
    assert image_part["image_url"]["detail"] == "original"


def test_openai_image_detail_original_is_sent_for_gpt54_responses_by_default(
    httpx_mock,
):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json={
            "id": "resp_test_1",
            "object": "response",
            "created_at": 1,
            "model": "gpt-5.4",
            "output": [
                {
                    "type": "message",
                    "id": "msg_1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Original detail",
                            "annotations": [],
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": 5,
                "output_tokens": 3,
                "total_tokens": 8,
            },
            "status": "completed",
        },
        headers={"Content-Type": "application/json"},
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "-m",
            "gpt-5.4",
            "-o",
            "image_detail",
            "original",
            "--at",
            "https://example.com/image.jpg",
            "image/jpeg",
            "--no-stream",
            "--key",
            "x",
            "Describe this",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    image_part = request_body["input"][0]["content"][1]
    assert image_part == {
        "type": "input_image",
        "image_url": "https://example.com/image.jpg",
        "detail": "original",
    }
    assert "image_detail" not in request_body


def test_openai_image_detail_original_is_rejected_for_other_models():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["-m", "gpt-5", "-o", "image_detail", "original", "Say hi"],
    )
    assert result.exit_code == 1
    assert "Input should be 'low', 'high' or 'auto'" in result.output


@pytest.mark.parametrize("async_", (False, True))
@pytest.mark.parametrize("usage", (None, "-u", "--usage"))
def test_gpt4o_mini_sync_and_async(monkeypatch, tmpdir, httpx_mock, async_, usage):
    user_path = tmpdir / "user_dir"
    log_db = user_path / "logs.db"
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    assert not log_db.exists()
    httpx_mock.add_response(
        method="POST",
        # chat completion request
        url="https://api.openai.com/v1/chat/completions",
        json={
            "id": "chatcmpl-AQT9a30kxEaM1bqxRPepQsPlCyGJh",
            "object": "chat.completion",
            "created": 1730871958,
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Ho ho ho",
                        "refusal": None,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 2000,
                "total_tokens": 12,
            },
            "system_fingerprint": "fp_49254d0e9b",
        },
        headers={"Content-Type": "application/json"},
    )
    runner = CliRunner()
    args = ["-m", "gpt-4o-mini", "--key", "x", "--no-stream"]
    if usage:
        args.append(usage)
    if async_:
        args.append("--async")
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0
    assert result.stdout == "Ho ho ho\n"
    if usage:
        assert result.stderr == "Token usage: 1,000 input, 2,000 output\n"
    # Confirm it was correctly logged
    assert log_db.exists()
    db = sqlite_utils.Database(str(log_db))
    assert db["turns"].count == 1
    turn = next(db["turns"].rows)
    store = LogStore(db)
    chain = store.load_chain(turn["tip_message_hash"])
    assert chain[-1].parts[0].text == "Ho ho ho"


def test_build_options_class_is_cached():
    """Same feature-flag combination -> the same shared Options class.

    Plugins that register hundreds of OpenAI-compatible models call
    this once per model; without the cache each call builds a fresh
    pydantic class and dominates registration time."""
    from llm.default_plugins.openai_models import build_options_class

    reasoning = build_options_class(reasoning=True)
    assert build_options_class(reasoning=True) is reasoning
    plain = build_options_class()
    assert plain is not reasoning
    assert "reasoning_effort" in reasoning.model_fields
    assert "reasoning_effort" not in plain.model_fields
