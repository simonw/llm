from click.testing import CliRunner
from llm.cli import cli
from llm.migrations import migrate
import json
import os
import pytest
import sqlite_utils
from unittest import mock


def test_version():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert result.output.startswith("cli, version ")


@pytest.mark.parametrize("n", (None, 0, 2))
def test_logs(n, log_path):
    db = sqlite_utils.Database(str(log_path))
    migrate(db)
    db["log"].insert_all(
        {
            "system": "system",
            "prompt": "prompt",
            "response": "response",
            "model": "davinci",
        }
        for i in range(100)
    )
    runner = CliRunner()
    args = ["logs", "-p", log_path]
    if n is not None:
        args.extend(["-n", str(n)])
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0
    logs = json.loads(result.output)
    expected_length = 3
    if n is not None:
        if n == 0:
            expected_length = 100
        else:
            expected_length = n
    assert len(logs) == expected_length


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "X"})
@pytest.mark.parametrize("use_stdin", (True, False))
def test_llm_default_prompt(requests_mock, use_stdin, log_path):
    # Reset the log_path database
    log_db = sqlite_utils.Database(str(log_path))
    log_db["log"].delete_where()
    mocked = requests_mock.post(
        "https://api.openai.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "Bob, Alice, Eve"}}]},
        headers={"Content-Type": "application/json"},
    )
    runner = CliRunner()
    prompt = "three names for a pet pelican"
    input = None
    args = ["--no-stream"]
    if use_stdin:
        input = prompt
    else:
        args.append(prompt)
    result = runner.invoke(cli, args, input=input, catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output == "Bob, Alice, Eve\n"
    assert mocked.last_request.headers["Authorization"] == "Bearer X"
    # Was it logged?
    rows = list(log_db["log"].rows)
    assert len(rows) == 1
    expected = {
        "model": "gpt-3.5-turbo",
        "prompt": "three names for a pet pelican",
        "system": None,
        "response": "Bob, Alice, Eve",
        "chat_id": None,
    }
    assert expected.items() <= rows[0].items()
