import importlib
import pluggy
import sys
from typing import Dict, List
from . import hookspecs
from .models import ModelWithAliases, Model

DEFAULT_PLUGINS = ("llm.default_plugins.openai_models",)

pm = pluggy.PluginManager("llm")
pm.add_hookspecs(hookspecs)

if not hasattr(sys, "_called_from_test"):
    # Only load plugins if not running tests
    pm.load_setuptools_entrypoints("llm")

for plugin in DEFAULT_PLUGINS:
    mod = importlib.import_module(plugin)
    pm.register(mod, plugin)


def get_plugins():
    plugins = []
    plugin_to_distinfo = dict(pm.list_plugin_distinfo())
    for plugin in pm.get_plugins():
        plugin_info = {
            "name": plugin.__name__,
            "hooks": [h.name for h in pm.get_hookcallers(plugin)],
        }
        distinfo = plugin_to_distinfo.get(plugin)
        if distinfo:
            plugin_info["version"] = distinfo.version
            plugin_info["name"] = distinfo.project_name
        plugins.append(plugin_info)
    return plugins


def get_models_with_aliases() -> List[ModelWithAliases]:
    model_aliases = []

    def register(model, aliases=None):
        model_aliases.append(ModelWithAliases(model, aliases or set()))

    pm.hook.register_models(register=register)
    return model_aliases


def get_model_aliases() -> Dict[str, Model]:
    model_aliases = {}
    for model_with_aliases in get_models_with_aliases():
        for alias in model_with_aliases.aliases:
            model_aliases[alias] = model_with_aliases.model
        model_aliases[model_with_aliases.model.model_id] = model_with_aliases.model
    return model_aliases
