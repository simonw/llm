"""Tests for the OpenAI built-in plugin's messages= path.

Phase 4a covers build_messages reading prompt.messages (instead of the
legacy prompt.prompt / prompt.system / prompt.attachments fields), which
lets users pass structured message history via model.prompt(messages=[...]).

Phase 4b covers execute() yielding StreamEvent objects instead of plain
str — including tool_call_name + tool_call_args event streams.
"""

import json

import pytest
from pytest_httpx import IteratorStream

import llm
from llm.default_plugins.openai_models import Chat
from llm.models import Prompt


API_KEY = "badkey"


def _sse(delta, finish_reason=None, usage=None, tool_calls=None):
    chunk = {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "gpt-4o-mini",
        "choices": [
            {"index": 0, "delta": delta, "finish_reason": finish_reason}
        ],
    }
    if tool_calls is not None:
        chunk["choices"][0]["delta"]["tool_calls"] = tool_calls
    if usage is not None:
        chunk["usage"] = usage
    return f"data: {json.dumps(chunk)}\n\n".encode("utf-8")


def _text_stream():
    yield _sse({"role": "assistant", "content": ""})
    yield _sse({"content": "Hel"})
    yield _sse({"content": "lo"})
    yield _sse({}, finish_reason="stop")
    yield b"data: [DONE]\n\n"


def _tool_call_stream():
    """Mimic an OpenAI stream with a tool call (no preceding text)."""
    yield _sse({"role": "assistant", "content": None})
    yield _sse(
        {},
        tool_calls=[
            {
                "index": 0,
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": ""},
            }
        ],
    )
    yield _sse(
        {},
        tool_calls=[
            {
                "index": 0,
                "function": {"arguments": '{"city":'},
            }
        ],
    )
    yield _sse(
        {},
        tool_calls=[
            {
                "index": 0,
                "function": {"arguments": '"Paris"}'},
            }
        ],
    )
    yield _sse({}, finish_reason="tool_calls")
    yield b"data: [DONE]\n\n"


def _text_then_tool_call_stream():
    """Text arrives first, then a tool call — the tool call must get
    a part_index past the text so assembly doesn't mix families."""
    yield _sse({"role": "assistant", "content": ""})
    yield _sse({"content": "Looking up"})
    yield _sse(
        {},
        tool_calls=[
            {
                "index": 0,
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"c":1}'},
            }
        ],
    )
    yield _sse({}, finish_reason="tool_calls")
    yield b"data: [DONE]\n\n"


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


# -- Phase 4b: execute() yields StreamEvents ---------------------------


class TestStreamingExecuteYieldsStreamEvents:
    def test_text_stream_yields_text_events(self, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            stream=IteratorStream(_text_stream()),
            headers={"Content-Type": "text/event-stream"},
        )
        model = llm.get_model("gpt-4o-mini")
        response = model.prompt("hi", key=API_KEY)
        events = list(response.stream_events())
        # At least one StreamEvent, all text, all at part_index=0.
        assert events, "expected stream events"
        assert all(isinstance(e, llm.StreamEvent) for e in events)
        assert all(e.type == "text" for e in events)
        assert all(e.part_index == 0 for e in events)
        # Text chunks concatenate to the expected full text.
        assert "".join(e.chunk for e in events) == "Hello"

    def test_text_stream_plain_iteration_still_returns_strings(
        self, httpx_mock
    ):
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            stream=IteratorStream(_text_stream()),
            headers={"Content-Type": "text/event-stream"},
        )
        model = llm.get_model("gpt-4o-mini")
        response = model.prompt("hi", key=API_KEY)
        chunks = list(response)
        assert all(isinstance(c, str) for c in chunks)
        assert "".join(chunks) == "Hello"

    def test_text_stream_messages_assembled(self, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            stream=IteratorStream(_text_stream()),
            headers={"Content-Type": "text/event-stream"},
        )
        model = llm.get_model("gpt-4o-mini")
        response = model.prompt("hi", key=API_KEY)
        response.text()
        assert response.messages == [
            llm.Message(
                role="assistant", parts=[llm.TextPart(text="Hello")]
            )
        ]

    def test_tool_call_stream_yields_name_and_args_events(self, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            stream=IteratorStream(_tool_call_stream()),
            headers={"Content-Type": "text/event-stream"},
        )

        def get_weather(city: str) -> str:
            "Look up the weather."
            return "sunny"

        model = llm.get_model("gpt-4o-mini")
        response = model.prompt("weather?", tools=[get_weather], key=API_KEY)
        events = list(response.stream_events())
        types = [e.type for e in events]
        assert "tool_call_name" in types
        assert "tool_call_args" in types
        # Name event carries the tool_call_id and name.
        name_ev = next(e for e in events if e.type == "tool_call_name")
        assert name_ev.tool_call_id == "call_1"
        assert name_ev.chunk == "get_weather"
        # Args events share the same part_index and concatenate to
        # valid JSON.
        args_events = [e for e in events if e.type == "tool_call_args"]
        assert all(e.part_index == name_ev.part_index for e in args_events)
        assert json.loads("".join(e.chunk for e in args_events)) == {
            "city": "Paris"
        }

    def test_tool_call_registered_via_add_tool_call(self, httpx_mock):
        """response.tool_calls() still works — chain/execute relies on it."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            stream=IteratorStream(_tool_call_stream()),
            headers={"Content-Type": "text/event-stream"},
        )

        def get_weather(city: str) -> str:
            "Look up the weather."
            return "sunny"

        model = llm.get_model("gpt-4o-mini")
        response = model.prompt("weather?", tools=[get_weather], key=API_KEY)
        response.text()
        tcs = response.tool_calls()
        assert len(tcs) == 1
        assert tcs[0].name == "get_weather"
        assert tcs[0].arguments == {"city": "Paris"}
        assert tcs[0].tool_call_id == "call_1"

    def test_text_then_tool_call_part_index_advances(self, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            stream=IteratorStream(_text_then_tool_call_stream()),
            headers={"Content-Type": "text/event-stream"},
        )

        def get_weather(c: int) -> str:
            "Weather."
            return "sunny"

        model = llm.get_model("gpt-4o-mini")
        response = model.prompt("q", tools=[get_weather], key=API_KEY)
        response.text()
        # After streaming, messages has both a TextPart and a ToolCallPart.
        parts = response.messages[0].parts
        assert any(isinstance(p, llm.TextPart) for p in parts)
        assert any(isinstance(p, llm.ToolCallPart) for p in parts)
        text_part = next(p for p in parts if isinstance(p, llm.TextPart))
        tc_part = next(p for p in parts if isinstance(p, llm.ToolCallPart))
        assert text_part.text == "Looking up"
        assert tc_part.name == "get_weather"
        assert tc_part.arguments == {"c": 1}


class TestAsyncStreamingExecuteYieldsStreamEvents:
    @pytest.mark.asyncio
    async def test_text_stream_yields_text_events(self, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            stream=IteratorStream(_text_stream()),
            headers={"Content-Type": "text/event-stream"},
        )
        model = llm.get_async_model("gpt-4o-mini")
        response = model.prompt("hi", key=API_KEY)
        events = []
        async for event in response.astream_events():
            events.append(event)
        assert all(isinstance(e, llm.StreamEvent) for e in events)
        assert [e.type for e in events] == ["text"] * len(events)
        assert "".join(e.chunk for e in events) == "Hello"


class TestNonStreamingExecuteYieldsStreamEvents:
    def test_non_streaming_text_yields_single_event(self, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Hello"},
                        "finish_reason": "stop",
                    }
                ],
            },
            headers={"Content-Type": "application/json"},
        )
        model = llm.get_model("gpt-4o-mini")
        response = model.prompt("hi", key=API_KEY, stream=False)
        events = list(response.stream_events())
        assert events == [
            llm.StreamEvent(type="text", chunk="Hello", part_index=0)
        ]
        assert response.messages == [
            llm.Message(
                role="assistant", parts=[llm.TextPart(text="Hello")]
            )
        ]
