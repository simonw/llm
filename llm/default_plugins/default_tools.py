import llm
from llm.tools import llm_time, llm_version


@llm.hookimpl
def register_tools(register):
    register(llm_version)
    register(llm_time)
