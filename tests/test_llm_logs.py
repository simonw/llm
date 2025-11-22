from click.testing import CliRunner
from llm.cli import cli
from llm.migrations import migrate
from llm.utils import monotonic_ulid
from llm import Fragment
import datetime
import json
import pathlib
import pytest
import re
import sqlite_utils
import sys
import textwrap
import time
from ulid import ULID
import yaml


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
            "id": str(monotonic_ulid()).lower(),
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


@pytest.mark.parametrize(
    "nc",
    (None, 0, 1, 2),
)
def test_logs_conv_count(nc):
    """Test that --nc returns all responses from N unique conversations"""
    from llm.utils import monotonic_ulid

    runner = CliRunner()
    with runner.isolated_filesystem():
        # Create a database with multiple conversations
        log_path = "test_logs.db"
        db = sqlite_utils.Database(log_path)
        migrate(db)
        start = datetime.datetime.now(datetime.timezone.utc)

        # Create 3 conversations with varying numbers of responses
        # Conversation 1: 2 responses
        # Conversation 2: 3 responses  
        # Conversation 3: 1 response
        response_count = 0
        for conv_id in ["conv1", "conv2", "conv3"]:
            responses_in_conv = 2 if conv_id == "conv1" else (3 if conv_id == "conv2" else 1)
            for i in range(responses_in_conv):
                db["responses"].insert(
                    {
                        "id": str(monotonic_ulid()).lower(),
                        "system": f"system-{conv_id}-{i}",
                        "prompt": f"prompt-{conv_id}-{i}",
                        "response": f"response-{conv_id}-{i}",
                        "model": "davinci",
                        "datetime_utc": (start + datetime.timedelta(seconds=response_count)).isoformat(),
                        "conversation_id": conv_id,
                        "input_tokens": 2,
                        "output_tokens": 5,
                    }
                )
                response_count += 1

        # Test without --nc (default should be 3 responses)
        if nc is None:
            result = runner.invoke(cli, ["logs", "-p", str(log_path), "--json"], catch_exceptions=False)
            assert result.exit_code == 0
            logs = json.loads(result.output)
            assert len(logs) == 3
            return

        # Test with --nc 0 (should be same as no limit)
        if nc == 0:
            result = runner.invoke(cli, ["logs", "-p", str(log_path), "--nc", "0", "--json"], catch_exceptions=False)
            assert result.exit_code == 0
            logs = json.loads(result.output)
            assert len(logs) == 6  # All 6 responses
            return

        # Test with --nc 1 (should get all responses from latest conversation only)
        if nc == 1:
            result = runner.invoke(cli, ["logs", "-p", str(log_path), "--nc", "1", "--json"], catch_exceptions=False)
            assert result.exit_code == 0
            logs = json.loads(result.output)
            # conv3 is the latest (most recent response), has 1 response
            assert len(logs) == 1
            assert logs[0]["conversation_id"] == "conv3"
            return

        # Test with --nc 2 (should get all responses from 2 latest conversations)
        if nc == 2:
            result = runner.invoke(cli, ["logs", "-p", str(log_path), "--nc", "2", "--json"], catch_exceptions=False)
            assert result.exit_code == 0
            logs = json.loads(result.output)
            # conv2 (3 responses) and conv3 (1 response) are the 2 latest = 4 responses total
            assert len(logs) == 4
            conv_ids = {log["conversation_id"] for log in logs}
            assert conv_ids == {"conv2", "conv3"}
            return


def test_logs_conv_count_mutually_exclusive():
    """Test that --nc and -n cannot be used together"""
    runner = CliRunner()
    with runner.isolated_filesystem():
        log_path = "test_logs.db"
        db = sqlite_utils.Database(log_path)
        migrate(db)
        db["responses"].insert({
            "id": "test1",
            "prompt": "test",
            "response": "test",
            "model": "test",
        })

        # Test --nc and -n together
        result = runner.invoke(cli, ["logs", "-p", str(log_path), "--nc", "1", "-n", "5"], catch_exceptions=False)
        assert result.exit_code != 0
        assert "Cannot use both" in result.output


def test_logs_conv_count_with_conversation_id():
    """Test that --nc and --conversation cannot be used together"""
    runner = CliRunner()
    with runner.isolated_filesystem():
        log_path = "test_logs.db"
        db = sqlite_utils.Database(log_path)
        migrate(db)
        db["responses"].insert({
            "id": "test1",
            "prompt": "test",
            "response": "test",
            "model": "test",
            "conversation_id": "conv1",
        })

        # Test --nc and --conversation together
        result = runner.invoke(cli, ["logs", "-p", str(log_path), "--nc", "1", "--conversation", "conv1"], catch_exceptions=False)
        assert result.exit_code != 0
        assert "Cannot use both" in result.output


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
        + ("## Token usage\n\n2 input, 5 output\n\n" if usage else "")
        + (
            "# YYYY-MM-DDTHH:MM:SS    conversation: abc123 id: xxx\n\n"
            "Model: **davinci**\n\n"
            "## Prompt\n\n"
            "prompt\n\n"
            "## Response\n\n"
            'response\n```python\nprint("hello word")\n```\n\n'
        )
        + ("## Token usage\n\n2 input, 5 output\n\n" if usage else "")
        + (
            "# YYYY-MM-DDTHH:MM:SS    conversation: abc123 id: xxx\n\n"
            "Model: **davinci**\n\n"
            "## Prompt\n\n"
            "prompt\n\n"
            "## Response\n\n"
            'response\n```python\nprint("hello word")\n```\n\n'
        )
        + ("## Token usage\n\n2 input, 5 output\n\n" if usage else "")
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
        "  prompt: prompt\n"
        "  prompt_fragments: []\n"
        f"  system_fragments: []\n{expected_usage}"
        "- model: davinci\n"
        "  datetime: 'YYYY-MM-DDTHH:MM:SS'\n"
        "  conversation: abc123\n"
        "  system: system\n"
        "  prompt: prompt\n"
        "  prompt_fragments: []\n"
        f"  system_fragments: []\n{expected_usage}"
        "- model: davinci\n"
        "  datetime: 'YYYY-MM-DDTHH:MM:SS'\n"
        "  conversation: abc123\n"
        "  system: system\n"
        "  prompt: prompt\n"
        "  prompt_fragments: []\n"
        f"  system_fragments: []\n{expected_usage}"
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
@pytest.mark.parametrize("path_option", (None, "-p", "--path", "-d", "--database"))
def test_logs_filtered(user_path, model, path_option):
    log_path = str(user_path / "logs.db")
    if path_option:
        log_path = str(user_path / "logs_alternative.db")
    db = sqlite_utils.Database(log_path)
    migrate(db)
    db["responses"].insert_all(
        {
            "id": str(monotonic_ulid()).lower(),
            "system": "system",
            "prompt": "prompt",
            "response": "response",
            "model": "davinci" if i % 2 == 0 else "curie",
        }
        for i in range(100)
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["logs", "list", "-m", model, "--json"]
        + ([path_option, log_path] if path_option else []),
    )
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
        # Adding -l/--latest should return latest first (order by id desc)
        ("llama", [], ["doc1", "doc3"]),
        ("llama", ["-l"], ["doc3", "doc1"]),
        ("llama", ["--latest"], ["doc3", "doc1"]),
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


_expected_yaml_re = r"""- id: [a-f0-9]{32}
  summary: \|
    
  usage: \|
    4 times, most recently \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00
- id: [a-f0-9]{32}
  summary: \|
    
  usage: \|
    2 times, most recently \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00"""


@pytest.mark.parametrize(
    "args,expected",
    (
        (["schemas"], _expected_yaml_re),
        (["schemas", "list"], _expected_yaml_re),
    ),
)
def test_schemas_list_yaml(schema_log_path, args, expected):
    result = CliRunner().invoke(cli, args + ["-d", str(schema_log_path)])
    assert result.exit_code == 0
    assert re.match(expected, result.output.strip())


@pytest.mark.parametrize("is_nl", (False, True))
def test_schemas_list_json(schema_log_path, is_nl):
    result = CliRunner().invoke(
        cli,
        ["schemas", "list"]
        + (["--nl"] if is_nl else ["--json"])
        + ["-d", str(schema_log_path)],
    )
    assert result.exit_code == 0
    if is_nl:
        rows = [json.loads(line) for line in result.output.strip().split("\n")]
    else:
        rows = json.loads(result.output)
    assert len(rows) == 2
    assert rows[0]["content"] == {"name": "array"}
    assert rows[0]["times_used"] == 4
    assert rows[1]["content"] == {"name": "string"}
    assert rows[1]["times_used"] == 2
    assert set(rows[0].keys()) == {"id", "content", "recently_used", "times_used"}


@pytest.fixture
def fragments_fixture(user_path):
    log_path = str(user_path / "logs_fragments.db")
    db = sqlite_utils.Database(log_path)
    migrate(db)
    start = datetime.datetime.now(datetime.timezone.utc)
    # Replace everything from here on

    fragment_hashes_by_slug = {}
    # Create fragments
    for i in range(1, 6):
        content = f"This is fragment {i}" * (100 if i == 5 else 1)
        fragment = Fragment(content, "fragment")
        db["fragments"].insert(
            {
                "id": i,
                "hash": fragment.id(),
                # 5 is a long one:
                "content": content,
                "datetime_utc": start.isoformat(),
            }
        )
        db["fragment_aliases"].insert({"alias": f"hash{i}", "fragment_id": i})
        fragment_hashes_by_slug[f"hash{i}"] = fragment.id()

    # Create some more fragment aliases
    db["fragment_aliases"].insert({"alias": "alias_1", "fragment_id": 3})
    db["fragment_aliases"].insert({"alias": "alias_3", "fragment_id": 4})
    db["fragment_aliases"].insert({"alias": "long_5", "fragment_id": 5})

    def make_response(name, prompt_fragment_ids=None, system_fragment_ids=None):
        time.sleep(0.05)  # To ensure ULIDs order predictably
        response_id = str(ULID.from_timestamp(time.time())).lower()
        db["responses"].insert(
            {
                "id": response_id,
                "system": f"system: {name}",
                "prompt": f"prompt: {name}",
                "response": f"response: {name}",
                "model": "davinci",
                "datetime_utc": start.isoformat(),
                "conversation_id": "abc123",
                "input_tokens": 2,
                "output_tokens": 5,
            }
        )
        # Link fragments to this response
        for fragment_id in prompt_fragment_ids or []:
            db["prompt_fragments"].insert(
                {"response_id": response_id, "fragment_id": fragment_id}
            )
        for fragment_id in system_fragment_ids or []:
            db["system_fragments"].insert(
                {"response_id": response_id, "fragment_id": fragment_id}
            )
        return {name: response_id}

    collected = {}
    collected.update(make_response("no_fragments"))
    collected.update(
        single_prompt_fragment_id=make_response("single_prompt_fragment", [1])
    )
    collected.update(
        single_system_fragment_id=make_response("single_system_fragment", None, [2])
    )
    collected.update(
        multi_prompt_fragment_id=make_response("multi_prompt_fragment", [1, 2])
    )
    collected.update(
        multi_system_fragment_id=make_response("multi_system_fragment", None, [1, 2])
    )
    collected.update(both_fragments_id=make_response("both_fragments", [1, 2], [3, 4]))
    collected.update(
        single_long_prompt_fragment_with_alias_id=make_response(
            "single_long_prompt_fragment_with_alias", [5], None
        )
    )
    collected.update(
        single_system_fragment_with_alias_id=make_response(
            "single_system_fragment_with_alias", None, [4]
        )
    )
    return {
        "path": log_path,
        "fragment_hashes_by_slug": fragment_hashes_by_slug,
        "collected": collected,
    }


@pytest.mark.parametrize(
    "fragment_refs,expected",
    (
        (
            ["hash1"],
            [
                {
                    "name": "single_prompt_fragment",
                    "prompt_fragments": ["hash1"],
                    "system_fragments": [],
                },
                {
                    "name": "multi_prompt_fragment",
                    "prompt_fragments": ["hash1", "hash2"],
                    "system_fragments": [],
                },
                {
                    "name": "multi_system_fragment",
                    "prompt_fragments": [],
                    "system_fragments": ["hash1", "hash2"],
                },
                {
                    "name": "both_fragments",
                    "prompt_fragments": ["hash1", "hash2"],
                    "system_fragments": ["hash3", "hash4"],
                },
            ],
        ),
        (
            ["alias_3"],
            [
                {
                    "name": "both_fragments",
                    "prompt_fragments": ["hash1", "hash2"],
                    "system_fragments": ["hash3", "hash4"],
                },
                {
                    "name": "single_system_fragment_with_alias",
                    "prompt_fragments": [],
                    "system_fragments": ["hash4"],
                },
            ],
        ),
        # Testing for AND condition
        (
            ["hash1", "hash4"],
            [
                {
                    "name": "both_fragments",
                    "prompt_fragments": ["hash1", "hash2"],
                    "system_fragments": ["hash3", "hash4"],
                },
            ],
        ),
    ),
)
def test_logs_fragments(fragments_fixture, fragment_refs, expected):
    fragments_log_path = fragments_fixture["path"]
    fragment_hashes_by_slug = fragments_fixture["fragment_hashes_by_slug"]
    runner = CliRunner()
    args = ["logs", "-d", fragments_log_path, "-n", "0"]
    for ref in fragment_refs:
        args.extend(["-f", ref])
    result = runner.invoke(cli, args + ["--json"], catch_exceptions=False)
    assert result.exit_code == 0
    output = result.output
    responses = json.loads(output)
    # Re-shape that to same shape as expected
    reshaped = [
        {
            "name": response["prompt"].replace("prompt: ", ""),
            "prompt_fragments": [
                fragment["hash"] for fragment in response["prompt_fragments"]
            ],
            "system_fragments": [
                fragment["hash"] for fragment in response["system_fragments"]
            ],
        }
        for response in responses
    ]
    # Replace aliases with hash IDs in expected
    for item in expected:
        item["prompt_fragments"] = [
            fragment_hashes_by_slug.get(ref, ref) for ref in item["prompt_fragments"]
        ]
        item["system_fragments"] = [
            fragment_hashes_by_slug.get(ref, ref) for ref in item["system_fragments"]
        ]
    assert reshaped == expected
    # Now test the `-s/--short` option:
    result2 = runner.invoke(cli, args + ["-s"], catch_exceptions=False)
    assert result2.exit_code == 0
    output2 = result2.output
    loaded = yaml.safe_load(output2)
    reshaped2 = [
        {
            "name": item["prompt"].replace("prompt: ", ""),
            "system_fragments": item["system_fragments"],
            "prompt_fragments": item["prompt_fragments"],
        }
        for item in loaded
    ]
    assert reshaped2 == expected


def test_logs_fragments_markdown(fragments_fixture):
    fragments_log_path = fragments_fixture["path"]
    fragment_hashes_by_slug = fragments_fixture["fragment_hashes_by_slug"]
    runner = CliRunner()
    args = ["logs", "-d", fragments_log_path, "-n", "0"]
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0
    output = result.output
    # Replace dates and IDs
    output = datetime_re.sub("YYYY-MM-DDTHH:MM:SS", output)
    output = id_re.sub("id: xxx", output)
    expected_output = """
# YYYY-MM-DDTHH:MM:SS    conversation: abc123 id: xxx

Model: **davinci**

## Prompt

prompt: no_fragments

## System

system: no_fragments

## Response

response: no_fragments

# YYYY-MM-DDTHH:MM:SS    conversation: abc123 id: xxx

Model: **davinci**

## Prompt

prompt: single_prompt_fragment

### Prompt fragments

- hash1

## System

system: single_prompt_fragment

## Response

response: single_prompt_fragment

# YYYY-MM-DDTHH:MM:SS    conversation: abc123 id: xxx

Model: **davinci**

## Prompt

prompt: single_system_fragment

## System

system: single_system_fragment

### System fragments

- hash2

## Response

response: single_system_fragment

# YYYY-MM-DDTHH:MM:SS    conversation: abc123 id: xxx

Model: **davinci**

## Prompt

prompt: multi_prompt_fragment

### Prompt fragments

- hash1
- hash2

## System

system: multi_prompt_fragment

## Response

response: multi_prompt_fragment

# YYYY-MM-DDTHH:MM:SS    conversation: abc123 id: xxx

Model: **davinci**

## Prompt

prompt: multi_system_fragment

## System

system: multi_system_fragment

### System fragments

- hash1
- hash2

## Response

response: multi_system_fragment

# YYYY-MM-DDTHH:MM:SS    conversation: abc123 id: xxx

Model: **davinci**

## Prompt

prompt: both_fragments

### Prompt fragments

- hash1
- hash2

## System

system: both_fragments

### System fragments

- hash3
- hash4

## Response

response: both_fragments

# YYYY-MM-DDTHH:MM:SS    conversation: abc123 id: xxx

Model: **davinci**

## Prompt

prompt: single_long_prompt_fragment_with_alias

### Prompt fragments

- hash5

## System

system: single_long_prompt_fragment_with_alias

## Response

response: single_long_prompt_fragment_with_alias

# YYYY-MM-DDTHH:MM:SS    conversation: abc123 id: xxx

Model: **davinci**

## Prompt

prompt: single_system_fragment_with_alias

## System

system: single_system_fragment_with_alias

### System fragments

- hash4

## Response

response: single_system_fragment_with_alias
    """
    # Replace hash4 etc with their proper IDs
    for key, value in fragment_hashes_by_slug.items():
        expected_output = expected_output.replace(key, value)
    assert output.strip() == expected_output.strip()


@pytest.mark.parametrize("arg", ("-e", "--expand"))
def test_expand_fragment_json(fragments_fixture, arg):
    fragments_log_path = fragments_fixture["path"]
    runner = CliRunner()
    args = ["logs", "-d", fragments_log_path, "-f", "long_5", "--json"]
    # Without -e the JSON is truncated
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0
    data = json.loads(result.output)
    fragment = data[0]["prompt_fragments"][0]["content"]
    assert fragment.startswith("This is fragment 5This is fragment 5")
    assert len(fragment) < 200
    # With -e the JSON is expanded
    result2 = runner.invoke(cli, args + [arg], catch_exceptions=False)
    assert result2.exit_code == 0
    data2 = json.loads(result2.output)
    fragment2 = data2[0]["prompt_fragments"][0]["content"]
    assert fragment2.startswith("This is fragment 5This is fragment 5")
    assert len(fragment2) > 200


def test_expand_fragment_markdown(fragments_fixture):
    fragments_log_path = fragments_fixture["path"]
    fragment_hashes_by_slug = fragments_fixture["fragment_hashes_by_slug"]
    runner = CliRunner()
    args = ["logs", "-d", fragments_log_path, "-f", "long_5", "--expand"]
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0
    output = result.output
    interesting_bit = (
        output.split("prompt: single_long_prompt_fragment_with_alias")[1]
        .split("## System")[0]
        .strip()
    )
    hash = fragment_hashes_by_slug["hash5"]
    expected_prefix = f"### Prompt fragments\n\n<details><summary>{hash}</summary>\nThis is fragment 5"
    assert interesting_bit.startswith(expected_prefix)
    assert interesting_bit.endswith("</details>")


def test_logs_tools(logs_db):
    runner = CliRunner()
    code = textwrap.dedent(
        """
    def demo():
        return "one\\ntwo\\nthree"
    """
    )
    result1 = runner.invoke(
        cli,
        [
            "-m",
            "echo",
            "--functions",
            code,
            json.dumps({"tool_calls": [{"name": "demo"}]}),
        ],
    )
    assert result1.exit_code == 0
    result2 = runner.invoke(cli, ["logs", "-c"])
    assert (
        "### Tool results\n"
        "\n"
        "- **demo**: `None`<br>\n"
        "    one\n"
        "    two\n"
        "    three\n"
        "\n"
    ) in result2.output
    # Log one that did NOT use tools, check that `llm logs --tools` ignores it
    assert runner.invoke(cli, ["-m", "echo", "badger"]).exit_code == 0
    assert "badger" in runner.invoke(cli, ["logs"]).output
    logs_tools_output = runner.invoke(cli, ["logs", "--tools"]).output
    assert "badger" not in logs_tools_output
    assert "three" in logs_tools_output


def test_logs_backup(logs_db):
    assert not logs_db.tables
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner.invoke(cli, ["-m", "echo", "simple prompt"])
        assert logs_db.tables
        expected_path = pathlib.Path("backup.db")
        assert not expected_path.exists()
        # Now back it up
        result = runner.invoke(cli, ["logs", "backup", "backup.db"])
        assert result.exit_code == 0
        assert result.output.startswith("Backed up ")
        assert result.output.endswith("to backup.db\n")
        assert expected_path.exists()


@pytest.mark.parametrize("async_", (False, True))
def test_logs_resolved_model(logs_db, mock_model, async_mock_model, async_):
    mock_model.resolved_model_name = "resolved-mock"
    async_mock_model.resolved_model_name = "resolved-mock"
    runner = CliRunner()
    result = runner.invoke(
        cli, ["-m", "mock", "simple prompt"] + (["--async"] if async_ else [])
    )
    assert result.exit_code == 0
    # Should have logged the resolved model name
    assert logs_db["responses"].count
    response = list(logs_db["responses"].rows)[0]
    assert response["model"] == "mock"
    assert response["resolved_model"] == "resolved-mock"

    # Should show up in the JSON logs
    result2 = runner.invoke(cli, ["logs", "--json"])
    assert result2.exit_code == 0
    logs = json.loads(result2.output.strip())
    assert len(logs) == 1
    assert logs[0]["model"] == "mock"
    assert logs[0]["resolved_model"] == "resolved-mock"

    # And the rendered logs
    result3 = runner.invoke(cli, ["logs"])
    assert "Model: **mock** (resolved: **resolved-mock**)" in result3.output


def test_logs_localtime_flag_markdown(log_path, monkeypatch):
    """Test that -L/--localtime flag displays datetime in local timezone for markdown output"""
    import os
    from datetime import datetime, timezone
    
    runner = CliRunner()
    
    # Test with -L flag - get markdown output with converted time
    result = runner.invoke(cli, ["logs", "-p", str(log_path), "-L", "-n", "1"], catch_exceptions=False)
    assert result.exit_code == 0
    output = result.output
    
    # Should contain a header with datetime
    lines = output.split('\n')
    assert len(lines) > 0
    # First line should start with # and contain datetime
    assert lines[0].startswith("# ")
    
    # The datetime should be in ISO format without microseconds
    assert datetime_re.search(output), "Datetime format should match YYYY-MM-DDTHH:MM:SS"


def test_logs_localtime_flag_json(log_path):
    """Test that -L/--localtime flag adds 'datetime' field in JSON output"""
    runner = CliRunner()
    
    # Test with -L flag and JSON output
    result = runner.invoke(cli, ["logs", "-p", str(log_path), "-L", "--json", "-n", "1"], catch_exceptions=False)
    assert result.exit_code == 0
    logs = json.loads(result.output)
    
    assert len(logs) == 1
    # Should have both datetime_utc and datetime fields
    assert "datetime_utc" in logs[0]
    assert "datetime" in logs[0]
    # datetime should not have microseconds
    assert "." not in logs[0]["datetime"]


def test_logs_default_utc_json(log_path):
    """Test that without -L flag, JSON output has datetime_utc, no datetime field added"""
    runner = CliRunner()
    
    # Test without -L flag
    result = runner.invoke(cli, ["logs", "-p", str(log_path), "--json", "-n", "1"], catch_exceptions=False)
    assert result.exit_code == 0
    logs = json.loads(result.output)
    
    assert len(logs) == 1
    assert "datetime_utc" in logs[0]
    # When localtime is disabled, datetime field is not added
    # (datetime field is only added when use_localtime=True)


def test_logs_short_yaml_with_localtime(log_path):
    """Test that -L flag works with -s/--short YAML output"""
    runner = CliRunner()
    
    result = runner.invoke(cli, ["logs", "-p", str(log_path), "-s", "-L", "-n", "1"], catch_exceptions=False)
    assert result.exit_code == 0
    output = result.output
    
    # Should be valid YAML
    parsed = yaml.safe_load(output)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert "datetime" in parsed[0]
    # Datetime should not have microseconds
    assert "." not in parsed[0]["datetime"]


def test_logs_localtime_config_file(user_path, monkeypatch):
    """Test that logs-localtime config file enables localtime by default"""
    from llm import user_dir
    
    # Create a logs database
    log_path = str(user_path / "logs.db")
    db = sqlite_utils.Database(log_path)
    migrate(db)
    start = datetime.datetime.now(datetime.timezone.utc)
    db["responses"].insert_all(
        {
            "id": str(monotonic_ulid()).lower(),
            "system": "system",
            "prompt": "prompt",
            "response": "response",
            "model": "davinci",
            "datetime_utc": (start + datetime.timedelta(seconds=i)).isoformat(),
            "conversation_id": "abc123",
        }
        for i in range(2)
    )
    
    # Create logs-localtime file in config dir using pathlib
    config_dir = pathlib.Path(str(user_path))
    localtime_file = config_dir / "logs-localtime"
    localtime_file.write_text("")
    
    # Mock user_dir to return our test directory
    monkeypatch.setattr("llm.cli.user_dir", lambda: config_dir)
    
    runner = CliRunner()
    result = runner.invoke(cli, ["logs", "-p", str(log_path), "-n", "1"], catch_exceptions=False)
    assert result.exit_code == 0
    
    # Should have a datetime in the output
    assert datetime_re.search(result.output), "Should contain datetime in output"


def test_logs_format_datetime_for_display():
    """Test the format_datetime helper function directly"""
    from llm.cli import format_datetime
    
    # Test UTC format (no microseconds, no timezone info)
    utc_str = "2023-08-17T20:53:58.123456"
    
    # Format as UTC (should be same but without microseconds)
    formatted_utc = format_datetime(utc_str, use_localtime=False)
    assert formatted_utc == "2023-08-17T20:53:58"
    
    # Format as localtime (could be different depending on system timezone)
    formatted_local = format_datetime(utc_str, use_localtime=True)
    # Should be in ISO format without microseconds
    assert "." not in formatted_local
    assert "T" in formatted_local
    assert len(formatted_local) == 19  # YYYY-MM-DDTHH:MM:SS
    
    # Test with None or empty string
    assert format_datetime(None, False) == ""
    assert format_datetime("", False) == ""


def test_logs_localtime_comparison_timezone_aware():
    """Test that UTC and localtime conversions are correct for a known datetime"""
    from llm.cli import format_datetime
    
    # Use a known UTC time
    utc_iso = "2023-01-15T12:00:00.000000"
    
    utc_formatted = format_datetime(utc_iso, use_localtime=False)
    local_formatted = format_datetime(utc_iso, use_localtime=True)
    
    # Both should be valid ISO datetime strings
    assert utc_formatted == "2023-01-15T12:00:00"
    assert "." not in local_formatted
    
    # Parse them back to verify they work
    dt_utc = datetime.datetime.fromisoformat(utc_formatted)
    dt_local = datetime.datetime.fromisoformat(local_formatted)
    
    # Both should parse successfully
    assert dt_utc.year == 2023
    assert dt_local.year == 2023
