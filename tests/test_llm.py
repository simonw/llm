from click.testing import CliRunner
from llm.cli import cli
from llm.migrations import migrate
import json
import os
import pytest
import sqlite_utils
from ulid import ULID
from unittest import mock


def test_version():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert result.output.startswith("cli, version ")


@pytest.mark.parametrize("n", (None, 0, 2))
def test_logs(n, user_path):
    "Test that logs command correctly returns requested -n records"
    log_path = str(user_path / "logs.db")
    db = sqlite_utils.Database(log_path)
    migrate(db)
    db["responses"].insert_all(
        {
            "id": str(ULID()).lower(),
            "system": "system",
            "prompt": "prompt",
            "response": "response",
            "model": "davinci",
        }
        for i in range(100)
    )
    runner = CliRunner()
    args = ["logs", "-p", str(log_path)]
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


@pytest.mark.parametrize("env", ({}, {"LLM_USER_PATH": "/tmp/llm-user-path"}))
def test_logs_path(monkeypatch, env, user_path):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    runner = CliRunner()
    result = runner.invoke(cli, ["logs", "path"])
    assert result.exit_code == 0
    if env:
        expected = env["LLM_USER_PATH"] + "/logs.db"
    else:
        expected = str(user_path) + "/logs.db"
    assert result.output.strip() == expected


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "X"})
@pytest.mark.parametrize("use_stdin", (True, False))
@pytest.mark.parametrize("logs_off", (True, False))
def test_llm_default_prompt(mocked_openai, use_stdin, user_path, logs_off):
    # Reset the log_path database
    log_path = user_path / "logs.db"
    log_db = sqlite_utils.Database(str(log_path))
    log_db["responses"].delete_where()

    logs_off_path = user_path / "logs-off"
    if logs_off:
        # Turn off logging
        assert not logs_off_path.exists()
        CliRunner().invoke(cli, ["logs", "off"])
        assert logs_off_path.exists()
    else:
        # Turn on logging
        CliRunner().invoke(cli, ["logs", "on"])
        assert not logs_off_path.exists()

    # Run the prompt
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
    assert mocked_openai.last_request.headers["Authorization"] == "Bearer X"

    # Was it logged?
    rows = list(log_db["responses"].rows)

    if logs_off:
        assert len(rows) == 0
        return

    assert len(rows) == 1
    expected = {
        "model": "gpt-3.5-turbo",
        "prompt": "three names for a pet pelican",
        "system": None,
        "options_json": "{}",
        "response": "Bob, Alice, Eve",
    }
    row = rows[0]
    assert expected.items() <= row.items()
    assert isinstance(row["duration_ms"], int)
    assert isinstance(row["datetime_utc"], str)
    assert json.loads(row["prompt_json"]) == {
        "messages": [{"role": "user", "content": "three names for a pet pelican"}]
    }
    assert json.loads(row["response_json"]) == {
        "model": "gpt-3.5-turbo",
        "usage": {},
        "choices": [{"message": {"content": "Bob, Alice, Eve"}}],
    }

    # Test "llm logs"
    log_result = runner.invoke(cli, ["logs", "-n", "1"], catch_exceptions=False)
    log_json = json.loads(log_result.output)

    # Should have logged correctly:
    assert (
        log_json[0].items()
        >= {
            "model": "gpt-3.5-turbo",
            "prompt": "three names for a pet pelican",
            "system": None,
            "prompt_json": {
                "messages": [
                    {"role": "user", "content": "three names for a pet pelican"}
                ]
            },
            "options_json": {},
            "response": "Bob, Alice, Eve",
            "response_json": {
                "model": "gpt-3.5-turbo",
                "usage": {},
                "choices": [{"message": {"content": "Bob, Alice, Eve"}}],
            },
        }.items()
    )
