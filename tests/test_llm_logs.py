from click.testing import CliRunner
from llm.cli import cli
from llm.migrations import migrate
from llm import Fragment
from ulid import ULID
import datetime
import json
import pathlib
import pytest
import re
import sqlite_utils
import sys
import time
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
            "id": str(ULID()).lower(),
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
