from pluggy import HookimplMarker
from pluggy import HookspecMarker
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .models import Tool

hookspec = HookspecMarker("llm")
hookimpl = HookimplMarker("llm")


@hookspec
def register_commands(cli):
    """Register additional CLI commands, e.g. 'llm mycommand ...'"""


@hookspec
def register_models(register, model_aliases):
    "Register additional model instances representing LLM models that can be called"


@hookspec
def register_embedding_models(register):
    "Register additional model instances that can be used for embedding"


@hookspec
def register_template_loaders(register):
    "Register additional template loaders with prefixes"


@hookspec
def register_fragment_loaders(register):
    "Register additional fragment loaders with prefixes"


@hookspec
def register_tools(register):
    "Register functions that can be used as tools by the LLMs"


@hookspec
def before_tool_execution(
    tool_name: str, parameters: dict, tool: Optional["Tool"] = None
) -> Optional[bool]:
    """Called before a tool is executed.

    Return False to block execution, or raise an exception to abort with a message.
    Return True or None to allow.
    Plugins can use this for trust verification, logging, policy checks etc before tool calls (including MCP servers).
    """
