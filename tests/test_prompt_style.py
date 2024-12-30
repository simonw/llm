from click.testing import CliRunner
from llm import cli
import pytest


@pytest.mark.parametrize(("style", "expected"), [
    (None, "describe this input from stdin"),  # same as `prepend` (default)
    ("append", "input from stdin describe this"),
    ("fence-prepend", "describe this\n\n```\ninput from stdin\n```"),
    ("fence-append", "```\ninput from stdin\n```\n\ndescribe this"),
])
def test_prompt_input_style(mock_model, logs_db, style, expected):
    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        ["prompt", "-m", "mock", "describe this", *(["--input-style", style] if style else [])],
        input="input from stdin",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert mock_model.history[0][0].prompt == expected
