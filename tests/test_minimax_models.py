"""Tests for the MiniMax models default plugin."""

import json

from click.testing import CliRunner
from llm.cli import cli
from llm.default_plugins.minimax_models import (
    MiniMaxChat,
    MiniMaxAsyncChat,
    MiniMaxOptions,
    MINIMAX_API_BASE,
)
import pytest
from pytest_httpx import IteratorStream


# ---------------------------------------------------------------------------
# Unit tests – model registration, options, and string representation
# ---------------------------------------------------------------------------


class TestModelRegistration:
    """Verify MiniMax models appear in the model registry."""

    def test_minimax_m3_registered(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["models", "list"])
        assert result.exit_code == 0
        assert "MiniMax-M3" in result.output

    def test_minimax_m27_registered(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["models", "list"])
        assert result.exit_code == 0
        assert "MiniMax-M2.7" in result.output

    def test_minimax_m27_highspeed_registered(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["models", "list"])
        assert result.exit_code == 0
        assert "MiniMax-M2.7-highspeed" in result.output

    def test_minimax_m25_removed(self):
        """Older MiniMax-M2.5 models should no longer be registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["models", "list"])
        assert result.exit_code == 0
        assert "MiniMax-M2.5" not in result.output
        assert "MiniMax-M2.5-highspeed" not in result.output

    def test_minimax_aliases(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["aliases", "list"])
        assert result.exit_code == 0
        assert "minimax" in result.output
        assert "m3" in result.output
        assert "m2.7" in result.output
        assert "minimax-fast" in result.output
        assert "m2.7-highspeed" in result.output

    def test_minimax_default_alias_points_to_m3(self):
        """The 'minimax' alias should resolve to MiniMax-M3."""
        runner = CliRunner()
        result = runner.invoke(cli, ["aliases", "list"])
        assert result.exit_code == 0
        for line in result.output.splitlines():
            if line.strip().startswith("minimax"):
                assert "MiniMax-M3" in line
                break

    def test_m3_registered_before_m27(self):
        """M3 should appear before M2.7 in the model list."""
        runner = CliRunner()
        result = runner.invoke(cli, ["models", "list"])
        assert result.exit_code == 0
        m3_pos = result.output.index("MiniMax-M3")
        m27_pos = result.output.index("MiniMax-M2.7")
        assert m3_pos < m27_pos


class TestMiniMaxChatModel:
    """Verify MiniMaxChat model attributes."""

    def test_needs_key(self):
        model = MiniMaxChat("test-model", api_base=MINIMAX_API_BASE)
        assert model.needs_key == "minimax"

    def test_key_env_var(self):
        model = MiniMaxChat("test-model", api_base=MINIMAX_API_BASE)
        assert model.key_env_var == "MINIMAX_API_KEY"

    def test_str(self):
        model = MiniMaxChat("MiniMax-M3", api_base=MINIMAX_API_BASE)
        assert str(model) == "MiniMax Chat: MiniMax-M3"

    def test_api_base(self):
        model = MiniMaxChat("MiniMax-M3", api_base=MINIMAX_API_BASE)
        assert model.api_base == "https://api.minimax.io/v1"

    def test_m3_supports_vision(self):
        """MiniMax-M3 should accept image attachments."""
        model = MiniMaxChat("MiniMax-M3", api_base=MINIMAX_API_BASE, vision=True)
        assert "image/png" in model.attachment_types
        assert "image/jpeg" in model.attachment_types


class TestMiniMaxAsyncChatModel:
    """Verify MiniMaxAsyncChat model attributes."""

    def test_needs_key(self):
        model = MiniMaxAsyncChat("test-model", api_base=MINIMAX_API_BASE)
        assert model.needs_key == "minimax"

    def test_key_env_var(self):
        model = MiniMaxAsyncChat("test-model", api_base=MINIMAX_API_BASE)
        assert model.key_env_var == "MINIMAX_API_KEY"

    def test_str(self):
        model = MiniMaxAsyncChat("MiniMax-M3", api_base=MINIMAX_API_BASE)
        assert str(model) == "MiniMax Chat: MiniMax-M3"


class TestMiniMaxOptions:
    """Verify MiniMax-specific option constraints."""

    def test_temperature_valid(self):
        opts = MiniMaxOptions(temperature=0.5)
        assert opts.temperature == 0.5

    def test_temperature_max(self):
        opts = MiniMaxOptions(temperature=1.0)
        assert opts.temperature == 1.0

    def test_temperature_near_zero(self):
        opts = MiniMaxOptions(temperature=0.01)
        assert opts.temperature == 0.01

    def test_temperature_zero_rejected(self):
        with pytest.raises(Exception):
            MiniMaxOptions(temperature=0)

    def test_temperature_above_one_rejected(self):
        with pytest.raises(Exception):
            MiniMaxOptions(temperature=1.5)

    def test_temperature_negative_rejected(self):
        with pytest.raises(Exception):
            MiniMaxOptions(temperature=-0.5)

    def test_json_object_option(self):
        opts = MiniMaxOptions(json_object=True)
        assert opts.json_object is True


# ---------------------------------------------------------------------------
# Unit tests – mocked HTTP calls (non-streaming)
# ---------------------------------------------------------------------------


MINIMAX_CHAT_URL = "https://api.minimax.io/v1/chat/completions"


@pytest.fixture
def mocked_minimax_chat(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url=MINIMAX_CHAT_URL,
        json={
            "id": "chatcmpl-minimax-001",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "MiniMax-M3",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello from MiniMax!",
                        "refusal": None,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        },
        headers={"Content-Type": "application/json"},
    )
    return httpx_mock


class TestMiniMaxNonStreaming:
    """Test MiniMax models with mocked non-streaming HTTP responses."""

    def test_minimax_prompt(self, mocked_minimax_chat):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "-m",
                "MiniMax-M3",
                "--key",
                "test-key",
                "--no-stream",
                "Hello",
            ],
        )
        assert result.exit_code == 0
        assert "Hello from MiniMax!" in result.output

    def test_minimax_alias(self, mocked_minimax_chat):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["-m", "minimax", "--key", "test-key", "--no-stream", "Hello"],
        )
        assert result.exit_code == 0
        assert "Hello from MiniMax!" in result.output

    def test_minimax_with_system_prompt(self, mocked_minimax_chat):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "-m",
                "MiniMax-M3",
                "--key",
                "test-key",
                "--no-stream",
                "-s",
                "You are helpful.",
                "Hello",
            ],
        )
        assert result.exit_code == 0
        assert "Hello from MiniMax!" in result.output

    def test_minimax_with_temperature(self, mocked_minimax_chat):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "-m",
                "MiniMax-M3",
                "--key",
                "test-key",
                "--no-stream",
                "-o",
                "temperature",
                "0.7",
                "Hello",
            ],
        )
        assert result.exit_code == 0

    def test_minimax_temperature_zero_cli(self):
        """Temperature=0 should fail validation for MiniMax."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "-m",
                "MiniMax-M3",
                "--key",
                "test-key",
                "--no-stream",
                "-o",
                "temperature",
                "0",
                "Hello",
            ],
        )
        assert result.exit_code == 1
        assert "greater than 0" in result.output

    def test_minimax_temperature_above_one_cli(self):
        """Temperature>1 should fail validation for MiniMax."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "-m",
                "MiniMax-M3",
                "--key",
                "test-key",
                "--no-stream",
                "-o",
                "temperature",
                "1.5",
                "Hello",
            ],
        )
        assert result.exit_code == 1
        assert "less than or equal to 1" in result.output


# ---------------------------------------------------------------------------
# Unit tests – mocked HTTP calls (streaming)
# ---------------------------------------------------------------------------


def minimax_stream_events():
    """Generate SSE events mimicking MiniMax streaming response."""
    for delta, finish_reason in (
        ({"role": "assistant", "content": ""}, None),
        ({"content": "Streaming"}, None),
        ({"content": " from"}, None),
        ({"content": " MiniMax!"}, None),
        ({}, "stop"),
    ):
        yield "data: {}\n\n".format(
            json.dumps(
                {
                    "id": "chatcmpl-minimax-stream-001",
                    "object": "chat.completion.chunk",
                    "created": 1700000000,
                    "model": "MiniMax-M3",
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "finish_reason": finish_reason,
                        }
                    ],
                }
            )
        ).encode("utf-8")
    yield "data: [DONE]\n\n".encode("utf-8")


@pytest.fixture
def mocked_minimax_chat_stream(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url=MINIMAX_CHAT_URL,
        stream=IteratorStream(minimax_stream_events()),
        headers={"Content-Type": "text/event-stream"},
    )
    return httpx_mock


class TestMiniMaxStreaming:
    """Test MiniMax models with mocked streaming HTTP responses."""

    def test_minimax_stream(self, mocked_minimax_chat_stream):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["-m", "MiniMax-M3", "--key", "test-key", "Hello"],
        )
        assert result.exit_code == 0
        assert "Streaming from MiniMax!" in result.output


# ---------------------------------------------------------------------------
# Unit tests – highspeed model variant
# ---------------------------------------------------------------------------


@pytest.fixture
def mocked_minimax_highspeed(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url=MINIMAX_CHAT_URL,
        json={
            "id": "chatcmpl-minimax-hs-001",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "MiniMax-M2.7-highspeed",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Fast response from MiniMax!",
                        "refusal": None,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 8,
                "completion_tokens": 6,
                "total_tokens": 14,
            },
        },
        headers={"Content-Type": "application/json"},
    )
    return httpx_mock


class TestMiniMaxHighspeed:
    """Test MiniMax-M2.7-highspeed model variant."""

    def test_highspeed_prompt(self, mocked_minimax_highspeed):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "-m",
                "MiniMax-M2.7-highspeed",
                "--key",
                "test-key",
                "--no-stream",
                "Hello",
            ],
        )
        assert result.exit_code == 0
        assert "Fast response from MiniMax!" in result.output

    def test_highspeed_alias(self, mocked_minimax_highspeed):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "-m",
                "minimax-fast",
                "--key",
                "test-key",
                "--no-stream",
                "Hello",
            ],
        )
        assert result.exit_code == 0
        assert "Fast response from MiniMax!" in result.output


# ---------------------------------------------------------------------------
# Unit tests – usage tracking
# ---------------------------------------------------------------------------


class TestMiniMaxUsage:
    """Test that token usage is properly tracked."""

    def test_usage_reported(self, monkeypatch, tmpdir, mocked_minimax_chat):
        user_path = tmpdir / "user_dir"
        monkeypatch.setenv("LLM_USER_PATH", str(user_path))
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "-m",
                "MiniMax-M3",
                "--key",
                "test-key",
                "--no-stream",
                "-u",
                "Hello",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "Hello from MiniMax!" in result.output
        assert "Token usage: 10 input, 5 output" in result.output


# ---------------------------------------------------------------------------
# Integration tests – live API calls (skipped unless MINIMAX_API_KEY is set)
# ---------------------------------------------------------------------------


@pytest.fixture
def minimax_api_key():
    import os

    key = os.environ.get("MINIMAX_API_KEY")
    if not key:
        pytest.skip("MINIMAX_API_KEY not set")
    return key


class TestMiniMaxIntegration:
    """Integration tests that call the real MiniMax API."""

    @pytest.mark.integration
    def test_live_prompt_m3(self, minimax_api_key):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "-m",
                "MiniMax-M3",
                "--key",
                minimax_api_key,
                "--no-stream",
                "Say hello in exactly three words.",
            ],
        )
        assert result.exit_code == 0
        assert len(result.output.strip()) > 0

    @pytest.mark.integration
    def test_live_prompt_m27(self, minimax_api_key):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "-m",
                "MiniMax-M2.7",
                "--key",
                minimax_api_key,
                "--no-stream",
                "Say hello in exactly three words.",
            ],
        )
        assert result.exit_code == 0
        assert len(result.output.strip()) > 0

    @pytest.mark.integration
    def test_live_stream(self, minimax_api_key):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "-m",
                "MiniMax-M3",
                "--key",
                minimax_api_key,
                "What is 2+2? Answer with just the number.",
            ],
        )
        assert result.exit_code == 0
        assert "4" in result.output

    @pytest.mark.integration
    def test_live_highspeed(self, minimax_api_key):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "-m",
                "MiniMax-M2.7-highspeed",
                "--key",
                minimax_api_key,
                "--no-stream",
                "Say hi.",
            ],
        )
        assert result.exit_code == 0
        assert len(result.output.strip()) > 0
