import sqlite3

import click
import pytest
from click.testing import CliRunner

from llm.cli import cli, load_conversation


@pytest.fixture
def opened_connections(monkeypatch):
    """Keep connections alive so closure checks do not depend on garbage collection."""
    connections = []
    original_connect = sqlite3.connect

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    yield connections
    for connection in connections:
        connection.close()


def assert_connections_closed(connections):
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("select 1")


@pytest.mark.parametrize(
    "args, input_, exit_code",
    [
        (["prompt", "hello", "-m", "mock"], None, 0),
        (["prompt", "hello", "-m", "mock", "-n", "--json"], None, 0),
        (["prompt", "hello", "-m", "mock", "--schema", "missing-schema"], None, 2),
        (["chat", "-m", "mock"], "hello\nquit\n", 0),
        (["logs", "list"], None, 0),
        (["logs", "status"], None, 0),
        (["schemas", "list"], None, 0),
        (["fragments", "list"], None, 0),
        (["embed", "test", "1", "-m", "embed-demo", "-c", "hello"], None, 0),
        (["embed", "test", "1", "-m", "embed-demo", "-c", ""], "", 1),
        (
            [
                "openai",
                "endpoint",
                "https://example.com/v1",
                "hello",
                "-m",
                "test",
                "--schema",
                "missing-schema",
            ],
            None,
            2,
        ),
    ],
)
def test_cli_closes_connections(
    mock_model, opened_connections, args, input_, exit_code
):
    runner = CliRunner()
    mock_model.enqueue(["hello"])
    # Seed logs so read-only commands also open their database.
    assert runner.invoke(cli, ["prompt", "seed", "-m", "mock"]).exit_code == 0
    assert_connections_closed(opened_connections)
    opened_connections.clear()
    mock_model.enqueue(["hello"])
    result = runner.invoke(cli, args, input=input_)
    assert result.exit_code == exit_code, result.output
    assert_connections_closed(opened_connections)


@pytest.mark.parametrize("conversation_id", [None, "missing"])
def test_load_conversation_closes_connection_on_empty_or_missing(
    opened_connections, conversation_id
):
    if conversation_id is None:
        assert load_conversation(None) is None
    else:
        with pytest.raises(click.ClickException, match="No conversation found"):
            load_conversation(conversation_id)
    assert_connections_closed(opened_connections)


def test_loaded_conversation_survives_closed_connection(mock_model, opened_connections):
    mock_model.enqueue(["first reply"])
    result = CliRunner().invoke(cli, ["prompt", "first question", "-m", "mock"])
    assert result.exit_code == 0
    conversation = load_conversation(None)
    assert_connections_closed(opened_connections)
    assert conversation.loaded_messages[0].parts[0].text == "first question"
    mock_model.enqueue(["second reply"])
    assert conversation.prompt("follow up").text() == "second reply"
