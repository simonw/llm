from pluggy import HookimplMarker
from pluggy import HookspecMarker

hookspec = HookspecMarker("llm")
hookimpl = HookimplMarker("llm")


@hookspec
def register_commands(cli):
    """Register additional CLI commands, e.g. 'llm mycommand ...'"""


@hookspec
def register_models(register):
    "Register additional model instances representing LLM models that can be called"


@hookspec
def register_embedding_models(register):
    "Register additional model instances that can be used for embedding"


@hookspec
def register_template_types():
    """Register additional template types that can be used for prompt templates.
    
    Returns:
        dict: A dictionary mapping template type names to template classes
    """
