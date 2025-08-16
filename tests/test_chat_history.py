# tests/test_chat_history.py
import pytest
import sys
import textwrap
from click.testing import CliRunner
from unittest.mock import ANY
import llm.cli
import sqlite_utils
import datetime
from ulid import ULID


# Fixture to pre-populate the logs database with a conversation
@pytest.fixture
def populated_logs_db(user_path):
    """
    Returns a logs_db instance pre-populated with a conversation
    containing 5 message turns, located at user_path/logs.db.
    """
    log_db_path = user_path / "logs.db"
    db = sqlite_utils.Database(str(log_db_path))

    # Ensure migrations are run for the database
    llm.cli.migrate(db)

    # Create a consistent conversation ID for these test messages
    conversation_id = str(ULID()).lower()

    # Insert conversation record
    db["conversations"].insert({
        "id": conversation_id,
        "name": "Pre-populated Chat History",
        "model": "mock",
    }, pk="id")

    prompts = [f"Prompt {i}" for i in range(1, 6)]
    responses_text = [f"Response {i}" for i in range(1, 6)]

    # Populate responses table with a history of 5 turns
    # Ensure timestamps are unique and chronologically ordered for consistent history loading
    for i in range(5):
        # Using ULID.from_datetime for consistent, ordered IDs and timestamps
        timestamp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=i)
        response_ulid = ULID.from_datetime(timestamp)

        db["responses"].insert({
            "id": str(response_ulid).lower(),
            "model": "mock",
            "resolved_model": None,
            "prompt": prompts[i],
            "system": None,
            "prompt_json": None,
            "options_json": "{}",
            "response": responses_text[i],
            "response_json": None,
            "conversation_id": conversation_id,
            "duration_ms": 100,
            "datetime_utc": timestamp.isoformat(timespec='microseconds'), # Ensure high precision for ordering
            "input_tokens": len(prompts[i].split()),
            "output_tokens": len(responses_text[i].split()),
            "token_details": None,
            "schema_id": None,
        }, pk="id")

    return db, conversation_id # Return the db instance and the conversation_id


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_chat_continue_with_bare_l(mock_model, populated_logs_db):
    runner = CliRunner()
    db, conversation_id = populated_logs_db # Get the pre-populated db and conversation_id

    mock_model.enqueue(["New Response"]) # Response for the new prompt

    result = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "mock", "-c", "-l"], # -l defaults to 2 messages
        input="New Prompt\nquit\n",
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    output_lines = result.output.splitlines()

    # Check for history header
    assert "--- Conversation History (Last 2 messages) ---" in output_lines

    # Check that the last two turns are displayed
    assert "User:" in output_lines # Check for the label itself
    assert "Prompt 4" in output_lines
    assert "AI:" in output_lines # Check for the label itself
    assert "Response 4" in output_lines
    assert "Prompt 5" in output_lines
    assert "Response 5" in output_lines

    # Ensure older messages are NOT in history
    assert "Prompt 1" not in output_lines
    assert "Prompt 2" not in output_lines
    assert "Prompt 3" not in output_lines

    # Check for history footer
    assert "--- End History ---" in output_lines

    # Ensure the new prompt and response are also present
    assert "> New Prompt" in output_lines
    assert "New Response" in output_lines

    # Verify order: Prompt 4, Response 4, Prompt 5, Response 5
    # Find indices of the specific content lines
    index_prompt4_line = output_lines.index("Prompt 4")
    index_response4_line = output_lines.index("Response 4")
    index_prompt5_line = output_lines.index("Prompt 5")
    index_response5_line = output_lines.index("Response 5")

    assert index_prompt4_line < index_response4_line < index_prompt5_line < index_response5_line


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_chat_continue_with_l_set_to_1(mock_model, populated_logs_db):
    runner = CliRunner()
    db, conversation_id = populated_logs_db # Get the pre-populated db and conversation_id

    mock_model.enqueue(["New Response"]) # Response for the new prompt

    result = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "mock", "-c", "-l", "1"],
        input="New Prompt\nquit\n",
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    output_lines = result.output.splitlines()

    assert "--- Conversation History (Last 1 messages) ---" in output_lines
    # Only the last turn should be in history
    assert "User:" in output_lines
    assert "Prompt 5" in output_lines
    assert "AI:" in output_lines
    assert "Response 5" in output_lines

    # Ensure older messages are NOT in history
    assert "Prompt 4" not in output_lines
    assert "Prompt 3" not in output_lines
    assert "Prompt 2" not in output_lines
    assert "Prompt 1" not in output_lines

    assert "--- End History ---" in output_lines

    assert "> New Prompt" in output_lines
    assert "New Response" in output_lines


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_chat_continue_with_l_set_to_3(mock_model, populated_logs_db):
    runner = CliRunner()
    db, conversation_id = populated_logs_db # Get the pre-populated db and conversation_id

    mock_model.enqueue(["New Response"]) # Response for the new prompt

    result = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "mock", "-c", "-l", "3"],
        input="New Prompt\nquit\n",
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    output_lines = result.output.splitlines()

    assert "--- Conversation History (Last 3 messages) ---" in output_lines
    # Check that the last three turns are displayed
    assert "User:" in output_lines
    assert "Prompt 3" in output_lines
    assert "AI:" in output_lines
    assert "Response 3" in output_lines
    assert "Prompt 4" in output_lines
    assert "Response 4" in output_lines
    assert "Prompt 5" in output_lines
    assert "Response 5" in output_lines

    # Ensure older messages are NOT in history
    assert "Prompt 1" not in output_lines
    assert "Prompt 2" not in output_lines

    assert "--- End History ---" in output_lines

    # Verify order
    index_prompt3_line = output_lines.index("Prompt 3")
    index_prompt4_line = output_lines.index("Prompt 4")
    index_prompt5_line = output_lines.index("Prompt 5")

    assert index_prompt3_line < index_prompt4_line < index_prompt5_line

    assert "> New Prompt" in output_lines
    assert "New Response" in output_lines


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_chat_l_without_c_is_ignored(mock_model, populated_logs_db):
    runner = CliRunner()
    db, original_conversation_id = populated_logs_db # Get the pre-populated db and conversation_id

    mock_model.enqueue(["New Chat Response"]) # Response for the new prompt

    result = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "mock", "-l", "1"], # -l specified, but -c omitted
        input="New Prompt\nquit\n",
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    output_lines = result.output.splitlines()

    # History header should NOT be present because -c was not used
    assert "--- Conversation History" not in result.output
    assert "--- End History ---" not in result.output

    # The new prompt and response should be present
    assert "> New Prompt" in output_lines
    assert "New Chat Response" in output_lines

    # Old conversation messages from the pre-populated DB should not be displayed
    assert "Prompt 5" not in output_lines
    assert "Response 5" not in output_lines

    # Verify that a new conversation was started in the logs
    # We expect 2 conversations: the original populated one, and the new one.
    conversations = list(db["conversations"].rows)
    assert len(conversations) == 2

    # Get the ID of the newly created conversation
    new_conversation_id = None
    for convo in conversations:
        if convo["id"] != original_conversation_id:
            new_conversation_id = convo["id"]
            break
    assert new_conversation_id is not None

    # Verify the last logged response belongs to the new conversation
    responses = list(db["responses"].rows)
    assert responses[-1]["prompt"] == "New Prompt"
    assert responses[-1]["conversation_id"] == new_conversation_id
    assert responses[-1]["conversation_id"] != original_conversation_id


