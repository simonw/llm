from click.testing import CliRunner
import datetime
import llm
from llm.cli import cli
from llm.migrations import migrate
from llm.models import Usage
import json
import os
import pathlib
import pytest
import re
import sqlite_utils
import sys
from ulid import ULID
from unittest import mock


def test_version():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert result.output.startswith("cli, version ")


@pytest.fixture
def log_path(user_path):
    log_path = str(user_path / "logs.db")
    db = sqlite_utils.Database(log_path)
    migrate(db)
    start = datetime.datetime.now(datetime.timezone.utc)
    db["responses"].insert_all(
        {
            "id": str(ULID()).lower(),
            "system": "system",
            "prompt": "prompt",
            "response": "response",
            "model": "davinci",
            "datetime_utc": (start + datetime.timedelta(seconds=i)).isoformat(),
            "conversation_id": "abc123",
            "input_tokens": 2,
            "output_tokens": 5,
        }
        for i in range(100)
    )
    return log_path


datetime_re = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


@pytest.mark.parametrize("usage", (False, True))
def test_logs_text(log_path, usage):
    runner = CliRunner()
    args = ["logs", "-p", str(log_path)]
    if usage:
        args.append("-u")
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0
    output = result.output
    # Replace 2023-08-17T20:53:58 with YYYY-MM-DDTHH:MM:SS
    output = datetime_re.sub("YYYY-MM-DDTHH:MM:SS", output)

    assert output == (
        "# YYYY-MM-DDTHH:MM:SS    conversation: abc123\n\n"
        "Model: **davinci**\n\n"
        "## Prompt:\n\n"
        "prompt\n\n"
        "## System:\n\n"
        "system\n\n"
        "## Response:\n\n"
        "response\n\n"
    ) + ("## Token usage:\n\n2 input, 5 output\n\n" if usage else "") + (
        "# YYYY-MM-DDTHH:MM:SS    conversation: abc123\n\n"
        "Model: **davinci**\n\n"
        "## Prompt:\n\n"
        "prompt\n\n"
        "## Response:\n\n"
        "response\n\n"
    ) + (
        "## Token usage:\n\n2 input, 5 output\n\n" if usage else ""
    ) + (
        "# YYYY-MM-DDTHH:MM:SS    conversation: abc123\n\n"
        "Model: **davinci**\n\n"
        "## Prompt:\n\n"
        "prompt\n\n"
        "## Response:\n\n"
        "response\n\n"
    ) + (
        "## Token usage:\n\n2 input, 5 output\n\n" if usage else ""
    )


@pytest.mark.parametrize("n", (None, 0, 2))
def test_logs_json(n, log_path):
    "Test that logs command correctly returns requested -n records"
    runner = CliRunner()
    args = ["logs", "-p", str(log_path), "--json"]
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


@pytest.mark.parametrize(
    "args", (["-r"], ["--response"], ["list", "-r"], ["list", "--response"])
)
def test_logs_response_only(args, log_path):
    "Test that logs -r/--response returns just the last response"
    runner = CliRunner()
    result = runner.invoke(cli, ["logs"] + args, catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output == "response\n"


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
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


@pytest.mark.parametrize("model", ("davinci", "curie"))
def test_logs_filtered(user_path, model):
    log_path = str(user_path / "logs.db")
    db = sqlite_utils.Database(log_path)
    migrate(db)
    db["responses"].insert_all(
        {
            "id": str(ULID()).lower(),
            "system": "system",
            "prompt": "prompt",
            "response": "response",
            "model": "davinci" if i % 2 == 0 else "curie",
        }
        for i in range(100)
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["logs", "list", "-m", model, "--json"])
    assert result.exit_code == 0
    records = json.loads(result.output.strip())
    assert all(record["model"] == model for record in records)


@pytest.mark.parametrize(
    "query,extra_args,expected",
    (
        # With no search term order should be by datetime
        ("", [], ["doc1", "doc2", "doc3"]),
        # With a search it's order by rank instead
        ("llama", [], ["doc1", "doc3"]),
        ("alpaca", [], ["doc2"]),
        # Model filter should work too
        ("llama", ["-m", "davinci"], ["doc1", "doc3"]),
        ("llama", ["-m", "davinci2"], []),
    ),
)
def test_logs_search(user_path, query, extra_args, expected):
    log_path = str(user_path / "logs.db")
    db = sqlite_utils.Database(log_path)
    migrate(db)

    def _insert(id, text):
        db["responses"].insert(
            {
                "id": id,
                "system": "system",
                "prompt": text,
                "response": "response",
                "model": "davinci",
            }
        )

    _insert("doc1", "llama")
    _insert("doc2", "alpaca")
    _insert("doc3", "llama llama")
    runner = CliRunner()
    result = runner.invoke(cli, ["logs", "list", "-q", query, "--json"] + extra_args)
    assert result.exit_code == 0
    records = json.loads(result.output.strip())
    assert [record["id"] for record in records] == expected


def test_llm_prompt_creates_log_database(mocked_openai_chat, tmpdir, monkeypatch):
    user_path = tmpdir / "user"
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["three names \nfor a pet pelican", "--no-stream", "--key", "x"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert result.output == "Bob, Alice, Eve\n"
    # Should have created user_path and put a logs.db in it
    assert (user_path / "logs.db").exists()
    assert sqlite_utils.Database(str(user_path / "logs.db"))["responses"].count == 1


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
    mocked_openai_chat, use_stdin, user_path, logs_off, logs_args, should_log
):
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
    last_request = mocked_openai_chat.get_requests()[-1]
    assert last_request.headers["Authorization"] == "Bearer X"

    # Was it logged?
    rows = list(log_db["responses"].rows)

    if not should_log:
        assert len(rows) == 0
        return

    assert len(rows) == 1
    expected = {
        "model": "gpt-4o-mini",
        "prompt": "three names \nfor a pet pelican",
        "system": None,
        "options_json": "{}",
        "response": "Bob, Alice, Eve",
    }
    row = rows[0]
    assert expected.items() <= row.items()
    assert isinstance(row["duration_ms"], int)
    assert isinstance(row["datetime_utc"], str)
    assert json.loads(row["prompt_json"]) == {
        "messages": [{"role": "user", "content": "three names \nfor a pet pelican"}]
    }
    assert json.loads(row["response_json"]) == {
        "model": "gpt-4o-mini",
        "choices": [{"message": {"content": "Bob, Alice, Eve"}}],
    }

    # Test "llm logs"
    log_result = runner.invoke(
        cli, ["logs", "-n", "1", "--json"], catch_exceptions=False
    )
    log_json = json.loads(log_result.output)

    # Should have logged correctly:
    assert (
        log_json[0].items()
        >= {
            "model": "gpt-4o-mini",
            "prompt": "three names \nfor a pet pelican",
            "system": None,
            "prompt_json": {
                "messages": [
                    {"role": "user", "content": "three names \nfor a pet pelican"}
                ]
            },
            "options_json": {},
            "response": "Bob, Alice, Eve",
            "response_json": {
                "model": "gpt-4o-mini",
                "choices": [{"message": {"content": "Bob, Alice, Eve"}}],
            },
            # This doesn't have the \n after three names:
            "conversation_name": "three names for a pet pelican",
            "conversation_model": "gpt-4o-mini",
        }.items()
    )


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


def test_openai_chat_stream(mocked_openai_chat_stream, user_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["-m", "gpt-3.5-turbo", "--key", "x", "Say hi"])
    assert result.exit_code == 0
    assert result.output == "Hi.\n"


def test_openai_completion(mocked_openai_completion, user_path):
    log_path = user_path / "logs.db"
    log_db = sqlite_utils.Database(str(log_path))
    log_db["responses"].delete_where()
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
    rows = list(log_db["responses"].rows)
    assert len(rows) == 1
    expected = {
        "model": "gpt-3.5-turbo-instruct",
        "prompt": "Say this is a test",
        "system": None,
        "prompt_json": '{"messages": ["Say this is a test"]}',
        "options_json": "{}",
        "response": "\n\nThis is indeed a test",
    }
    row = rows[0]
    assert expected.items() <= row.items()


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
        catch_exceptions=False,
    )
    assert result.exit_code == 1
    assert (
        result.output
        == "Error: System prompts are not supported for OpenAI completion models\n"
    )


def test_openai_completion_logprobs_stream(
    mocked_openai_completion_logprobs_stream, user_path
):
    log_path = user_path / "logs.db"
    log_db = sqlite_utils.Database(str(log_path))
    log_db["responses"].delete_where()
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
    rows = list(log_db["responses"].rows)
    assert len(rows) == 1
    row = rows[0]
    assert json.loads(row["response_json"]) == {
        "content": "\n\nHi.",
        "logprobs": [
            {"text": "\n\n", "top_logprobs": [{"\n\n": -0.6, "\n": -1.9}]},
            {"text": "Hi", "top_logprobs": [{"Hi": -1.1, "Hello": -0.7}]},
            {"text": ".", "top_logprobs": [{".": -1.1, "!": -0.9}]},
            {"text": "", "top_logprobs": []},
        ],
        "id": "cmpl-80MdSaou7NnPuff5ZyRMysWBmgSPS",
        "object": "text_completion",
        "model": "gpt-3.5-turbo-instruct",
        "created": 1695097702,
    }


def test_openai_completion_logprobs_nostream(
    mocked_openai_completion_logprobs, user_path
):
    log_path = user_path / "logs.db"
    log_db = sqlite_utils.Database(str(log_path))
    log_db["responses"].delete_where()
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
    rows = list(log_db["responses"].rows)
    assert len(rows) == 1
    row = rows[0]
    assert json.loads(row["response_json"]) == {
        "choices": [
            {
                "finish_reason": "stop",
                "index": 0,
                "logprobs": {
                    "text_offset": [16, 18, 20],
                    "token_logprobs": [-0.6, -1.1, -0.9],
                    "tokens": ["\n\n", "Hi", "1"],
                    "top_logprobs": [
                        {"\n": -1.9, "\n\n": -0.6},
                        {"Hello": -0.7, "Hi": -1.1},
                        {"!": -1.1, ".": -0.9},
                    ],
                },
                "text": "\n\nHi.",
            }
        ],
        "created": 1695097747,
        "id": "cmpl-80MeBfKJutM0uMNJkRrebJLeP3bxL",
        "model": "gpt-3.5-turbo-instruct",
        "object": "text_completion",
        "usage": {"completion_tokens": 3, "prompt_tokens": 5, "total_tokens": 8},
    }


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
    image/gif, image/jpeg, image/png, image/webp
"""


def test_llm_models_options(user_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["models", "--options"], catch_exceptions=False)
    assert result.exit_code == 0
    assert EXPECTED_OPTIONS.strip() in result.output
    assert "AsyncMockModel: mock" not in result.output


def test_llm_models_async(user_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["models", "--async"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "AsyncMockModel: mock" in result.output


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
    assert llm.get_default_model() == "gpt-4o-mini"
    assert llm.get_model().model_id == "gpt-4o-mini"
    llm.set_default_model("gpt-4o")
    assert config_path.exists()
    assert llm.get_default_model() == "gpt-4o"
    assert llm.get_model().model_id == "gpt-4o"


def test_get_models():
    models = llm.get_models()
    assert all(isinstance(model, llm.Model) for model in models)
    model_ids = [model.model_id for model in models]
    assert "gpt-4o-mini" in model_ids
    # Ensure no model_ids are duplicated
    # https://github.com/simonw/llm/issues/667
    assert len(model_ids) == len(set(model_ids))


def test_get_async_models():
    models = llm.get_async_models()
    assert all(isinstance(model, llm.AsyncModel) for model in models)
    model_ids = [model.model_id for model in models]
    assert "gpt-4o-mini" in model_ids


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
