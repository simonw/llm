from click.testing import CliRunner
import json
import llm
from llm.cli import cli
import pytest
import sqlite_utils


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


@pytest.mark.parametrize("model_id", ("gpt-4o", "gpt-4.5-preview", "o3", "o4-mini"))
def test_non_gpt5_openai_chat_models_do_not_support_verbosity_option(model_id):
    assert "verbosity" not in llm.get_model(model_id).Options.model_fields
    assert "verbosity" not in llm.get_async_model(model_id).Options.model_fields


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


@pytest.mark.parametrize("model", ("gpt-4o-mini", "gpt-4o-audio-preview"))
@pytest.mark.parametrize("filetype", ("mp3", "wav"))
def test_only_gpt4_audio_preview_allows_mp3_or_wav(httpx_mock, model, filetype):
    httpx_mock.add_response(
        method="HEAD",
        url=f"https://www.example.com/example.{filetype}",
        content=b"binary-data",
        headers={"Content-Type": "audio/mpeg" if filetype == "mp3" else "audio/wav"},
    )
    if model == "gpt-4o-audio-preview":
        httpx_mock.add_response(
            method="POST",
            # chat completion request
            url="https://api.openai.com/v1/chat/completions",
            json={
                "id": "chatcmpl-AQT9a30kxEaM1bqxRPepQsPlCyGJh",
                "object": "chat.completion",
                "created": 1730871958,
                "model": "gpt-4o-audio-preview-2024-10-01",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Why did the pelican get kicked out of the restaurant?\n\nBecause he had a big bill and no way to pay it!",
                            "refusal": None,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 55,
                    "completion_tokens": 25,
                    "total_tokens": 80,
                    "prompt_tokens_details": {
                        "cached_tokens": 0,
                        "audio_tokens": 44,
                        "text_tokens": 11,
                        "image_tokens": 0,
                    },
                    "completion_tokens_details": {
                        "reasoning_tokens": 0,
                        "audio_tokens": 0,
                        "text_tokens": 25,
                        "accepted_prediction_tokens": 0,
                        "rejected_prediction_tokens": 0,
                    },
                },
                "system_fingerprint": "fp_49254d0e9b",
            },
            headers={"Content-Type": "application/json"},
        )
        httpx_mock.add_response(
            method="GET",
            url=f"https://www.example.com/example.{filetype}",
            content=b"binary-data",
            headers={
                "Content-Type": "audio/mpeg" if filetype == "mp3" else "audio/wav"
            },
        )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "-m",
            model,
            "-a",
            f"https://www.example.com/example.{filetype}",
            "--no-stream",
            "--key",
            "x",
        ],
    )
    if model == "gpt-4o-audio-preview":
        assert result.exit_code == 0
        assert result.output == (
            "Why did the pelican get kicked out of the restaurant?\n\n"
            "Because he had a big bill and no way to pay it!\n"
        )
    else:
        assert result.exit_code == 1
        long = "audio/mpeg" if filetype == "mp3" else "audio/wav"
        assert (
            f"This model does not support attachments of type '{long}'" in result.output
        )


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
    runner = CliRunner(mix_stderr=False)
    args = ["-m", "gpt-4o-mini", "--key", "x", "--no-stream"]
    if usage:
        args.append(usage)
    if async_:
        args.append("--async")
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output == "Ho ho ho\n"
    if usage:
        assert result.stderr == "Token usage: 1,000 input, 2,000 output\n"
    # Confirm it was correctly logged
    assert log_db.exists()
    db = sqlite_utils.Database(str(log_db))
    assert db["responses"].count == 1
    row = next(db["responses"].rows)
    assert row["response"] == "Ho ho ho"
