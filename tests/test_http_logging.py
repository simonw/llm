"""
Tests for universal HTTP logging functionality.

This module tests the HTTP logging system that enables debug visibility
into requests/responses across all LLM providers (OpenAI, Anthropic, Gemini, etc).
"""

import asyncio
import json
import logging
import os
import httpx
import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from llm.cli import cli
from llm.utils import (
    HTTPColorFormatter,
    SafeHTTPCoreFilter,
    SpinnerLogHandler,
    _get_http_logging_config,
    _log_request_tui,
    _log_request_tui_async,
    _log_response_tui,
    _log_response_tui_async,
    buffered_stream_end,
    configure_http_logging,
    is_http_logging_enabled,
)
import llm.utils


@pytest.fixture(autouse=True)
def _reset_http_logging_state():
    """Reset the idempotency guard between tests."""
    llm.utils._http_logging_configured = False
    llm.utils._active_tui_request_ids.set(())
    yield
    llm.utils._http_logging_configured = False
    llm.utils._active_tui_request_ids.set(())


class TestHTTPLoggingConfig:
    """Test HTTP logging configuration detection."""

    def test_logging_disabled_by_default(self):
        """HTTP logging should be disabled when no env vars are set."""
        with patch.dict(os.environ, {}, clear=True):
            config = _get_http_logging_config()
            assert config["enabled"] is False

    def test_debug_1_enables_info_level(self):
        """LLM_HTTP_DEBUG=1 should enable INFO level logging."""
        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "1"}, clear=True):
            config = _get_http_logging_config()
            assert config["enabled"] is True
            assert config["level"] == "INFO"

    def test_debug_2_enables_debug_level(self):
        """LLM_HTTP_DEBUG=2 should enable DEBUG level logging."""
        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "2"}, clear=True):
            config = _get_http_logging_config()
            assert config["enabled"] is True
            assert config["level"] == "DEBUG"

    def test_backward_compatibility_with_openai_flag(self):
        """LLM_OPENAI_SHOW_RESPONSES=1 should enable logging for backward compatibility."""
        with patch.dict(os.environ, {"LLM_OPENAI_SHOW_RESPONSES": "1"}, clear=True):
            config = _get_http_logging_config()
            assert config["enabled"] is True
            assert config["level"] == "INFO"

    def test_non_numeric_value_treated_as_level_1(self):
        """Non-numeric truthy values should be treated as level 1."""
        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "true"}, clear=True):
            config = _get_http_logging_config()
            assert config["enabled"] is True
            assert config["level"] == "INFO"

    def test_zero_disables_logging(self):
        """LLM_HTTP_DEBUG=0 should not enable logging."""
        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "0"}, clear=True):
            config = _get_http_logging_config()
            assert config["enabled"] is False


class TestHTTPLoggingConfiguration:
    """Test HTTP logging configuration setup."""

    def test_configure_http_logging_when_disabled(self):
        """configure_http_logging should do nothing when logging is disabled."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("logging.getLogger") as mock_get_logger:
                configure_http_logging()
                mock_get_logger.assert_not_called()

    def test_configure_http_logging_when_enabled(self):
        """configure_http_logging should set up loggers when enabled."""
        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "1"}, clear=True):
            with (
                patch("logging.getLogger") as mock_get_logger,
                patch("logging.basicConfig"),
                patch("logging.StreamHandler"),
            ):
                mock_logger = MagicMock()
                mock_get_logger.return_value = mock_logger

                configure_http_logging()

                logger_names = []
                for call in mock_get_logger.call_args_list:
                    if len(call.args) > 0:
                        logger_names.append(call.args[0])

                for logger_name in ["httpx", "httpcore", "openai", "anthropic"]:
                    assert logger_name in logger_names

    def test_configure_debug_level_loggers(self):
        """DEBUG level should configure additional loggers."""
        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "2"}, clear=True):
            with (
                patch("logging.getLogger") as mock_get_logger,
                patch("logging.basicConfig"),
                patch("logging.StreamHandler"),
            ):
                mock_logger = MagicMock()
                mock_get_logger.return_value = mock_logger

                configure_http_logging()

                logger_names = []
                for call in mock_get_logger.call_args_list:
                    if len(call.args) > 0:
                        logger_names.append(call.args[0])

                assert "urllib3" in logger_names
                assert "requests" in logger_names

    def test_is_http_logging_enabled_function(self):
        """is_http_logging_enabled should return correct boolean."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_http_logging_enabled() is False

        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "1"}):
            assert is_http_logging_enabled() is True


class TestCLIIntegration:
    """Test CLI integration with HTTP logging."""

    def test_cli_help_includes_debug_option(self):
        """CLI help should document the --debug option."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "--debug" in result.output
        assert "LLM_HTTP_DEBUG" in result.output

    def test_cli_debug_flag(self):
        """--debug flag should be accepted by CLI."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--debug", "1", "--help"])
        assert result.exit_code == 0

    def test_cli_help_succeeds(self):
        """CLI --help should exit 0."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0

    def test_cli_help_succeeds_with_http_debug_env(self):
        """CLI --help should exit 0 with LLM_HTTP_DEBUG set."""
        runner = CliRunner()
        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "1"}):
            result = runner.invoke(cli, ["--help"])
            assert result.exit_code == 0


class TestHTTPLoggingIntegration:
    """Test HTTP logging integration with real logging system."""

    def test_logging_setup_creates_handlers(self):
        """Test that logging setup actually creates handlers."""
        for logger_name in ["httpx", "httpcore", "llm.http"]:
            logger = logging.getLogger(logger_name)
            logger.handlers.clear()
            logger.setLevel(logging.NOTSET)

        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "1"}, clear=True):
            configure_http_logging()

            httpx_logger = logging.getLogger("httpx")
            assert httpx_logger.level == logging.INFO

            httpcore_logger = logging.getLogger("httpcore")
            assert httpcore_logger.level == logging.INFO

    def test_debug_level_configuration(self):
        """Test DEBUG level configuration (level 2)."""
        for logger_name in ["httpx", "httpcore"]:
            logger = logging.getLogger(logger_name)
            logger.handlers.clear()
            logger.setLevel(logging.NOTSET)

        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "2"}, clear=True):
            configure_http_logging()

            httpx_logger = logging.getLogger("httpx")
            assert httpx_logger.level == logging.DEBUG

            httpcore_logger = logging.getLogger("httpcore")
            assert httpcore_logger.level == logging.DEBUG


class TestHTTPLoggingDocumentation:
    """Test that HTTP logging is properly documented."""

    def test_cli_help_mentions_debug_levels(self):
        """CLI help should document debug levels."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "LLM_HTTP_DEBUG" in result.output

    def test_function_docstrings_are_comprehensive(self):
        """Test that key functions have good docstrings."""
        assert configure_http_logging.__doc__ is not None
        assert "httpx" in configure_http_logging.__doc__
        assert "httpcore" in configure_http_logging.__doc__
        assert "LLM_HTTP_DEBUG" in configure_http_logging.__doc__

        assert _get_http_logging_config.__doc__ is not None
        assert is_http_logging_enabled.__doc__ is not None


class TestSafeHTTPCoreFilter:
    """Test that the filter allows/suppresses the correct httpcore events.

    Uses the REAL event names that httpcore emits (receive_response_body,
    not response_body).
    """

    def setup_method(self):
        self.f = SafeHTTPCoreFilter()

    def _record(self, name, msg):
        return logging.LogRecord(name, logging.DEBUG, "", 0, msg, (), None)

    def test_allows_stream_start(self):
        r = self._record(
            "httpcore.http11",
            "receive_response_body.started request=<Request [b'POST']>",
        )
        assert self.f.filter(r) is True

    def test_allows_stream_end(self):
        r = self._record(
            "httpcore.http11", "receive_response_body.complete return_value=None"
        )
        assert self.f.filter(r) is True

    def test_allows_response_complete(self):
        r = self._record("httpcore.http11", "response_closed.complete")
        assert self.f.filter(r) is True

    def test_suppresses_request_body(self):
        r = self._record(
            "httpcore.http11", "send_request_body.started request=<Request [b'POST']>"
        )
        assert self.f.filter(r) is False

    def test_suppresses_response_headers(self):
        r = self._record(
            "httpcore.http11", "receive_response_headers.complete return_value=(...)"
        )
        assert self.f.filter(r) is False

    def test_suppresses_response_closed_started(self):
        r = self._record("httpcore.http11", "response_closed.started")
        assert self.f.filter(r) is False

    def test_allows_connection_events(self):
        r = self._record(
            "httpcore.connection", "connect_tcp.started host='api.openai.com' port=443"
        )
        assert self.f.filter(r) is True

    def test_allows_tls_events(self):
        r = self._record(
            "httpcore.connection", "start_tls.started server_hostname='api.openai.com'"
        )
        assert self.f.filter(r) is True


class TestHTTPColorFormatterMarkers:
    """Test that the formatter renders lifecycle markers from real httpcore events."""

    def setup_method(self):
        self.fmt = HTTPColorFormatter(use_colors=False)

    def _record(self, name, msg):
        r = logging.LogRecord(name, logging.DEBUG, "", 0, msg, (), None)
        r.msecs = 123
        return r

    def test_stream_start_marker(self):
        r = self._record(
            "httpcore.http11",
            "receive_response_body.started request=<Request [b'POST']>",
        )
        output = self.fmt.format(r)
        assert "Stream Start" in output
        assert "▼" in output

    def test_stream_end_marker(self):
        r = self._record(
            "httpcore.http11", "receive_response_body.complete return_value=None"
        )
        output = self.fmt.format(r)
        assert "Stream End" in output
        assert "■" in output

    def test_response_complete_marker(self):
        r = self._record("httpcore.http11", "response_closed.complete")
        output = self.fmt.format(r)
        assert "Response Complete" in output
        assert "✓" in output

    def test_markers_have_timestamps(self):
        r = self._record("httpcore.http11", "response_closed.complete")
        output = self.fmt.format(r)
        # Timestamp format is HH:MM:SS.mmm
        assert ".123" in output  # msecs we set

    def test_stream_start_skips_header(self):
        """Stream Start should render as a standalone banner, no logger header."""
        r = self._record("httpcore.http11", "receive_response_body.started request=<>")
        output = self.fmt.format(r)
        assert "httpcore" not in output

    def test_stream_end_skips_header(self):
        """Stream End should render as a standalone banner, no logger header."""
        r = self._record("httpcore.http11", "receive_response_body.complete")
        output = self.fmt.format(r)
        assert "httpcore" not in output

    def test_marker_spacing_single_leading_newline(self):
        """Markers should have exactly 1 leading \\n (one blank line before) and no trailing \\n."""
        r = self._record("httpcore.http11", "response_closed.complete")
        output = self.fmt.format(r)
        # format() owns the single leading \n; marker body has none
        assert output.startswith("\n")
        assert not output.startswith("\n\n")
        # No trailing newline — handler's terminator provides that
        assert not output.endswith("\n")

    def test_markers_include_request_id(self):
        """Correlated TUI events should carry their own request ID."""
        msg = 'TUI Event: {"kind": "stream_start", "request_id": "req-001"}'
        r = self._record("llm.http", msg)
        output = self.fmt.format(r)
        assert "[req-001]" in output

    def test_markers_omit_request_id_when_empty(self):
        """Markers should not include brackets when no request ID is set."""
        msg = 'TUI Event: {"kind": "response_complete", "request_id": ""}'
        r = self._record("llm.http", msg)
        output = self.fmt.format(r)
        assert "[]" not in output

    def test_interleaved_requests_keep_their_own_ids(self):
        """Markers should not inherit the most recently seen request ID."""
        req2 = self._record(
            "llm.http",
            'TUI Event: {"kind": "request", "request_id": "req-002", "method": "POST", "url": "https://two", "headers": {}}',
        )
        self.fmt.format(req2)

        req1_done = self._record(
            "llm.http",
            'TUI Event: {"kind": "response_complete", "request_id": "req-001"}',
        )
        output = self.fmt.format(req1_done)
        assert "[req-001]" in output
        assert "[req-002]" not in output


class TestBufferedStreamEnd:
    """Test the buffered_stream_end context manager."""

    def setup_method(self):
        self.fmt = HTTPColorFormatter(use_colors=False)

    def _record(self, msg):
        r = logging.LogRecord("httpcore.http11", logging.DEBUG, "", 0, msg, (), None)
        r.msecs = 0
        return r

    def test_defers_stream_end(self):
        with buffered_stream_end() as get_pending:
            r = self._record("receive_response_body.complete")
            output = self.fmt.format(r)
            assert output == ""  # suppressed
            pending = get_pending()
            assert len(pending) == 1
            assert "Stream End" in pending[0]

    def test_defers_response_complete(self):
        with buffered_stream_end() as get_pending:
            r = self._record("response_closed.complete")
            output = self.fmt.format(r)
            assert output == ""
            pending = get_pending()
            assert len(pending) == 1
            assert "Response Complete" in pending[0]

    def test_defers_both_in_order(self):
        with buffered_stream_end() as get_pending:
            self.fmt.format(self._record("receive_response_body.complete"))
            self.fmt.format(self._record("response_closed.complete"))
            pending = get_pending()
            assert len(pending) == 2
            assert "Stream End" in pending[0]
            assert "Response Complete" in pending[1]

    def test_does_not_defer_stream_start(self):
        with buffered_stream_end() as get_pending:
            r = self._record("receive_response_body.started request=<>")
            output = self.fmt.format(r)
            assert "Stream Start" in output  # not deferred
            assert len(get_pending()) == 0

    def test_clears_on_exit(self):
        """Pending messages are cleared when the context exits."""
        with buffered_stream_end() as _get_pending:
            self.fmt.format(self._record("response_closed.complete"))
        # After exiting, deferral is off
        r = self._record("response_closed.complete")
        output = self.fmt.format(r)
        assert "Response Complete" in output  # not deferred


class TestConfigureIdempotent:
    """Test that configure_http_logging is idempotent."""

    def test_second_call_does_not_add_handlers(self):
        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "1"}, clear=True):
            configure_http_logging()
            logger = logging.getLogger("httpcore")
            handler_count = len(logger.handlers)

            configure_http_logging()
            assert len(logger.handlers) == handler_count

    def test_propagate_is_false(self):
        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "1"}, clear=True):
            configure_http_logging()
            for name in ["httpcore", "httpx", "openai"]:
                assert logging.getLogger(name).propagate is False

    def test_subsequent_call_updates_levels(self):
        """Second call with different LLM_HTTP_DEBUG should update log levels."""
        for name in ["httpx", "httpcore"]:
            logging.getLogger(name).handlers.clear()
            logging.getLogger(name).setLevel(logging.NOTSET)

        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "1"}, clear=True):
            configure_http_logging()
            assert logging.getLogger("httpcore").level == logging.INFO

        # Call again with level 2 — latch is already set from the first call
        with patch.dict(os.environ, {"LLM_HTTP_DEBUG": "2"}, clear=True):
            configure_http_logging()
            assert logging.getLogger("httpcore").level == logging.DEBUG


class TestTUIEventFiltering:
    def test_suppresses_raw_openai_response_when_tui_request_active(self):
        llm.utils._active_tui_request_ids.set(("req-001",))
        record = logging.LogRecord(
            "openai._base_client",
            logging.DEBUG,
            "",
            0,
            'HTTP Response: POST https://api.openai.com/v1/chat/completions "200 OK"',
            (),
            None,
        )
        assert SafeHTTPCoreFilter().filter(record) is False


class TestTUIEventHooks:
    def test_log_request_tui_emits_request_event_and_sets_extensions(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        with patch("llm.utils._log_tui_event") as mock_log:
            _log_request_tui(request)

        assert request.extensions["llm_request_id"].startswith("req-")
        assert callable(request.extensions["trace"])
        kind = mock_log.call_args.args[0]
        kwargs = mock_log.call_args.kwargs
        assert kind == "request"
        assert kwargs["request_id"] == request.extensions["llm_request_id"]

    def test_trace_callback_emits_lifecycle_events(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        _log_request_tui(request)
        trace = request.extensions["trace"]
        request_id = request.extensions["llm_request_id"]

        with patch("llm.utils._log_tui_event") as mock_log:
            trace("http11.connect_tcp.started", {"host": "api.openai.com", "port": 443})
            trace("http11.send_request_headers.started", {"request": request})
            trace("http11.receive_response_body.started", {})
            trace("http11.receive_response_body.complete", {})
            trace("http11.response_closed.complete", {})

        calls = [(call.args[0], call.kwargs) for call in mock_log.call_args_list]
        assert [kind for kind, _ in calls] == [
            "connect",
            "request_sent",
            "stream_start",
            "stream_end",
            "response_complete",
        ]
        assert all(kwargs["request_id"] == request_id for _, kwargs in calls)

    def test_log_response_tui_emits_response_start(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        request.extensions["llm_request_id"] = "req-123"
        response = httpx.Response(
            200,
            headers={"x-request-id": "req_openai"},
            request=request,
        )
        with patch("llm.utils._log_tui_event") as mock_log:
            _log_response_tui(response)

        assert mock_log.call_args.args[0] == "response_start"
        kwargs = mock_log.call_args.kwargs
        assert kwargs["request_id"] == "req-123"
        assert kwargs["status"].startswith("200")
        assert kwargs["headers"]["x-request-id"] == "req_openai"

    def test_async_hooks_mirror_sync_hooks(self):
        async def run():
            request = httpx.Request(
                "POST", "https://api.openai.com/v1/chat/completions"
            )
            await _log_request_tui_async(request)
            trace = request.extensions["trace"]
            await trace("http11.receive_response_body.started", {})
            response = httpx.Response(200, request=request)
            await _log_response_tui_async(response)
            return request

        with patch("llm.utils._log_tui_event") as mock_log:
            request = asyncio.run(run())

        assert request.extensions["llm_request_id"].startswith("req-")
        kinds = [call.args[0] for call in mock_log.call_args_list]
        assert kinds[0] == "request"
        assert "stream_start" in kinds
        assert "response_start" in kinds


class TestStructuredTUIFormatting:
    def setup_method(self):
        self.fmt = HTTPColorFormatter(use_colors=False)

    def _record(self, payload):
        record = logging.LogRecord(
            "llm.http",
            logging.DEBUG,
            "",
            0,
            f"TUI Event: {json.dumps(payload)}",
            (),
            None,
        )
        record.msecs = 222
        return record

    def test_formats_connect_event(self):
        output = self.fmt.format(
            self._record(
                {
                    "kind": "connect",
                    "request_id": "req-001",
                    "host": "api.openai.com",
                    "port": 443,
                }
            )
        )
        assert "Connection [req-001]" in output
        assert "host: api.openai.com" in output

    def test_formats_tls_event(self):
        output = self.fmt.format(
            self._record(
                {
                    "kind": "tls",
                    "request_id": "req-001",
                    "server_hostname": "api.openai.com",
                }
            )
        )
        assert "TLS Handshake [req-001]" in output
        assert "server_hostname: api.openai.com" in output

    def test_formats_request_sent_event(self):
        output = self.fmt.format(
            self._record(
                {"kind": "request_sent", "request_id": "req-001", "method": "POST"}
            )
        )
        assert "Request [req-001]" in output
        assert "Sending POST Request" in output

    def test_formats_response_start_event(self):
        output = self.fmt.format(
            self._record(
                {
                    "kind": "response_start",
                    "request_id": "req-001",
                    "method": "POST",
                    "url": "https://api.openai.com/v1/chat/completions",
                    "status": "200 OK",
                    "headers": {"x-request-id": "req_openai"},
                }
            )
        )
        assert "Response Start [req-001]" in output
        assert "x-request-id: req_openai" in output


class TestHTTPColorFormatterTruncation:
    def setup_method(self):
        self.fmt = HTTPColorFormatter(use_colors=False)

    def test_truncates_long_json_values_before_whole_body(self):
        payload = {
            "model": "gpt-5.4",
            "messages": [
                {"role": "system", "content": "x" * 900},
                {"role": "user", "content": "what models do you use?"},
            ],
            "stream": True,
        }

        output = self.fmt._format_json(payload, colored=False)

        assert '"model": "gpt-5.4"' in output
        assert '"stream": true' in output
        assert "[truncated, 900 chars total]" in output

    def test_no_truncate_env_disables_value_and_body_truncation(self):
        payload = {"content": "x" * 900}

        with patch.dict(os.environ, {"LLM_HTTP_NO_TRUNCATE": "1"}, clear=True):
            output = self.fmt._format_json(payload, colored=False)

        assert "[truncated," not in output
        assert '"content": "' + ("x" * 900) + '"' in output

    def test_body_limit_can_be_configured_with_env_var(self):
        payload = {"model": "gpt-5.4", "content": "x" * 300}

        with patch.dict(
            os.environ,
            {"LLM_HTTP_MAX_BODY_CHARS": "80", "LLM_HTTP_MAX_VALUE_CHARS": "80"},
            clear=True,
        ):
            output = self.fmt._format_json(payload, colored=False)

        assert "[truncated, " in output
        assert len(output.splitlines()[0]) <= 81

    def test_value_limit_can_be_disabled_with_negative_env_var(self):
        payload = {"content": "x" * 200}

        with patch.dict(
            os.environ,
            {"LLM_HTTP_MAX_VALUE_CHARS": "-1", "LLM_HTTP_MAX_BODY_CHARS": "-1"},
            clear=True,
        ):
            output = self.fmt._format_json(payload, colored=False)

        assert "[truncated," not in output
        assert '"content": "' + ("x" * 200) + '"' in output


class TestSpinnerLogHandler:
    class FakeSpinner:
        def __init__(self):
            self.states = []
            self.started = 0
            self.stopped = 0
            self._running = False

        def start(self):
            self.started += 1
            self._running = True

        def stop(self):
            self.stopped += 1
            self._running = False

        def set_state(self, state, **kwargs):
            self.states.append((state, kwargs))

        @property
        def is_running(self):
            return self._running

    def test_llm_http_events_drive_spinner_lifecycle(self):
        spinner = self.FakeSpinner()
        handler = SpinnerLogHandler(spinner)
        events = [
            'TUI Event: {"kind": "request", "request_id": "req-001"}',
            'TUI Event: {"kind": "connect", "request_id": "req-001"}',
            'TUI Event: {"kind": "request_sent", "request_id": "req-001"}',
            'TUI Event: {"kind": "response_start", "request_id": "req-001"}',
        ]
        for message in events:
            record = logging.LogRecord(
                "llm.http", logging.DEBUG, "", 0, message, (), None
            )
            handler.emit(record)

        assert spinner.started == 1
        assert spinner.states == [
            ("starting", {}),
            ("connecting", {}),
            ("waiting", {}),
        ]
        assert spinner.stopped == 1

    def test_httpcore_fallback_still_updates_spinner(self):
        spinner = self.FakeSpinner()
        handler = SpinnerLogHandler(spinner)
        connect = logging.LogRecord(
            "httpcore.connection",
            logging.DEBUG,
            "",
            0,
            "connect_tcp.started host='api.openai.com' port=443",
            (),
            None,
        )
        request = logging.LogRecord(
            "httpcore.http11",
            logging.DEBUG,
            "",
            0,
            "send_request_headers.started request=<Request [b'POST']>",
            (),
            None,
        )
        handler.emit(connect)
        handler.emit(request)
        assert spinner.states == [("connecting", {}), ("waiting", {})]

    def test_suppresses_raw_httpcore_lifecycle_when_tui_request_active(self):
        llm.utils._active_tui_request_ids.set(("req-001",))
        record = logging.LogRecord(
            "httpcore.http11",
            logging.DEBUG,
            "",
            0,
            "receive_response_body.started request=<>",
            (),
            None,
        )
        assert SafeHTTPCoreFilter().filter(record) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
