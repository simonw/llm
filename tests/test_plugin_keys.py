"""Tests for the plugin keys functionality in the CLI.

These tests verify that the keys_plugin_keys function correctly identifies
and displays key information for installed plugins.
"""

from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from llm.cli import cli


def test_keys_plugin_keys_empty(monkeypatch, tmpdir):
    """Test keys_plugin_keys when no plugins with keys are installed"""
    # Set up an isolated environment
    user_path = tmpdir / "user"
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    
    # Create a mock for get_models_with_aliases
    mock_models = []
    
    with patch("llm.get_models_with_aliases", return_value=mock_models):
        runner = CliRunner()
        result = runner.invoke(cli, ["keys", "plugin-keys"])
        
        # Verify the command executed successfully
        assert result.exit_code == 0
        # Verify no output was produced
        assert result.output.strip() == ""


def test_keys_plugin_keys_single_plugin(monkeypatch, tmpdir):
    """Test keys_plugin_keys with a single plugin that has a key"""
    # Set up an isolated environment
    user_path = tmpdir / "user"
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    
    # Create a mock model
    mock_model = MagicMock()
    mock_model.needs_key = "test-plugin-key"
    mock_model.key_env_var = "TEST_API_KEY"
    mock_model.__class__.__module__ = "test_plugin.models"
    
    # Create a mock model with aliases
    mock_model_with_aliases = MagicMock()
    mock_model_with_aliases.model = mock_model
    
    # Create a mock for get_models_with_aliases
    mock_models = [mock_model_with_aliases]
    
    with patch("llm.get_models_with_aliases", return_value=mock_models):
        runner = CliRunner()
        result = runner.invoke(cli, ["keys", "plugin-keys"])
        
        # Verify the command executed successfully
        assert result.exit_code == 0
        # Verify the output
        assert "test_plugin: test-plugin-key (env: TEST_API_KEY)" in result.output


def test_keys_plugin_keys_multiple_plugins(monkeypatch, tmpdir):
    """Test keys_plugin_keys with multiple plugins that have keys"""
    # Set up an isolated environment
    user_path = tmpdir / "user"
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    
    # Create mock models from different plugins
    mock_model1 = MagicMock()
    mock_model1.needs_key = "test-plugin-key-1"
    mock_model1.key_env_var = "TEST_API_KEY_1"
    mock_model1.__class__.__module__ = "plugin1.models"
    
    mock_model2 = MagicMock()
    mock_model2.needs_key = "test-plugin-key-2"
    mock_model2.key_env_var = "TEST_API_KEY_2"
    mock_model2.__class__.__module__ = "plugin2.models"
    
    # Create mock models with aliases
    mock_model_with_aliases1 = MagicMock()
    mock_model_with_aliases1.model = mock_model1
    
    mock_model_with_aliases2 = MagicMock()
    mock_model_with_aliases2.model = mock_model2
    
    # Create a mock for get_models_with_aliases
    mock_models = [mock_model_with_aliases1, mock_model_with_aliases2]
    
    with patch("llm.get_models_with_aliases", return_value=mock_models):
        runner = CliRunner()
        result = runner.invoke(cli, ["keys", "plugin-keys"])
        
        # Verify the command executed successfully
        assert result.exit_code == 0
        # Verify the output
        assert "plugin1: test-plugin-key-1 (env: TEST_API_KEY_1)" in result.output
        assert "plugin2: test-plugin-key-2 (env: TEST_API_KEY_2)" in result.output


def test_keys_plugin_keys_multiple_models_same_plugin(monkeypatch, tmpdir):
    """Test keys_plugin_keys with multiple models from the same plugin"""
    # Set up an isolated environment
    user_path = tmpdir / "user"
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    
    # Create multiple mock models from the same plugin
    mock_model1 = MagicMock()
    mock_model1.needs_key = "plugin-key"
    mock_model1.key_env_var = "PLUGIN_API_KEY"
    mock_model1.__class__.__module__ = "same_plugin.models"
    
    mock_model2 = MagicMock()
    mock_model2.needs_key = "plugin-key"
    mock_model2.key_env_var = "PLUGIN_API_KEY"
    mock_model2.__class__.__module__ = "same_plugin.models"
    
    # Create mock models with aliases
    mock_model_with_aliases1 = MagicMock()
    mock_model_with_aliases1.model = mock_model1
    
    mock_model_with_aliases2 = MagicMock()
    mock_model_with_aliases2.model = mock_model2
    
    # Create a mock for get_models_with_aliases
    mock_models = [mock_model_with_aliases1, mock_model_with_aliases2]
    
    with patch("llm.get_models_with_aliases", return_value=mock_models):
        runner = CliRunner()
        result = runner.invoke(cli, ["keys", "plugin-keys"])
        
        # Verify the command executed successfully
        assert result.exit_code == 0
        # Verify the output - should only show one key entry for the plugin
        assert result.output.count("same_plugin:") == 1
        assert "same_plugin: plugin-key (env: PLUGIN_API_KEY)" in result.output


def test_keys_plugin_keys_no_key_needed(monkeypatch, tmpdir):
    """Test keys_plugin_keys with a plugin that doesn't need a key"""
    # Set up an isolated environment
    user_path = tmpdir / "user"
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    
    # Create a mock model that doesn't need a key
    mock_model = MagicMock()
    mock_model.needs_key = None
    mock_model.key_env_var = None
    mock_model.__class__.__module__ = "no_key_plugin.models"
    
    # Create a mock model with aliases
    mock_model_with_aliases = MagicMock()
    mock_model_with_aliases.model = mock_model
    
    # Create a mock for get_models_with_aliases
    mock_models = [mock_model_with_aliases]
    
    with patch("llm.get_models_with_aliases", return_value=mock_models):
        runner = CliRunner()
        result = runner.invoke(cli, ["keys", "plugin-keys"])
        
        # Verify the command executed successfully
        assert result.exit_code == 0
        # Verify the output
        assert "no_key_plugin: NONE" in result.output

def test_keys_plugin_keys_model_without_needs_key(monkeypatch, tmpdir):
    """Test keys_plugin_keys with a model that doesn't have the needs_key attribute"""
    # Set up an isolated environment
    user_path = tmpdir / "user"
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    
    # Create a mock model without the needs_key attribute
    mock_model = MagicMock(spec=[])
    mock_model.__class__.__module__ = "no_attr_plugin.models"
    
    # Create a mock model with aliases
    mock_model_with_aliases = MagicMock()
    mock_model_with_aliases.model = mock_model
    
    # Create a mock for get_models_with_aliases
    mock_models = [mock_model_with_aliases]
    
    with patch("llm.get_models_with_aliases", return_value=mock_models):
        runner = CliRunner()
        result = runner.invoke(cli, ["keys", "plugin-keys"])
        
        # Verify the command executed successfully
        assert result.exit_code == 0
        # Verify the output - should be empty since the model doesn't have needs_key
        assert result.output.strip() == ""
