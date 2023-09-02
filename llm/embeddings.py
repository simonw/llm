from .models import EmbeddingModel
from .embeddings_migrations import embeddings_migrations
from dataclasses import dataclass
from itertools import islice
import json
from sqlite_utils import Database
from sqlite_utils.db import Table
from typing import cast, Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class Entry:
    id: str
    score: Optional[float]
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class Collection:
    max_batch_size: int = 100

    class DoesNotExist(Exception):
        pass

    def __init__(
        self,
        db: Database,
        name: str,
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

        self.db = db
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
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        store: bool = False,
    ) -> None:
        """
        Embed text and store it in the collection with a given ID.

        Args:
            id (str): ID for the text
            text (str): Text to be embedded
            metadata (dict, optional): Metadata to be stored
            store (bool, optional): Whether to store the text in the content column
        """
        from llm import encode

        embedding = self.model().embed(text)
        cast(Table, self.db["embeddings"]).insert(
            {
                "collection_id": self.id,
                "id": id,
                "embedding": encode(embedding),
                "content": text if store else None,
                "metadata": json.dumps(metadata) if metadata else None,
            },
            replace=True,
        )

    def embed_multi(
        self, entries: Iterable[Tuple[str, str]], store: bool = False
    ) -> None:
        """
        Embed multiple texts and store them in the collection with given IDs.

        Args:
            entries (iterable): Iterable of (id: str, text: str) tuples
            store (bool, optional): Whether to store the text in the content column
        """
        self.embed_multi_with_metadata(
            ((id, text, None) for id, text in entries), store=store
        )

    def embed_multi_with_metadata(
        self,
        entries: Iterable[Tuple[str, str, Optional[Dict[str, Any]]]],
        store: bool = False,
    ) -> None:
        """
        Embed multiple texts along with metadata and store them in the collection with given IDs.

        Args:
            entries (iterable): Iterable of (id: str, text: str, metadata: None or dict)
            store (bool, optional): Whether to store the text in the content column
        """
        import llm

        batch_size = min(
            self.max_batch_size, (self.model().batch_size or self.max_batch_size)
        )
        iterator = iter(entries)
        collection_id = self.id
        while True:
            batch = list(islice(iterator, batch_size))
            if not batch:
                break
            embeddings = list(self.model().embed_multi(item[1] for item in batch))
            with self.db.conn:
                cast(Table, self.db["embeddings"]).insert_all(
                    (
                        {
                            "collection_id": collection_id,
                            "id": id,
                            "embedding": llm.encode(embedding),
                            "content": text if store else None,
                            "metadata": json.dumps(metadata) if metadata else None,
                        }
                        for (embedding, (id, text, metadata)) in zip(embeddings, batch)
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

    def similar(self, text: str, number: int = 10) -> List[Entry]:
        """
        Find similar items in the collection by a given text.

        Args:
            text (str): Text to search by
            number (int, optional): Number of similar items to return

        Returns:
            list: List of Entry objects
        """
        comparison_vector = self.model().embed(text)
        return self.similar_by_vector(comparison_vector, number)
