from importlib.metadata import version
import llm
from llm.tools import llm_time, llm_version
import os
import pytest


API_KEY = os.environ.get("PYTEST_OPENAI_API_KEY", None) or "badkey"


# This response contains streaming variant "a" where arguments="" is followed by arguments="{}"
@pytest.mark.vcr(record_mode="none")
def test_tools_streaming_variant_a():
    model = llm.get_model("gpt-4.1-mini")

    chain = model.chain("What is the current llm version?", tools=[llm_version], key=API_KEY)

    output = "".join(chain)

    print(chain._responses)

    assert "".join(str(output)) == "The current version of *llm* is **{}**.".format(version("llm"))


# This response contains streaming variant "b" where arguments="{}" is the first partial stream received.
@pytest.mark.vcr(record_mode="none")
def test_tools_streaming_variant_b():
    model = llm.get_model("gpt-4.1-mini")

    chain = model.chain("What is the current llm version?", tools=[llm_version], key=API_KEY)

    output = "".join(chain)

    print(chain._responses)

    assert "".join(str(output)) == "The current version of *llm* is **{}**.".format(version("llm"))
