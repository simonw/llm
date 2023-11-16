from click.testing import CliRunner
import llm.cli
from unittest.mock import ANY
import pytest


def test_mock_model(mock_model):
    """
    Test the functionality of the mock model.

    Parameters:
    - mock_model: A mock model object for testing.

    This test function simulates interactions with a mock language model.
    It enqueues prompts, retrieves responses, and asserts the expected outcomes.

    """
    mock_model.enqueue(["hello world"])
    mock_model.enqueue(["second"])
    model = llm.get_model("mock")
    response = model.prompt(prompt="hello")
    assert response.text() == "hello world"
    assert str(response) == "hello world"
    assert model.history[0][0].prompt == "hello"
    response2 = model.prompt(prompt="hello again")
    assert response2.text() == "second"


def test_chat_basic(mock_model, logs_db):
    """
    Test the basic chat functionality with a mock model.

    Parameters:
    - mock_model: A mock model object for testing.
    - logs_db: A database object for logging conversations and responses.

    This test function simulates a chat interaction using the llm CLI.
    It enqueues prompts, invokes the CLI with specific inputs, and checks the output and logs.

    """
    runner = CliRunner()
    mock_model.enqueue(["one world"])
    mock_model.enqueue(["one again"])
    result = runner.invoke(
        llm.cli.cli, ["chat", "-m", "mock"], input="Hi\nHi two\nquit\n"
    )
    assert result.exit_code == 0
    assert result.output == (
        "Chatting with mock"
        "\nType 'exit' or 'quit' to exit"
        "\nType '!multi' to enter multiple lines, then '!end' to finish"
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
        },
    ]
    # Now continue that conversation
    mock_model.enqueue(["continued"])
    result2 = runner.invoke(
        llm.cli.cli, ["chat", "-m", "mock", "-c"], input="Continue\nquit\n"
    )
    assert result2.exit_code == 0
    assert result2.output == (
        "Chatting with mock"
        "\nType 'exit' or 'quit' to exit"
        "\nType '!multi' to enter multiple lines, then '!end' to finish"
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
        }
    ]


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
        }
    ]


def test_chat_options(mock_model, logs_db):
    """
    Test the chat functionality with a system message using a mock model.

    Parameters:
    - mock_model: A mock model object for testing.
    - logs_db: A database object for logging conversations and responses.

    This test function simulates a chat interaction with a system message using the llm CLI.
    It enqueues prompts, invokes the CLI with specific inputs, and checks the output and logs.

    """
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
            "duration_ms": 0,
            "datetime_utc": ANY,
        }
    ]


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
    """
    Test the chat functionality with multiple lines using a mock model.

    Parameters:
    - mock_model: A mock model object for testing.
    - logs_db: A database object for logging conversations and responses.
    - input: Input string for the CLI.
    - expected: Expected prompt-response pairs for validation.

    This test function simulates a chat interaction with multiple lines using the llm CLI.
    It enqueues prompts, invokes the CLI with specific inputs, and checks the output and logs.

    """
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
