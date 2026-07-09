import json

from click.testing import CliRunner

import llm
from llm.cli import cli


def test_prompt_messages_json_string(mock_model):
    mock_model.enqueue(["Berlin"])
    messages = [
        llm.system("You are a helpful pirate.").to_dict(),
        llm.user("What is the capital of France?").to_dict(),
        llm.assistant("Paris, matey.").to_dict(),
    ]

    result = CliRunner().invoke(
        cli,
        [
            "prompt",
            "-m",
            "mock",
            "--no-stream",
            "--messages",
            json.dumps(messages),
            "And Germany?",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "Berlin\n"
    assert mock_model.history[0][0].messages == [
        llm.system("You are a helpful pirate."),
        llm.user("What is the capital of France?"),
        llm.assistant("Paris, matey."),
        llm.user("And Germany?"),
    ]


def test_prompt_messages_from_file_and_message_options(mock_model, tmp_path):
    mock_model.enqueue(["Summary"])
    messages_path = tmp_path / "messages.json"
    messages_path.write_text(
        json.dumps([llm.user("What happened?").to_dict()]), "utf-8"
    )

    result = CliRunner().invoke(
        cli,
        [
            "prompt",
            "-m",
            "mock",
            "--no-stream",
            "--messages",
            str(messages_path),
            "-M",
            "assistant",
            "Lots happened.",
            "--message",
            "user",
            "Summarize it.",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "Summary\n"
    assert mock_model.history[0][0].messages == [
        llm.user("What happened?"),
        llm.assistant("Lots happened."),
        llm.user("Summarize it."),
    ]


def test_prompt_message_appends_prompt_from_stdin(mock_model):
    mock_model.enqueue(["ok"])

    result = CliRunner().invoke(
        cli,
        [
            "prompt",
            "-m",
            "mock",
            "--no-stream",
            "-M",
            "system",
            "Be concise.",
            "question",
        ],
        input="context",
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "ok\n"
    assert mock_model.history[0][0].messages == [
        llm.system("Be concise."),
        llm.user("context question"),
    ]


def test_prompt_messages_dash_reads_stdin_for_messages_not_prompt(mock_model):
    mock_model.enqueue(["continued"])
    messages = json.dumps([llm.user("Earlier question").to_dict()])

    result = CliRunner().invoke(
        cli,
        [
            "prompt",
            "-m",
            "mock",
            "--no-stream",
            "--messages",
            "-",
            "Now continue",
        ],
        input=messages,
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output == "continued\n"
    assert mock_model.history[0][0].messages == [
        llm.user("Earlier question"),
        llm.user("Now continue"),
    ]


def test_prompt_messages_cannot_use_system_option():
    result = CliRunner().invoke(
        cli,
        [
            "prompt",
            "-m",
            "mock",
            "--messages",
            "[]",
            "-s",
            "Use a system message instead",
        ],
    )

    assert result.exit_code == 1
    assert "--messages/--message cannot be used with -s/--system" in result.output
