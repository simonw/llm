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
