from llm import hookimpl
from llm.context import EmbeddingsContextProvider


@hookimpl
def register_context_providers(register):
    register(EmbeddingsContextProvider())
