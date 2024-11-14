from click.testing import CliRunner
from llm.cli import cli
import pytest


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
        "id                    owned_by    created            \n"
        "ada:2020-05-03        openai      2020-05-03T20:26:40\n"
        "babbage:2020-05-03    openai      2020-05-03T20:26:40\n"
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
