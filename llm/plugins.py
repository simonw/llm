import contextlib
import datetime
import importlib
from importlib import metadata
import io
import json
import logging
import os
import pathlib
import pluggy
import sys
import traceback
import warnings
import click
import sqlite_utils
from . import hookspecs
from .migrations import migrate

DEFAULT_PLUGINS = (
    "llm.default_plugins.openai_models",
    "llm.default_plugins.default_tools",
)

pm = pluggy.PluginManager("llm")
pm.add_hookspecs(hookspecs)

LLM_LOAD_PLUGINS = os.environ.get("LLM_LOAD_PLUGINS", None)

_loaded = False
_plugin_events_db = None
_plugin_events_db_path = None


def _user_dir():
    llm_user_path = os.environ.get("LLM_USER_PATH")
    if llm_user_path:
        path = pathlib.Path(llm_user_path)
    else:
        path = pathlib.Path(click.get_app_dir("io.datasette.llm"))
    path.mkdir(exist_ok=True, parents=True)
    return path


def _logs_db():
    global _plugin_events_db, _plugin_events_db_path
    path = _user_dir() / "logs.db"
    if _plugin_events_db is None or _plugin_events_db_path != path:
        db = sqlite_utils.Database(path)
        migrate(db)
        _plugin_events_db = db
        _plugin_events_db_path = path
    return _plugin_events_db


def _persist_plugin_event(
    *,
    plugin: str,
    phase: str,
    kind: str,
    level: str,
    message: str,
    logger_name: str = "",
    details: dict | None = None,
    response_id: str | None = None,
) -> None:
    if not message:
        return
    try:
        db = _logs_db()
        db["plugin_events"].insert(
            {
                "plugin": plugin,
                "phase": phase,
                "kind": kind,
                "level": level,
                "logger_name": logger_name or None,
                "message": message,
                "details_json": json.dumps(details) if details else None,
                "response_id": response_id,
                "datetime_utc": str(datetime.datetime.now(datetime.timezone.utc)),
            }
        )
    except Exception:
        # Plugin diagnostics should never break command output.
        return


class _PluginCaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        details = {}
        if record.exc_info:
            details["traceback"] = "".join(traceback.format_exception(*record.exc_info))
        self.records.append(
            {
                "level": record.levelname,
                "logger_name": record.name,
                "message": record.getMessage(),
                "details": details or None,
            }
        )


class PluginQuarantine:
    def __init__(self, plugin: str, phase: str, response_id: str | None = None):
        self.plugin = plugin
        self.phase = phase
        self.response_id = response_id
        self._capture_handler = _PluginCaptureHandler()
        self._stdout = io.StringIO()
        self._stderr = io.StringIO()

    def __enter__(self):
        self._root = logging.getLogger()
        self._original_handlers = list(self._root.handlers)
        self._original_level = self._root.level
        self._original_disabled = self._root.disabled
        self._stdout_cm = contextlib.redirect_stdout(self._stdout)
        self._stderr_cm = contextlib.redirect_stderr(self._stderr)
        self._warnings_cm = warnings.catch_warnings(record=True)
        self._stdout_cm.__enter__()
        self._stderr_cm.__enter__()
        self._caught_warnings = self._warnings_cm.__enter__()
        warnings.simplefilter("always")
        self._root.handlers = [self._capture_handler]
        self._root.setLevel(logging.DEBUG)
        self._root.disabled = False
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stdout_cm.__exit__(exc_type, exc, tb)
        self._stderr_cm.__exit__(exc_type, exc, tb)
        self._warnings_cm.__exit__(exc_type, exc, tb)
        self._root.handlers = self._original_handlers
        self._root.setLevel(self._original_level)
        self._root.disabled = self._original_disabled

        for record in self._capture_handler.records:
            _persist_plugin_event(
                plugin=self.plugin,
                phase=self.phase,
                kind="logging",
                level=record["level"],
                logger_name=record["logger_name"],
                message=record["message"],
                details=record["details"],
                response_id=self.response_id,
            )

        for warning_message in self._caught_warnings:
            _persist_plugin_event(
                plugin=self.plugin,
                phase=self.phase,
                kind="warning",
                level="WARNING",
                logger_name="warnings",
                message=str(warning_message.message),
                details={
                    "category": warning_message.category.__name__,
                    "filename": warning_message.filename,
                    "lineno": warning_message.lineno,
                },
                response_id=self.response_id,
            )

        stdout = self._stdout.getvalue().strip()
        if stdout:
            _persist_plugin_event(
                plugin=self.plugin,
                phase=self.phase,
                kind="stdout",
                level="INFO",
                message=stdout,
                response_id=self.response_id,
            )

        stderr = self._stderr.getvalue().strip()
        if stderr:
            _persist_plugin_event(
                plugin=self.plugin,
                phase=self.phase,
                kind="stderr",
                level="WARNING",
                message=stderr,
                response_id=self.response_id,
            )

        if exc is not None:
            _persist_plugin_event(
                plugin=self.plugin,
                phase=self.phase,
                kind="exception",
                level="ERROR",
                message=str(exc),
                details={"traceback": "".join(traceback.format_exception(exc_type, exc, tb))},
                response_id=self.response_id,
            )
        return False


def _plugin_name(plugin) -> str:
    return pm.get_name(plugin) or getattr(
        plugin, "__name__", plugin.__class__.__name__
    )


def _register_loaded_plugin(mod, name, distribution=None):
    pm.register(mod, name=name)
    if distribution is not None:
        pm._plugin_distinfo.append((mod, distribution))  # type: ignore[attr-defined]


def _load_entrypoint(entry_point, distribution=None):
    with PluginQuarantine(entry_point.name, "import"):
        mod = entry_point.load()
    _register_loaded_plugin(mod, entry_point.name, distribution)


def _call_hook_impl(impl, hook_name, **kwargs):
    with PluginQuarantine(_plugin_name(impl.plugin), hook_name):
        return impl.function(**kwargs)


def call_hook_impl(impl, hook_name, **kwargs):
    return _call_hook_impl(impl, hook_name, **kwargs)


def call_hook(hook_name, **kwargs):
    hook_caller = getattr(pm.hook, hook_name)
    results = []
    for impl in hook_caller.get_hookimpls():
        results.append(_call_hook_impl(impl, hook_name, **kwargs))
    return results


def register_commands(cli):
    call_hook("register_commands", cli=cli)


def load_plugins():
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not hasattr(sys, "_called_from_test") and LLM_LOAD_PLUGINS is None:
        # Only load plugins if not running tests
        for entry_point in metadata.entry_points(group="llm"):
            _load_entrypoint(entry_point, getattr(entry_point, "dist", None))

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
                    _load_entrypoint(entry_point, distribution)
            except metadata.PackageNotFoundError:
                _persist_plugin_event(
                    plugin=package_name,
                    phase="import",
                    kind="exception",
                    level="ERROR",
                    message=f"Plugin {package_name} could not be found",
                )

    for plugin in DEFAULT_PLUGINS:
        with PluginQuarantine(plugin, "import"):
            mod = importlib.import_module(plugin)
        pm.register(mod, plugin)
