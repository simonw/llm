from sqlite_migrate import Migrations
import hashlib
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


@embeddings_migrations()
def m004_store_content_hash(db):
    db["embeddings"].add_column("content_hash", bytes)
    db["embeddings"].transform(
        column_order=(
            "collection_id",
            "id",
            "embedding",
            "content",
            "content_hash",
            "metadata",
            "updated",
        )
    )

    # Backfill content_hash
    @db.register_function
    def md5(text):
        return hashlib.md5(text.encode("utf8")).digest()

    @db.register_function
    def random_md5():
        return hashlib.md5(str(time.time()).encode("utf8")).digest()

    rows = list(db["embeddings"].rows)
    print(rows)

    with db.conn:
        db.execute(
            """
            update embeddings
            set content_hash = md5(content)
            where content is not null
        """
        )
        db.execute(
            """
            update embeddings
            set content_hash = random_md5()
            where content is null
        """
        )
    # rows = list(db["embeddings"].rows)
    db["embeddings"].create_index(["content_hash"])
