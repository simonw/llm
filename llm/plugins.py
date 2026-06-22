import importlib
from importlib import metadata
import os
import pluggy
from pluggy._manager import DistFacade
import sys
from . import hookspecs

DEFAULT_PLUGINS = (
    "llm.default_plugins.openai_models",
    "llm.default_plugins.default_tools",
)

pm = pluggy.PluginManager("llm")
pm.add_hookspecs(hookspecs)

LLM_LOAD_PLUGINS = os.environ.get("LLM_LOAD_PLUGINS", None)

_loaded = False


def _raise_plugin_errors():
    return os.environ.get("LLM_RAISE_PLUGIN_ERRORS") not in (None, "", "0")


def _load_entrypoint(entry_point, distribution):
    plugin = entry_point.load()
    pm.register(plugin, name=entry_point.name)
    # Ensure name can be found in plugin_to_distinfo later:
    pm._plugin_distinfo.append((plugin, DistFacade(distribution)))  # type: ignore


def _warn_entrypoint_error(entry_point_name, ex):
    sys.stderr.write(
        "Plugin {} could not be loaded: {}: {}\n".format(
            entry_point_name, type(ex).__name__, ex
        )
    )


def _load_setuptools_entrypoints(group):
    count = 0
    for distribution in list(metadata.distributions()):
        for entry_point in distribution.entry_points:
            if (
                entry_point.group != group
                or pm.get_plugin(entry_point.name)
                or pm.is_blocked(entry_point.name)
            ):
                continue
            try:
                _load_entrypoint(entry_point, distribution)
                count += 1
            except Exception as ex:
                if _raise_plugin_errors():
                    raise
                _warn_entrypoint_error(entry_point.name, ex)
    return count


def load_plugins():
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not hasattr(sys, "_called_from_test") and LLM_LOAD_PLUGINS is None:
        # Only load plugins if not running tests
        _load_setuptools_entrypoints("llm")

    # Load any plugins specified in LLM_LOAD_PLUGINS")
    if LLM_LOAD_PLUGINS is not None:
        for package_name in [
            name for name in LLM_LOAD_PLUGINS.split(",") if name.strip()
        ]:
            try:
                distribution = metadata.distribution(package_name)  # Updated call
                llm_entry_points = [
                    ep for ep in distribution.entry_points if ep.group == "llm"
                ]
                for entry_point in llm_entry_points:
                    try:
                        _load_entrypoint(entry_point, distribution)
                    except Exception as ex:
                        if _raise_plugin_errors():
                            raise
                        _warn_entrypoint_error(entry_point.name, ex)
            except metadata.PackageNotFoundError:
                sys.stderr.write(f"Plugin {package_name} could not be found\n")

    for plugin in DEFAULT_PLUGINS:
        mod = importlib.import_module(plugin)
        pm.register(mod, plugin)
