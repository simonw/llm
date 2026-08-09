import json
import re
import sys
import textwrap
from unittest.mock import ANY

import pytest
import sqlite_utils
from click.testing import CliRunner

import llm.cli
from llm.logs import LogStore, merged_log_rows


def logged_rows(db):
    """Chronological log rows from the store, reduced to the fields
    these tests care about."""
    rows = merged_log_rows(LogStore(db))
    rows.reverse()
    return [
        {
            "model": row["model"],
            "prompt": row["prompt"],
            "system": row["system"],
            "options_json": row["options_json"],
            "response": row["response"],
            "conversation_id": row["conversation_id"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
        }
        for row in rows
    ]


TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\xa6\x00\x00\x01\x1a"
    b"\x02\x03\x00\x00\x00\xe6\x99\xc4^\x00\x00\x00\tPLTE\xff\xff\xff"
    b"\x00\xff\x00\xfe\x01\x00\x12t\x01J\x00\x00\x00GIDATx\xda\xed\xd81\x11"
    b"\x000\x08\xc0\xc0.]\xea\xaf&Q\x89\x04V\xe0>\xf3+\xc8\x91Z\xf4\xa2\x08EQ\x14E"
    b"Q\x14EQ\x14EQ\xd4B\x91$I3\xbb\xbf\x08EQ\x14EQ\x14EQ\x14E\xd1\xa5"
    b"\xd4\x17\x91\xc6\x95\x05\x15\x0f\x9f\xc5\t\x9f\xa4\x00\x00\x00\x00IEND\xaeB`"
    b"\x82"
)


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_chat_basic(mock_model, logs_db):
    runner = CliRunner()
    mock_model.enqueue(["one world"])
    mock_model.enqueue(["one again"])
    result = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "mock"],
        input="Hi\nHi two\nquit\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert result.output == (
        "Chatting with mock"
        "\nType 'exit' or 'quit' to exit"
        "\nType '!multi' to enter multiple lines, then '!end' to finish"
        "\nType '!edit' to open your default editor and modify the prompt"
        "\nType '!fragment <my_fragment> [<another_fragment> ...]' to insert one or more fragments"
        "\nType '!attach <url-or-path>' to attach a file"
        "\n> Hi"
        "\none world"
        "\n> Hi two"
        "\none again"
        "\n> quit"
        "\n"
    )
    # Should have logged
    threads = list(logs_db["threads"].rows)
    assert threads[0]["name"] == "Hi"
    conversation_id = threads[0]["id"]
    responses = logged_rows(logs_db)
    assert responses == [
        {
            "model": "mock",
            "prompt": "Hi",
            "system": None,
            "options_json": "{}",
            "response": "one world",
            "conversation_id": conversation_id,
            "input_tokens": 1,
            "output_tokens": 1,
        },
        {
            "model": "mock",
            "prompt": "Hi two",
            "system": None,
            "options_json": "{}",
            "response": "one again",
            "conversation_id": conversation_id,
            "input_tokens": 2,
            "output_tokens": 1,
        },
    ]
    # Now continue that conversation
    mock_model.enqueue(["continued"])
    result2 = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "mock", "-c"],
        input="Continue\nquit\n",
        catch_exceptions=False,
    )
    assert result2.exit_code == 0
    assert result2.output == (
        "Chatting with mock"
        "\nType 'exit' or 'quit' to exit"
        "\nType '!multi' to enter multiple lines, then '!end' to finish"
        "\nType '!edit' to open your default editor and modify the prompt"
        "\nType '!fragment <my_fragment> [<another_fragment> ...]' to insert one or more fragments"
        "\nType '!attach <url-or-path>' to attach a file"
        "\n> Continue"
        "\ncontinued"
        "\n> quit"
        "\n"
    )
    new_responses = logged_rows(logs_db)[len(responses) :]
    assert new_responses == [
        {
            "model": "mock",
            "prompt": "Continue",
            "system": None,
            "options_json": "{}",
            "response": "continued",
            "conversation_id": conversation_id,
            "input_tokens": 1,
            "output_tokens": 1,
        }
    ]


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_chat_system(mock_model, logs_db):
    runner = CliRunner()
    mock_model.enqueue(["I am mean"])
    result = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "mock", "--system", "You are mean"],
        input="Hi\nquit\n",
    )
    assert result.exit_code == 0
    assert result.output == (
        "Chatting with mock"
        "\nType 'exit' or 'quit' to exit"
        "\nType '!multi' to enter multiple lines, then '!end' to finish"
        "\nType '!edit' to open your default editor and modify the prompt"
        "\nType '!fragment <my_fragment> [<another_fragment> ...]' to insert one or more fragments"
        "\nType '!attach <url-or-path>' to attach a file"
        "\n> Hi"
        "\nI am mean"
        "\n> quit"
        "\n"
    )
    responses = logged_rows(logs_db)
    assert responses == [
        {
            "model": "mock",
            "prompt": "Hi",
            "system": "You are mean",
            "options_json": "{}",
            "response": "I am mean",
            "conversation_id": ANY,
            "input_tokens": 1,
            "output_tokens": 1,
        }
    ]


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_chat_options(mock_model, logs_db, user_path):
    options_path = user_path / "model_options.json"
    options_path.write_text(json.dumps({"mock": {"max_tokens": "5"}}), "utf-8")

    runner = CliRunner()
    mock_model.enqueue(["Default options response"])
    result = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "mock"],
        input="Hi\nquit\n",
    )
    assert result.exit_code == 0
    mock_model.enqueue(["Override options response"])
    result = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "mock", "--option", "max_tokens", "10"],
        input="Hi with override\nquit\n",
    )
    assert result.exit_code == 0
    responses = logged_rows(logs_db)
    assert responses == [
        {
            "model": "mock",
            "prompt": "Hi",
            "system": None,
            "options_json": '{"max_tokens": 5}',
            "response": "Default options response",
            "conversation_id": ANY,
            "input_tokens": 1,
            "output_tokens": 1,
        },
        {
            "model": "mock",
            "prompt": "Hi with override",
            "system": None,
            "options_json": '{"max_tokens": 10}',
            "response": "Override options response",
            "conversation_id": ANY,
            "input_tokens": 3,
            "output_tokens": 1,
        },
    ]


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
@pytest.mark.parametrize(
    "input,expected",
    (
        (
            "Hi\n!multi\nthis is multiple lines\nuntil the !end\n!end\nquit\n",
            [
                {"prompt": "Hi", "response": "One\n"},
                {
                    "prompt": "this is multiple lines\nuntil the !end",
                    "response": "Two\n",
                },
            ],
        ),
        # quit should not work within !multi
        (
            "!multi\nthis is multiple lines\nquit\nuntil the !end\n!end\nquit\n",
            [
                {
                    "prompt": "this is multiple lines\nquit\nuntil the !end",
                    "response": "One\n",
                }
            ],
        ),
        # Try custom delimiter
        (
            "!multi abc\nCustom delimiter\n!end\n!end 123\n!end abc\nquit\n",
            [{"prompt": "Custom delimiter\n!end\n!end 123", "response": "One\n"}],
        ),
    ),
)
def test_chat_multi(mock_model, logs_db, input, expected):
    runner = CliRunner()
    mock_model.enqueue(["One\n"])
    mock_model.enqueue(["Two\n"])
    mock_model.enqueue(["Three\n"])
    result = runner.invoke(
        llm.cli.cli, ["chat", "-m", "mock", "--option", "max_tokens", "10"], input=input
    )
    assert result.exit_code == 0
    rows = [
        {"prompt": row["prompt"], "response": row["response"]}
        for row in logged_rows(logs_db)
    ]
    assert rows == expected


@pytest.mark.parametrize("custom_database_path", (False, True))
def test_llm_chat_creates_log_database(tmpdir, monkeypatch, custom_database_path):
    user_path = tmpdir / "user"
    custom_db_path = tmpdir / "custom_log.db"
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    runner = CliRunner()
    args = ["chat", "-m", "mock"]
    if custom_database_path:
        args.extend(["--database", str(custom_db_path)])
    result = runner.invoke(
        llm.cli.cli,
        args,
        catch_exceptions=False,
        input="Hi\nHi two\nquit\n",
    )
    assert result.exit_code == 0
    # Should have created user_path and put a logs.db in it
    if custom_database_path:
        assert custom_db_path.exists()
        db_path = str(custom_db_path)
    else:
        assert (user_path / "logs.db").exists()
        db_path = str(user_path / "logs.db")
    assert sqlite_utils.Database(db_path)["turns"].count == 2


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_chat_tools(logs_db):
    runner = CliRunner()
    functions = textwrap.dedent("""
    def upper(text: str) -> str:
        "Convert text to upper case"
        return text.upper()                         
    """)
    result = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "echo", "--functions", functions],
        input="\n".join(
            [
                json.dumps(
                    {
                        "prompt": "Convert hello to uppercase",
                        "tool_calls": [
                            {"name": "upper", "arguments": {"text": "hello"}}
                        ],
                    }
                ),
                "quit",
            ]
        ),
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    normalized_output = re.sub(r"tc_[0-9a-z]{26}", "tc_TCID", result.output)
    assert normalized_output == (
        "Chatting with echo\n"
        "Type 'exit' or 'quit' to exit\n"
        "Type '!multi' to enter multiple lines, then '!end' to finish\n"
        "Type '!edit' to open your default editor and modify the prompt\n"
        "Type '!fragment <my_fragment> [<another_fragment> ...]' to insert one or more fragments\n"
        "Type '!attach <url-or-path>' to attach a file\n"
        '> {"prompt": "Convert hello to uppercase", "tool_calls": [{"name": "upper", '
        '"arguments": {"text": "hello"}}]}\n'
        "{\n"
        '  "prompt": "Convert hello to uppercase",\n'
        '  "system": "",\n'
        '  "attachments": [],\n'
        '  "stream": true,\n'
        '  "previous": []\n'
        "} {\n"
        '  "prompt": "",\n'
        '  "system": "",\n'
        '  "attachments": [],\n'
        '  "stream": true,\n'
        '  "previous": [\n'
        "    {\n"
        '      "prompt": "{\\"prompt\\": \\"Convert hello to uppercase\\", '
        '\\"tool_calls\\": [{\\"name\\": \\"upper\\", \\"arguments\\": {\\"text\\": '
        '\\"hello\\"}}]}"\n'
        "    }\n"
        "  ],\n"
        '  "tool_results": [\n'
        "    {\n"
        '      "name": "upper",\n'
        '      "output": "HELLO",\n'
        '      "tool_call_id": "tc_TCID"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "> quit\n"
    )


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_chat_fragments(tmpdir):
    path1 = str(tmpdir / "frag1.txt")
    path2 = str(tmpdir / "frag2.txt")
    with open(path1, "w") as fp:
        fp.write("one")
    with open(path2, "w") as fp:
        fp.write("two")
    runner = CliRunner()
    output = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "echo", "-f", path1],
        input=(f"hi\n!fragment {path2}\nquit\n"),
    ).output
    assert '"prompt": "one' in output
    assert '"prompt": "two"' in output


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_chat_attach(tmp_path, mock_model, logs_db):
    image_path = tmp_path / "image with spaces.png"
    image_path.write_bytes(TINY_PNG)
    runner = CliRunner()
    mock_model.enqueue(["saw image"])
    result = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "mock"],
        input=f"!attach {image_path}\nquit\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert result.output.endswith("\n> quit\n")
    prompt = mock_model.history[0][0]
    assert prompt.prompt == ""
    assert prompt.attachments == [
        llm.Attachment(
            type="image/png",
            path=str(image_path),
            url=None,
            content=None,
            _id=ANY,
        )
    ]
    attachment = next(iter(logs_db["attachments"].rows))
    assert attachment == {
        "id": ANY,
        "type": "image/png",
        "path": str(image_path),
        "url": None,
        "content": None,
    }


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_chat_multi_fragments_and_attach(tmp_path, mock_model, logs_db):
    fragment_path = tmp_path / "fragment.txt"
    fragment_path.write_text("fragment text")
    image_path = tmp_path / "image.png"
    image_path.write_bytes(TINY_PNG)
    runner = CliRunner()
    mock_model.enqueue(["parsed"])
    result = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "mock"],
        input=(
            "!multi\n"
            "Describe this image using this fragment:\n"
            f"!fragment {fragment_path}\n"
            f"!attach {image_path}\n"
            "!end\n"
            "quit\n"
        ),
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert result.output.endswith("\n> quit\n")
    prompt = mock_model.history[0][0]
    assert prompt.prompt == "fragment text\nDescribe this image using this fragment:"
    assert prompt.fragments == ["fragment text"]
    assert prompt.attachments == [
        llm.Attachment(
            type="image/png",
            path=str(image_path),
            url=None,
            content=None,
            _id=ANY,
        )
    ]
    attachment = next(iter(logs_db["attachments"].rows))
    assert attachment == {
        "id": ANY,
        "type": "image/png",
        "path": str(image_path),
        "url": None,
        "content": None,
    }
