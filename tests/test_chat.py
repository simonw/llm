from click.testing import CliRunner
from unittest.mock import ANY
import json
import llm.cli
import pytest
import sqlite_utils
import sys
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
        "\nType '!fragment <my_fragment> [<another_fragment> ...]' to insert one or more fragments"
        "\nType !tool <my_tool> to add a tool to the conversation"
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
        "\nType '!fragment <my_fragment> [<another_fragment> ...]' to insert one or more fragments"
        "\nType !tool <my_tool> to add a tool to the conversation"
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
        "\nType '!fragment <my_fragment> [<another_fragment> ...]' to insert one or more fragments"
        "\nType !tool <my_tool> to add a tool to the conversation"
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
    responses = list(logs_db["responses"].rows)
    assert responses == [
        {
            "id": ANY,
            "model": "mock",
            "prompt": "Hi",
            "system": None,
            "prompt_json": None,
            "options_json": '{"max_tokens": 5}',
            "response": "Default options response",
            "response_json": None,
            "conversation_id": ANY,
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
            "prompt": "Hi with override",
            "system": None,
            "prompt_json": None,
            "options_json": '{"max_tokens": 10}',
            "response": "Override options response",
            "response_json": None,
            "conversation_id": ANY,
            "duration_ms": ANY,
            "datetime_utc": ANY,
            "input_tokens": 3,
            "output_tokens": 1,
            "token_details": None,
            "schema_id": None,
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
        "Type '!fragment <my_fragment> [<another_fragment> ...]' to insert one or more fragments\n"
        "Type !tool <my_tool> to add a tool to the conversation\n"
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
        input=("hi\n!fragment {}\nquit\n".format(path2)),
    ).output
    assert '"prompt": "one' in output
    assert '"prompt": "two"' in output


def test_process_tools_in_chat():
    """Test process_tools_in_chat function"""
    # Test with no tools
    prompt, tools = llm.cli.process_tools_in_chat("Hello world")
    assert prompt == "Hello world"
    assert tools == []
    
    # Test with single tool
    prompt, tools = llm.cli.process_tools_in_chat("!tool calculator\nCalculate 2+2")
    assert prompt == "Calculate 2+2"
    assert tools == ["calculator"]
    
    # Test with multiple tools
    prompt, tools = llm.cli.process_tools_in_chat("!tool calc\n!tool time\nDo something")
    assert prompt == "Do something"
    assert tools == ["calc", "time"]
    
    # Test with tool at end
    prompt, tools = llm.cli.process_tools_in_chat("Calculate this\n!tool calculator")
    assert prompt == "Calculate this"
    assert tools == ["calculator"]
    
    # Test with only tool commands
    prompt, tools = llm.cli.process_tools_in_chat("!tool calc\n!tool time")
    assert prompt == ""
    assert tools == ["calc", "time"]


def test_process_fragments_in_chat(tmpdir):
    """Test process_fragments_in_chat function"""
    # Create test database with proper schema
    db_path = tmpdir / "test.db"
    db = sqlite_utils.Database(str(db_path))
    
    # Create tables with proper schema
    db.executescript("""
        CREATE TABLE fragments (
            id INTEGER PRIMARY KEY,
            hash TEXT,
            content TEXT,
            datetime_utc TEXT,
            source TEXT
        );
        CREATE TABLE fragment_aliases (
            alias TEXT PRIMARY KEY,
            fragment_id INTEGER,
            FOREIGN KEY (fragment_id) REFERENCES fragments(id)
        );
        INSERT INTO fragments (hash, content, datetime_utc, source) VALUES ('test_hash', 'Fragment content', '2023-01-01T00:00:00Z', 'test_source');
        INSERT INTO fragment_aliases (alias, fragment_id) VALUES ('test_frag', 1);
    """)
    
    # Test with no fragments
    prompt, fragments, attachments = llm.cli.process_fragments_in_chat(db, "Hello world")
    assert prompt == "Hello world"
    assert fragments == []
    assert attachments == []
    
    # Test with single fragment
    prompt, fragments, attachments = llm.cli.process_fragments_in_chat(db, "!fragment test_frag\nHello")
    assert prompt == "Hello"
    assert len(fragments) == 1
    assert str(fragments[0]) == "Fragment content"
    assert fragments[0].source == "test_source"
    
    # Test with invalid fragment (should raise ClickException)
    with pytest.raises(Exception):  # FragmentNotFound wrapped in ClickException
        llm.cli.process_fragments_in_chat(db, "!fragment nonexistent\nHello")


def test_update_tools():
    """Test update_tools function"""
    class MockTool:
        def __init__(self, name):
            self.name = name
    
    # Test with empty current tools
    current = []
    new = [MockTool("calc"), MockTool("time")]
    result = llm.cli.update_tools(current, new)
    assert len(result) == 2
    assert result[0].name == "calc"
    assert result[1].name == "time"
    
    # Test with overlapping tools (should deduplicate)
    current = [MockTool("calc"), MockTool("search")]
    new = [MockTool("calc"), MockTool("time")]
    result = llm.cli.update_tools(current, new)
    assert len(result) == 3
    tool_names = [t.name for t in result]
    assert "search" in tool_names  # kept from current
    assert "calc" in tool_names    # replaced by new
    assert "time" in tool_names    # added from new
    
    # Test with no new tools
    current = [MockTool("calc")]
    new = []
    result = llm.cli.update_tools(current, new)
    assert len(result) == 1
    assert result[0].name == "calc"


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_chat_tool_command():
    """Test !tool command integration in chat"""
    runner = CliRunner()
    # Test that !tool command is processed and removed from prompt
    result = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "echo"],
        input="!tool nonexistent_tool\nHello world\nquit\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    # Should show warning about tool not found
    assert "Warning:" in result.output
    assert "not found" in result.output
    # The prompt should be processed without the !tool line
    assert '"prompt": "Hello world"' in result.output
