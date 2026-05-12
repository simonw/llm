import llm
from llm.cli import cli
from click.testing import CliRunner
from llm.plugins import pm
import pydantic
from pydantic import BaseModel
import pytest

class SmallModel(BaseModel):
    required_field: str

def test_resilient_model_discovery():
    class PoisonedPlugin:
        __name__ = "PoisonedPlugin"
        @llm.hookimpl
        def register_models(self, register):
            SmallModel() # Raises ValidationError

    class HealthyModel(llm.Model):
        model_id = "healthy-model"
        
        def execute(self, prompt, stream, response, conversation):
            return ["response"]

    class HealthyPlugin:
        __name__ = "HealthyPlugin"
        @llm.hookimpl
        def register_models(self, register):            
            register(HealthyModel())

    # Register both
    pm.register(PoisonedPlugin(), name="poisoned")
    pm.register(HealthyPlugin(), name="healthy")
    
    try:
        runner = CliRunner(mix_stderr=False)
        # Using -q to make sure we are testing the discovery part which happens before filtering
        result = runner.invoke(cli, ["models", "-q", "healthy-model"])
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
        print(f"EXIT CODE: {result.exit_code}")
        
        # Verify healthy model is present in stdout
        assert "healthy-model" in result.stdout, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        # Verify warning is in stderr
        assert "Warning: model backend 'poisoned' failed during discovery" in result.stderr, f"STDERR: {result.stderr}"
        assert "required_field" in result.stderr, f"STDERR: {result.stderr}"
        
        # Verify exit code 0
        assert result.exit_code == 0, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    finally:
        pm.unregister(name="poisoned")
        pm.unregister(name="healthy")

def test_library_remains_strict():
    class PoisonedPlugin:
        __name__ = "PoisonedPluginLibrary"
        @llm.hookimpl
        def register_models(self, register):
            SmallModel() # Raises ValidationError

    pm.register(PoisonedPlugin(), name="poisoned-lib")
    
    try:
        # Calling the library function should still raise ValidationError
        with pytest.raises(pydantic.ValidationError):
            llm.get_models_with_aliases()
    finally:
        pm.unregister(name="poisoned-lib")

def test_resilient_discovery_all_fail():
    class PoisonedPlugin1:
        __name__ = "PoisonedPlugin1"
        @llm.hookimpl
        def register_models(self, register):
            SmallModel()

    # In tests, there are usually default models registered (echo, mock).
    # To truly test "all fail", we would need to unregister everything.
    # Instead, we can verify that the ClickException is raised IF the helper returns nothing and had errors.
    
    # We'll unregister the standard test models for this specific test
    # Note: this might be risky if tests run in parallel, but standard pytest is fine.
    
    # Find and unregister all plugins that implement register_models
    to_unregister = []
    for plugin in pm.get_plugins():
        if hasattr(plugin, "register_models"):
            to_unregister.append((plugin, pm.get_name(plugin)))
    
    for plugin, name in to_unregister:
        pm.unregister(plugin)
        
    pm.register(PoisonedPlugin1(), name="p1")
    
    try:
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["models"])
        
        assert result.exit_code != 0
        assert "Error: All model backends failed during discovery" in result.stderr
        assert "Warning: model backend 'p1' failed during discovery" in result.stderr
    finally:
        pm.unregister(name="p1")
        # Restore them
        for plugin, name in to_unregister:
            pm.register(plugin, name=name)
