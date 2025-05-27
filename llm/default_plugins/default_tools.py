import llm
from llm.tools import llm_version


@llm.hookimpl
def register_tools(register):
    register(llm_version)
