"""Tests for the OpenAI built-in plugin's messages= path.

Phase 4a covers build_messages reading prompt.messages (instead of the
legacy prompt.prompt / prompt.system / prompt.attachments fields), which
lets users pass structured message history via model.prompt(messages=[...]).
"""

import json

import pytest

import llm
from llm.default_plugins.openai_models import Chat
from llm.models import Prompt


@pytest.fixture
def chat_model():
    # A plain Chat instance with vision and tools enabled — enough
    # capabilities for the Part subtypes we translate.
    return Chat("gpt-4o-mini", vision=True, supports_tools=True)


class TestBuildMessagesFromExplicitMessages:
    def test_single_user_message(self, chat_model):
        prompt = Prompt(
            None, model=chat_model, messages=[llm.user("hi")]
        )
        result = chat_model.build_messages(prompt, None)
        assert result == [{"role": "user", "content": "hi"}]

    def test_system_plus_user(self, chat_model):
        prompt = Prompt(
            None,
            model=chat_model,
            messages=[llm.system("be brief"), llm.user("hi")],
        )
        result = chat_model.build_messages(prompt, None)
        assert result == [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"},
        ]

    def test_user_with_attachment(self, chat_model):
        att = llm.Attachment(
            type="image/jpeg", url="http://example.com/cat.jpg"
        )
        prompt = Prompt(
            None,
            model=chat_model,
            messages=[llm.user("describe", att)],
        )
        result = chat_model.build_messages(prompt, None)
        assert result == [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "http://example.com/cat.jpg"},
                    },
                ],
            }
        ]

    def test_assistant_with_tool_call(self, chat_model):
        tool_call = llm.ToolCallPart(
            name="search",
            arguments={"q": "weather"},
            tool_call_id="c1",
        )
        prompt = Prompt(
            None,
            model=chat_model,
            messages=[
                llm.user("search weather"),
                llm.assistant("on it", tool_call),
            ],
        )
        result = chat_model.build_messages(prompt, None)
        assert result == [
            {"role": "user", "content": "search weather"},
            {
                "role": "assistant",
                "content": "on it",
                "tool_calls": [
                    {
                        "type": "function",
                        "id": "c1",
                        "function": {
                            "name": "search",
                            "arguments": json.dumps({"q": "weather"}),
                        },
                    }
                ],
            },
        ]

    def test_assistant_tool_call_only_no_text(self, chat_model):
        """When an assistant message has tool_calls but no text, OpenAI
        expects content=null."""
        tool_call = llm.ToolCallPart(
            name="search", arguments={"q": "x"}, tool_call_id="c1"
        )
        prompt = Prompt(
            None,
            model=chat_model,
            messages=[llm.user("q"), llm.assistant(tool_call)],
        )
        result = chat_model.build_messages(prompt, None)
        assert result[1] == {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "type": "function",
                    "id": "c1",
                    "function": {
                        "name": "search",
                        "arguments": json.dumps({"q": "x"}),
                    },
                }
            ],
        }

    def test_tool_role_message_with_tool_result(self, chat_model):
        tr = llm.ToolResultPart(
            name="search", output="sunny", tool_call_id="c1"
        )
        prompt = Prompt(
            None,
            model=chat_model,
            messages=[
                llm.user("q"),
                llm.tool_message(tr),
            ],
        )
        result = chat_model.build_messages(prompt, None)
        assert result == [
            {"role": "user", "content": "q"},
            {"role": "tool", "tool_call_id": "c1", "content": "sunny"},
        ]

    def test_multiple_tool_results_emit_multiple_messages(self, chat_model):
        """Parallel tool results: one OpenAI 'tool' message per result."""
        a = llm.ToolResultPart(name="t", output="A", tool_call_id="c1")
        b = llm.ToolResultPart(name="t", output="B", tool_call_id="c2")
        prompt = Prompt(
            None,
            model=chat_model,
            messages=[llm.user("q"), llm.tool_message(a, b)],
        )
        result = chat_model.build_messages(prompt, None)
        assert result == [
            {"role": "user", "content": "q"},
            {"role": "tool", "tool_call_id": "c1", "content": "A"},
            {"role": "tool", "tool_call_id": "c2", "content": "B"},
        ]


class TestBuildMessagesLegacyFieldsStillWork:
    """prompt=, system=, attachments= keep working — they synthesize
    messages via Prompt.messages before build_messages sees them."""

    def test_prompt_only(self, chat_model):
        prompt = Prompt("hi", model=chat_model)
        result = chat_model.build_messages(prompt, None)
        assert result == [{"role": "user", "content": "hi"}]

    def test_system_and_prompt(self, chat_model):
        prompt = Prompt("hi", model=chat_model, system="be brief")
        result = chat_model.build_messages(prompt, None)
        assert result == [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"},
        ]

    def test_attachments(self, chat_model):
        att = llm.Attachment(type="image/jpeg", url="http://example.com/a.jpg")
        prompt = Prompt("look", model=chat_model, attachments=[att])
        result = chat_model.build_messages(prompt, None)
        assert result == [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "http://example.com/a.jpg"},
                    },
                ],
            }
        ]


class TestBuildMessagesSystemDedup:
    def test_same_system_not_repeated(self, chat_model):
        """If two turns share a system prompt, only the first emits it."""
        # Simulate a conversation with a prior response plus a current
        # turn; both have the same system prompt.
        from llm import Conversation, Response

        conv = Conversation(model=chat_model)
        prev_prompt = Prompt(
            "first question", model=chat_model, system="be brief"
        )
        prev_response = Response(prev_prompt, chat_model, stream=False)
        prev_response._chunks = ["first answer"]
        prev_response._done = True
        conv.responses = [prev_response]

        new_prompt = Prompt(
            "second question", model=chat_model, system="be brief"
        )

        result = chat_model.build_messages(new_prompt, conv)
        # System appears once.
        system_msgs = [m for m in result if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == "be brief"

    def test_system_change_emitted(self, chat_model):
        from llm import Conversation, Response

        conv = Conversation(model=chat_model)
        prev_prompt = Prompt(
            "q1", model=chat_model, system="be brief"
        )
        prev_response = Response(prev_prompt, chat_model, stream=False)
        prev_response._chunks = ["a1"]
        prev_response._done = True
        conv.responses = [prev_response]

        new_prompt = Prompt(
            "q2", model=chat_model, system="be expansive"
        )

        result = chat_model.build_messages(new_prompt, conv)
        system_msgs = [m for m in result if m["role"] == "system"]
        assert [m["content"] for m in system_msgs] == [
            "be brief",
            "be expansive",
        ]


class TestBuildMessagesConversationHistory:
    def test_prior_turn_text_plus_current_user(self, chat_model):
        from llm import Conversation, Response

        conv = Conversation(model=chat_model)
        prev_prompt = Prompt("what's 1+1?", model=chat_model)
        prev_response = Response(prev_prompt, chat_model, stream=False)
        prev_response._chunks = ["2"]
        prev_response._done = True
        conv.responses = [prev_response]

        new_prompt = Prompt("what about 2+2?", model=chat_model)
        result = chat_model.build_messages(new_prompt, conv)
        assert result == [
            {"role": "user", "content": "what's 1+1?"},
            {"role": "assistant", "content": "2"},
            {"role": "user", "content": "what about 2+2?"},
        ]
