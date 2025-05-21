from click.testing import CliRunner
import json
import llm.cli
from unittest.mock import ANY
import pytest
import sys
import sqlite_utils
import textwrap


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
        "\n> Hi"
        "\none world"
        "\n> Hi two"
        "\none again"
        "\n> quit"
        "\n"
    )
    # Should have logged
    conversations = list(logs_db["conversations"].rows)
    assert conversations[0] == {
        "id": ANY,
        "name": "Hi",
        "model": "mock",
    }
    conversation_id = conversations[0]["id"]
    responses = list(logs_db["responses"].rows)
    assert responses == [
        {
            "id": ANY,
            "model": "mock",
            "prompt": "Hi",
            "system": None,
            "prompt_json": None,
            "options_json": "{}",
            "response": "one world",
            "response_json": None,
            "conversation_id": conversation_id,
            "duration_ms": ANY,
            "datetime_utc": ANY,
            "input_tokens": 1,
            "output_tokens": 1,
            "token_details": None,
            "schema_id": None,
        },
        {
            "id": ANY,
            "model": "mock",
            "prompt": "Hi two",
            "system": None,
            "prompt_json": None,
            "options_json": "{}",
            "response": "one again",
            "response_json": None,
            "conversation_id": conversation_id,
            "duration_ms": ANY,
            "datetime_utc": ANY,
            "input_tokens": 2,
            "output_tokens": 1,
            "token_details": None,
            "schema_id": None,
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
        "\n> Continue"
        "\ncontinued"
        "\n> quit"
        "\n"
    )
    new_responses = list(
        logs_db.query(
            "select * from responses where id not in ({})".format(
                ", ".join("?" for _ in responses)
            ),
            [r["id"] for r in responses],
        )
    )
    assert new_responses == [
        {
            "id": ANY,
            "model": "mock",
            "prompt": "Continue",
            "system": None,
            "prompt_json": None,
            "options_json": "{}",
            "response": "continued",
            "response_json": None,
            "conversation_id": conversation_id,
            "duration_ms": ANY,
            "datetime_utc": ANY,
            "input_tokens": 1,
            "output_tokens": 1,
            "token_details": None,
            "schema_id": None,
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
        "\n> Hi"
        "\nI am mean"
        "\n> quit"
        "\n"
    )
    responses = list(logs_db["responses"].rows)
    assert responses == [
        {
            "id": ANY,
            "model": "mock",
            "prompt": "Hi",
            "system": "You are mean",
            "prompt_json": None,
            "options_json": "{}",
            "response": "I am mean",
            "response_json": None,
            "conversation_id": ANY,
            "duration_ms": ANY,
            "datetime_utc": ANY,
            "input_tokens": 1,
            "output_tokens": 1,
            "token_details": None,
            "schema_id": None,
        }
    ]


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_chat_options(mock_model, logs_db):
    runner = CliRunner()
    mock_model.enqueue(["Some text"])
    result = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "mock", "--option", "max_tokens", "10"],
        input="Hi\nquit\n",
    )
    assert result.exit_code == 0
    responses = list(logs_db["responses"].rows)
    assert responses == [
        {
            "id": ANY,
            "model": "mock",
            "prompt": "Hi",
            "system": None,
            "prompt_json": None,
            "options_json": '{"max_tokens": 10}',
            "response": "Some text",
            "response_json": None,
            "conversation_id": ANY,
            "duration_ms": ANY,
            "datetime_utc": ANY,
            "input_tokens": 1,
            "output_tokens": 1,
            "token_details": None,
            "schema_id": None,
        }
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
    rows = list(logs_db["responses"].rows_where(select="prompt, response"))
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
    assert sqlite_utils.Database(db_path)["responses"].count == 2


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_chat_tools(logs_db):
    runner = CliRunner()
    functions = textwrap.dedent(
        """
    def upper(text: str) -> str:
        "Convert text to upper case"
        return text.upper()                         
    """
    )
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
    assert result.output == (
        "Chatting with echo\n"
        "Type 'exit' or 'quit' to exit\n"
        "Type '!multi' to enter multiple lines, then '!end' to finish\n"
        "Type '!edit' to open your default editor and modify the prompt\n"
        '> {"prompt": "Convert hello to uppercase", "tool_calls": [{"name": "upper", '
        '"arguments": {"text": "hello"}}]}\n'
        "{\n"
        '  "prompt": "Convert hello to uppercase",\n'
        '  "system": "",\n'
        '  "attachments": [],\n'
        '  "stream": true,\n'
        '  "previous": []\n'
        "}{\n"
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
        '      "tool_call_id": null\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "> quit\n"
    )
