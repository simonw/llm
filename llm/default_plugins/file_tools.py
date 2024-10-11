import json
import glob
from typing import Annotated
import llm


@llm.hookimpl
def register_tools(register):
    register(llm.Tool(read_files))


def read_files(
    filenames: Annotated[
        list[str],
        "A list of file paths to read. Paths can be a Python `glob.glob()` pattern.",
    ]
) -> str:
    """Read the given filenames and return the contents."""
    result = []
    for path in filenames:
        for filename in glob.glob(path):
            with open(filename, "r") as f:
                result.append({"filename": filename, "contents": f.read()})
    return json.dumps(result)
