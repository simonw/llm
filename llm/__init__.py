from .hookspecs import hookimpl
from .errors import (
    ModelError,
    NeedsKeyException,
)
from .models import (
    Conversation,
    Model,
    ModelWithAliases,
    Options,
    Prompt,
    Response,
)
from .templates import Template
from .plugins import pm
import click
from typing import Dict, List
import json
import os
import pathlib

__all__ = [
    "hookimpl",
    "get_model",
    "get_key",
    "user_dir",
    "Conversation",
    "Model",
    "Options",
    "Prompt",
    "Response",
    "Template",
    "ModelError",
    "NeedsKeyException",
]


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


def get_models_with_aliases() -> List["ModelWithAliases"]:
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


class UnknownModelError(KeyError):
    pass


def get_model(name):
    aliases = get_model_aliases()
    try:
        return aliases[name]
    except KeyError:
        raise UnknownModelError("Unknown model: " + name)


def get_key(key_arg, default_key, env_var=None):
    keys = load_keys()
    if key_arg in keys:
        return keys[key_arg]
    if key_arg:
        return key_arg
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    return keys.get(default_key)


def load_keys():
    path = user_dir() / "keys.json"
    if path.exists():
        return json.loads(path.read_text())
    else:
        return {}


def user_dir():
    llm_user_path = os.environ.get("LLM_USER_PATH")
    if llm_user_path:
        return pathlib.Path(llm_user_path)
    return pathlib.Path(click.get_app_dir("io.datasette.llm"))
