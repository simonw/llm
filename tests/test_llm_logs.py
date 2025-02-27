from click.testing import CliRunner
from llm.cli import cli
from llm.migrations import migrate
from ulid import ULID
import datetime
import json
import pytest
import re
import sqlite_utils
import sys


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
            "response": 'response\n```python\nprint("hello word")\n```',
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
    expected = (
        (
            "# YYYY-MM-DDTHH:MM:SS    conversation: abc123\n\n"
            "Model: **davinci**\n\n"
            "## Prompt\n\n"
            "prompt\n\n"
            "## System\n\n"
            "system\n\n"
            "## Response\n\n"
            'response\n```python\nprint("hello word")\n```\n\n'
        )
        + ("## Token usage:\n\n2 input, 5 output\n\n" if usage else "")
        + (
            "# YYYY-MM-DDTHH:MM:SS    conversation: abc123\n\n"
            "Model: **davinci**\n\n"
            "## Prompt\n\n"
            "prompt\n\n"
            "## Response\n\n"
            'response\n```python\nprint("hello word")\n```\n\n'
        )
        + ("## Token usage:\n\n2 input, 5 output\n\n" if usage else "")
        + (
            "# YYYY-MM-DDTHH:MM:SS    conversation: abc123\n\n"
            "Model: **davinci**\n\n"
            "## Prompt\n\n"
            "prompt\n\n"
            "## Response\n\n"
            'response\n```python\nprint("hello word")\n```\n\n'
        )
        + ("## Token usage:\n\n2 input, 5 output\n\n" if usage else "")
    )
    assert output == expected


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
    assert result.output == 'response\n```python\nprint("hello word")\n```\n'


@pytest.mark.parametrize(
    "args",
    (
        ["-x"],
        ["--extract"],
        ["list", "-x"],
        ["list", "--extract"],
        # Using -xr together should have same effect as just -x
        ["-xr"],
        ["-x", "-r"],
        ["--extract", "--response"],
    ),
)
def test_logs_extract_first_code(args, log_path):
    "Test that logs -x/--extract returns the first code block"
    runner = CliRunner()
    result = runner.invoke(cli, ["logs"] + args, catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output == 'print("hello word")\n\n'


@pytest.mark.parametrize(
    "args",
    (
        ["--xl"],
        ["--extract-last"],
        ["list", "--xl"],
        ["list", "--extract-last"],
        ["--xl", "-r"],
        ["-x", "--xl"],
    ),
)
def test_logs_extract_last_code(args, log_path):
    "Test that logs --xl/--extract-last returns the last code block"
    runner = CliRunner()
    result = runner.invoke(cli, ["logs"] + args, catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output == 'print("hello word")\n\n'


@pytest.mark.parametrize("arg", ("-s", "--short"))
@pytest.mark.parametrize("usage", (None, "-u", "--usage"))
def test_logs_short(log_path, arg, usage):
    runner = CliRunner()
    args = ["logs", arg, "-p", str(log_path)]
    if usage:
        args.append(usage)
    result = runner.invoke(cli, args)
    assert result.exit_code == 0
    output = datetime_re.sub("YYYY-MM-DDTHH:MM:SS", result.output)
    expected_usage = ""
    if usage:
        expected_usage = "  usage:\n    input: 2\n    output: 5\n"
    expected = (
        "- model: davinci\n"
        "  datetime: 'YYYY-MM-DDTHH:MM:SS'\n"
        "  conversation: abc123\n"
        "  system: system\n"
        f"  prompt: prompt\n{expected_usage}"
        "- model: davinci\n"
        "  datetime: 'YYYY-MM-DDTHH:MM:SS'\n"
        "  conversation: abc123\n"
        "  system: system\n"
        f"  prompt: prompt\n{expected_usage}"
        "- model: davinci\n"
        "  datetime: 'YYYY-MM-DDTHH:MM:SS'\n"
        "  conversation: abc123\n"
        "  system: system\n"
        f"  prompt: prompt\n{expected_usage}"
    )
    assert output == expected


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
