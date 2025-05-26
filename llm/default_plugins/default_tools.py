import llm
from importlib.metadata import version


def llm_version() -> str:
    "Return the installed version of llm"
    return version("llm")


@llm.hookimpl
def register_tools(register):
    register(llm_version)
