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


def test_model_options_list_and_show(user_path):
    (user_path / "model_options.json").write_text(
        json.dumps(
            {"gpt-4o-mini": {"temperature": 0.5}, "gpt-4o": {"temperature": 0.7}}
        ),
        "utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["models", "options", "list"])
    assert result.exit_code == 0
    assert (
        result.output
        == "gpt-4o-mini:\n  temperature: 0.5\ngpt-4o:\n  temperature: 0.7\n"
    )
    result = runner.invoke(cli, ["models", "options", "show", "gpt-4o-mini"])
    assert result.exit_code == 0
    assert result.output == "temperature: 0.5\n"


def test_model_options_clear(user_path):
    path = user_path / "model_options.json"
    path.write_text(
        json.dumps(
            {
                "gpt-4o-mini": {"temperature": 0.5},
                "gpt-4o": {"temperature": 0.7, "top_p": 0.9},
            }
        ),
        "utf-8",
    )
    assert path.exists()
    runner = CliRunner()
    # Clear all for gpt-4o-mini
    result = runner.invoke(cli, ["models", "options", "clear", "gpt-4o-mini"])
    assert result.exit_code == 0
    # Clear just top_p for gpt-4o
    result2 = runner.invoke(cli, ["models", "options", "clear", "gpt-4o", "top_p"])
    assert result2.exit_code == 0
    data = json.loads(path.read_text("utf-8"))
    assert data == {"gpt-4o": {"temperature": 0.7}}
