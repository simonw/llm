import llm
from llm.tools import llm_version
import os
import pytest


API_KEY = os.environ.get("PYTEST_OPENAI_API_KEY", None) or "badkey"


# This response contains streaming variant "a" where arguments="" is followed by arguments="{}"
@pytest.mark.vcr(record_mode="none")
def test_tools_streaming_variant_a():
    model = llm.get_model("gpt-4.1-mini")
    chain = model.chain(
        "What is the current llm version?", tools=[llm_version], key=API_KEY
    )
    assert "".join(chain) == "The current version of *llm* is **0.fixed-version**."


# This response contains streaming variant "b" where arguments="{}" is the first partial stream received.
@pytest.mark.vcr(record_mode="none")
def test_tools_streaming_variant_b():
    model = llm.get_model("gpt-4.1-mini")
    chain = model.chain(
        "What is the current llm version?", tools=[llm_version], key=API_KEY
    )
    assert "".join(chain) == "The current version of *llm* is **0.fixed-version**."


# This response contains streaming variant "c".
@pytest.mark.vcr(record_mode="none")
def test_tools_streaming_variant_c():
    model = llm.get_model("gpt-4.1-mini")
    chain = model.chain(
        "What is the current llm version?", tools=[llm_version], key=API_KEY
    )
    assert (
        "".join(chain)
        == "The installed version of LLM on this system is 0.fixed-version."
    )
