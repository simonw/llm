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
import time


SINGLE_ID = "5843577700ba729bb14c327b30441885"
MULTI_ID = "4860edd987df587d042a9eb2b299ce5c"


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


@pytest.fixture
def schema_log_path(user_path):
    log_path = str(user_path / "logs_schema.db")
    db = sqlite_utils.Database(log_path)
    migrate(db)
    start = datetime.datetime.now(datetime.timezone.utc)
    db["schemas"].insert({"id": SINGLE_ID, "content": '{"name": "string"}'})
    db["schemas"].insert({"id": MULTI_ID, "content": '{"name": "array"}'})
    for i in range(2):
        db["responses"].insert(
            {
                "id": str(ULID.from_timestamp(time.time() + i)).lower(),
                "system": "system",
                "prompt": "prompt",
                "response": '{"name": "' + str(i) + '"}',
                "model": "davinci",
                "datetime_utc": (start + datetime.timedelta(seconds=i)).isoformat(),
                "conversation_id": "abc123",
                "input_tokens": 2,
                "output_tokens": 5,
                "schema_id": SINGLE_ID,
            }
        )
    for j in range(4):
        db["responses"].insert(
            {
                "id": str(ULID.from_timestamp(time.time() + j)).lower(),
                "system": "system",
                "prompt": "prompt",
                "response": '{"items": [{"name": "one"}, {"name": "two"}]}',
                "model": "davinci",
                "datetime_utc": (start + datetime.timedelta(seconds=i)).isoformat(),
                "conversation_id": "abc456",
                "input_tokens": 2,
                "output_tokens": 5,
                "schema_id": MULTI_ID,
            }
        )

    return log_path


datetime_re = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
id_re = re.compile(r"id: \w+")


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
    # Replace id: whatever with id: xxx
    output = id_re.sub("id: xxx", output)
    expected = (
        (
            "# YYYY-MM-DDTHH:MM:SS    conversation: abc123 id: xxx\n\n"
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
            "# YYYY-MM-DDTHH:MM:SS    conversation: abc123 id: xxx\n\n"
            "Model: **davinci**\n\n"
            "## Prompt\n\n"
            "prompt\n\n"
            "## Response\n\n"
            'response\n```python\nprint("hello word")\n```\n\n'
        )
        + ("## Token usage:\n\n2 input, 5 output\n\n" if usage else "")
        + (
            "# YYYY-MM-DDTHH:MM:SS    conversation: abc123 id: xxx\n\n"
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


@pytest.mark.parametrize(
    "args,expected",
    (
        (["--data", "--schema", SINGLE_ID], '{"name": "1"}\n{"name": "0"}\n'),
        (
            ["--data", "--schema", MULTI_ID],
            (
                '{"items": [{"name": "one"}, {"name": "two"}]}\n'
                '{"items": [{"name": "one"}, {"name": "two"}]}\n'
                '{"items": [{"name": "one"}, {"name": "two"}]}\n'
                '{"items": [{"name": "one"}, {"name": "two"}]}\n'
            ),
        ),
        (
            ["--data-array", "--schema", MULTI_ID],
            (
                '[{"items": [{"name": "one"}, {"name": "two"}]},\n'
                ' {"items": [{"name": "one"}, {"name": "two"}]},\n'
                ' {"items": [{"name": "one"}, {"name": "two"}]},\n'
                ' {"items": [{"name": "one"}, {"name": "two"}]}]\n'
            ),
        ),
        (
            ["--schema", MULTI_ID, "--data-key", "items"],
            (
                '{"name": "one"}\n'
                '{"name": "two"}\n'
                '{"name": "one"}\n'
                '{"name": "two"}\n'
                '{"name": "one"}\n'
                '{"name": "two"}\n'
                '{"name": "one"}\n'
                '{"name": "two"}\n'
            ),
        ),
    ),
)
def test_logs_schema(schema_log_path, args, expected):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["logs", "-n", "0", "-p", str(schema_log_path)] + args,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert result.output == expected


def test_logs_schema_data_ids(schema_log_path):
    db = sqlite_utils.Database(schema_log_path)
    ulid = ULID.from_timestamp(time.time() + 100)
    db["responses"].insert(
        {
            "id": str(ulid).lower(),
            "system": "system",
            "prompt": "prompt",
            "response": json.dumps(
                {
                    "name": "three",
                    "response_id": 1,
                    "conversation_id": 2,
                    "conversation_id_": 3,
                }
            ),
            "model": "davinci",
            "datetime_utc": ulid.datetime.isoformat(),
            "conversation_id": "abc123",
            "input_tokens": 2,
            "output_tokens": 5,
            "schema_id": SINGLE_ID,
        }
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "logs",
            "-n",
            "0",
            "-p",
            str(schema_log_path),
            "--data-ids",
            "--data-key",
            "items",
            "--data-array",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    rows = json.loads(result.output)
    last_row = rows.pop(-1)
    assert set(last_row.keys()) == {
        "conversation_id_",
        "conversation_id",
        "response_id",
        "response_id_",
        "name",
        "conversation_id__",
    }
    for row in rows:
        assert set(row.keys()) == {"conversation_id", "response_id", "name"}
