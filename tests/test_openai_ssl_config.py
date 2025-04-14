import os
from unittest import mock
import pytest

# Import the function we're testing
from llm.default_plugins.openai_models import _configure_ssl_client


@pytest.fixture
def mock_environ():
    with mock.patch.dict(os.environ, {}, clear=True):
        yield


@mock.patch("openai.DefaultHttpxClient")
@mock.patch("httpx.HTTPTransport")
def test_default_ssl_config(mock_transport, mock_client, mock_environ):
    # Test that without any environment variables, no special SSL config is returned
    ssl_client = _configure_ssl_client("test-model")
    assert ssl_client is None


@mock.patch("openai.DefaultHttpxClient")
@mock.patch("httpx.HTTPTransport")
def test_env_var_native_tls(mock_transport, mock_client, mock_environ):
    # Set up mocks
    mock_client_instance = mock.MagicMock()
    mock_client.return_value = mock_client_instance

    # Set the environment variable
    os.environ["LLM_SSL_CONFIG"] = "native_tls"

    # Test the helper function
    ssl_client = _configure_ssl_client("test-model")

    # Should return the mock client
    assert ssl_client is mock_client_instance
    # Verify transport was created with verify=True
    mock_transport.assert_called_once_with(verify=True)


@mock.patch("openai.DefaultHttpxClient")
@mock.patch("httpx.HTTPTransport")
def test_env_var_no_verify(mock_transport, mock_client, mock_environ):
    # Set up mocks
    mock_client_instance = mock.MagicMock()
    mock_client.return_value = mock_client_instance

    # Set the environment variable
    os.environ["LLM_SSL_CONFIG"] = "no_verify"

    # Test the helper function
    ssl_client = _configure_ssl_client("test-model")

    # Should return the mock client
    assert ssl_client is mock_client_instance
    # Verify transport was created with verify=False
    mock_transport.assert_called_once_with(verify=False)


@mock.patch("openai.DefaultHttpxClient")
@mock.patch("httpx.HTTPTransport")
@mock.patch("os.path.exists")
def test_env_var_ca_bundle(mock_exists, mock_transport, mock_client, mock_environ):
    # Set up mocks
    mock_client_instance = mock.MagicMock()
    mock_client.return_value = mock_client_instance
    mock_exists.return_value = True

    # Set environment variable
    os.environ["LLM_CA_BUNDLE"] = "/path/to/ca-bundle.pem"

    # Test the helper function
    ssl_client = _configure_ssl_client("test-model")

    # Should return the mock client
    assert ssl_client is mock_client_instance
    # Verify transport was created with verify pointing to certificate
    mock_transport.assert_called_once_with(verify="/path/to/ca-bundle.pem")


def test_invalid_ssl_config(mock_environ):
    # Set an invalid ssl_config value
    os.environ["LLM_SSL_CONFIG"] = "invalid_value"

    # Should raise a warning and return None
    with pytest.warns(UserWarning, match="Invalid ssl_config value"):
        ssl_client = _configure_ssl_client("test-model")
        assert ssl_client is None


@mock.patch("os.path.exists")
def test_missing_ca_bundle(mock_exists, mock_environ):
    # Set a non-existent certificate file
    os.environ["LLM_CA_BUNDLE"] = "/nonexistent/path/to/cert.pem"
    mock_exists.return_value = False

    # Should raise a warning and return None
    with pytest.warns(UserWarning, match="Certificate file not found"):
        ssl_client = _configure_ssl_client("test-model")
        assert ssl_client is None


# Integration test with mocked dependencies
class MockShared:
    def __init__(self, model_id):
        self.model_id = model_id
        self.needs_key = None
        self.api_base = None
        self.api_type = None
        self.api_version = None
        self.api_engine = None
        self.headers = None

    def get_key(self, key):
        return "mock-key"

    def get_client(self, key, *, async_=False):
        # Simple implementation that should call _configure_ssl_client
        # and pass the result to OpenAI
        from llm.default_plugins.openai_models import _configure_ssl_client, openai

        kwargs = {"api_key": self.get_key(key)}

        ssl_client = _configure_ssl_client(self.model_id)
        if ssl_client:
            kwargs["http_client"] = ssl_client

        if async_:
            return openai.AsyncOpenAI(**kwargs)
        else:
            return openai.OpenAI(**kwargs)


@mock.patch("llm.default_plugins.openai_models._Shared", MockShared)
@mock.patch("llm.default_plugins.openai_models._configure_ssl_client")
@mock.patch("llm.default_plugins.openai_models.openai.OpenAI")
def test_get_client_with_ssl(mock_openai, mock_ssl_client):
    # Import shared class after mocking
    from llm.default_plugins.openai_models import _Shared

    # Set up a mock ssl client
    mock_ssl = mock.MagicMock()
    mock_ssl_client.return_value = mock_ssl

    # Create a client
    shared = _Shared("test-model")
    shared.needs_key = "openai"
    shared.get_client(key="dummy-key")

    # _configure_ssl_client should be called with the model_id
    mock_ssl_client.assert_called_once_with("test-model")

    # OpenAI client should be called with http_client parameter
    mock_openai.assert_called_once()
    kwargs = mock_openai.call_args[1]
    assert kwargs["http_client"] == mock_ssl
