from .models import EmbeddingModel
from .embeddings_migrations import embeddings_migrations
from dataclasses import dataclass
import hashlib
from itertools import islice
import json
from sqlite_utils import Database
from sqlite_utils.db import Table
import time
from typing import cast, Any, Dict, Iterable, List, Optional, Tuple, Union


@dataclass
class Entry:
    id: str
    score: Optional[float]
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class Collection:
    class DoesNotExist(Exception):
        pass

    def __init__(
        self,
        name: str,
        db: Optional[Database] = None,
        *,
        model: Optional[EmbeddingModel] = None,
        model_id: Optional[str] = None,
        create: bool = True,
    ) -> None:
        """
        A collection of embeddings

        Returns the collection with the given name, creating it if it does not exist.

        If you set create=False a Collection.DoesNotExist exception will be raised if the
        collection does not already exist.

        Args:
            db (sqlite_utils.Database): Database to store the collection in
            name (str): Name of the collection
            model (llm.models.EmbeddingModel, optional): Embedding model to use
            model_id (str, optional): Alternatively, ID of the embedding model to use
            create (bool, optional): Whether to create the collection if it does not exist
        """
        import llm

        self.db = db or Database(memory=True)
        self.name = name
        self._model = model

        embeddings_migrations.apply(self.db)

        rows = list(self.db["collections"].rows_where("name = ?", [self.name]))
        if rows:
            row = rows[0]
            self.id = row["id"]
            self.model_id = row["model"]
        else:
            if create:
                # Collection does not exist, so model or model_id is required
                if not model and not model_id:
                    raise ValueError(
                        "Either model= or model_id= must be provided when creating a new collection"
                    )
                # Create it
                if model_id:
                    # Resolve alias
                    model = llm.get_embedding_model(model_id)
                    self._model = model
                model_id = cast(EmbeddingModel, model).model_id
                self.id = (
                    cast(Table, self.db["collections"])
                    .insert(
                        {
                            "name": self.name,
                            "model": model_id,
                        }
                    )
                    .last_pk
                )
            else:
                raise self.DoesNotExist(f"Collection '{name}' does not exist")

    def model(self) -> EmbeddingModel:
        "Return the embedding model used by this collection"
        import llm

        if self._model is None:
            self._model = llm.get_embedding_model(self.model_id)

        return cast(EmbeddingModel, self._model)

    def count(self) -> int:
        """
        Count the number of items in the collection.

        Returns:
            int: Number of items in the collection
        """
        return next(
            self.db.query(
                """
            select count(*) as c from embeddings where collection_id = (
                select id from collections where name = ?
            )
            """,
                (self.name,),
            )
        )["c"]

    def embed(
        self,
        id: str,
        value: Union[str, bytes],
        metadata: Optional[Dict[str, Any]] = None,
        store: bool = False,
    ) -> None:
        """
        Embed value and store it in the collection with a given ID.

        Args:
            id (str): ID for the value
            value (str or bytes): value to be embedded
            metadata (dict, optional): Metadata to be stored
            store (bool, optional): Whether to store the value in the content or content_blob column
        """
        from llm import encode

        content_hash = self.content_hash(value)
        if self.db["embeddings"].count_where(
            "content_hash = ? and collection_id = ?", [content_hash, self.id]
        ):
            return
        embedding = self.model().embed(value)
        cast(Table, self.db["embeddings"]).insert(
            {
                "collection_id": self.id,
                "id": id,
                "embedding": encode(embedding),
                "content": value if (store and isinstance(value, str)) else None,
                "content_blob": value if (store and isinstance(value, bytes)) else None,
                "content_hash": content_hash,
                "metadata": json.dumps(metadata) if metadata else None,
                "updated": int(time.time()),
            },
            replace=True,
        )

    def embed_multi(
        self,
        entries: Iterable[Tuple[str, Union[str, bytes]]],
        store: bool = False,
        batch_size: int = 100,
    ) -> None:
        """
        Embed multiple texts and store them in the collection with given IDs.

        Args:
            entries (iterable): Iterable of (id: str, text: str) tuples
            store (bool, optional): Whether to store the text in the content column
            batch_size (int, optional): custom maximum batch size to use
        """
        self.embed_multi_with_metadata(
            ((id, value, None) for id, value in entries),
            store=store,
            batch_size=batch_size,
        )

    def embed_multi_with_metadata(
        self,
        entries: Iterable[Tuple[str, Union[str, bytes], Optional[Dict[str, Any]]]],
        store: bool = False,
        batch_size: int = 100,
    ) -> None:
        """
        Embed multiple values along with metadata and store them in the collection with given IDs.

        Args:
            entries (iterable): Iterable of (id: str, value: str or bytes, metadata: None or dict)
            store (bool, optional): Whether to store the value in the content or content_blob column
            batch_size (int, optional): custom maximum batch size to use
        """
        import llm

        batch_size = min(batch_size, (self.model().batch_size or batch_size))
        iterator = iter(entries)
        collection_id = self.id
        while True:
            batch = list(islice(iterator, batch_size))
            if not batch:
                break
            # Calculate hashes first
            items_and_hashes = [(item, self.content_hash(item[1])) for item in batch]
            # Any of those hashes already exist?
            existing_ids = [
                row["id"]
                for row in self.db.query(
                    """
                    select id from embeddings
                    where collection_id = ? and content_hash in ({})
                    """.format(
                        ",".join("?" for _ in items_and_hashes)
                    ),
                    [collection_id]
                    + [item_and_hash[1] for item_and_hash in items_and_hashes],
                )
            ]
            filtered_batch = [item for item in batch if item[0] not in existing_ids]
            embeddings = list(
                self.model().embed_multi(item[1] for item in filtered_batch)
            )
            with self.db.conn:
                cast(Table, self.db["embeddings"]).insert_all(
                    (
                        {
                            "collection_id": collection_id,
                            "id": id,
                            "embedding": llm.encode(embedding),
                            "content": (
                                value if (store and isinstance(value, str)) else None
                            ),
                            "content_blob": (
                                value if (store and isinstance(value, bytes)) else None
                            ),
                            "content_hash": self.content_hash(value),
                            "metadata": json.dumps(metadata) if metadata else None,
                            "updated": int(time.time()),
                        }
                        for (embedding, (id, value, metadata)) in zip(
                            embeddings, filtered_batch
                        )
                    ),
                    replace=True,
                )

    def similar_by_vector(
        self, vector: List[float], number: int = 10, skip_id: Optional[str] = None
    ) -> List[Entry]:
        """
        Find similar items in the collection by a given vector.

        Args:
            vector (list): Vector to search by
            number (int, optional): Number of similar items to return

        Returns:
            list: List of Entry objects
        """
        import llm

        def distance_score(other_encoded):
            other_vector = llm.decode(other_encoded)
            return llm.cosine_similarity(other_vector, vector)

        self.db.register_function(distance_score, replace=True)

        where_bits = ["collection_id = ?"]
        where_args = [str(self.id)]

        if skip_id:
            where_bits.append("id != ?")
            where_args.append(skip_id)

        return [
            Entry(
                id=row["id"],
                score=row["score"],
                content=row["content"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else None,
            )
            for row in self.db.query(
                """
            select id, content, metadata, distance_score(embedding) as score
            from embeddings
            where {where}
            order by score desc limit {number}
        """.format(
                    where=" and ".join(where_bits),
                    number=number,
                ),
                where_args,
            )
        ]

    def similar_by_id(self, id: str, number: int = 10) -> List[Entry]:
        """
        Find similar items in the collection by a given ID.

        Args:
            id (str): ID to search by
            number (int, optional): Number of similar items to return

        Returns:
            list: List of Entry objects
        """
        import llm

        matches = list(
            self.db["embeddings"].rows_where(
                "collection_id = ? and id = ?", (self.id, id)
            )
        )
        if not matches:
            raise self.DoesNotExist("ID not found")
        embedding = matches[0]["embedding"]
        comparison_vector = llm.decode(embedding)
        return self.similar_by_vector(comparison_vector, number, skip_id=id)

    def similar(self, value: Union[str, bytes], number: int = 10) -> List[Entry]:
        """
        Find similar items in the collection by a given value.

        Args:
            value (str or bytes): value to search by
            number (int, optional): Number of similar items to return

        Returns:
            list: List of Entry objects
        """
        comparison_vector = self.model().embed(value)
        return self.similar_by_vector(comparison_vector, number)

    @classmethod
    def exists(cls, db: Database, name: str) -> bool:
        """
        Does this collection exist in the database?

        Args:
            name (str): Name of the collection
        """
        rows = list(db["collections"].rows_where("name = ?", [name]))
        return bool(rows)

    def delete(self):
        """
        Delete the collection and its embeddings from the database
        """
        with self.db.conn:
            self.db.execute("delete from embeddings where collection_id = ?", [self.id])
            self.db.execute("delete from collections where id = ?", [self.id])

    @staticmethod
    def content_hash(input: Union[str, bytes]) -> bytes:
        "Hash content for deduplication. Override to change hashing behavior."
        if isinstance(input, str):
            input = input.encode("utf8")
        return hashlib.md5(input).digest()
