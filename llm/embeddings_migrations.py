from sqlite_migrate import Migrations
import time

embeddings_migrations = Migrations("llm.embeddings")


@embeddings_migrations()
def m001_create_tables(db):
    db["collections"].create({"id": int, "name": str, "model": str}, pk="id")
    db["collections"].create_index(["name"], unique=True)
    db["embeddings"].create(
        {
            "collection_id": int,
            "id": str,
            "embedding": bytes,
            "content": str,
            "metadata": str,
        },
        pk=("collection_id", "id"),
    )


@embeddings_migrations()
def m002_foreign_key(db):
    db["embeddings"].add_foreign_key("collection_id", "collections", "id")


@embeddings_migrations()
def m003_add_updated(db):
    db["embeddings"].add_column("updated", int)
    # Pretty-print the schema
    db["embeddings"].transform()
    # Assume anything existing was last updated right now
    db.query(
        "update embeddings set updated = ? where updated is null", [int(time.time())]
    )
