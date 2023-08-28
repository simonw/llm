from pluggy import HookimplMarker
from pluggy import HookspecMarker

hookspec = HookspecMarker("llm")
hookimpl = HookimplMarker("llm")


@hookspec
def register_commands(cli):
    """Register additional CLI commands, e.g. 'llm mycommand ...'"""


@hookspec
def register_models(register):
    "Return a list of model instances representing LLM models that can be called"


@hookspec
def register_embedding_models(register):
    "Return a list of model instances that can be used for embedding"
