from click.testing import CliRunner
from llm.cli import cli
import pytest


@pytest.fixture
def mocked_models(requests_mock):
    requests_mock.get(
        "https://api.openai.com/v1/models",
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
    return requests_mock


def test_openai_models(mocked_models):
    runner = CliRunner()
    result = runner.invoke(cli, ["openai", "models", "--key", "x"])
    assert result.exit_code == 0
    assert result.output == (
        "id                    owned_by    created            \n"
        "ada:2020-05-03        openai      2020-05-03T20:26:40\n"
        "babbage:2020-05-03    openai      2020-05-03T20:26:40\n"
    )


def test_openai_options_min_max(mocked_models):
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
        assert (
            result.output
            == f"Error: {option}\n  Input should be greater than or equal to {min_val}\n"
        )

        result = runner.invoke(cli, ["-m", "chatgpt", "-o", option, "10"])
        assert result.exit_code == 1
        assert (
            result.output
            == f"Error: {option}\n  Input should be less than or equal to {max_val}\n"
        )
