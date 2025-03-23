from click.testing import CliRunner
from llm.cli import cli
import pytest
import json


@pytest.mark.parametrize(
    "args,expected_options,expected_error",
    (
        (
            ["gpt-4o-mini", "temperature", "0.5"],
            {"gpt-4o-mini": {"temperature": "0.5"}},
            None,
        ),
        (
            ["gpt-4o-mini", "temperature", "invalid"],
            {},
            "Error: temperature\n  Input should be a valid number",
        ),
        (
            ["gpt-4o-mini", "not-an-option", "invalid"],
            {},
            "Extra inputs are not permitted",
        ),
    ),
)
def test_set_model_default_options(user_path, args, expected_options, expected_error):
    path = user_path / "model_options.json"
    assert not path.exists()
    runner = CliRunner()
    result = runner.invoke(cli, ["models", "options", "set"] + args)
    if not expected_error:
        assert result.exit_code == 0
        assert path.exists()
        data = json.loads(path.read_text("utf-8"))
        assert data == expected_options
    else:
        assert result.exit_code == 1
        assert expected_error in result.output
