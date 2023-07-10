import importlib
import pluggy
import sys
from . import hookspecs

DEFAULT_PLUGINS = ("llm.default_plugins.openai_models",)

pm = pluggy.PluginManager("llm")
pm.add_hookspecs(hookspecs)

if not hasattr(sys, "_called_from_test"):
    # Only load plugins if not running tests
    pm.load_setuptools_entrypoints("llm")

for plugin in DEFAULT_PLUGINS:
    mod = importlib.import_module(plugin)
    pm.register(mod, plugin)
