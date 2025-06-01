import llm
from llm.tools import llm_time, llm_version, fetch_image_url


@llm.hookimpl
def register_tools(register):
    register(llm_version)
    register(llm_time)
    register(fetch_image_url)
