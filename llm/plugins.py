import importlib
from importlib import metadata
import os
import pluggy
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


def _is_truthy(value):
    if value is None:
        return False
    return value.lower() not in ("", "0", "false", "no", "off")


def _load_entrypoint_plugins(plugin_manager, entry_points=None):
    strict_plugin_loading = _is_truthy(os.environ.get("LLM_STRICT_PLUGIN_LOADING"))
    if entry_points is None:
        entry_points = metadata.entry_points(group="llm")
    for entry_point in entry_points:
        if plugin_manager.get_plugin(entry_point.name) is not None:
            continue
        if plugin_manager.is_blocked(entry_point.name):
            continue
        try:
            plugin = entry_point.load()
            try:
                plugin_manager.register(plugin, name=entry_point.name)
            except Exception:
                # Clean up if our plugin was partially registered
                if plugin_manager.get_plugin(entry_point.name) is plugin:
                    plugin_manager.unregister(name=entry_point.name)
                raise
            dist = getattr(entry_point, "dist", None)
            if dist is not None:
                plugin_manager._plugin_distinfo.append((plugin, dist))  # type: ignore
        except Exception as ex:
            if strict_plugin_loading:
                raise
            sys.stderr.write(
                "Plugin {} failed to load: {}\n".format(entry_point.name, ex)
            )


def load_plugins():
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not hasattr(sys, "_called_from_test") and LLM_LOAD_PLUGINS is None:
        # Only load plugins if not running tests
        _load_entrypoint_plugins(pm)

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
                    mod = entry_point.load()
                    pm.register(mod, name=entry_point.name)
                    # Ensure name can be found in plugin_to_distinfo later:
                    pm._plugin_distinfo.append((mod, distribution))  # type: ignore
            except metadata.PackageNotFoundError:
                sys.stderr.write(f"Plugin {package_name} could not be found\n")

    for plugin in DEFAULT_PLUGINS:
        mod = importlib.import_module(plugin)
        pm.register(mod, plugin)
