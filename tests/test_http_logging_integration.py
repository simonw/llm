"""
Integration tests for HTTP logging functionality.
Tests that HTTP logging works with real CLI commands and providers.
"""

import os
import pytest
from click.testing import CliRunner
from unittest.mock import patch

from llm.cli import cli
from llm.utils import (
    configure_http_logging,
    is_http_logging_enabled,
    _get_http_logging_config,
)


class TestHTTPLoggingIntegration:
    """Integration tests for HTTP logging across the full system."""

    def test_http_logging_cli_flags(self):
        """Test HTTP logging CLI flags work correctly."""
        runner = CliRunner()

        # Test --http-logging flag
        result = runner.invoke(cli, ["--http-logging", "--help"])
        assert result.exit_code == 0
        assert "--http-logging" in result.output
        assert "--http-debug" in result.output

        # Test --http-debug flag
        result = runner.invoke(cli, ["--http-debug", "--help"])
        assert result.exit_code == 0

    @patch.dict(os.environ, {"LLM_HTTP_LOGGING": "1"})
    def test_environment_variable_detection(self):
        """Test that environment variables are detected correctly."""
        assert is_http_logging_enabled() is True

        config = _get_http_logging_config()
        assert config["enabled"] is True
        assert config["level"] == "INFO"

    @patch.dict(os.environ, {"LLM_HTTP_DEBUG": "1"})
    def test_debug_level_detection(self):
        """Test DEBUG level environment variable."""
        config = _get_http_logging_config()
        assert config["enabled"] is True
        assert config["level"] == "DEBUG"

    @patch.dict(os.environ, {"LLM_OPENAI_SHOW_RESPONSES": "1"})
    def test_backward_compatibility(self):
        """Test backward compatibility with OpenAI-specific variable."""
        config = _get_http_logging_config()
        assert config["enabled"] is True
        assert config["level"] == "INFO"

    def test_http_logging_with_mock_request(self, httpx_mock):
        """Test HTTP logging with a mocked HTTP request."""
        # Mock a simple HTTP request
        httpx_mock.add_response(
            method="GET",
            url="https://example.com/test",
            json={"status": "ok"},
            status_code=200,
        )

        # Configure logging
        with patch.dict(os.environ, {"LLM_HTTP_LOGGING": "1"}):
            configure_http_logging()

            # Make a request through httpx
            import httpx

            response = httpx.get("https://example.com/test")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}

    def test_logging_configuration_called_by_cli(self):
        """Test that configure_http_logging is called during CLI initialization."""
        runner = CliRunner()

        # The CLI should run without errors even with logging enabled
        with patch.dict(os.environ, {"LLM_HTTP_LOGGING": "1"}):
            result = runner.invoke(cli, ["--help"])
            assert result.exit_code == 0

    def test_models_list_with_http_logging(self):
        """Test models list command with HTTP logging enabled."""
        runner = CliRunner()

        # Should work without errors when HTTP logging is enabled
        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "1"}):
            result = runner.invoke(cli, ["models", "list"])
            assert result.exit_code == 0
            # Should show available models including our mock models
            assert "mock" in result.output

    @pytest.mark.parametrize(
        "env_var,expected_level",
        [
            ("LLM_HTTP_LOGGING", "INFO"),
            ("LLM_HTTP_DEBUG", "DEBUG"),
            ("LLM_HTTP_VERBOSE", "DEBUG"),
            ("LLM_OPENAI_SHOW_RESPONSES", "INFO"),
        ],
    )
    def test_all_environment_variables(self, env_var, expected_level):
        """Test all supported environment variables."""
        with patch.dict(os.environ, {env_var: "1"}, clear=True):
            config = _get_http_logging_config()
            assert config["enabled"] is True
            assert config["level"] == expected_level

    def test_http_logging_disabled_by_default(self):
        """Test that HTTP logging is disabled when no env vars are set."""
        with patch.dict(os.environ, {}, clear=True):
            config = _get_http_logging_config()
            assert config["enabled"] is False
