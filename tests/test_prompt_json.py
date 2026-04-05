import json
from click.testing import CliRunner
from llm.cli import cli

def test_prompt_json(mock_model):
    runner = CliRunner()
    result = runner.invoke(cli, ["prompt", "say hello", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    # The output is a list containing the log entry
    assert isinstance(data, list)
    assert len(data) == 1
    assert "response" in data[0]
    assert "conversation_id" in data[0]
    assert data[0]["prompt"] == "say hello"

def test_prompt_json_no_log_error():
    runner = CliRunner()
    result = runner.invoke(cli, ["prompt", "say hello", "--json", "--no-log"])
    assert result.exit_code != 0
    assert "Cannot use --json with --no-log" in result.output

def test_prompt_json_no_stream(mock_model):
    runner = CliRunner()
    result = runner.invoke(cli, ["prompt", "say hello", "--json", "--no-stream"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert "response" in data[0]
