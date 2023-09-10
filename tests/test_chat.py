from click.testing import CliRunner
import llm.cli
from unittest.mock import ANY


def test_mock_model(mock_model):
    mock_model.enqueue(["hello world"])
    mock_model.enqueue(["second"])
    model = llm.get_model("mock")
    response = model.prompt(prompt="hello")
    assert response.text() == "hello world"
    assert model.history[0][0].prompt == "hello"
    response2 = model.prompt(prompt="hello again")
    assert response2.text() == "second"


def test_chat_basic(mock_model, logs_db):
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
