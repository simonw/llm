from llm import hookimpl
from llm.context import EmbeddingsContextProvider, FragmentsContextProvider


@hookimpl
def register_context_providers(register):
    register(EmbeddingsContextProvider())
    register(FragmentsContextProvider())
