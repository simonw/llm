from importlib.metadata import version


def llm_version() -> str:
    "Return the installed version of llm"
    return version("llm")
