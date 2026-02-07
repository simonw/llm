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

    # Register functions manually so we can de-register later
    def md5(text):
        return hashlib.md5(text.encode("utf8")).digest()

    def random_md5():
        return hashlib.md5(str(time.time()).encode("utf8")).digest()

    db.conn.create_function("temp_md5", 1, md5)
    db.conn.create_function("temp_random_md5", 0, random_md5)

    with db.conn:
        db.execute(
            """
            update embeddings
            set content_hash = temp_md5(content)
            where content is not null
        """
        )
        db.execute(
            """
            update embeddings
            set content_hash = temp_random_md5()
            where content is null
        """
        )

    db["embeddings"].create_index(["content_hash"])

    # De-register functions
    db.conn.create_function("temp_md5", 1, None)
    db.conn.create_function("temp_random_md5", 0, None)


@embeddings_migrations()
def m005_add_content_blob(db):
    db["embeddings"].add_column("content_blob", bytes)
    db["embeddings"].transform(
        column_order=("collection_id", "id", "embedding", "content", "content_blob")
    )
