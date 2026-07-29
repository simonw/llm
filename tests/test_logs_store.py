"""Tests for llm.logs — the content-addressed message store.

The store keeps conversations as a parent-linked tree of messages, each
identified by a hash over its own content plus its parent's hash. Shared
prefixes are stored once, so forking a conversation and re-sending a
history from a stateless client both write only what is new.
"""

import json
import sqlite3

import pytest
import sqlite_utils
from click.testing import CliRunner

import llm
from llm.cli import cli
from llm.logs import (
    LogStore,
    canonical_json,
    log_row_extras,
    merged_log_rows,
    message_hash,
)
from llm.migrations import migrate
from llm.models import Attachment
from llm.parts import (
    AttachmentPart,
    Message,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from llm.utils import ensure_fragment

NEW_TABLES = {
    "messages",
    "parts",
    "part_attachments",
    "part_fragments",
    "turns",
    "turn_tools",
    "turn_fragments",
    "threads",
}

# Tables the pre-existing logging path writes to. The new store must
# leave every one of them alone, so old logs stay readable without a
# backfill.
LEGACY_TABLES = {
    "conversations",
    "responses",
    "attachments",
    "prompt_attachments",
    "fragments",
    "tools",
    "tool_calls",
    "tool_results",
}


@pytest.fixture
def store():
    return LogStore(sqlite_utils.Database(memory=True))


# ---- canonical form + hashing ----------------------------------------


class TestCanonicalJson:
    def test_key_order_does_not_matter(self):
        assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})

    def test_is_compact(self):
        assert canonical_json({"a": 1, "b": 2}) == '{"a":1,"b":2}'

    def test_non_ascii_is_not_escaped(self):
        assert canonical_json({"a": "é"}) == '{"a":"é"}'

    def test_nested_keys_are_sorted(self):
        assert canonical_json({"a": {"z": 1, "y": 2}}) == '{"a":{"y":2,"z":1}}'


class TestMessageHash:
    def test_is_deterministic(self):
        message = llm.user("Hello")
        assert message_hash(message, None) == message_hash(message, None)

    def test_carries_algorithm_prefix(self):
        assert message_hash(llm.user("Hello"), None).startswith("b2:")

    def test_equal_content_hashes_equal(self):
        assert message_hash(llm.user("Hello"), None) == message_hash(
            llm.user("Hello"), None
        )

    def test_different_text_hashes_differently(self):
        assert message_hash(llm.user("Hello"), None) != message_hash(
            llm.user("Goodbye"), None
        )

    def test_role_participates(self):
        assert message_hash(llm.user("Hello"), None) != message_hash(
            llm.assistant("Hello"), None
        )

    def test_parent_participates(self):
        message = llm.user("Hello")
        root = message_hash(message, None)
        assert message_hash(message, root) != root

    def test_part_order_participates(self):
        one = Message(role="user", parts=[TextPart(text="a"), TextPart(text="b")])
        two = Message(role="user", parts=[TextPart(text="b"), TextPart(text="a")])
        assert message_hash(one, None) != message_hash(two, None)

    def test_provider_metadata_participates(self):
        plain = Message(role="assistant", parts=[TextPart(text="Hi")])
        with_meta = Message(
            role="assistant",
            parts=[TextPart(text="Hi", provider_metadata={"openai": {"id": "rs_1"}})],
        )
        assert message_hash(plain, None) != message_hash(with_meta, None)

    def test_provider_metadata_key_order_does_not_matter(self):
        one = Message(
            role="assistant",
            parts=[TextPart(text="Hi", provider_metadata={"a": 1, "b": 2})],
        )
        two = Message(
            role="assistant",
            parts=[TextPart(text="Hi", provider_metadata={"b": 2, "a": 1})],
        )
        assert message_hash(one, None) == message_hash(two, None)

    def test_redacted_reasoning_differs_from_empty_reasoning(self):
        redacted = Message(role="assistant", parts=[ReasoningPart(redacted=True)])
        empty = Message(role="assistant", parts=[ReasoningPart()])
        assert message_hash(redacted, None) != message_hash(empty, None)


# ---- schema ----------------------------------------------------------


class TestSchema:
    def test_creates_new_tables(self, store):
        assert NEW_TABLES <= set(store.db.table_names())

    def test_leaves_legacy_tables_in_place(self, store):
        assert LEGACY_TABLES <= set(store.db.table_names())

    def test_migrating_twice_is_a_noop(self, store):
        before = store.db.schema
        LogStore(store.db)
        assert store.db.schema == before

    def test_messages_are_keyed_by_hash(self, store):
        assert store.db["messages"].pks == ["hash"]

    def test_parts_are_ordered_within_a_message(self, store):
        indexes = {tuple(index.columns) for index in store.db["parts"].indexes}
        assert ("message_hash", "position") in indexes


# ---- chain round-trip ------------------------------------------------


def round_trip(store, messages):
    "Write a chain, read it straight back."
    return store.load_chain(store.ensure_chain(messages))


class TestChainRoundTrip:
    def test_empty_chain_has_no_tip(self, store):
        assert store.ensure_chain([]) is None

    def test_load_chain_of_none_is_empty(self, store):
        assert store.load_chain(None) == []

    def test_tip_is_the_hash_of_the_last_message(self, store):
        messages = [llm.user("Hi"), llm.assistant("Hello")]
        tip = store.ensure_chain(messages)
        root = message_hash(messages[0], None)
        assert tip == message_hash(messages[1], root)

    def test_single_message(self, store):
        messages = [llm.user("Hi")]
        assert round_trip(store, messages) == messages

    def test_multiple_turns(self, store):
        messages = [
            llm.system("Be brief"),
            llm.user("Hi"),
            llm.assistant("Hello"),
            llm.user("Again"),
            llm.assistant("Hello again"),
        ]
        assert round_trip(store, messages) == messages

    def test_reasoning_including_redacted(self, store):
        messages = [
            llm.user("Think"),
            llm.assistant(
                ReasoningPart(redacted=True),
                ReasoningPart(text="Considering it"),
                TextPart(text="Done"),
            ),
        ]
        assert round_trip(store, messages) == messages

    def test_interleaved_parts_keep_their_order(self, store):
        # The ordering the old schema could not express: reasoning, a
        # tool call, more reasoning, then text, all in one message.
        messages = [
            llm.user("Search"),
            llm.assistant(
                ReasoningPart(text="first"),
                ToolCallPart(name="search", arguments={"q": "a"}, tool_call_id="tc1"),
                ReasoningPart(text="second"),
                TextPart(text="answer"),
                ToolCallPart(name="search", arguments={"q": "b"}, tool_call_id="tc2"),
            ),
        ]
        assert round_trip(store, messages) == messages

    def test_tool_call_with_server_executed(self, store):
        messages = [
            llm.assistant(
                ToolCallPart(
                    name="web_search",
                    arguments={"query": "pelicans"},
                    tool_call_id="tc1",
                    server_executed=True,
                )
            )
        ]
        assert round_trip(store, messages) == messages

    def test_tool_result_with_exception(self, store):
        messages = [
            llm.tool_message(
                ToolResultPart(
                    name="lookup",
                    output="",
                    tool_call_id="tc1",
                    exception="ValueError: nope",
                )
            )
        ]
        assert round_trip(store, messages) == messages

    def test_provider_metadata_survives(self, store):
        messages = [
            Message(
                role="assistant",
                parts=[
                    ReasoningPart(
                        redacted=True,
                        provider_metadata={
                            "openai": {"id": "rs_1", "encrypted_content": "xyz"}
                        },
                    )
                ],
                provider_metadata={"openai": {"response_id": "resp_1"}},
            )
        ]
        assert round_trip(store, messages) == messages

    def test_attachment_part(self, store):
        messages = [
            llm.user(
                "Describe",
                Attachment(type="image/png", content=b"fake-png-bytes"),
            )
        ]
        assert round_trip(store, messages) == messages

    def test_attachment_part_with_provider_metadata(self, store):
        messages = [
            llm.user(
                AttachmentPart(
                    attachment=Attachment(type="image/png", content=b"bytes"),
                    provider_metadata={"openai": {"file_id": "file_1"}},
                )
            )
        ]
        assert round_trip(store, messages) == messages

    def test_attachment_part_without_an_attachment(self, store):
        messages = [llm.user(AttachmentPart())]
        assert round_trip(store, messages) == messages

    def test_tool_result_attachments_keep_their_order(self, store):
        messages = [
            llm.tool_message(
                ToolResultPart(
                    name="render",
                    output="two images",
                    tool_call_id="tc1",
                    attachments=[
                        Attachment(type="image/png", content=b"first"),
                        Attachment(type="image/png", content=b"second"),
                    ],
                )
            )
        ]
        assert round_trip(store, messages) == messages

    def test_attachment_content_is_shared_with_legacy_table(self, store):
        store.ensure_chain(
            [llm.user("Describe", Attachment(type="image/png", content=b"bytes"))]
        )
        assert store.db["attachments"].count == 1

    def test_unknown_tip_raises(self, store):
        with pytest.raises(KeyError):
            store.load_chain("b2:does-not-exist")


# ---- dedup -----------------------------------------------------------


class TestDedup:
    def test_writing_the_same_chain_twice_adds_nothing(self, store):
        messages = [llm.user("Hi"), llm.assistant("Hello")]
        first = store.ensure_chain(messages)
        second = store.ensure_chain(messages)
        assert first == second
        assert store.db["messages"].count == 2
        assert store.db["parts"].count == 2

    def test_extending_a_chain_only_writes_the_new_message(self, store):
        messages = [llm.user("Hi"), llm.assistant("Hello")]
        store.ensure_chain(messages)
        store.ensure_chain(messages + [llm.user("More")])
        assert store.db["messages"].count == 3

    def test_stateless_client_resending_history_writes_only_the_tail(self, store):
        # What an OpenAI Chat Completions style server sees: the client
        # holds the conversation and posts the whole thing every turn.
        history = []
        for turn in range(5):
            history.append(llm.user(f"question {turn}"))
            history.append(llm.assistant(f"answer {turn}"))
            store.ensure_chain(history)
        assert store.db["messages"].count == 10

    def test_diverging_chains_share_their_prefix(self, store):
        prefix = [llm.user("Hi"), llm.assistant("Hello")]
        store.ensure_chain(prefix + [llm.user("left")])
        store.ensure_chain(prefix + [llm.user("right")])
        # Two shared messages plus one for each branch.
        assert store.db["messages"].count == 4

    def test_appending_to_a_known_tip_skips_the_prefix_entirely(self, store):
        tip = store.ensure_chain([llm.user("Hi"), llm.assistant("Hello")])
        new_tip = store.ensure_chain([llm.user("More")], parent=tip)
        assert store.db["messages"].count == 3
        assert [message.parts[0].text for message in store.load_chain(new_tip)] == [
            "Hi",
            "Hello",
            "More",
        ]

    def test_same_content_under_a_different_parent_is_a_different_message(self, store):
        store.ensure_chain([llm.user("Hi"), llm.assistant("Same")])
        store.ensure_chain([llm.user("Different"), llm.assistant("Same")])
        assert store.db["messages"].count == 4


# ---- threads and forking ---------------------------------------------


class TestThreads:
    def test_new_thread_has_no_tip(self, store):
        thread_id = store.create_thread(name="Empty")
        assert store.thread_messages(thread_id) == []

    def test_appending_advances_the_tip(self, store):
        thread_id = store.create_thread(name="Chat")
        store.append(thread_id, [llm.user("Hi")])
        store.append(thread_id, [llm.assistant("Hello")])
        assert [message.role for message in store.thread_messages(thread_id)] == [
            "user",
            "assistant",
        ]

    def test_thread_records_its_name(self, store):
        thread_id = store.create_thread(name="Named")
        assert store.db["threads"].get(thread_id)["name"] == "Named"

    def test_unknown_thread_raises(self, store):
        with pytest.raises(KeyError):
            store.append("nope", [llm.user("Hi")])


class TestForking:
    def test_fork_shares_history_up_to_the_fork_point(self, store):
        thread_id = store.create_thread(name="Original")
        store.append(thread_id, [llm.user("Hi"), llm.assistant("Hello")])
        fork_point = store.append(thread_id, [llm.user("Original branch")])

        forked = store.fork(fork_point, name="What if")
        assert [message.parts[0].text for message in store.thread_messages(forked)] == [
            "Hi",
            "Hello",
            "Original branch",
        ]

    def test_forking_writes_no_new_messages(self, store):
        thread_id = store.create_thread()
        tip = store.append(thread_id, [llm.user("Hi"), llm.assistant("Hello")])
        before = store.db["messages"].count
        store.fork(tip, name="Copy")
        assert store.db["messages"].count == before

    def test_forked_branches_diverge_without_copying_the_prefix(self, store):
        original = store.create_thread(name="Original")
        fork_point = store.append(original, [llm.user("Hi"), llm.assistant("Hello")])
        forked = store.fork(fork_point, name="Alternative")

        store.append(original, [llm.user("down one path")])
        store.append(forked, [llm.user("down another")])

        # Two shared messages, plus one new message per branch.
        assert store.db["messages"].count == 4
        assert len(store.thread_messages(original)) == 3
        assert len(store.thread_messages(forked)) == 3

    def test_fork_records_where_it_came_from(self, store):
        original = store.create_thread(name="Original")
        tip = store.append(original, [llm.user("Hi")])
        forked = store.fork(tip, name="Copy", forked_from=original)
        assert store.db["threads"].get(forked)["forked_from"] == original

    def test_fork_of_an_interior_message_drops_the_later_history(self, store):
        thread_id = store.create_thread()
        fork_point = store.append(thread_id, [llm.user("Hi")])
        store.append(thread_id, [llm.assistant("Hello"), llm.user("More")])
        forked = store.fork(fork_point)
        assert len(store.thread_messages(forked)) == 1


# ---- pending tool calls ----------------------------------------------


class TestPendingToolCalls:
    def test_trailing_tool_calls_are_pending(self, store):
        tip = store.ensure_chain(
            [
                llm.user("Search"),
                llm.assistant(
                    ToolCallPart(name="search", arguments={}, tool_call_id="tc1")
                ),
            ]
        )
        assert [call.tool_call_id for call in store.pending_tool_calls(tip)] == ["tc1"]

    def test_tool_calls_followed_by_results_are_not_pending(self, store):
        tip = store.ensure_chain(
            [
                llm.user("Search"),
                llm.assistant(
                    ToolCallPart(name="search", arguments={}, tool_call_id="tc1")
                ),
                llm.tool_message(
                    ToolResultPart(name="search", output="done", tool_call_id="tc1")
                ),
            ]
        )
        assert store.pending_tool_calls(tip) == []

    def test_a_plain_reply_has_nothing_pending(self, store):
        tip = store.ensure_chain([llm.user("Hi"), llm.assistant("Hello")])
        assert store.pending_tool_calls(tip) == []


# ---- logging a response ----------------------------------------------


class TestLogResponse:
    def test_writes_a_turn(self, store, mock_model):
        mock_model.enqueue(["Hello"])
        response = mock_model.prompt("Hi")
        response.text()
        turn_id = store.log(response)
        assert store.db["turns"].get(turn_id)["model"] == "mock"

    def test_turn_records_usage(self, store, mock_model):
        mock_model.enqueue(["Hello"])
        response = mock_model.prompt("Hi there")
        response.text()
        turn = store.db["turns"].get(store.log(response))
        assert turn["input_tokens"] == 2
        assert turn["output_tokens"] == 1

    def test_turn_spans_from_its_parent_to_its_tip(self, store, mock_model):
        mock_model.enqueue(["Hello"])
        response = mock_model.prompt("Hi")
        response.text()
        turn = store.db["turns"].get(store.log(response))
        chain = store.load_chain(turn["tip_message_hash"])
        assert [message.role for message in chain] == ["user", "assistant"]
        assert chain[-1].parts[0].text == "Hello"

    def test_logging_advances_the_thread(self, store, mock_model):
        thread_id = store.create_thread(name="Chat")
        mock_model.enqueue(["Hello"])
        response = mock_model.prompt("Hi")
        response.text()
        store.log(response, thread_id=thread_id)
        assert [
            message.parts[0].text for message in store.thread_messages(thread_id)
        ] == [
            "Hi",
            "Hello",
        ]

    def test_logging_the_same_response_twice_is_idempotent(self, store, mock_model):
        # A turn is identified by the response it records, so re-logging
        # one updates it in place rather than duplicating the event.
        mock_model.enqueue(["Hello"])
        response = mock_model.prompt("Hi")
        response.text()
        assert store.log(response) == store.log(response)
        assert store.db["messages"].count == 2
        assert store.db["turns"].count == 1


# ---- conversations map onto threads ----------------------------------


class TestConversationThreads:
    def test_log_uses_the_conversation_id_as_the_thread_id(self, store, mock_model):
        conversation = mock_model.conversation()
        mock_model.enqueue(["Hello"])
        response = conversation.prompt("Hi")
        response.text()
        store.log(response)
        assert store.db["threads"].get(conversation.id) is not None

    def test_successive_turns_extend_the_same_thread(self, store, mock_model):
        conversation = mock_model.conversation()
        for reply in ("Hello", "Hello again"):
            mock_model.enqueue([reply])
            response = conversation.prompt("Hi")
            response.text()
            store.log(response)
        assert store.db["threads"].count == 1
        assert [
            message.parts[0].text for message in store.thread_messages(conversation.id)
        ] == ["Hi", "Hello", "Hi", "Hello again"]

    def test_a_response_without_a_conversation_gets_its_own_thread(
        self, store, mock_model
    ):
        # Parity with the legacy tables, which recorded a conversation
        # for every response - without this, a response logged through
        # the library API could never be continued with `llm -c`.
        mock_model.enqueue(["Hello"])
        response = mock_model.prompt("Hi")
        response.text()
        store.log(response)
        assert store.db["threads"].count == 1

    def test_an_explicit_thread_id_wins(self, store, mock_model):
        thread_id = store.create_thread(name="Mine")
        conversation = mock_model.conversation()
        mock_model.enqueue(["Hello"])
        response = conversation.prompt("Hi")
        response.text()
        store.log(response, thread_id=thread_id)
        assert store.db["threads"].count == 1
        assert len(store.thread_messages(thread_id)) == 2


# ---- CLI integration -------------------------------------------------


@pytest.fixture
def cli_store(user_path):
    "A LogStore over the same database the CLI logs to."
    return LogStore(sqlite_utils.Database(str(user_path / "logs.db")))


def run(*args):
    result = CliRunner().invoke(cli, list(args), catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result


class TestCliWrites:
    def test_a_prompt_writes_a_turn(self, cli_store):
        run("-m", "echo", "Hi")
        assert cli_store.db["turns"].count == 1

    def test_a_prompt_does_not_write_the_legacy_tables(self, cli_store):
        run("-m", "echo", "Hi")
        assert cli_store.db["responses"].count == 0
        assert cli_store.db["conversations"].count == 0

    def test_the_turn_points_at_the_stored_chain(self, cli_store):
        run("-m", "echo", "Hi")
        turn = next(iter(cli_store.db["turns"].rows))
        chain = cli_store.load_chain(turn["tip_message_hash"])
        assert [message.role for message in chain] == ["user", "assistant"]

    def test_the_thread_has_a_tip(self, cli_store):
        run("-m", "echo", "Hi")
        conversation_id = next(iter(cli_store.db["threads"].rows))["id"]
        assert cli_store.thread_tip(conversation_id) is not None

    def test_no_log_writes_nothing(self, cli_store):
        run("-m", "echo", "Hi", "--no-log")
        assert cli_store.db["turns"].count == 0
        assert cli_store.db["messages"].count == 0


class TestCliContinuation:
    def test_continuing_extends_the_same_thread(self, cli_store):
        run("-m", "echo", "First")
        run("-m", "echo", "Second", "-c")
        assert cli_store.db["threads"].count == 1
        conversation_id = next(iter(cli_store.db["threads"].rows))["id"]
        assert len(cli_store.thread_messages(conversation_id)) == 4

    def test_history_comes_from_the_new_tables(self, user_path):
        run("-m", "echo", "First")

        db = sqlite_utils.Database(str(user_path / "logs.db"))
        conversation_id = next(iter(db["threads"].rows))["id"]
        db.close()

        run("-m", "echo", "Second", "-c")

        # Four messages only if the second turn was built on top of the
        # first. Had the history been lost, the second turn would have
        # started a fresh root and the thread would hold just two.
        store = LogStore(sqlite_utils.Database(str(user_path / "logs.db")))
        chain = store.thread_messages(conversation_id)
        assert len(chain) == 4
        assert chain[0].parts[0].text == "First"

    def test_continuing_writes_only_the_new_messages(self, cli_store):
        run("-m", "echo", "First")
        before = cli_store.db["messages"].count
        run("-m", "echo", "Second", "-c")
        assert cli_store.db["messages"].count == before + 2


# ---- history loaded from storage -------------------------------------


class TestLoadedMessages:
    def test_loaded_messages_supply_the_history(self, mock_model):
        conversation = mock_model.conversation()
        conversation.loaded_messages = [llm.user("Earlier"), llm.assistant("Reply")]
        mock_model.enqueue(["Next"])
        response = conversation.prompt("Now")
        response.text()
        assert [message.parts[0].text for message in response.prompt.messages] == [
            "Earlier",
            "Reply",
            "Now",
        ]

    def test_a_completed_response_supersedes_them(self, mock_model):
        conversation = mock_model.conversation()
        conversation.loaded_messages = [llm.user("Earlier"), llm.assistant("Reply")]
        mock_model.enqueue(["First"])
        conversation.prompt("One").text()
        mock_model.enqueue(["Second"])
        response = conversation.prompt("Two")
        response.text()
        # The live response takes over; the loaded history is not
        # replayed a second time.
        assert [message.parts[0].text for message in response.prompt.messages] == [
            "Earlier",
            "Reply",
            "One",
            "First",
            "Two",
        ]


class TestLegacyConversations:
    def test_continuing_a_conversation_with_no_thread_still_works(self, user_path):
        # Conversations logged before this schema existed have no thread,
        # so `-c` has to fall back to rebuilding from the legacy rows.
        # Nothing writes those rows any more - seed them the way an
        # older version of llm would have.
        path = str(user_path / "logs.db")
        db = sqlite_utils.Database(path)
        migrate(db)
        db["conversations"].insert(
            {"id": "01aaaaaaaaaaaaaaaaaaaaaaaa", "name": "First", "model": "echo"}
        )
        db["responses"].insert(
            {
                "id": "01aaaaaaaaaaaaaaaaaaaaaaab",
                "model": "echo",
                "prompt": "First",
                "system": None,
                "prompt_json": None,
                "options_json": "{}",
                "response": "First response",
                "response_json": None,
                "conversation_id": "01aaaaaaaaaaaaaaaaaaaaaaaa",
                "duration_ms": 1,
                "datetime_utc": "2025-01-01T00:00:00",
                "schema_id": None,
            },
            alter=True,
        )
        db.close()

        result = run("-m", "echo", "Second", "-c")
        assert "First" in result.output


# ---- logging through the library API ---------------------------------


class TestLibraryLogging:
    """`log_to_db` is what plugins call, so the store write belongs there
    rather than in the CLI - otherwise anything that is not `llm` itself
    writes only the legacy tables."""

    def test_log_to_db_writes_the_store_too(self, store, mock_model):
        mock_model.enqueue(["Hello"])
        response = mock_model.prompt("Hi")
        response.text()
        response.log_to_db(store.db)
        assert store.db["turns"].count == 1
        assert store.db["messages"].count == 2

    def test_log_to_db_leaves_the_legacy_tables_alone(self, store, mock_model):
        mock_model.enqueue(["Hello"])
        response = mock_model.prompt("Hi")
        response.text()
        response.log_to_db(store.db)
        assert store.db["responses"].count == 0
        assert store.db["conversations"].count == 0

    def test_log_to_db_without_conversation_still_gets_a_thread(
        self, store, mock_model
    ):
        # The legacy path recorded a conversation for every response;
        # the store keeps that guarantee with a thread, so `llm -c` can
        # continue a response logged through the library API.
        mock_model.enqueue(["Hello"])
        response = mock_model.prompt("Hi")
        response.text()
        response.log_to_db(store.db)
        assert store.db["threads"].count == 1
        turn = next(iter(store.db["turns"].rows))
        assert turn["thread_id"] is not None

    def test_a_chain_writes_the_store_too(self, store, mock_model):
        conversation = mock_model.conversation()
        mock_model.enqueue(["Hello"])
        chain = conversation.chain("Hi")
        chain.text()
        chain.log_to_db(store.db)
        assert store.db["turns"].count == 1
        assert len(store.thread_messages(conversation.id)) == 2

    def test_messages_plus_prompt_both_reach_the_chain(self, store, mock_model):
        """prompt= alongside messages= used to vanish from the logged
        chain: Prompt.messages returned the explicit list verbatim, so
        the text the model answered was absent from the store."""
        mock_model.enqueue(["Hello"])
        response = mock_model.prompt("follow-up", messages=[llm.user("original")])
        response.text()
        response.log_to_db(store.db)
        turn = next(iter(store.db["turns"].rows))
        chain = store.load_chain(turn["tip_message_hash"])
        texts = [part.text for message in chain for part in message.parts]
        assert texts == ["original", "follow-up", "Hello"]
        assert store.verify() == []

    def test_log_to_db_records_tool_instantiations(self, store, mock_model):
        class Notes(llm.Toolbox):
            def __init__(self, path: str):
                self.path = path

        mock_model.enqueue(["ok"])
        response = mock_model.prompt(
            "next",
            tool_results=[
                llm.ToolResult(
                    name="Notes_read",
                    output="hello",
                    tool_call_id="tc_1",
                    instance=Notes("/tmp/notes"),
                )
            ],
        )
        response.text()
        response.log_to_db(store.db)
        turn_id = next(iter(store.db["turns"].rows))["id"]
        assert list(store.db["tool_instantiations"].rows) == [
            {
                "tool_call_id": "tc_1",
                "name": "Notes",
                "plugin": None,
                "arguments": '{"path": "/tmp/notes"}',
                "turn_id": turn_id,
            }
        ]

    def test_tool_instantiations_are_scoped_by_turn(self, store, mock_model):
        # Providers with per-request counters can reuse a tool_call_id
        # across turns - each turn keeps its own provenance row.
        class Notes(llm.Toolbox):
            def __init__(self, path: str):
                self.path = path

        for path in ("/tmp/one", "/tmp/two"):
            mock_model.enqueue(["ok"])
            response = mock_model.prompt(
                "next",
                tool_results=[
                    llm.ToolResult(
                        name="Notes_read",
                        output="hello",
                        tool_call_id="call_0",
                        instance=Notes(path),
                    )
                ],
            )
            response.text()
            response.log_to_db(store.db)
        arguments = {
            row["turn_id"]: row["arguments"]
            for row in store.db["tool_instantiations"].rows
        }
        assert sorted(arguments.values()) == [
            '{"path": "/tmp/one"}',
            '{"path": "/tmp/two"}',
        ]

    def test_successive_library_turns_extend_the_thread(self, store, mock_model):
        conversation = mock_model.conversation()
        for reply in ("One", "Two"):
            mock_model.enqueue([reply])
            response = conversation.prompt("Ask")
            response.text()
            response.log_to_db(store.db)
        assert len(store.thread_messages(conversation.id)) == 4


# ---- storage by reference --------------------------------------------


class TestPerTurnToolResolution:
    def test_same_name_different_definitions_resolve_per_turn(self, store, mock_model):
        # Two turns using tools that share a name but differ in
        # definition - each turn's extras must report its own tool_id.
        def make_tool(description):
            return llm.Tool(name="lookup", description=description, input_schema={})

        for description in ("first definition", "second definition"):
            mock_model.enqueue(["ok"])
            response = mock_model.prompt("hi", tools=[make_tool(description)])
            response.text()
            response.log_to_db(store.db)

        rows = merged_log_rows(store)
        rows.reverse()
        for row in rows:
            extras = log_row_extras(store, row)
            assert len(extras["tools"]) == 1
        descriptions_to_ids = {
            log_row_extras(store, row)["tools"][0]["description"]: log_row_extras(
                store, row
            )["tools"][0]["id"]
            for row in rows
        }
        assert len(descriptions_to_ids) == 2
        assert len(set(descriptions_to_ids.values())) == 2


class TestRepeatedFragments:
    def test_passing_the_same_fragment_twice_keeps_both_rows(self, store, mock_model):
        mock_model.enqueue(["ok"])
        response = mock_model.prompt("hi", fragments=["CONTEXT", "CONTEXT"])
        response.text()
        response.log_to_db(store.db)
        rows = list(
            store.db["turn_fragments"].rows_where("kind = 'prompt'", order_by='"order"')
        )
        assert [row["order"] for row in rows] == [0, 1]
        assert rows[0]["fragment_id"] == rows[1]["fragment_id"]


class TestAtomicWrites:
    """sqlite-utils runs in autocommit, so `with db.conn` was never a
    transaction - a crash mid-write could strand a message without its
    parts, and the dedup check would then skip it forever."""

    def test_failed_part_write_rolls_back_the_message(self, store, monkeypatch):
        message = Message(role="user", parts=[TextPart(text="a"), TextPart(text="b")])
        original = LogStore._write_part

        def flaky(self, hash_, position, part, fragment_map):
            if position == 1:
                raise RuntimeError("disk full")
            return original(self, hash_, position, part, fragment_map)

        monkeypatch.setattr(LogStore, "_write_part", flaky)
        with pytest.raises(RuntimeError):
            store.ensure_chain([message])
        monkeypatch.undo()
        assert store.db["messages"].count == 0
        assert store.db["parts"].count == 0
        # A retry can now write the whole message
        tip = store.ensure_chain([message])
        assert store.load_chain(tip) == [message]
        assert store.verify() == []

    def test_failed_turn_write_rolls_back_the_whole_turn(
        self, store, mock_model, monkeypatch
    ):
        mock_model.enqueue(["ok"])
        response = mock_model.prompt("Hi")
        response.text()
        # Fail at the search refresh, one of the last steps of log()
        monkeypatch.setattr("llm.logs.TURN_SEARCH_INSERT_SQL", "this is not sql")
        with pytest.raises(sqlite3.OperationalError):
            store.log(response)
        monkeypatch.undo()
        assert store.db["turns"].count == 0
        assert store.db["messages"].count == 0
        assert store.db["threads"].count == 0
        # And the retry writes everything
        store.log(response)
        assert store.db["turns"].count == 1
        assert store.verify() == []


class TestConcurrentWriters:
    def test_losing_the_insert_race_neither_raises_nor_duplicates(
        self, tmp_path, monkeypatch
    ):
        # Two connections to the same database. B checks for the hash
        # while it is absent - simulated by disabling its fast-path
        # check - then A wins the insert. B's own insert must quietly
        # lose: no UNIQUE error, no second set of parts.
        path = str(tmp_path / "logs.db")
        store_a = LogStore(sqlite_utils.Database(path))
        store_b = LogStore(sqlite_utils.Database(path))
        message = llm.user("Hi")
        tip = store_a.ensure_chain([message])
        monkeypatch.setattr(
            sqlite_utils.db.Table, "count_where", lambda *args, **kwargs: 0
        )
        assert store_b.ensure_chain([message]) == tip
        monkeypatch.undo()
        assert store_a.db["messages"].count == 1
        assert store_a.db["parts"].count == 1
        assert store_a.verify() == []


class TestTurnInputBoundary:
    """A turn whose input ends [tool results, user prompt] owns both -
    the tool results must not vanish from display or the -T filter just
    because a user message follows them."""

    def _log_turn_with_results_and_prompt(self, store, mock_model):
        mock_model.enqueue(["ok"])
        response = mock_model.prompt(
            "next question",
            messages=[llm.user("orig"), llm.assistant("first answer")],
            tool_results=[llm.ToolResult(name="t", output="RESULT", tool_call_id="c9")],
        )
        response.text()
        response.log_to_db(store.db)

    def test_tool_results_and_prompt_both_display(self, store, mock_model):
        self._log_turn_with_results_and_prompt(store, mock_model)
        row = merged_log_rows(store)[0]
        assert row["prompt"] == "next question"
        extras = log_row_extras(store, row)
        assert [result["output"] for result in extras["tool_results"]] == ["RESULT"]
        # The parts row id resolves even though the result sits one
        # message above the parent.
        assert extras["tool_results"][0]["id"] is not None

    def test_tool_filters_match(self, store, mock_model):
        self._log_turn_with_results_and_prompt(store, mock_model)
        assert len(merged_log_rows(store, any_tools=True)) == 1
        assert len(merged_log_rows(store, tool_names=["t"])) == 1
        assert merged_log_rows(store, tool_names=["other"]) == []


class TestUnsupportedBranchDatabases:
    def test_existing_message_store_tables_fail_loudly(self, tmp_path):
        # The message store migration creates its tables in final form
        # and assumes they do not exist - a database carrying tables
        # from unreleased development revisions is an unsupported
        # state, and the migration fails loudly rather than dropping
        # or adapting whatever is there.
        db = sqlite_utils.Database(str(tmp_path / "old-branch.db"))
        db["messages"].create({"hash": str}, pk="hash")
        with pytest.raises(sqlite3.OperationalError):
            migrate(db)


class TestAttachmentHashing:
    """Message identity covers attachment content, never the filesystem
    path the bytes were loaded from."""

    def test_same_bytes_at_two_paths_are_one_identity(self, tmp_path):
        path_a = tmp_path / "a.png"
        path_b = tmp_path / "b.png"
        path_a.write_bytes(b"SAME BYTES")
        path_b.write_bytes(b"SAME BYTES")
        hashes = [
            message_hash(
                Message(
                    role="user",
                    parts=[
                        AttachmentPart(
                            attachment=Attachment(type="image/png", path=str(p))
                        )
                    ],
                ),
                None,
            )
            for p in (path_a, path_b)
        ]
        assert hashes[0] == hashes[1]

    def test_changed_bytes_at_the_same_path_change_the_hash(self, tmp_path):
        path = tmp_path / "x.png"

        def hash_now():
            return message_hash(
                Message(
                    role="user",
                    parts=[
                        AttachmentPart(
                            attachment=Attachment(type="image/png", path=str(path))
                        )
                    ],
                ),
                None,
            )

        path.write_bytes(b"first version")
        first = hash_now()
        path.write_bytes(b"second version")
        assert hash_now() != first

    def test_same_bytes_at_two_paths_share_the_stored_row(self, store, tmp_path):
        for name in ("a.png", "b.png"):
            path = tmp_path / name
            path.write_bytes(b"SAME BYTES")
            store.ensure_chain(
                [
                    Message(
                        role="user",
                        parts=[
                            AttachmentPart(
                                attachment=Attachment(type="image/png", path=str(path))
                            )
                        ],
                    )
                ]
            )
        assert store.db["messages"].count == 1

    def test_attachment_chain_verifies(self, store, tmp_path):
        path = tmp_path / "x.png"
        path.write_bytes(b"PNG BYTES")
        store.ensure_chain(
            [
                Message(
                    role="user",
                    parts=[
                        AttachmentPart(
                            attachment=Attachment(type="image/png", path=str(path))
                        )
                    ],
                ),
                llm.assistant("A fine image"),
            ]
        )
        assert store.verify() == []

    def test_media_type_participates_in_identity(self, tmp_path):
        path = tmp_path / "x.bin"
        path.write_bytes(b"SAME BYTES")

        def hash_as(type_):
            return message_hash(
                Message(
                    role="user",
                    parts=[
                        AttachmentPart(
                            attachment=Attachment(type=type_, path=str(path))
                        )
                    ],
                ),
                None,
            )

        # The model sees the media type: identical bytes sent as
        # different types are different requests.
        assert hash_as("image/png") != hash_as("text/plain")

    def test_cached_attachment_id_is_not_trusted(self, tmp_path):
        path = tmp_path / "x.png"
        path.write_bytes(b"first")
        attachment = Attachment(type="image/png", path=str(path))
        attachment.id()  # caches _id from the current bytes
        message = Message(role="user", parts=[AttachmentPart(attachment=attachment)])
        first = message_hash(message, None)
        path.write_bytes(b"second")
        assert message_hash(message, None) != first

    def test_editing_the_file_after_logging_breaks_verify(self, store, tmp_path):
        path = tmp_path / "x.png"
        path.write_bytes(b"ORIGINAL")
        tip = store.ensure_chain(
            [
                Message(
                    role="user",
                    parts=[
                        AttachmentPart(
                            attachment=Attachment(type="image/png", path=str(path))
                        )
                    ],
                )
            ]
        )
        assert store.verify() == []
        path.write_bytes(b"TAMPERED")
        assert store.verify() == [tip]

    def test_deleting_the_file_is_detected_not_fatal(self, store, tmp_path):
        path = tmp_path / "x.png"
        path.write_bytes(b"ORIGINAL")
        tip = store.ensure_chain(
            [
                Message(
                    role="user",
                    parts=[
                        AttachmentPart(
                            attachment=Attachment(type="image/png", path=str(path))
                        )
                    ],
                )
            ]
        )
        path.unlink()
        assert store.verify() == [tip]


class TestRepeatedAttachments:
    def test_a_tool_result_can_carry_the_same_attachment_twice(self, store):
        attachment = Attachment(type="image/png", content=b"PNG BYTES")
        message = Message(
            role="tool",
            parts=[
                ToolResultPart(
                    name="t",
                    output="ok",
                    tool_call_id="c1",
                    attachments=[attachment, attachment],
                )
            ],
        )
        tip = store.ensure_chain([message])
        assert store.db["part_attachments"].count == 2
        loaded = store.load_chain(tip)
        assert len(loaded[0].parts[0].attachments) == 2
        assert store.verify() == []


class TestPartStorageFormat:
    """Literal text is stored raw in its own column - never escaped,
    never parsed - and the JSON payload holds only structure, with the
    type key left to the type column."""

    def test_plain_text_stores_raw_text_and_no_payload(self, store):
        text = '{"looks": "like json", "but": "is text"}'
        store.ensure_chain([llm.user(text)])
        row = next(iter(store.db["parts"].rows))
        assert row["type"] == "text"
        assert row["text"] == text
        assert row["payload"] is None

    def test_redacted_reasoning_splits_text_from_structure(self, store):
        message = Message(
            role="assistant",
            parts=[ReasoningPart(text="thinking", redacted=True)],
        )
        tip = store.ensure_chain([message])
        row = next(iter(store.db["parts"].rows))
        assert row["text"] == "thinking"
        assert json.loads(row["payload"]) == {"redacted": True}
        assert store.load_chain(tip) == [message]

    def test_no_stored_payload_contains_a_type_key(self, store):
        messages = [
            llm.user("hi"),
            Message(
                role="assistant",
                parts=[
                    ReasoningPart(text="thinking", redacted=True),
                    ToolCallPart(name="t", arguments={"a": 1}, tool_call_id="c1"),
                ],
            ),
            Message(
                role="tool",
                parts=[ToolResultPart(name="t", output="ok", tool_call_id="c1")],
            ),
        ]
        tip = store.ensure_chain(messages)
        for row in store.db["parts"].rows:
            if row["payload"] is not None:
                assert "type" not in json.loads(row["payload"])
        assert store.load_chain(tip) == messages
        assert store.verify() == []

    def test_fragment_referencing_text_stays_structured(self, store):
        novel = "CALL ME ISHMAEL. " * 20
        ensure_fragment(store.db, novel)
        store.ensure_chain([llm.user(f"{novel}\nwho?")], fragments=[novel])
        row = next(iter(store.db["parts"].rows))
        assert row["text"] is None
        assert json.loads(row["payload"]) == {
            "text_ref": [{"fragment": 1}, {"literal": "\nwho?"}]
        }


class TestFragmentReferences:
    """The point of fragments is that a novel is stored once and pointed
    at from every prompt about it, so the text must not be expanded into
    each message that uses it."""

    NOVEL = "CALL ME ISHMAEL. " * 500

    def messages_using(self, fragment, question):
        # What Prompt.prompt builds: fragments joined to the prompt text.
        return [llm.user(f"{fragment}\n{question}")]

    def test_fragment_text_is_not_duplicated_into_the_part(self, store):
        ensure_fragment(store.db, self.NOVEL)
        store.ensure_chain(
            self.messages_using(self.NOVEL, "who is the narrator?"),
            fragments=[self.NOVEL],
        )
        payload = next(iter(store.db["parts"].rows))["payload"]
        assert self.NOVEL not in payload
        assert len(payload) < 200

    def test_many_prompts_about_one_fragment_store_it_once(self, store):
        ensure_fragment(store.db, self.NOVEL)
        for question in ("who?", "where?", "when?", "why?"):
            store.ensure_chain(
                self.messages_using(self.NOVEL, question), fragments=[self.NOVEL]
            )
        assert store.db["fragments"].count == 1
        assert store.db["parts"].count == 4
        total = sum(len(row["payload"]) for row in store.db["parts"].rows)
        assert total < len(self.NOVEL)

    def test_referenced_text_round_trips(self, store):
        ensure_fragment(store.db, self.NOVEL)
        messages = self.messages_using(self.NOVEL, "who is the narrator?")
        tip = store.ensure_chain(messages, fragments=[self.NOVEL])
        assert store.load_chain(tip) == messages

    def test_several_fragments_in_one_part_round_trip(self, store):
        one, two = "FIRST FRAGMENT", "SECOND FRAGMENT"
        for content in (one, two):
            ensure_fragment(store.db, content)
        messages = [llm.user(f"{one}\n{two}\ncompare them")]
        tip = store.ensure_chain(messages, fragments=[one, two])
        assert store.load_chain(tip) == messages

    def test_part_fragments_records_the_link(self, store):
        ensure_fragment(store.db, self.NOVEL)
        store.ensure_chain(
            self.messages_using(self.NOVEL, "who?"), fragments=[self.NOVEL]
        )
        assert store.db["part_fragments"].count == 1

    def test_messages_using_a_fragment_are_one_join_away(self, store):
        ensure_fragment(store.db, self.NOVEL)
        for question in ("who?", "where?"):
            store.ensure_chain(
                self.messages_using(self.NOVEL, question), fragments=[self.NOVEL]
            )
        fragment_id = next(iter(store.db["fragments"].rows))["id"]
        found = list(
            store.db.query(
                """
                select distinct parts.message_hash from part_fragments
                join parts on parts.id = part_fragments.part_id
                where part_fragments.fragment_id = ?
                """,
                [fragment_id],
            )
        )
        assert len(found) == 2

    def test_unknown_fragments_are_stored_inline(self, store):
        messages = [llm.user("just some text")]
        tip = store.ensure_chain(messages)
        assert store.db["part_fragments"].count == 0
        assert store.load_chain(tip) == messages

    def test_hashes_do_not_depend_on_where_the_bytes_live(self, store):
        # Identity is the resolved content, so storing by reference must
        # produce exactly the hash that storing inline would.
        messages = self.messages_using(self.NOVEL, "who?")
        inline = store.ensure_chain(messages)
        ensure_fragment(store.db, self.NOVEL)
        by_reference = store.ensure_chain(messages, fragments=[self.NOVEL])
        assert inline == by_reference


# ---- verification ----------------------------------------------------


class TestVerify:
    """Reads resolve references, so a reconstruction bug would produce a
    chain that differs from what was hashed - and would do it silently.
    Re-hashing every stored message catches the whole class at once."""

    def test_a_fresh_store_verifies(self, store):
        assert store.verify() == []

    def test_every_kind_of_part_verifies(self, store):
        novel = "CALL ME ISHMAEL. " * 100
        store.ensure_chain(
            [
                llm.system("be brief"),
                llm.user(
                    f"{novel}\nwho is the narrator?",
                    Attachment(type="image/png", content=b"bytes"),
                ),
                llm.assistant(
                    ReasoningPart(text="thinking", provider_metadata={"a": 1}),
                    ReasoningPart(redacted=True),
                    ToolCallPart(name="s", arguments={"q": 1}, tool_call_id="tc1"),
                    TextPart(text="answer"),
                ),
                llm.tool_message(
                    ToolResultPart(
                        name="s",
                        output="out",
                        tool_call_id="tc1",
                        exception="ValueError: x",
                        attachments=[Attachment(type="image/png", content=b"one")],
                    )
                ),
            ],
            fragments=[novel],
        )
        assert store.verify() == []

    def test_a_corrupted_part_is_caught(self, store):
        tip = store.ensure_chain([llm.user("Hi")])
        with store.db.conn:
            store.db.execute("update parts set text = 'tampered'")
        assert store.verify() == [tip]

    def test_a_missing_fragment_is_caught(self, store):
        novel = "CALL ME ISHMAEL. " * 100
        tip = store.ensure_chain([llm.user(f"{novel}\nwho?")], fragments=[novel])
        with store.db.conn:
            store.db.execute("delete from fragments")
        assert store.verify() == [tip]


class TestFragmentsEndToEnd:

    def test_a_conversation_chain_includes_fragment_text(self, mock_model):
        # prompt.messages is meant to be exactly what the model sees, and
        # what the model sees has the fragments concatenated in.
        conversation = mock_model.conversation()
        mock_model.enqueue(["ok"])
        response = conversation.prompt("question", fragments=["FRAGMENT-BODY"])
        response.text()
        assert response.prompt.messages[-1].parts[0].text == response.prompt.prompt

    def test_the_cli_stores_a_fragment_by_reference(self, user_path, tmpdir):
        novel = "CALL ME ISHMAEL. " * 3000
        path = tmpdir / "novel.txt"
        path.write_text(novel, "utf-8")
        for question in ("who?", "where?", "when?"):
            run("-m", "echo", question, "-f", str(path))

        db = sqlite_utils.Database(str(user_path / "logs.db"))
        assert db["fragments"].count == 1
        assert db["part_fragments"].count >= 3
        # Every question re-sends the novel; it must be stored once.
        user_payloads = sum(
            len(row["payload"])
            for row in db.query(
                "select payload from parts join messages"
                " on messages.hash = parts.message_hash"
                " where messages.role = 'user'"
            )
        )
        assert user_payloads < len(novel)
        assert LogStore(db).verify() == []


# ---- async ------------------------------------------------------------


class TestAsyncLogging:
    """The CLI converts an async response to a sync one before logging,
    so anything the conversion drops is dropped from the log."""

    def enqueue_reasoning(self, model):
        model.enqueue(
            [
                llm.parts.StreamEvent(
                    type="reasoning",
                    chunk="thinking hard",
                    provider_metadata={"anthropic": {"signature": "SIG"}},
                ),
                llm.parts.StreamEvent(type="text", chunk="the answer"),
            ]
        )

    async def respond(self, model, prompt="q"):
        response = model.prompt(prompt)
        await response.text()
        return response

    @pytest.mark.asyncio
    async def test_to_sync_response_keeps_the_parts(self, async_mock_model):
        self.enqueue_reasoning(async_mock_model)
        response = await self.respond(async_mock_model)
        before = response._messages_now()
        after = (await response.to_sync_response())._messages_now()
        assert after == before

    @pytest.mark.asyncio
    async def test_logging_an_async_response_keeps_reasoning(
        self, store, async_mock_model
    ):
        self.enqueue_reasoning(async_mock_model)
        response = await self.respond(async_mock_model)
        store.log(await response.to_sync_response())

        parts = store.load_chain(
            next(iter(store.db["turns"].rows))["tip_message_hash"]
        )[-1].parts
        assert [type(part).__name__ for part in parts] == [
            "ReasoningPart",
            "TextPart",
        ]
        assert parts[0].provider_metadata == {"anthropic": {"signature": "SIG"}}
        assert store.verify() == []


# ---- llm logs against the new tables ---------------------------------


def forget_legacy(user_path):
    """Empty the table the old `llm logs` reads from.

    Every test below runs this first, so a passing assertion can only
    have been served by the content-addressed tables. Without it these
    tests pass against the legacy path and prove nothing.
    """
    db = sqlite_utils.Database(str(user_path / "logs.db"))
    with db.conn:
        db.execute("delete from responses")
    db.close()


class TestLogsCommand:
    """`llm logs` reads the content-addressed tables only. Conversations
    logged before this schema existed are deliberately not shown yet."""

    def test_shows_a_logged_prompt(self, user_path):
        run("-m", "echo", "hello there")
        forget_legacy(user_path)
        assert "hello there" in run("logs", "-n", "1").output

    def test_json_output_carries_the_turn(self, user_path):
        run("-m", "echo", "hello there")
        forget_legacy(user_path)
        rows = json.loads(run("logs", "-n", "1", "--json").output)
        assert len(rows) == 1
        assert rows[0]["model"] == "echo"
        assert rows[0]["prompt"] == "hello there"
        assert "hello there" in rows[0]["response"]

    def test_count_limits_results(self, user_path):
        for word in ("one", "two", "three"):
            run("-m", "echo", word)
        forget_legacy(user_path)
        assert len(json.loads(run("logs", "-n", "2", "--json").output)) == 2

    def test_results_are_chronological(self, user_path):
        for word in ("one", "two", "three"):
            run("-m", "echo", word)
        forget_legacy(user_path)
        rows = json.loads(run("logs", "-n", "0", "--json").output)
        assert [r["prompt"] for r in rows] == ["one", "two", "three"]

    def test_filters_by_model(self, user_path):
        run("-m", "echo", "hello")
        forget_legacy(user_path)
        assert json.loads(run("logs", "-m", "echo", "--json").output)
        assert json.loads(run("logs", "-m", "gpt-4o", "--json").output) == []

    def test_filters_to_a_conversation(self, user_path):
        run("-m", "echo", "first")
        run("-c", "second")
        run("-m", "echo", "unrelated")
        forget_legacy(user_path)
        db = sqlite_utils.Database(str(user_path / "logs.db"))
        thread_id = next(
            iter(db.query("select thread_id from turns order by id limit 1"))
        )["thread_id"]
        rows = json.loads(run("logs", "--cid", thread_id, "--json").output)
        assert [r["prompt"] for r in rows] == ["first", "second"]

    def test_filters_by_fragment(self, user_path, tmpdir):
        path = tmpdir / "frag.txt"
        path.write_text("FRAGMENT BODY", "utf-8")
        run("-m", "echo", "with fragment", "-f", str(path))
        run("-m", "echo", "without fragment")
        forget_legacy(user_path)

        db = sqlite_utils.Database(str(user_path / "logs.db"))
        fragment_hash = next(iter(db["fragments"].rows))["hash"]
        rows = json.loads(run("logs", "-f", fragment_hash, "--json").output)
        # The stored prompt is the resolved text the model was sent.
        assert [r["prompt"] for r in rows] == ["FRAGMENT BODY\nwith fragment"]

    def test_filters_by_tool(self, user_path):
        run(
            "-m",
            "echo",
            '{"tool_calls": [{"name": "llm_version"}]}',
            "-T",
            "llm_version",
        )
        run("-m", "echo", "no tools here")
        forget_legacy(user_path)
        assert len(json.loads(run("logs", "-T", "llm_version", "--json").output)) == 1

    def test_usage_is_reported(self, user_path):
        run("-m", "echo", "hello")
        forget_legacy(user_path)
        rows = json.loads(run("logs", "--json").output)
        assert "input_tokens" in rows[0]
        assert "datetime_utc" in rows[0]


class TestPayloadOrdering:
    def test_tool_call_argument_order_is_preserved(self, store):
        # canonical_json sorts keys - that is for hashing, not storage.
        # Arguments come back in the order the model produced them.
        messages = [
            llm.assistant(
                ToolCallPart(
                    name="demo",
                    arguments={"timeout": 120, "options": ["tick"]},
                    tool_call_id="tc1",
                )
            )
        ]
        tip = store.ensure_chain(messages)
        assert list(store.load_chain(tip)[0].parts[0].arguments) == [
            "timeout",
            "options",
        ]

    def test_hashing_still_ignores_key_order(self, store):
        one = store.ensure_chain(
            [llm.assistant(ToolCallPart(name="d", arguments={"a": 1, "b": 2}))]
        )
        two = store.ensure_chain(
            [llm.assistant(ToolCallPart(name="d", arguments={"b": 2, "a": 1}))]
        )
        assert one == two
        assert store.db["messages"].count == 1
