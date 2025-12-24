from llm.context import FragmentsContextProvider
from llm.migrations import migrate
from llm.utils import ensure_fragment, Fragment
import sqlite_utils

def test_fragments_context_provider(embed_demo):
    db = sqlite_utils.Database(memory=True)
    migrate(db)
    ensure_fragment(db, Fragment("hello world", "one"))
    ensure_fragment(db, Fragment("hi world", "two"))
    ensure_fragment(db, Fragment("goodbye world", "three"))
    provider = FragmentsContextProvider(db=db, model_id="embed-demo")
    results = provider.search_context("conv", "hello")
    assert results
    assert results[1].content == "hello world"
    assert results[1].metadata["source"] == "one"

