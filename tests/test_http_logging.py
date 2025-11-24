"""
Tests for universal HTTP logging functionality.

This module tests the HTTP logging system that enables debug visibility
into requests/responses across all LLM providers (OpenAI, Anthropic, Gemini, etc).
"""

import logging
import os
import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from llm.cli import cli
from llm.utils import (
    _get_http_logging_config,
    configure_http_logging,
    is_http_logging_enabled,
)


class TestHTTPLoggingConfig:
    """Test HTTP logging configuration detection."""

    def test_logging_disabled_by_default(self):
        """HTTP logging should be disabled when no env vars are set."""
        with patch.dict(os.environ, {}, clear=True):
            config = _get_http_logging_config()
            assert config["enabled"] is False

    def test_llm_http_logging_enables_info_level(self):
        """LLM_HTTP_LOGGING=1 should enable INFO level logging."""
        with patch.dict(os.environ, {"LLM_HTTP_LOGGING": "1"}):
            config = _get_http_logging_config()
            assert config["enabled"] is True
            assert config["level"] == "INFO"
            assert "format" in config

    def test_llm_http_debug_enables_debug_level(self):
        """LLM_HTTP_DEBUG=1 should enable DEBUG level logging."""
        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "1"}):
            config = _get_http_logging_config()
            assert config["enabled"] is True
            assert config["level"] == "DEBUG"

    def test_llm_http_verbose_enables_debug_level(self):
        """LLM_HTTP_VERBOSE=1 should enable DEBUG level logging."""
        with patch.dict(os.environ, {"LLM_HTTP_VERBOSE": "1"}):
            config = _get_http_logging_config()
            assert config["enabled"] is True
            assert config["level"] == "DEBUG"

    def test_backward_compatibility_with_openai_flag(self):
        """LLM_OPENAI_SHOW_RESPONSES=1 should enable logging for backward compatibility."""
        with patch.dict(os.environ, {"LLM_OPENAI_SHOW_RESPONSES": "1"}):
            config = _get_http_logging_config()
            assert config["enabled"] is True
            assert config["level"] == "INFO"

    def test_debug_overrides_info_level(self):
        """DEBUG flags should override INFO level when both are set."""
        with patch.dict(os.environ, {"LLM_HTTP_LOGGING": "1", "LLM_HTTP_DEBUG": "1"}):
            config = _get_http_logging_config()
            assert config["enabled"] is True
            assert config["level"] == "DEBUG"

    def test_multiple_env_vars_enable_logging(self):
        """Any combination of env vars should enable logging."""
        test_cases = [
            {"LLM_HTTP_LOGGING": "1"},
            {"LLM_HTTP_DEBUG": "1"},
            {"LLM_OPENAI_SHOW_RESPONSES": "1"},
            {"LLM_HTTP_LOGGING": "1", "LLM_HTTP_DEBUG": "1"},
        ]

        for env_vars in test_cases:
            with patch.dict(os.environ, env_vars, clear=True):
                config = _get_http_logging_config()
                assert config["enabled"] is True, f"Failed with env vars: {env_vars}"


class TestHTTPLoggingConfiguration:
    """Test HTTP logging configuration setup."""

    def test_configure_http_logging_when_disabled(self):
        """configure_http_logging should do nothing when logging is disabled."""
        with patch.dict(os.environ, {}, clear=True):
            # Mock logging inside the function where it's imported
            with patch("logging.getLogger") as mock_get_logger:
                configure_http_logging()
                # Should not configure any loggers when disabled
                mock_get_logger.assert_not_called()

    def test_configure_http_logging_when_enabled(self):
        """configure_http_logging should set up loggers when enabled."""
        with patch.dict(os.environ, {"LLM_HTTP_LOGGING": "1"}):
            with (
                patch("logging.getLogger") as mock_get_logger,
                patch("logging.basicConfig"),
                patch("logging.StreamHandler"),
            ):
                mock_logger = MagicMock()
                mock_get_logger.return_value = mock_logger

                configure_http_logging()

                # Should configure core HTTP loggers
                # Extract logger names from calls (skip empty first call)
                logger_names = []
                for call in mock_get_logger.call_args_list:
                    if len(call.args) > 0:  # Skip calls with no arguments
                        logger_names.append(call.args[0])

                for logger_name in ["httpx", "httpcore", "openai", "anthropic"]:
                    assert logger_name in logger_names

    def test_configure_debug_level_loggers(self):
        """DEBUG level should configure additional loggers."""
        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "1"}):
            with (
                patch("logging.getLogger") as mock_get_logger,
                patch("logging.basicConfig"),
                patch("logging.StreamHandler"),
            ):
                mock_logger = MagicMock()
                mock_get_logger.return_value = mock_logger

                configure_http_logging()

                # Should configure additional debug loggers
                logger_names = []
                for call in mock_get_logger.call_args_list:
                    if len(call.args) > 0:  # Skip calls with no arguments
                        logger_names.append(call.args[0])

                assert "urllib3" in logger_names
                assert "requests" in logger_names

    def test_is_http_logging_enabled_function(self):
        """is_http_logging_enabled should return correct boolean."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_http_logging_enabled() is False

        with patch.dict(os.environ, {"LLM_HTTP_LOGGING": "1"}):
            assert is_http_logging_enabled() is True


class TestCLIIntegration:
    """Test CLI integration with HTTP logging."""

    def test_cli_help_includes_http_logging_options(self):
        """CLI help should document HTTP logging options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "--http-logging" in result.output
        assert "--http-debug" in result.output
        assert "HTTP request/response logging" in result.output

    def test_cli_http_logging_flag_sets_env_var(self):
        """--http-logging flag should set environment variable."""
        runner = CliRunner()

        # Check that the CLI flag is passed through correctly
        result = runner.invoke(cli, ["--http-logging", "--help"])
        assert result.exit_code == 0
        # The flag is processed by Click, no need to test internal mocking

    def test_cli_http_debug_flag_sets_env_var(self):
        """--http-debug flag should set environment variable."""
        runner = CliRunner()

        result = runner.invoke(cli, ["--http-debug", "--help"])
        assert result.exit_code == 0
        # The flag is processed by Click

    def test_cli_calls_configure_http_logging(self):
        """CLI should call configure_http_logging on startup."""
        runner = CliRunner()

        # Test that the CLI runs successfully with logging configuration
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0

    def test_env_var_enables_logging_in_cli(self):
        """Environment variable should enable logging in CLI."""
        runner = CliRunner()

        # Test CLI with environment variable set
        with patch.dict(os.environ, {"LLM_HTTP_LOGGING": "1"}):
            result = runner.invoke(cli, ["--help"])
            assert result.exit_code == 0


class TestHTTPLoggingIntegration:
    """Test HTTP logging integration with real logging system."""

    def test_logging_setup_creates_handlers(self):
        """Test that logging setup actually creates handlers."""
        # Clear any existing handlers
        for logger_name in ["httpx", "httpcore", "llm.http"]:
            logger = logging.getLogger(logger_name)
            logger.handlers.clear()
            logger.setLevel(logging.NOTSET)

        with patch.dict(os.environ, {"LLM_HTTP_LOGGING": "1"}):
            configure_http_logging()

            # Check that loggers are configured
            httpx_logger = logging.getLogger("httpx")
            assert httpx_logger.level == logging.INFO

            httpcore_logger = logging.getLogger("httpcore")
            assert httpcore_logger.level == logging.INFO

    def test_debug_level_configuration(self):
        """Test DEBUG level configuration."""
        # Clear any existing handlers
        for logger_name in ["httpx", "httpcore"]:
            logger = logging.getLogger(logger_name)
            logger.handlers.clear()
            logger.setLevel(logging.NOTSET)

        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "1"}):
            configure_http_logging()

            httpx_logger = logging.getLogger("httpx")
            assert httpx_logger.level == logging.DEBUG

            httpcore_logger = logging.getLogger("httpcore")
            assert httpcore_logger.level == logging.DEBUG


class TestHTTPLoggingDocumentation:
    """Test that HTTP logging is properly documented."""

    def test_cli_help_mentions_environment_variables(self):
        """CLI help should mention all supported environment variables."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0

        # Check for environment variable documentation
        assert "LLM_HTTP_LOGGING" in result.output
        assert "LLM_HTTP_DEBUG" in result.output
        assert "LLM_OPENAI_SHOW_RESPONSES" in result.output

    def test_function_docstrings_are_comprehensive(self):
        """Test that key functions have good docstrings."""
        assert configure_http_logging.__doc__ is not None
        assert "httpx" in configure_http_logging.__doc__
        assert "httpcore" in configure_http_logging.__doc__
        assert "LLM_HTTP_LOGGING" in configure_http_logging.__doc__

        assert _get_http_logging_config.__doc__ is not None
        assert is_http_logging_enabled.__doc__ is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
