"""Tests for secret scrubbing in the log store (llm.redaction).

The log database stores prompts, fragments, tool arguments and attachment
bytes verbatim. These tests pin the scrub applied on the write path
(LogStore) and on the way out of the `llm logs` / `llm fragments`
commands: configured key values and secret-shaped strings must never
reach disk or stdout, while ordinary content - including opaque
provider_metadata blobs - passes through untouched.
"""

import json
import pathlib

import pytest
from click.testing import CliRunner

import llm
from llm.cli import cli
from llm.logs import LogStore
from llm.models import Attachment
from llm.migrations import migrate
from llm.parts import (
    AttachmentPart,
    ReasoningPart,
    ToolCallPart,
    ToolResultPart,
    tool_message,
)
from llm.redaction import SecretScrubber, default_scrubber, known_secret_values
from llm.utils import ensure_fragment

CONFIGURED = "configured-secret-value-123"
ENV_SECRET = "env-secret-value-456"
SHAPED = "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
GH_TOKEN = "ghp_" + "A" * 36


def make_store(db_factory):
    return LogStore(db_factory(memory=True))


def db_dump(db):
    "Every value in every table, as one searchable string."
    bits = []
    for table in db.table_names():
        for row in db[table].rows:
            bits.append(repr(row))
    return "\n".join(bits)


@pytest.fixture
def configured_keys(user_path, monkeypatch):
    "keys.json and an env key holding the test secrets."
    pathlib.Path(str(user_path), "keys.json").write_text(
        json.dumps({"openai": CONFIGURED}), "utf-8"
    )
    monkeypatch.setenv("SOME_API_KEY", ENV_SECRET)


class TestScrubText:
    def test_configured_value_is_replaced(self):
        scrubber = SecretScrubber(known_values=[CONFIGURED])
        assert scrubber.scrub_text(f"key is {CONFIGURED} ok") == "key is *** ok"

    def test_secret_shapes_are_replaced_without_configuration(self):
        scrubber = SecretScrubber(known_values=[])
        assert scrubber.scrub_text(f"token {SHAPED}") == "token ***"
        assert scrubber.scrub_text(f"token {GH_TOKEN}") == "token ***"
        assert scrubber.scrub_text("AKIAIOSFODNN7EXAMPLE") == "***"

    def test_ordinary_text_is_untouched(self):
        scrubber = SecretScrubber(known_values=[CONFIGURED])
        text = "The pelican brief: sk- is short for sketch, ask me anything"
        assert scrubber.scrub_text(text) == text

    def test_longest_value_wins(self):
        scrubber = SecretScrubber(known_values=["abcdefgh", "abcdefgh-wxyz"])
        assert scrubber.scrub_text("abcdefgh-wxyz") == "***"

    def test_json_escaped_form_is_replaced(self):
        # A configured value containing characters JSON escapes must still
        # be caught inside serialized JSON output.
        value = 'pa"ss\\word-123456'
        scrubber = SecretScrubber(known_values=[value])
        payload = json.dumps({"key": value})
        assert value not in scrubber.scrub_text(payload)
        assert "***" in scrubber.scrub_text(payload)


class TestScrubObj:
    def test_nested_structures(self):
        scrubber = SecretScrubber(known_values=[CONFIGURED])
        obj = {"a": [CONFIGURED, {"b": SHAPED}], "c": 3}
        assert scrubber.scrub_obj(obj) == {"a": ["***", {"b": "***"}], "c": 3}

    def test_provider_metadata_keeps_opaque_blobs(self):
        # Reasoning signatures and encrypted content must be echoed back
        # byte-for-byte, so shape patterns do not apply under
        # provider_metadata - but a configured key value still goes.
        scrubber = SecretScrubber(known_values=[CONFIGURED])
        obj = {
            "provider_metadata": {"signature": SHAPED, "leaked": CONFIGURED},
            "text": SHAPED,
        }
        out = scrubber.scrub_obj(obj)
        assert out["provider_metadata"]["signature"] == SHAPED
        assert out["provider_metadata"]["leaked"] == "***"
        assert out["text"] == "***"


class TestScrubBytes:
    def test_utf8_text(self):
        scrubber = SecretScrubber(known_values=[])
        data = f"header {SHAPED} trailer".encode("utf-8")
        assert scrubber.scrub_bytes(data) == b"header *** trailer"

    def test_binary_with_embedded_secret(self):
        scrubber = SecretScrubber(known_values=[])
        data = b"\x89PNG\x00\xff" + SHAPED.encode("ascii") + b"\x00\xfe"
        out = scrubber.scrub_bytes(data)
        assert SHAPED.encode("ascii") not in out
        assert out.startswith(b"\x89PNG\x00\xff")


class TestKnownValues:
    def test_keys_file_and_environment(self, configured_keys):
        values = known_secret_values()
        assert CONFIGURED in values
        assert ENV_SECRET in values

    def test_short_values_are_ignored(self, user_path):
        pathlib.Path(str(user_path), "keys.json").write_text(
            json.dumps({"short": "abc"}), "utf-8"
        )
        assert "abc" not in known_secret_values()

    def test_opt_out(self, monkeypatch):
        monkeypatch.setenv("LLM_NO_LOG_REDACTION", "1")
        assert default_scrubber() is None


class TestWritePath:
    def test_prompt_and_response_scrubbed(self, db_factory, configured_keys, mock_model):
        store = make_store(db_factory)
        mock_model.enqueue([f"echo {CONFIGURED} and {SHAPED}"])
        response = mock_model.prompt(f"my key is {CONFIGURED}")
        response.text()
        store.log(response)
        dump = db_dump(store.db)
        assert CONFIGURED not in dump
        assert SHAPED not in dump
        assert "***" in dump
        # The hash chain covers the scrubbed form, so it still verifies
        assert store.verify() == []

    def test_loaded_chain_is_the_scrubbed_form(self, db_factory, configured_keys):
        store = make_store(db_factory)
        tip = store.ensure_chain([llm.user(f"key {ENV_SECRET}"), llm.assistant("ok")])
        chain = store.load_chain(tip)
        assert chain[0].parts[0].text == "key ***"

    def test_response_json_payload_scrubbed(self, db_factory, mock_model):
        # A provider payload that echoes a secret (a model repeating a
        # key back) is stored on the turn - scrubbed like everything else.
        store = make_store(db_factory)
        mock_model.enqueue(["Hello"])
        response = mock_model.prompt("Hi")
        response.text()
        response.response_json = {"output": f"echo {SHAPED}"}
        turn_id = store.log(response)
        stored = store.db["turns"].get(turn_id)["response_json"]
        assert SHAPED not in stored
        assert "***" in stored

    def test_thread_name_scrubbed(self, db_factory, configured_keys, mock_model):
        store = make_store(db_factory)
        mock_model.enqueue(["Hello"])
        response = mock_model.prompt(f"chat about {CONFIGURED}")
        response.text()
        turn_id = store.log(response)
        thread_id = store.db["turns"].get(turn_id)["thread_id"]
        name = store.db["threads"].get(thread_id)["name"]
        assert CONFIGURED not in name

    def test_fragment_content_scrubbed(self, db_factory, configured_keys):
        store = make_store(db_factory)
        fragment = f"fragment body {CONFIGURED}"
        tip = store.ensure_chain(
            [llm.user(f"before {fragment} after")], fragments=[fragment]
        )
        rows = list(store.db["fragments"].rows)
        assert rows and all(CONFIGURED not in row["content"] for row in rows)
        assert store.load_chain(tip)[0].parts[0].text == "before fragment body *** after"
        assert store.verify() == []

    def test_tool_call_arguments_scrubbed(self, db_factory):
        store = make_store(db_factory)
        tip = store.ensure_chain(
            [
                llm.user("go"),
                llm.assistant(
                    ToolCallPart(
                        name="lookup",
                        arguments={"api_key": SHAPED, "q": "pelicans"},
                        tool_call_id="tc1",
                    )
                ),
            ]
        )
        dump = db_dump(store.db)
        assert SHAPED not in dump
        loaded = store.load_chain(tip)
        assert loaded[1].parts[0].arguments == {"api_key": "***", "q": "pelicans"}

    def test_tool_result_output_scrubbed(self, db_factory):
        store = make_store(db_factory)
        store.ensure_chain(
            [
                llm.user("go"),
                tool_message(
                    ToolResultPart(
                        name="lookup",
                        output=f"found {SHAPED}",
                        tool_call_id="tc1",
                    )
                ),
            ]
        )
        assert SHAPED not in db_dump(store.db)

    def test_attachment_bytes_scrubbed(self, db_factory):
        store = make_store(db_factory)
        content = b"file body " + SHAPED.encode("ascii")
        store.ensure_chain(
            [llm.user(AttachmentPart(attachment=Attachment(content=content)))]
        )
        rows = list(store.db["attachments"].rows)
        assert len(rows) == 1
        assert SHAPED.encode("ascii") not in rows[0]["content"]
        # The content-addressed id matches the bytes actually stored
        assert rows[0]["id"] == Attachment(content=rows[0]["content"]).id()

    def test_provider_metadata_signature_survives(self, db_factory, configured_keys):
        store = make_store(db_factory)
        message = llm.assistant(
            ReasoningPart(
                text="thinking",
                provider_metadata={"anthropic": {"signature": SHAPED}},
            )
        )
        tip = store.ensure_chain([llm.user("hi"), message])
        loaded = store.load_chain(tip)
        assert loaded[1].parts[0].provider_metadata == {
            "anthropic": {"signature": SHAPED}
        }
        assert store.verify() == []

    def test_ordinary_content_round_trips(self, db_factory):
        store = make_store(db_factory)
        messages = [llm.user("Hi"), llm.assistant("Hello")]
        assert store.load_chain(store.ensure_chain(messages)) == messages

    def test_opt_out_keeps_verbatim(self, db_factory, configured_keys, monkeypatch):
        monkeypatch.setenv("LLM_NO_LOG_REDACTION", "1")
        store = make_store(db_factory)
        store.ensure_chain([llm.user(f"key {CONFIGURED}")])
        assert CONFIGURED in db_dump(store.db)


class TestOutputPath:
    "Databases written before the scrub existed are protected on the way out."

    def seed_legacy(self, db_factory, monkeypatch):
        monkeypatch.setenv("LLM_NO_LOG_REDACTION", "1")
        store = LogStore(db_factory(str(pathlib.Path(llm.user_dir()) / "logs.db")))
        return store

    def test_logs_json_output_scrubbed(
        self, db_factory, configured_keys, mock_model, monkeypatch
    ):
        store = self.seed_legacy(db_factory, monkeypatch)
        mock_model.enqueue(["Hello"])
        response = mock_model.prompt(f"my key is {CONFIGURED}")
        response.text()
        store.log(response)
        monkeypatch.delenv("LLM_NO_LOG_REDACTION")
        result = CliRunner().invoke(cli, ["logs", "--json"])
        assert result.exit_code == 0
        assert CONFIGURED not in result.output
        assert "***" in result.output

    def test_fragments_show_and_list_scrubbed(self, logs_db, configured_keys):
        migrate(logs_db)
        fragment_id = ensure_fragment(logs_db, f"saved fragment {CONFIGURED}")
        hash_ = list(logs_db["fragments"].rows)[0]["hash"]
        assert fragment_id
        runner = CliRunner()
        shown = runner.invoke(cli, ["fragments", "show", hash_])
        assert shown.exit_code == 0
        assert CONFIGURED not in shown.output
        listed = runner.invoke(cli, ["fragments", "list", "--json"])
        assert listed.exit_code == 0
        assert CONFIGURED not in listed.output
