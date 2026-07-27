import sys

from llm import hookimpl
from llm.model_cards import (
    register_embedding_model_cards,
    register_model_cards,
)

# The register hooks run every time models are enumerated - only warn
# about each broken card once per process
_warned: set = set()


def _warn(path, ex):
    key = (str(path), str(ex))
    if key in _warned:
        return
    _warned.add(key)
    sys.stderr.write(f"Could not load model card {path}: {ex}\n")


@hookimpl
def register_models(register):
    register_model_cards(register, on_error=_warn)


@hookimpl
def register_embedding_models(register):
    register_embedding_model_cards(register, on_error=_warn)
