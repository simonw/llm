import os
import pathlib

import sqlite_utils

import llm

DEFAULT_SIMILAR_NUMBER = 5


@llm.hookimpl
def register_fragment_loaders(register):
    register("similar", similar_loader)


def similar_loader(argument: str) -> list[llm.Fragment]:
    """
    Run a similarity search against an embeddings collection

    Argument is collection:search term, optionally followed by
    :N for the number of results to return (default 5)

    Only entries that were embedded with stored content are returned
    """
    collection_name, _, search_term = argument.partition(":")
    number = DEFAULT_SIMILAR_NUMBER
    term, _, size = search_term.rpartition(":")
    if term and size.isdigit():
        search_term, number = term, int(size)
    if not collection_name or not search_term:
        raise ValueError(
            "Argument must be in the form collection:search term or "
            "collection:search term:N"
        )
    if number < 1:
        raise ValueError("Number of results must be at least 1")

    db_path = pathlib.Path(
        os.environ.get("LLM_EMBEDDINGS_DB") or llm.user_dir() / "embeddings.db"
    )
    if not db_path.exists():
        raise ValueError(f"Embeddings database {db_path} does not exist")
    db = sqlite_utils.Database(db_path)
    try:
        try:
            collection = llm.Collection(collection_name, db, create=False)
        except llm.Collection.DoesNotExist:
            raise ValueError(f"Collection '{collection_name}' does not exist")
        entries = collection.similar(search_term, number=number)
    finally:
        db.close()

    fragments = [
        llm.Fragment(entry.content, f"{collection_name}:{entry.id}")
        for entry in entries
        if entry.content
    ]
    if not fragments:
        raise ValueError(
            f"No stored content found for '{search_term}' in collection "
            f"'{collection_name}' - use --store when embedding to store content"
        )
    return fragments
