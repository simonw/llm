"""
Tests for llm/responses.py - OpenResponses API client implementation.

Tests for the OpenResponses API client.
"""

import json
import pytest
from unittest.mock import MagicMock
from pytest_httpx import IteratorStream

from llm.responses import (
    # Pydantic models
    ResponseResource,
    Usage,
    OutputItem,
    OutputTextContent,
    # Streaming events
    ResponseCreatedEvent,
    ResponseCompletedEvent,
    ResponseOutputTextDeltaEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    # Error classes
    ResponsesAPIError,
    ResponsesAuthenticationError,
    ResponsesRateLimitError,
    ResponsesInvalidRequestError,
    # Model classes
    ResponsesModel,
    AsyncResponsesModel,
    # Utilities
    parse_sse_event,
)


# Test fixtures


@pytest.fixture
def sample_response_json():
    """Sample non-streaming response from the API."""
    return {
        "id": "resp_123abc",
        "object": "response",
        "created_at": 1741476777,
        "completed_at": 1741476778,
        "status": "completed",
        "model": "gpt-4o",
        "incomplete_details": None,
        "previous_response_id": None,
        "instructions": None,
        "input": [],
        "output": [
            {
                "type": "message",
                "id": "msg_123",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Hello, world!",
                        "annotations": [],
                    }
                ],
            }
        ],
        "error": None,
        "tools": [],
        "tool_choice": "auto",
        "truncation": "disabled",
        "parallel_tool_calls": True,
        "text": {"format": {"type": "text"}},
        "top_p": 1.0,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "top_logprobs": 0,
        "temperature": 1.0,
        "reasoning": None,
        "user": None,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        "max_output_tokens": None,
        "max_tool_calls": None,
        "store": False,
        "background": False,
        "service_tier": "default",
        "metadata": {},
        "safety_identifier": None,
        "prompt_cache_key": None,
    }


@pytest.fixture
def sample_streaming_events():
    """Sample SSE streaming events from the API."""
    return [
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": {
                "id": "resp_123abc",
                "object": "response",
                "created_at": 1741476777,
                "completed_at": None,
                "status": "in_progress",
                "model": "gpt-4o",
                "incomplete_details": None,
                "previous_response_id": None,
                "instructions": None,
                "input": [],
                "output": [],
                "error": None,
                "tools": [],
                "tool_choice": "auto",
                "truncation": "disabled",
                "parallel_tool_calls": True,
                "text": {"format": {"type": "text"}},
                "top_p": 1.0,
                "presence_penalty": 0.0,
                "frequency_penalty": 0.0,
                "top_logprobs": 0,
                "temperature": 1.0,
                "reasoning": None,
                "user": None,
                "usage": None,
                "max_output_tokens": None,
                "max_tool_calls": None,
                "store": False,
                "background": False,
                "service_tier": "default",
                "metadata": {},
                "safety_identifier": None,
                "prompt_cache_key": None,
            },
        },
        {
            "type": "response.output_item.added",
            "sequence_number": 1,
            "output_index": 0,
            "item": {
                "type": "message",
                "id": "msg_123",
                "status": "in_progress",
                "role": "assistant",
                "content": [],
            },
        },
        {
            "type": "response.output_text.delta",
            "sequence_number": 2,
            "item_id": "msg_123",
            "output_index": 0,
            "content_index": 0,
            "delta": "Hello",
            "logprobs": [],
        },
        {
            "type": "response.output_text.delta",
            "sequence_number": 3,
            "item_id": "msg_123",
            "output_index": 0,
            "content_index": 0,
            "delta": ", world!",
            "logprobs": [],
        },
        {
            "type": "response.completed",
            "sequence_number": 4,
            "response": {
                "id": "resp_123abc",
                "object": "response",
                "created_at": 1741476777,
                "completed_at": 1741476778,
                "status": "completed",
                "model": "gpt-4o",
                "incomplete_details": None,
                "previous_response_id": None,
                "instructions": None,
                "input": [],
                "output": [
                    {
                        "type": "message",
                        "id": "msg_123",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Hello, world!",
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "error": None,
                "tools": [],
                "tool_choice": "auto",
                "truncation": "disabled",
                "parallel_tool_calls": True,
                "text": {"format": {"type": "text"}},
                "top_p": 1.0,
                "presence_penalty": 0.0,
                "frequency_penalty": 0.0,
                "top_logprobs": 0,
                "temperature": 1.0,
                "reasoning": None,
                "user": None,
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
                "max_output_tokens": None,
                "max_tool_calls": None,
                "store": False,
                "background": False,
                "service_tier": "default",
                "metadata": {},
                "safety_identifier": None,
                "prompt_cache_key": None,
            },
        },
    ]


def make_sse_stream(events):
    """Convert a list of event dicts to SSE format bytes generator."""
    for event in events:
        yield f"data: {json.dumps(event)}\n\n".encode("utf-8")


# Test Pydantic Models


class TestPydanticModels:
    """Tests for Pydantic model parsing and validation."""

    def test_usage_model(self):
        """Test Usage model parsing."""
        usage_data = {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "input_tokens_details": {"cached_tokens": 10},
            "output_tokens_details": {"reasoning_tokens": 5},
        }
        usage = Usage(**usage_data)
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.total_tokens == 150

    def test_output_text_content_model(self):
        """Test OutputTextContent model parsing."""
        content_data = {
            "type": "output_text",
            "text": "Hello, world!",
            "annotations": [],
        }
        content = OutputTextContent(**content_data)
        assert content.type == "output_text"
        assert content.text == "Hello, world!"

    def test_output_item_message(self):
        """Test OutputItem model for message type."""
        item_data = {
            "type": "message",
            "id": "msg_123",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "Hello!",
                    "annotations": [],
                }
            ],
        }
        item = OutputItem(**item_data)
        assert item.type == "message"
        assert item.id == "msg_123"
        assert item.role == "assistant"

    def test_response_resource_model(self, sample_response_json):
        """Test ResponseResource model parsing."""
        response = ResponseResource(**sample_response_json)
        assert response.id == "resp_123abc"
        assert response.object == "response"
        assert response.status == "completed"
        assert response.model == "gpt-4o"
        assert len(response.output) == 1
        assert response.output[0].type == "message"

    def test_response_resource_with_usage(self, sample_response_json):
        """Test ResponseResource with usage data."""
        response = ResponseResource(**sample_response_json)
        assert response.usage is not None
        assert response.usage.input_tokens == 10
        assert response.usage.output_tokens == 5


# Test Streaming Event Models


class TestStreamingEvents:
    """Tests for streaming event model parsing."""

    def test_response_created_event(self, sample_streaming_events):
        """Test parsing response.created event."""
        event_data = sample_streaming_events[0]
        event = ResponseCreatedEvent(**event_data)
        assert event.type == "response.created"
        assert event.sequence_number == 0
        assert event.response.id == "resp_123abc"

    def test_response_output_text_delta_event(self, sample_streaming_events):
        """Test parsing response.output_text.delta event."""
        event_data = sample_streaming_events[2]
        event = ResponseOutputTextDeltaEvent(**event_data)
        assert event.type == "response.output_text.delta"
        assert event.delta == "Hello"
        assert event.item_id == "msg_123"
        assert event.output_index == 0
        assert event.content_index == 0

    def test_response_completed_event(self, sample_streaming_events):
        """Test parsing response.completed event."""
        event_data = sample_streaming_events[4]
        event = ResponseCompletedEvent(**event_data)
        assert event.type == "response.completed"
        assert event.response.status == "completed"
        assert event.response.usage.input_tokens == 10

    def test_parse_sse_event_text_delta(self):
        """Test parse_sse_event with text delta."""
        line = 'data: {"type": "response.output_text.delta", "sequence_number": 1, "item_id": "msg_1", "output_index": 0, "content_index": 0, "delta": "Hi", "logprobs": []}'
        event = parse_sse_event(line)
        assert isinstance(event, ResponseOutputTextDeltaEvent)
        assert event.delta == "Hi"

    def test_parse_sse_event_created(self, sample_streaming_events):
        """Test parse_sse_event with response.created."""
        line = f"data: {json.dumps(sample_streaming_events[0])}"
        event = parse_sse_event(line)
        assert isinstance(event, ResponseCreatedEvent)

    def test_parse_sse_event_completed(self, sample_streaming_events):
        """Test parse_sse_event with response.completed."""
        line = f"data: {json.dumps(sample_streaming_events[4])}"
        event = parse_sse_event(line)
        assert isinstance(event, ResponseCompletedEvent)


# Test Function Call Events


class TestFunctionCallEvents:
    """Tests for function call streaming events."""

    def test_function_call_arguments_delta_event(self):
        """Test parsing function call arguments delta event."""
        event_data = {
            "type": "response.function_call_arguments.delta",
            "sequence_number": 5,
            "item_id": "fc_123",
            "output_index": 0,
            "delta": '{"na',
        }
        event = ResponseFunctionCallArgumentsDeltaEvent(**event_data)
        assert event.type == "response.function_call_arguments.delta"
        assert event.delta == '{"na'
        assert event.item_id == "fc_123"

    def test_function_call_arguments_done_event(self):
        """Test parsing function call arguments done event."""
        event_data = {
            "type": "response.function_call_arguments.done",
            "sequence_number": 6,
            "item_id": "fc_123",
            "output_index": 0,
            "arguments": '{"name": "test"}',
        }
        event = ResponseFunctionCallArgumentsDoneEvent(**event_data)
        assert event.type == "response.function_call_arguments.done"
        assert event.arguments == '{"name": "test"}'


# Test Error Classes


class TestErrorClasses:
    """Tests for custom error classes."""

    def test_responses_api_error(self):
        """Test base ResponsesAPIError."""
        error = ResponsesAPIError("Something went wrong", status_code=500)
        assert str(error) == "Something went wrong"
        assert error.status_code == 500

    def test_responses_authentication_error(self):
        """Test ResponsesAuthenticationError."""
        error = ResponsesAuthenticationError("Invalid API key")
        assert isinstance(error, ResponsesAPIError)
        assert error.status_code == 401

    def test_responses_rate_limit_error(self):
        """Test ResponsesRateLimitError."""
        error = ResponsesRateLimitError("Rate limit exceeded")
        assert isinstance(error, ResponsesAPIError)
        assert error.status_code == 429

    def test_responses_invalid_request_error(self):
        """Test ResponsesInvalidRequestError."""
        error = ResponsesInvalidRequestError("Invalid parameter")
        assert isinstance(error, ResponsesAPIError)
        assert error.status_code == 400


# Test Sync Model


class TestResponsesModel:
    """Tests for the synchronous ResponsesModel class."""

    def test_model_init(self):
        """Test model initialization."""
        model = ResponsesModel(
            model_id="gpt-4o",
            api_base="https://api.example.com/v1",
        )
        assert model.model_id == "gpt-4o"
        assert model.api_base == "https://api.example.com/v1"
        assert model.needs_key == "openresponses"

    def test_model_default_api_base(self):
        """Test model uses default OpenAI API base."""
        model = ResponsesModel(model_id="gpt-4o")
        assert model.api_base == "https://api.openai.com/v1"

    @pytest.fixture
    def mocked_non_streaming_response(self, httpx_mock, sample_response_json):
        """Mock a non-streaming response."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/responses",
            json=sample_response_json,
            headers={"Content-Type": "application/json"},
        )
        return httpx_mock

    @pytest.fixture
    def mocked_streaming_response(self, httpx_mock, sample_streaming_events):
        """Mock a streaming response."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/responses",
            stream=IteratorStream(make_sse_stream(sample_streaming_events)),
            headers={"Content-Type": "text/event-stream"},
        )
        return httpx_mock

    def test_execute_non_streaming(self, mocked_non_streaming_response):
        """Test non-streaming execution."""
        model = ResponsesModel(model_id="gpt-4o")

        # Create a mock prompt and response
        from llm import Prompt

        prompt = Prompt(
            prompt="Hello",
            model=model,
            options=model.Options(),
        )

        # Mock the llm Response object
        mock_response = MagicMock()
        mock_response.response_json = None

        # Execute
        chunks = list(
            model.execute(
                prompt,
                stream=False,
                response=mock_response,
                conversation=None,
                key="test-key",
            )
        )

        assert chunks == ["Hello, world!"]

    def test_execute_streaming(self, mocked_streaming_response):
        """Test streaming execution yields text deltas."""
        model = ResponsesModel(model_id="gpt-4o")

        from llm import Prompt

        prompt = Prompt(
            prompt="Hello",
            model=model,
            options=model.Options(),
        )

        mock_response = MagicMock()
        mock_response.response_json = None

        chunks = list(
            model.execute(
                prompt,
                stream=True,
                response=mock_response,
                conversation=None,
                key="test-key",
            )
        )

        # Should yield the text deltas
        assert chunks == ["Hello", ", world!"]

    def test_execute_sets_usage(self, mocked_non_streaming_response):
        """Test that execution sets usage on response."""
        model = ResponsesModel(model_id="gpt-4o")

        from llm import Prompt

        prompt = Prompt(
            prompt="Hello",
            model=model,
            options=model.Options(),
        )

        mock_response = MagicMock()
        mock_response.response_json = None

        list(
            model.execute(
                prompt,
                stream=False,
                response=mock_response,
                conversation=None,
                key="test-key",
            )
        )

        # Check that set_usage was called
        mock_response.set_usage.assert_called()

    @pytest.fixture
    def mocked_error_response(self, httpx_mock):
        """Mock an error response."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/responses",
            status_code=401,
            json={
                "error": {"message": "Invalid API key", "type": "authentication_error"}
            },
            headers={"Content-Type": "application/json"},
        )
        return httpx_mock

    def test_execute_authentication_error(self, mocked_error_response):
        """Test that authentication errors raise ResponsesAuthenticationError."""
        model = ResponsesModel(model_id="gpt-4o")

        from llm import Prompt

        prompt = Prompt(
            prompt="Hello",
            model=model,
            options=model.Options(),
        )

        mock_response = MagicMock()

        with pytest.raises(ResponsesAuthenticationError):
            list(
                model.execute(
                    prompt,
                    stream=False,
                    response=mock_response,
                    conversation=None,
                    key="bad-key",
                )
            )


# Test Async Model


class TestAsyncResponsesModel:
    """Tests for the asynchronous AsyncResponsesModel class."""

    def test_async_model_init(self):
        """Test async model initialization."""
        model = AsyncResponsesModel(
            model_id="gpt-4o",
            api_base="https://api.example.com/v1",
        )
        assert model.model_id == "gpt-4o"
        assert model.api_base == "https://api.example.com/v1"
        assert model.needs_key == "openresponses"

    @pytest.fixture
    def mocked_async_non_streaming_response(self, httpx_mock, sample_response_json):
        """Mock an async non-streaming response."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/responses",
            json=sample_response_json,
            headers={"Content-Type": "application/json"},
        )
        return httpx_mock

    @pytest.fixture
    def mocked_async_streaming_response(self, httpx_mock, sample_streaming_events):
        """Mock an async streaming response."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/responses",
            stream=IteratorStream(make_sse_stream(sample_streaming_events)),
            headers={"Content-Type": "text/event-stream"},
        )
        return httpx_mock

    @pytest.mark.asyncio
    async def test_async_execute_non_streaming(
        self, mocked_async_non_streaming_response
    ):
        """Test async non-streaming execution."""
        model = AsyncResponsesModel(model_id="gpt-4o")

        from llm import Prompt

        prompt = Prompt(
            prompt="Hello",
            model=model,
            options=model.Options(),
        )

        mock_response = MagicMock()
        mock_response.response_json = None

        chunks = []
        async for chunk in model.execute(
            prompt,
            stream=False,
            response=mock_response,
            conversation=None,
            key="test-key",
        ):
            chunks.append(chunk)

        assert chunks == ["Hello, world!"]

    @pytest.mark.asyncio
    async def test_async_execute_streaming(self, mocked_async_streaming_response):
        """Test async streaming execution yields text deltas."""
        model = AsyncResponsesModel(model_id="gpt-4o")

        from llm import Prompt

        prompt = Prompt(
            prompt="Hello",
            model=model,
            options=model.Options(),
        )

        mock_response = MagicMock()
        mock_response.response_json = None

        chunks = []
        async for chunk in model.execute(
            prompt,
            stream=True,
            response=mock_response,
            conversation=None,
            key="test-key",
        ):
            chunks.append(chunk)

        assert chunks == ["Hello", ", world!"]


# Test Tool Calls


class TestToolCalls:
    """Tests for tool call handling."""

    @pytest.fixture
    def tool_call_streaming_events(self):
        """Sample streaming events with a tool call."""
        return [
            {
                "type": "response.created",
                "sequence_number": 0,
                "response": {
                    "id": "resp_456",
                    "object": "response",
                    "created_at": 1741476777,
                    "completed_at": None,
                    "status": "in_progress",
                    "model": "gpt-4o",
                    "incomplete_details": None,
                    "previous_response_id": None,
                    "instructions": None,
                    "input": [],
                    "output": [],
                    "error": None,
                    "tools": [
                        {
                            "type": "function",
                            "name": "get_weather",
                            "description": "Get weather for a location",
                            "parameters": {
                                "type": "object",
                                "properties": {"location": {"type": "string"}},
                            },
                        }
                    ],
                    "tool_choice": "auto",
                    "truncation": "disabled",
                    "parallel_tool_calls": True,
                    "text": {"format": {"type": "text"}},
                    "top_p": 1.0,
                    "presence_penalty": 0.0,
                    "frequency_penalty": 0.0,
                    "top_logprobs": 0,
                    "temperature": 1.0,
                    "reasoning": None,
                    "user": None,
                    "usage": None,
                    "max_output_tokens": None,
                    "max_tool_calls": None,
                    "store": False,
                    "background": False,
                    "service_tier": "default",
                    "metadata": {},
                    "safety_identifier": None,
                    "prompt_cache_key": None,
                },
            },
            {
                "type": "response.output_item.added",
                "sequence_number": 1,
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": "fc_789",
                    "status": "in_progress",
                    "call_id": "call_abc",
                    "name": "get_weather",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.delta",
                "sequence_number": 2,
                "item_id": "fc_789",
                "output_index": 0,
                "delta": '{"loc',
            },
            {
                "type": "response.function_call_arguments.delta",
                "sequence_number": 3,
                "item_id": "fc_789",
                "output_index": 0,
                "delta": 'ation": "NYC"}',
            },
            {
                "type": "response.function_call_arguments.done",
                "sequence_number": 4,
                "item_id": "fc_789",
                "output_index": 0,
                "arguments": '{"location": "NYC"}',
            },
            {
                "type": "response.output_item.done",
                "sequence_number": 5,
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": "fc_789",
                    "status": "completed",
                    "call_id": "call_abc",
                    "name": "get_weather",
                    "arguments": '{"location": "NYC"}',
                },
            },
            {
                "type": "response.completed",
                "sequence_number": 6,
                "response": {
                    "id": "resp_456",
                    "object": "response",
                    "created_at": 1741476777,
                    "completed_at": 1741476778,
                    "status": "completed",
                    "model": "gpt-4o",
                    "incomplete_details": None,
                    "previous_response_id": None,
                    "instructions": None,
                    "input": [],
                    "output": [
                        {
                            "type": "function_call",
                            "id": "fc_789",
                            "status": "completed",
                            "call_id": "call_abc",
                            "name": "get_weather",
                            "arguments": '{"location": "NYC"}',
                        }
                    ],
                    "error": None,
                    "tools": [],
                    "tool_choice": "auto",
                    "truncation": "disabled",
                    "parallel_tool_calls": True,
                    "text": {"format": {"type": "text"}},
                    "top_p": 1.0,
                    "presence_penalty": 0.0,
                    "frequency_penalty": 0.0,
                    "top_logprobs": 0,
                    "temperature": 1.0,
                    "reasoning": None,
                    "user": None,
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 10,
                        "total_tokens": 30,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens_details": {"reasoning_tokens": 0},
                    },
                    "max_output_tokens": None,
                    "max_tool_calls": None,
                    "store": False,
                    "background": False,
                    "service_tier": "default",
                    "metadata": {},
                    "safety_identifier": None,
                    "prompt_cache_key": None,
                },
            },
        ]

    @pytest.fixture
    def mocked_tool_call_response(self, httpx_mock, tool_call_streaming_events):
        """Mock a streaming response with tool calls."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/responses",
            stream=IteratorStream(make_sse_stream(tool_call_streaming_events)),
            headers={"Content-Type": "text/event-stream"},
        )
        return httpx_mock

    def test_tool_call_streaming(self, mocked_tool_call_response):
        """Test that tool calls are properly extracted from streaming response."""
        model = ResponsesModel(model_id="gpt-4o")

        from llm import Prompt

        prompt = Prompt(
            prompt="What's the weather in NYC?",
            model=model,
            options=model.Options(),
        )

        mock_response = MagicMock()
        mock_response.response_json = None

        # Consume all chunks
        chunks = list(
            model.execute(
                prompt,
                stream=True,
                response=mock_response,
                conversation=None,
                key="test-key",
            )
        )

        # Tool calls don't yield text, so chunks should be empty
        assert chunks == []

        # But tool_calls should be set on the response
        mock_response.add_tool_call.assert_called()


# Test Options


class TestModelOptions:
    """Tests for model options."""

    def test_temperature_option(self):
        """Test temperature option."""
        model = ResponsesModel(model_id="gpt-4o")
        options = model.Options(temperature=0.5)
        assert options.temperature == 0.5

    def test_max_tokens_option(self):
        """Test max_output_tokens option."""
        model = ResponsesModel(model_id="gpt-4o")
        options = model.Options(max_output_tokens=100)
        assert options.max_output_tokens == 100

    def test_top_p_option(self):
        """Test top_p option."""
        model = ResponsesModel(model_id="gpt-4o")
        options = model.Options(top_p=0.9)
        assert options.top_p == 0.9


# Test Conversation/Multi-turn


class TestConversation:
    """Tests for conversation/multi-turn support."""

    def test_build_input_from_conversation(self):
        """Test building input array from conversation history."""
        model = ResponsesModel(model_id="gpt-4o")

        # This tests the internal method that converts conversation to input items
        # The actual implementation will use previous_response_id or input array
        conversation_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]

        input_items = model._build_input_items(conversation_messages)

        assert len(input_items) == 3
        assert input_items[0]["type"] == "message"
        assert input_items[0]["role"] == "user"


# Test SSE Parser


class TestSSEParser:
    """Tests for SSE parsing utilities."""

    def test_parse_empty_line(self):
        """Test that empty lines return None."""
        assert parse_sse_event("") is None
        assert parse_sse_event("\n") is None

    def test_parse_comment_line(self):
        """Test that comment lines return None."""
        assert parse_sse_event(": this is a comment") is None

    def test_parse_done_event(self):
        """Test that [DONE] event returns None."""
        assert parse_sse_event("data: [DONE]") is None

    def test_parse_invalid_json(self):
        """Test that invalid JSON raises an error."""
        with pytest.raises(json.JSONDecodeError):
            parse_sse_event("data: {invalid json}")
