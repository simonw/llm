"""Tests for llm.message_store - content-addressed structured message
storage in the logs database."""

import hashlib
import json
import os
import re
import textwrap

import pytest
import sqlite_utils
from click.testing import CliRunner

import llm
from llm import message_store
from llm.cli import cli, load_conversation
from llm.migrations import migrate
from llm.parts import (
    AttachmentPart,
    Message,
    ReasoningPart,
    StreamEvent,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)

TINY_PNG = b"\x89PNG\r\n\x1a\n fake png bytes for tests"


@pytest.fixture
def db():
    return sqlite_utils.Database(memory=True)


class TestHashing:
    def test_message_hash_matches_documented_algorithm(self):
        message = llm.user("hello")
        expected = hashlib.sha256(
            json.dumps(
                {"parts": [{"text": "hello", "type": "text"}], "role": "user"},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        assert message_store.message_hash(message) == expected

    def test_equal_content_hashes_equal(self):
        assert message_store.message_hash(llm.user("hi")) == message_store.message_hash(
            Message(role="user", parts=[TextPart(text="hi")])
        )
        assert message_store.message_hash(llm.user("hi")) != message_store.message_hash(
            llm.user("ho")
        )
        assert message_store.message_hash(llm.user("hi")) != message_store.message_hash(
            llm.assistant("hi")
        )

    def test_attachments_hash_by_reference(self):
        # Two attachment objects with the same content produce the same
        # message hash, because the stored form references the
        # content-addressed attachment id rather than embedding bytes
        message_a = llm.user("look", llm.Attachment(content=TINY_PNG))
        message_b = llm.user("look", llm.Attachment(type="image/png", content=TINY_PNG))
        assert message_store.message_hash(message_a) == message_store.message_hash(
            message_b
        )

    def test_node_hash_matches_documented_algorithm(self):
        message_id = message_store.message_hash(llm.user("hi"))
        root = hashlib.sha256(":{}".format(message_id).encode("utf-8")).hexdigest()
        assert message_store.node_hash(None, message_id) == root
        assert (
            message_store.node_hash(root, message_id)
            == hashlib.sha256(
                "{}:{}".format(root, message_id).encode("utf-8")
            ).hexdigest()
        )


class TestStoreAndLoad:
    def messages(self):
        return [
            llm.system("be brief"),
            Message(
                role="user",
                parts=[
                    TextPart(text="describe this"),
                    AttachmentPart(
                        attachment=llm.Attachment(type="image/png", content=TINY_PNG)
                    ),
                ],
            ),
            Message(
                role="assistant",
                parts=[
                    ReasoningPart(
                        text="pondering",
                        provider_metadata={"signature": "sig-123"},
                    ),
                    TextPart(text="calling a tool"),
                    ToolCallPart(
                        name="lookup",
                        arguments={"q": "x"},
                        tool_call_id="tc_1",
                    ),
                ],
                provider_metadata={"message_level": True},
            ),
            Message(
                role="tool",
                parts=[
                    ToolResultPart(
                        name="lookup",
                        output="42",
                        tool_call_id="tc_1",
                        attachments=[
                            llm.Attachment(type="image/png", content=TINY_PNG)
                        ],
                    )
                ],
            ),
        ]

    def test_round_trip(self, db):
        messages = self.messages()
        node_id = message_store.store_messages(db, messages)
        loaded = message_store.load_messages(db, node_id)
        assert [message_store.message_hash(m) for m in loaded] == [
            message_store.message_hash(m) for m in messages
        ]
        # Structured details survive intact
        assert loaded[2].parts[0] == ReasoningPart(
            text="pondering", provider_metadata={"signature": "sig-123"}
        )
        assert loaded[2].provider_metadata == {"message_level": True}
        assert loaded[2].parts[2] == ToolCallPart(
            name="lookup", arguments={"q": "x"}, tool_call_id="tc_1"
        )
        # Attachments come back with their binary content
        assert loaded[1].parts[1].attachment.content == TINY_PNG
        assert loaded[3].parts[0].attachments[0].content == TINY_PNG
        # The identical attachment used twice is stored once
        assert db["attachments"].count == 1

    def test_store_is_idempotent(self, db):
        messages = self.messages()
        first = message_store.store_messages(db, messages)
        counts = (db["messages"].count, db["message_nodes"].count)
        second = message_store.store_messages(db, messages)
        assert first == second
        assert (db["messages"].count, db["message_nodes"].count) == counts

    def test_shared_prefixes_share_rows(self, db):
        prefix = [llm.user("a"), llm.assistant("b")]
        message_store.store_messages(db, prefix + [llm.user("c")])
        assert db["messages"].count == 3
        assert db["message_nodes"].count == 3
        # A second chain sharing the two-message prefix adds one of each
        message_store.store_messages(db, prefix + [llm.user("d")])
        assert db["messages"].count == 4
        assert db["message_nodes"].count == 4
        # The same message content in a different position is a new
        # node but not a new message row
        message_store.store_messages(db, prefix + [llm.user("c"), llm.user("d")])
        assert db["messages"].count == 4
        assert db["message_nodes"].count == 5

    def test_extend_existing_chain(self, db):
        head = message_store.store_messages(db, [llm.user("a")])
        extended = message_store.store_messages(
            db, [llm.assistant("b")], parent_node_id=head
        )
        assert message_store.load_messages(db, extended) == [
            Message(role="user", parts=[TextPart(text="a")]),
            Message(role="assistant", parts=[TextPart(text="b")]),
        ]
        assert db["message_nodes"].get(extended)["depth"] == 2

    def test_store_empty_returns_parent(self, db):
        assert message_store.store_messages(db, []) is None
        head = message_store.store_messages(db, [llm.user("a")])
        assert message_store.store_messages(db, [], parent_node_id=head) == head

    def test_load_unknown_node_raises(self, db):
        message_store.ensure_tables(db)
        with pytest.raises(ValueError):
            message_store.load_messages(db, "no-such-node")


class TestResponseLogging:
    def reasoning_events(self, text="hello"):
        return [
            StreamEvent(
                type="reasoning",
                chunk="thinking hard",
                provider_metadata={"signature": "sig-xyz"},
            ),
            StreamEvent(type="text", chunk=text),
        ]

    def test_log_to_db_writes_message_store(self, logs_db, mock_model):
        migrate(logs_db)
        mock_model.enqueue(self.reasoning_events())
        response = mock_model.prompt("hi")
        response.text()
        response.log_to_db(logs_db)
        node_row = logs_db["response_nodes"].get(response.id)
        input_messages = message_store.load_messages(logs_db, node_row["input_node_id"])
        assert input_messages == [Message(role="user", parts=[TextPart(text="hi")])]
        full_chain = message_store.load_messages(logs_db, node_row["output_node_id"])
        assert full_chain[len(input_messages) :] == [
            Message(
                role="assistant",
                parts=[
                    ReasoningPart(
                        text="thinking hard",
                        provider_metadata={"signature": "sig-xyz"},
                    ),
                    TextPart(text="hello"),
                ],
            )
        ]
        # Legacy columns are still fully populated
        row = logs_db["responses"].get(response.id)
        assert row["response"] == "hello"
        assert row["reasoning"] == "thinking hard"

    def test_conversation_turns_share_prefix_nodes(self, logs_db, mock_model):
        migrate(logs_db)
        conversation = mock_model.conversation()
        mock_model.enqueue(self.reasoning_events("one"))
        response1 = conversation.prompt("first")
        response1.text()
        response1.log_to_db(logs_db)
        mock_model.enqueue(["two"])
        response2 = conversation.prompt("second")
        response2.text()
        response2.log_to_db(logs_db)
        # Unique messages: user-first, assistant-one, user-second,
        # assistant-two. The second turn's input chain reuses the first
        # turn's nodes rather than duplicating them.
        assert logs_db["messages"].count == 4
        assert logs_db["message_nodes"].count == 4
        node1 = logs_db["response_nodes"].get(response1.id)
        node2 = logs_db["response_nodes"].get(response2.id)
        chain2 = message_store.load_messages(logs_db, node2["input_node_id"])
        assert len(chain2) == 3
        # response2's input chain passes through response1's output node
        assert node1["output_node_id"] != node2["input_node_id"]
        full_chain2 = message_store.load_messages(logs_db, node2["output_node_id"])
        assert len(full_chain2) == 4

    def test_load_response_round_trips_reasoning(self, logs_db, mock_model):
        migrate(logs_db)
        mock_model.enqueue(self.reasoning_events())
        response = mock_model.prompt("hi")
        response.text()
        response.log_to_db(logs_db)
        loaded = message_store.load_response(logs_db, response.id)
        assert loaded.text() == "hello"
        assert loaded.messages() == response.messages()
        assert loaded.messages()[0].parts[0] == ReasoningPart(
            text="thinking hard", provider_metadata={"signature": "sig-xyz"}
        )
        assert loaded.prompt.messages == [
            Message(role="user", parts=[TextPart(text="hi")])
        ]

    def test_load_conversation_hydrates_from_message_store(self, logs_db, mock_model):
        migrate(logs_db)
        conversation = mock_model.conversation()
        mock_model.enqueue(self.reasoning_events("one"))
        response1 = conversation.prompt("first")
        response1.text()
        response1.log_to_db(logs_db)
        mock_model.enqueue(["two"])
        response2 = conversation.prompt("second")
        response2.text()
        response2.log_to_db(logs_db)

        loaded = load_conversation(conversation.id)
        assert len(loaded.responses) == 2
        # Reasoning parts and provider_metadata survive, unlike the
        # legacy from_row() text reconstruction
        first_messages = loaded.responses[0]._messages_now()
        assert first_messages[0].parts[0] == ReasoningPart(
            text="thinking hard", provider_metadata={"signature": "sig-xyz"}
        )
        # The second response's input chain is the exact recorded chain
        assert loaded.responses[1].prompt.messages == response2.prompt.messages

    def test_load_conversation_mixed_old_and_new_rows(self, logs_db, mock_model):
        migrate(logs_db)
        conversation = mock_model.conversation()
        mock_model.enqueue(self.reasoning_events("one"))
        response1 = conversation.prompt("first")
        response1.text()
        response1.log_to_db(logs_db)
        mock_model.enqueue(["two"])
        response2 = conversation.prompt("second")
        response2.text()
        response2.log_to_db(logs_db)
        # Simulate response1 having been logged before the message
        # store existed
        logs_db["response_nodes"].delete(response1.id)

        loaded = load_conversation(conversation.id)
        assert len(loaded.responses) == 2
        # response1 falls back to the legacy reconstruction: text
        # survives, reasoning structure does not
        assert loaded.responses[0].text() == "one"
        # response2 still rehydrates at full fidelity
        second_input = loaded.responses[1].prompt.messages
        assert second_input == response2.prompt.messages
        assert second_input[1].parts[0] == ReasoningPart(
            text="thinking hard", provider_metadata={"signature": "sig-xyz"}
        )

    def test_empty_output_response(self, logs_db, mock_model):
        migrate(logs_db)
        mock_model.enqueue([])
        response = mock_model.prompt("hi")
        response.text()
        response.log_to_db(logs_db)
        node_row = logs_db["response_nodes"].get(response.id)
        assert node_row["output_node_id"] == node_row["input_node_id"]
        loaded = message_store.load_response(logs_db, response.id)
        assert loaded.messages() == []

    def test_log_response_public_api_on_fresh_database(self, mock_model, tmpdir):
        db = sqlite_utils.Database(str(tmpdir / "fresh.db"))
        mock_model.enqueue(self.reasoning_events())
        response = mock_model.prompt("hi")
        response.text()
        response_id = message_store.log_response(db, response)
        assert response_id == response.id
        # Full dual-write: legacy row plus structured messages
        assert db["responses"].get(response.id)["response"] == "hello"
        loaded = message_store.load_response(db, response.id)
        assert loaded.messages() == response.messages()


class TestAsyncFidelity:
    @pytest.mark.asyncio
    async def test_to_sync_response_preserves_parts(self, async_mock_model):
        async_mock_model.enqueue(
            [
                StreamEvent(
                    type="reasoning",
                    chunk="deep thought",
                    provider_metadata={"signature": "async-sig"},
                ),
                StreamEvent(type="text", chunk="hi there"),
            ]
        )
        response = await async_mock_model.prompt("hello")
        await response.text()
        sync_response = await response.to_sync_response()
        messages = sync_response._messages_now()
        assert messages[0].parts[0] == ReasoningPart(
            text="deep thought", provider_metadata={"signature": "async-sig"}
        )

    @pytest.mark.asyncio
    async def test_async_response_logs_full_fidelity(self, async_mock_model, logs_db):
        migrate(logs_db)
        async_mock_model.enqueue(
            [
                StreamEvent(
                    type="reasoning",
                    chunk="deep thought",
                    provider_metadata={"signature": "async-sig"},
                ),
                StreamEvent(type="text", chunk="hi there"),
            ]
        )
        response = await async_mock_model.prompt("hello")
        await response.text()
        sync_response = await response.to_sync_response()
        sync_response.log_to_db(logs_db)
        # The reasoning column now captures async reasoning too
        row = logs_db["responses"].get(sync_response.id)
        assert row["reasoning"] == "deep thought"
        loaded = message_store.load_response(logs_db, sync_response.id)
        assert loaded.messages()[0].parts[0] == ReasoningPart(
            text="deep thought", provider_metadata={"signature": "async-sig"}
        )


class TestLogFormats:
    def tool_chain(self):
        def multiply(a: int, b: int) -> int:
            "Multiply two numbers."
            return a * b

        model = llm.get_model("echo")
        chain = model.chain(
            json.dumps(
                {"tool_calls": [{"name": "multiply", "arguments": {"a": 3, "b": 4}}]}
            ),
            tools=[multiply],
        )
        chain.text()
        return chain

    def test_fresh_database_is_efficient(self, logs_db):
        migrate(logs_db)
        assert message_store.get_log_format(logs_db) == "efficient"

    def test_database_with_history_gets_dual(self, logs_db, mock_model):
        migrate(logs_db)
        mock_model.enqueue(["hi"])
        response = mock_model.prompt("x")
        response.text()
        response.log_to_db(logs_db)
        # Simulate a database that predates the log_format migration
        logs_db["logs_settings"].delete_where()
        logs_db["_llm_migrations"].delete_where("name = ?", ["m024_log_format"])
        migrate(logs_db)
        assert message_store.get_log_format(logs_db) == "dual"

    def test_set_log_format_validates(self, logs_db):
        migrate(logs_db)
        message_store.set_log_format(logs_db, "dual")
        assert message_store.get_log_format(logs_db) == "dual"
        with pytest.raises(ValueError):
            message_store.set_log_format(logs_db, "nope")

    def test_efficient_format_skips_duplicated_payloads(self, logs_db):
        migrate(logs_db)
        self.tool_chain().log_to_db(logs_db)
        rows = list(logs_db["responses"].rows)
        assert len(rows) == 2
        assert all(row["prompt_json"] is None for row in rows)
        tool_calls = list(logs_db["tool_calls"].rows)
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "multiply"
        assert tool_calls[0]["arguments"] is None
        tool_results = list(logs_db["tool_results"].rows)
        assert len(tool_results) == 1
        assert tool_results[0]["output"] is None
        assert tool_results[0]["tool_call_id"] == tool_calls[0]["tool_call_id"]

    def test_dual_format_still_writes_payloads(self, logs_db):
        migrate(logs_db)
        message_store.set_log_format(logs_db, "dual")
        self.tool_chain().log_to_db(logs_db)
        tool_calls = list(logs_db["tool_calls"].rows)
        assert json.loads(tool_calls[0]["arguments"]) == {"a": 3, "b": 4}
        tool_results = list(logs_db["tool_results"].rows)
        assert tool_results[0]["output"] == "12"
        # prompt_json is dropped in both formats
        assert all(row["prompt_json"] is None for row in logs_db["responses"].rows)

    def test_efficient_rows_hydrate_full_fidelity(self, logs_db):
        migrate(logs_db)
        self.tool_chain().log_to_db(logs_db)
        conversation_id = next(logs_db["responses"].rows)["conversation_id"]
        loaded = load_conversation(conversation_id)
        first, second = loaded.responses
        assert first.tool_calls()[0].arguments == {"a": 3, "b": 4}
        assert second.prompt.tool_results[0].output == "12"

    def _run_and_render_logs(self, user_path, format):
        db_path = str(user_path / "logs.db")
        if os.path.exists(db_path):
            os.remove(db_path)
        db = sqlite_utils.Database(db_path)
        migrate(db)
        message_store.set_log_format(db, format)
        runner = CliRunner()
        code = textwrap.dedent("""
            def demo():
                return "one\\ntwo\\nthree"
            """)
        result = runner.invoke(
            cli,
            [
                "-m",
                "echo",
                "--functions",
                code,
                json.dumps({"tool_calls": [{"name": "demo"}]}),
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        logs_result = runner.invoke(cli, ["logs", "-n", "0"], catch_exceptions=False)
        assert logs_result.exit_code == 0
        # Normalize ULIDs and timestamps, which differ between runs
        output = re.sub(r"[0-9a-z]{26}", "ULID", logs_result.output)
        return re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "DATETIME", output)

    def test_logs_render_identical_across_formats(self, user_path):
        efficient = self._run_and_render_logs(user_path, "efficient")
        dual = self._run_and_render_logs(user_path, "dual")
        assert "### Tool results" in efficient
        assert efficient == dual

    def test_logs_format_command(self, user_path):
        runner = CliRunner()
        assert runner.invoke(cli, ["-m", "echo", "hi"]).exit_code == 0
        result = runner.invoke(cli, ["logs", "format"])
        assert result.output.strip() == "efficient"
        result2 = runner.invoke(cli, ["logs", "format", "dual"])
        assert result2.exit_code == 0
        assert "dual" in result2.output
        assert runner.invoke(cli, ["logs", "format"]).output.strip() == "dual"
        status_output = runner.invoke(cli, ["logs", "status"]).output
        assert "Log format: dual" in status_output
