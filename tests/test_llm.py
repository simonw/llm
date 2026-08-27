import ast
import json
import os
import pathlib
import re
import sys
from importlib import metadata
from importlib.metadata import version
from unittest import mock

import pytest
import sqlite_utils
from click.testing import CliRunner
from pydantic import BaseModel

import llm
from llm.cli import cli
from llm.models import Usage


def test_version():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert result.output.startswith("cli, version ")


@pytest.mark.parametrize("custom_database_path", (False, True))
def test_llm_prompt_creates_log_database(
    mocked_openai_responses, tmpdir, monkeypatch, custom_database_path
):
    user_path = tmpdir / "user"
    custom_db_path = tmpdir / "custom_log.db"
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    runner = CliRunner()
    args = ["three names \nfor a pet pelican", "--no-stream", "--key", "x"]
    if custom_database_path:
        args.extend(["--database", str(custom_db_path)])
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output == "Bob, Alice, Eve\n"
    # Should have created user_path and put a logs.db in it
    if custom_database_path:
        assert custom_db_path.exists()
        db_path = str(custom_db_path)
    else:
        assert (user_path / "logs.db").exists()
        db_path = str(user_path / "logs.db")
    assert sqlite_utils.Database(db_path)["turns"].count == 1


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "X"})
@pytest.mark.parametrize("use_stdin", (True, False, "split"))
@pytest.mark.parametrize(
    "logs_off,logs_args,should_log",
    (
        (True, [], False),
        (False, [], True),
        (False, ["--no-log"], False),
        (False, ["--log"], True),
        (True, ["-n"], False),  # Short for --no-log
        (True, ["--log"], True),
    ),
)
def test_llm_default_prompt(
    mocked_openai_responses, use_stdin, user_path, logs_off, logs_args, should_log
):
    # Reset the log_path database
    log_path = user_path / "logs.db"
    log_db = sqlite_utils.Database(str(log_path))
    if "turns" in log_db.table_names():
        with log_db.conn:
            log_db.execute("delete from turns")

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
    prompt = "three names \nfor a pet pelican"
    input = None
    args = ["--no-stream"]
    if use_stdin == "split":
        input = "three names"
        args.append("\nfor a pet pelican")
    elif use_stdin:
        input = prompt
    else:
        args.append(prompt)
    args += logs_args
    result = runner.invoke(cli, args, input=input, catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output == "Bob, Alice, Eve\n"
    last_request = mocked_openai_responses.get_requests()[-1]
    assert last_request.headers["Authorization"] == "Bearer X"

    # Was it logged? The legacy tables are read-only now, so the turn
    # is the record; its content is asserted below through `llm logs`.
    rows = list(log_db["turns"].rows)

    if not should_log:
        assert len(rows) == 0
        assert log_db["responses"].count == 0
        return

    assert len(rows) == 1
    row = rows[0]
    assert row["model"] == "gpt-5.6-luna"
    assert isinstance(row["duration_ms"], int)
    assert isinstance(row["datetime_utc"], str)

    # Test "llm logs"
    log_result = runner.invoke(
        cli, ["logs", "-n", "1", "--json"], catch_exceptions=False
    )
    log_json = json.loads(log_result.output)

    # Should have logged correctly:
    assert (
        log_json[0].items()
        >= {
            "model": "gpt-5.6-luna",
            "prompt": "three names \nfor a pet pelican",
            "system": None,
            # prompt_json and response_json are no longer recorded: the
            # message chain holds the structure, and the raw provider
            # payload was dropped as redundant with it.
            "options_json": {},
            "response": "Bob, Alice, Eve",
            # This doesn't have the \n after three names:
            "conversation_name": "three names for a pet pelican",
            "conversation_model": "gpt-5.6-luna",
        }.items()
    )


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "X"})
@pytest.mark.parametrize("async_", (False, True))
def test_llm_prompt_continue(httpx_mock, mock_openai_responses, user_path, async_):
    mock_openai_responses(
        text="Bob, Alice, Eve",
        response_id="resp_first",
        message_id="msg_first",
    )
    mock_openai_responses(
        text="Terry",
        response_id="resp_second",
        message_id="msg_second",
    )

    log_path = user_path / "logs.db"
    log_db = sqlite_utils.Database(str(log_path))
    if "turns" in log_db.table_names():
        with log_db.conn:
            log_db.execute("delete from turns")

    # First prompt
    runner = CliRunner()
    args = ["three names \nfor a pet pelican", "--no-stream"] + (
        ["--async"] if async_ else []
    )
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert result.output == "Bob, Alice, Eve\n"

    # Should be logged
    rows = list(log_db["turns"].rows)
    assert len(rows) == 1

    # Now ask a follow-up
    args2 = ["one more", "-c", "--no-stream"] + (["--async"] if async_ else [])
    result2 = runner.invoke(cli, args2, catch_exceptions=False)
    assert result2.exit_code == 0, result2.output
    assert result2.output == "Terry\n"

    rows = list(log_db["turns"].rows)
    assert len(rows) == 2


@pytest.mark.parametrize(
    "args,expect_just_code",
    (
        (["-x"], True),
        (["--extract"], True),
        (["-x", "--async"], True),
        (["--extract", "--async"], True),
        # Use --no-stream here to ensure it passes test same as -x/--extract cases
        (["--no-stream"], False),
    ),
)
def test_extract_fenced_code(
    mocked_openai_chat_returning_fenced_code, args, expect_just_code
):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["-m", "gpt-4o-mini", "--key", "x", "Write code"] + args,
        catch_exceptions=False,
    )
    output = result.output
    if expect_just_code:
        assert "```" not in output
    else:
        assert "```" in output


def test_extract_fenced_code_crlf(httpx_mock):
    """The CLI extracts fenced code when the model response uses CRLF."""
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "usage": {},
            "choices": [
                {
                    "message": {
                        "content": 'Code:\r\n\r\n```python\r\nprint("ok")\r\n```\r\nDone.'
                    }
                }
            ],
        },
        headers={"Content-Type": "application/json"},
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["-m", "gpt-4o-mini", "--key", "x", "Write code", "--extract"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    # Click normalizes terminal output to LF; test_utils.py verifies that
    # extraction itself preserves the response's CRLF bytes.
    assert result.output == 'print("ok")\n\n'


def test_openai_chat_stream(mocked_openai_chat_stream, user_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["-m", "gpt-3.5-turbo", "--key", "x", "Say hi"])
    assert result.exit_code == 0
    assert result.output == "Hi.\n"


def test_openai_completion(mocked_openai_completion, user_path):
    log_path = user_path / "logs.db"
    log_db = sqlite_utils.Database(str(log_path))
    if "turns" in log_db.table_names():
        with log_db.conn:
            log_db.execute("delete from turns")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "-m",
            "gpt-3.5-turbo-instruct",
            "Say this is a test",
            "--no-stream",
            "--key",
            "x",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert result.output == "\n\nThis is indeed a test\n"

    # Should have requested 256 tokens
    last_request = mocked_openai_completion.get_requests()[-1]
    assert json.loads(last_request.content) == {
        "model": "gpt-3.5-turbo-instruct",
        "prompt": "Say this is a test",
        "stream": False,
        "max_tokens": 256,
    }

    # Check it was logged
    rows = list(log_db["turns"].rows)
    assert len(rows) == 1
    assert rows[0]["model"] == "gpt-3.5-turbo-instruct"
    log_result = runner.invoke(
        cli, ["logs", "-n", "1", "--json"], catch_exceptions=False
    )
    log_json = json.loads(log_result.output)
    assert (
        log_json[0].items()
        >= {
            "model": "gpt-3.5-turbo-instruct",
            "prompt": "Say this is a test",
            "system": None,
            "response": "\n\nThis is indeed a test",
        }.items()
    )


def test_openai_completion_continue_includes_history(
    mocked_openai_completion, user_path
):
    # A continued conversation reloaded from storage must send the
    # prior exchanges, not just the newest prompt - prompt.messages
    # carries them; conversation.responses does not.
    runner = CliRunner()
    base = ["-m", "gpt-3.5-turbo-instruct", "--no-stream", "--key", "x"]
    result = runner.invoke(cli, base + ["Say this is a test"], catch_exceptions=False)
    assert result.exit_code == 0
    result2 = runner.invoke(cli, base + ["Say it again", "-c"], catch_exceptions=False)
    assert result2.exit_code == 0
    body = json.loads(mocked_openai_completion.get_requests()[-1].content)
    assert body["prompt"] == (
        "Say this is a test\n\n\nThis is indeed a test\nSay it again"
    )


def test_openai_completion_system_prompt_error():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "-m",
            "gpt-3.5-turbo-instruct",
            "Say this is a test",
            "--no-stream",
            "--key",
            "x",
            "--system",
            "system prompts not allowed",
        ],
    )
    assert result.exit_code == 1
    assert (
        "System prompts are not supported for OpenAI completion models" in result.output
    )


def test_openai_completion_logprobs_stream(
    mocked_openai_completion_logprobs_stream, user_path
):
    log_path = user_path / "logs.db"
    log_db = sqlite_utils.Database(str(log_path))
    if "turns" in log_db.table_names():
        with log_db.conn:
            log_db.execute("delete from turns")
    runner = CliRunner()
    args = [
        "-m",
        "gpt-3.5-turbo-instruct",
        "Say hi",
        "-o",
        "logprobs",
        "2",
        "--key",
        "x",
    ]
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output == "\n\nHi.\n"
    # Raw provider payloads (which carried the logprobs) are no longer
    # persisted - the message chain is the record of what happened.
    rows = list(log_db["turns"].rows)
    assert len(rows) == 1
    assert rows[0]["model"] == "gpt-3.5-turbo-instruct"


def test_openai_completion_logprobs_nostream(
    mocked_openai_completion_logprobs, user_path
):
    log_path = user_path / "logs.db"
    log_db = sqlite_utils.Database(str(log_path))
    if "turns" in log_db.table_names():
        with log_db.conn:
            log_db.execute("delete from turns")
    runner = CliRunner()
    args = [
        "-m",
        "gpt-3.5-turbo-instruct",
        "Say hi",
        "-o",
        "logprobs",
        "2",
        "--key",
        "x",
        "--no-stream",
    ]
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output == "\n\nHi.\n"
    # Raw provider payloads (which carried the logprobs) are no longer
    # persisted - the message chain is the record of what happened.
    rows = list(log_db["turns"].rows)
    assert len(rows) == 1
    row = rows[0]
    assert row["model"] == "gpt-3.5-turbo-instruct"


EXTRA_MODELS_YAML = """
- model_id: orca
  model_name: orca-mini-3b
  api_base: "http://localai.localhost"
- model_id: completion-babbage
  model_name: babbage
  api_base: "http://localai.localhost"
  completion: 1
"""


def test_openai_localai_configuration(mocked_localai, user_path):
    log_path = user_path / "logs.db"
    sqlite_utils.Database(str(log_path))
    # Write the configuration file
    config_path = user_path / "extra-openai-models.yaml"
    config_path.write_text(EXTRA_MODELS_YAML, "utf-8")
    # Run the prompt
    runner = CliRunner()
    prompt = "three names \nfor a pet pelican"
    result = runner.invoke(cli, ["--no-stream", "--model", "orca", prompt])
    assert result.exit_code == 0
    assert result.output == "Bob, Alice, Eve\n"
    last_request = mocked_localai.get_requests()[-1]
    assert json.loads(last_request.content) == {
        "model": "orca-mini-3b",
        "messages": [{"role": "user", "content": "three names \nfor a pet pelican"}],
        "stream": False,
    }
    # And check the completion model too
    result2 = runner.invoke(cli, ["--no-stream", "--model", "completion-babbage", "hi"])
    assert result2.exit_code == 0
    assert result2.output == "Hello\n"
    last_request2 = mocked_localai.get_requests()[-1]
    assert json.loads(last_request2.content) == {
        "model": "babbage",
        "prompt": "hi",
        "stream": False,
    }


def test_extra_openai_models_async(user_path):
    from llm.default_plugins.openai_models import AsyncChat

    config_path = user_path / "extra-openai-models.yaml"
    config_path.write_text(EXTRA_MODELS_YAML, "utf-8")
    async_model = llm.get_async_model("orca")
    assert isinstance(async_model, AsyncChat)
    assert async_model.model_id == "orca"
    assert async_model.model_name == "orca-mini-3b"
    assert async_model.api_base == "http://localai.localhost"
    assert async_model.needs_key is None
    # Completion models should not have an async variant
    with pytest.raises(llm.UnknownModelError):
        llm.get_async_model("completion-babbage")


@pytest.mark.parametrize(
    "args,exit_code",
    (
        (["-q", "mo", "-q", "ck"], 0),
        (["-q", "mock"], 0),
        (["-q", "badmodel"], 1),
        (["-q", "mock", "-q", "badmodel"], 1),
    ),
)
def test_prompt_select_model_with_queries(mock_model, user_path, args, exit_code):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        args + ["hello"],
        catch_exceptions=False,
    )
    assert result.exit_code == exit_code


EXPECTED_OPTIONS = """
OpenAI Chat: gpt-4o (aliases: 4o)
  Options:
    temperature: float
      What sampling temperature to use, between 0 and 2. Higher values like
      0.8 will make the output more random, while lower values like 0.2 will
      make it more focused and deterministic.
    max_tokens: int
      Maximum number of tokens to generate.
    top_p: float
      An alternative to sampling with temperature, called nucleus sampling,
      where the model considers the results of the tokens with top_p
      probability mass. So 0.1 means only the tokens comprising the top 10%
      probability mass are considered. Recommended to use top_p or
      temperature but not both.
    frequency_penalty: float
      Number between -2.0 and 2.0. Positive values penalize new tokens based
      on their existing frequency in the text so far, decreasing the model's
      likelihood to repeat the same line verbatim.
    presence_penalty: float
      Number between -2.0 and 2.0. Positive values penalize new tokens based
      on whether they appear in the text so far, increasing the model's
      likelihood to talk about new topics.
    stop: str
      A string where the API will stop generating further tokens.
    logit_bias: dict, str
      Modify the likelihood of specified tokens appearing in the completion.
      Pass a JSON string like '{"1712":-100, "892":-100, "1489":-100}'
    seed: int
      Integer seed to attempt to sample deterministically
    json_object: boolean
      Output a valid JSON object {...}. Prompt must mention JSON.
  Attachment types:
    application/pdf, image/gif, image/jpeg, image/png, image/webp
  Keys:
    key: openai
    env_var: OPENAI_API_KEY
"""


def test_llm_models_options(user_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["models", "--options"], catch_exceptions=False)
    assert result.exit_code == 0
    # Check for key components instead of exact string match
    assert "OpenAI Chat: gpt-4o (aliases: 4o)" in result.output
    assert "  Options:" in result.output
    assert "    temperature: float" in result.output
    assert "  Keys:" in result.output
    assert "    key: openai" in result.output
    assert "    env_var: OPENAI_API_KEY" in result.output
    assert "AsyncMockModel (async): mock" not in result.output


def test_prompt_options_shows_selected_model_options(user_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["-m", "gpt-5.5", "--options"], catch_exceptions=False)
    expected = runner.invoke(
        cli, ["models", "-m", "gpt-5.5", "--options"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert expected.exit_code == 0
    assert result.output == expected.output
    assert "OpenAI Responses: gpt-5.5" in result.output
    assert "  Options:" in result.output
    assert "    reasoning_effort: str" in result.output
    assert not (user_path / "logs.db").exists()


def test_llm_models_async(user_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["models", "--async"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "AsyncMockModel (async): mock" in result.output


def test_llm_models_json_includes_server_side_tools():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "models",
            "--json",
            "-m",
            "gpt-5.6-luna",
            "-m",
            "chatgpt",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    models = {model["model_id"]: model for model in json.loads(result.output)}
    assert set(models) == {"gpt-5.6-luna", "gpt-3.5-turbo"}
    assert models["gpt-5.6-luna"]["server_side_tools"] == [
        {"name": "WebSearch", "plugin": None},
        {"name": "CodeInterpreter", "plugin": None},
        {"name": "ServerSideTool", "plugin": None},
    ]
    assert models["gpt-3.5-turbo"]["server_side_tools"] == []
    assert models["gpt-5.6-luna"]["supports_schema"] is True
    assert models["gpt-5.6-luna"]["supports_tools"] is True
    assert models["gpt-5.6-luna"]["can_stream"] is True
    assert models["gpt-5.6-luna"]["supports_async"] is True
    assert "application/pdf" in models["gpt-5.6-luna"]["attachment_types"]


def test_llm_models_json_options_and_alias_filter():
    result = CliRunner().invoke(
        cli,
        ["models", "--json", "--options", "-m", "4.1"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    models = json.loads(result.output)
    assert len(models) == 1
    assert models[0]["model_id"] == "gpt-4.1"
    assert "4.1" in models[0]["aliases"]
    assert "temperature" in models[0]["options"]


@pytest.mark.parametrize(
    "args,expected_model_ids,unexpected_model_ids",
    (
        (["-q", "gpt-4o"], ["OpenAI Chat: gpt-4o"], None),
        (["-q", "mock"], ["MockModel: mock"], None),
        (["--query", "mock"], ["MockModel: mock"], None),
        (
            ["-q", "4o", "-q", "mini"],
            ["OpenAI Chat: gpt-4o-mini"],
            ["OpenAI Chat: gpt-4o "],
        ),
        (
            ["-m", "gpt-4o-mini", "-m", "4.1"],
            ["OpenAI Chat: gpt-4o-mini", "OpenAI Chat: gpt-4.1"],
            ["OpenAI Chat: gpt-4o "],
        ),
    ),
)
def test_llm_models_filter(user_path, args, expected_model_ids, unexpected_model_ids):
    runner = CliRunner()
    result = runner.invoke(cli, ["models"] + args, catch_exceptions=False)
    assert result.exit_code == 0
    if expected_model_ids:
        for expected_model_id in expected_model_ids:
            assert expected_model_id in result.output
    if unexpected_model_ids:
        for unexpected_model_id in unexpected_model_ids:
            assert unexpected_model_id not in result.output


def test_llm_user_dir(tmpdir, monkeypatch):
    user_dir = str(tmpdir / "u")
    monkeypatch.setenv("LLM_USER_PATH", user_dir)
    assert not os.path.exists(user_dir)
    user_dir2 = llm.user_dir()
    assert user_dir == str(user_dir2)
    assert os.path.exists(user_dir)


def test_model_defaults(tmpdir, monkeypatch):
    user_dir = str(tmpdir / "u")
    monkeypatch.setenv("LLM_USER_PATH", user_dir)
    config_path = pathlib.Path(user_dir) / "default_model.txt"
    assert not config_path.exists()
    assert llm.get_default_model() == "gpt-5.6-luna"
    assert llm.get_model().model_id == "gpt-5.6-luna"
    llm.set_default_model("gpt-4o")
    assert config_path.exists()
    assert llm.get_default_model() == "gpt-4o"
    assert llm.get_model().model_id == "gpt-4o"


def test_get_models():
    models = llm.get_models()
    assert all(isinstance(model, (llm.Model, llm.KeyModel)) for model in models)
    model_ids = [model.model_id for model in models]
    assert "gpt-4o-mini" in model_ids
    assert "gpt-5.4-mini" in model_ids
    assert "gpt-5.4-nano" in model_ids
    # Ensure no model_ids are duplicated
    # https://github.com/simonw/llm/issues/667
    assert len(model_ids) == len(set(model_ids))


def test_get_async_models():
    models = llm.get_async_models()
    assert all(
        isinstance(model, (llm.AsyncModel, llm.AsyncKeyModel)) for model in models
    )
    model_ids = [model.model_id for model in models]
    assert "gpt-4o-mini" in model_ids
    assert "gpt-5.4-mini" in model_ids
    assert "gpt-5.4-nano" in model_ids


def test_mock_model(mock_model):
    mock_model.enqueue(["hello world"])
    mock_model.enqueue(["second"])
    model = llm.get_model("mock")
    response = model.prompt(prompt="hello")
    assert response.text() == "hello world"
    assert str(response) == "hello world"
    assert model.history[0][0].prompt == "hello"
    assert response.usage() == Usage(input=1, output=1, details=None)
    response2 = model.prompt(prompt="hello again")
    assert response2.text() == "second"
    assert response2.usage() == Usage(input=2, output=1, details=None)


class Dog(BaseModel):
    name: str
    age: int


dog_schema = {
    "properties": {
        "name": {"title": "Name", "type": "string"},
        "age": {"title": "Age", "type": "integer"},
    },
    "required": ["name", "age"],
    "title": "Dog",
    "type": "object",
}
dog = {"name": "Cleo", "age": 10}


@pytest.mark.parametrize("use_pydantic", (False, True))
def test_schema(mock_model, use_pydantic):
    assert dog_schema == Dog.model_json_schema()
    mock_model.enqueue([json.dumps(dog)])
    response = mock_model.prompt(
        "invent a dog", schema=Dog if use_pydantic else dog_schema
    )
    assert json.loads(response.text()) == dog
    assert response.prompt.schema == dog_schema


def test_model_environment_variable(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "echo")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--no-stream", "hello", "-s", "sys"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "prompt": "hello",
        "system": "sys",
        "attachments": [],
        "stream": False,
        "previous": [],
    }


@pytest.mark.parametrize("use_filename", (True, False))
def test_schema_via_cli(mock_model, tmpdir, monkeypatch, use_filename):
    user_path = tmpdir / "user"
    schema_path = tmpdir / "schema.json"
    mock_model.enqueue([json.dumps(dog)])
    schema_value = '{"schema": "one"}'
    with open(schema_path, "w") as f:
        f.write(schema_value)
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    if use_filename:
        schema_value = str(schema_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--schema", schema_value, "prompt", "-m", "mock"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert result.output == '{"name": "Cleo", "age": 10}\n'
    # Should have created user_path and put a logs.db in it
    assert (user_path / "logs.db").exists()
    rows = list(sqlite_utils.Database(str(user_path / "logs.db"))["schemas"].rows)
    assert rows == [
        {"id": "9a8ed2c9b17203f6d8905147234475b5", "content": '{"schema":"one"}'}
    ]
    if use_filename:
        # Run it again to check that the ID option works now it's in the DB
        result2 = runner.invoke(
            cli,
            ["--schema", "9a8ed2c9b17203f6d8905147234475b5", "prompt", "-m", "mock"],
            catch_exceptions=False,
        )
        assert result2.exit_code == 0


@pytest.mark.parametrize(
    "args,expected",
    (
        (
            ["--schema", "name, age int"],
            {
                "type": "object",
                "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                "required": ["name", "age"],
            },
        ),
        (
            ["--schema-multi", "name, age int"],
            {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "age": {"type": "integer"},
                            },
                            "required": ["name", "age"],
                        },
                    }
                },
                "required": ["items"],
            },
        ),
    ),
)
def test_schema_using_dsl(mock_model, tmpdir, monkeypatch, args, expected):
    user_path = tmpdir / "user"
    mock_model.enqueue([json.dumps(dog)])
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["prompt", "-m", "mock"] + args,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert result.output == '{"name": "Cleo", "age": 10}\n'
    rows = list(sqlite_utils.Database(str(user_path / "logs.db"))["schemas"].rows)
    assert json.loads(rows[0]["content"]) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("use_pydantic", (False, True))
async def test_schema_async(async_mock_model, use_pydantic):
    async_mock_model.enqueue([json.dumps(dog)])
    response = async_mock_model.prompt(
        "invent a dog", schema=Dog if use_pydantic else dog_schema
    )
    assert json.loads(await response.text()) == dog
    assert response.prompt.schema == dog_schema


def test_mock_key_model(mock_key_model):
    response = mock_key_model.prompt(prompt="hello", key="hi")
    assert response.text() == "key: hi"


@pytest.mark.asyncio
async def test_mock_async_key_model(mock_async_key_model):
    response = mock_async_key_model.prompt(prompt="hello", key="hi")
    output = await response.text()
    assert output == "async, key: hi"


def test_sync_on_done(mock_model):
    mock_model.enqueue(["hello world"])
    model = llm.get_model("mock")
    response = model.prompt(prompt="hello")
    caught = []

    def done(response):
        caught.append(response)

    response.on_done(done)
    assert len(caught) == 0
    str(response)
    assert len(caught) == 1


def test_schemas_dsl():
    runner = CliRunner()
    result = runner.invoke(cli, ["schemas", "dsl", "name, age int, bio: short bio"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "bio": {"type": "string", "description": "short bio"},
        },
        "required": ["name", "age", "bio"],
    }
    result2 = runner.invoke(cli, ["schemas", "dsl", "name, age int", "--multi"])
    assert result2.exit_code == 0
    assert json.loads(result2.output) == {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "integer"},
                    },
                    "required": ["name", "age"],
                },
            }
        },
        "required": ["items"],
    }


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "X"})
@pytest.mark.parametrize("custom_database_path", (False, True))
def test_llm_prompt_continue_with_database(
    tmpdir,
    monkeypatch,
    httpx_mock,
    mock_openai_responses,
    user_path,
    custom_database_path,
):
    mock_openai_responses(
        text="Bob, Alice, Eve",
        response_id="resp_first",
        message_id="msg_first",
    )
    mock_openai_responses(
        text="Terry",
        response_id="resp_second",
        message_id="msg_second",
    )

    user_path = tmpdir / "user"
    custom_db_path = tmpdir / "custom_log.db"
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))

    # First prompt
    runner = CliRunner()
    args = ["three names \nfor a pet pelican", "--no-stream"]
    if custom_database_path:
        args.extend(["--database", str(custom_db_path)])
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert result.output == "Bob, Alice, Eve\n"

    # Now ask a follow-up
    args2 = ["one more", "-c", "--no-stream"]
    if custom_database_path:
        args2.extend(["--database", str(custom_db_path)])
    result2 = runner.invoke(cli, args2, catch_exceptions=False)
    assert result2.exit_code == 0, result2.output
    assert result2.output == "Terry\n"

    if custom_database_path:
        assert custom_db_path.exists()
        db_path = str(custom_db_path)
    else:
        assert (user_path / "logs.db").exists()
        db_path = str(user_path / "logs.db")
    assert sqlite_utils.Database(db_path)["turns"].count == 2


@pytest.mark.parametrize("async_", (False, True))
def test_llm_prompt_json(logs_db, async_):
    "llm --json should output the same JSON as llm logs --json"
    runner = CliRunner()
    args = ["-m", "echo", "hello world", "--json"]
    if async_:
        args.append("--async")
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert len(rows) == 1
    row = rows[0]
    assert row["model"] == "echo"
    assert row["prompt"] == "hello world"
    assert json.loads(row["response"])["prompt"] == "hello world"
    assert row["attachments"] == []
    assert row["tools"] == []
    assert row["tool_calls"] == []
    assert row["tool_results"] == []
    # Should be identical to the output of llm logs --json
    logs_result = runner.invoke(
        cli, ["logs", "-n", "1", "--json"], catch_exceptions=False
    )
    assert logs_result.exit_code == 0, logs_result.output
    assert json.loads(logs_result.output) == rows


@pytest.mark.parametrize("logs_args", (["--no-log"], ["-n"], []))
def test_llm_prompt_json_without_logging(logs_db, logs_args):
    "--json should work even when the response is not logged to the database"
    runner = CliRunner()
    if not logs_args:
        # Turn logging off entirely instead
        runner.invoke(cli, ["logs", "off"], catch_exceptions=False)
    result = runner.invoke(
        cli, ["-m", "echo", "hello world", "--json"] + logs_args, catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert len(rows) == 1
    assert rows[0]["prompt"] == "hello world"
    # But nothing should have been logged
    assert logs_db["responses"].count == 0


def test_llm_prompt_json_with_tools(logs_db):
    "Each response in a tool chain should be included in the JSON"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "-m",
            "echo",
            "-T",
            "llm_version",
            json.dumps({"tool_calls": [{"name": "llm_version"}]}),
            "--json",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert len(rows) == 2
    assert [tool["name"] for tool in rows[0]["tools"]] == ["llm_version"]
    assert [call["name"] for call in rows[0]["tool_calls"]] == ["llm_version"]
    assert rows[0]["tool_results"] == []
    assert rows[1]["tool_calls"] == []
    assert [result_["output"] for result_ in rows[1]["tool_results"]] == [
        version("llm")
    ]
    logs_result = runner.invoke(
        cli, ["logs", "-n", "2", "--json"], catch_exceptions=False
    )
    assert json.loads(logs_result.output) == rows


def test_default_exports():
    "Check key exports in the llm __all__ list"
    for name in ("Model", "AsyncModel", "get_model", "get_async_model", "schema_dsl"):
        assert name in llm.__all__, f"{name} not in llm.__all__"


def test_all_third_party_imports_are_declared():
    """Every third-party module imported by llm/ must be a declared dependency.

    httpx was imported by four modules but only arrived transitively via openai,
    so it vanished when openai 3.0 moved to httpx2 and every fresh install broke.
    This catches the next one in CI instead of on a user's machine.
    """
    llm_dir = pathlib.Path(llm.__file__).parent

    imported = set()
    for path in sorted(llm_dir.rglob("*.py")):
        # Source under llm/ contains non-ASCII, so don't trust the platform
        # default encoding - that would fail on the Windows CI runners.
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            # level > 0 is a relative import, so it's internal to llm
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])

    third_party = imported - sys.stdlib_module_names - {"llm"}

    def normalize(name):
        return re.sub(r"[-_.]+", "-", name).lower()

    declared = set()
    for requirement in metadata.requires("llm") or []:
        # Skip anything gated behind an extra - those aren't guaranteed installed
        if "extra ==" in requirement:
            continue
        declared.add(normalize(re.split(r"[<>=!~;\s\[]", requirement, 1)[0]))

    module_to_distributions = metadata.packages_distributions()

    undeclared = set()
    for module in third_party:
        distributions = module_to_distributions.get(module)
        if not distributions:
            # Not installed in this environment, so we can't map it to a
            # distribution to check. Don't guess.
            continue
        if not any(normalize(dist) in declared for dist in distributions):
            undeclared.add(module)

    assert not undeclared, (
        "these modules are imported by llm/ but are not declared in "
        "pyproject.toml dependencies: " + ", ".join(sorted(undeclared))
    )
