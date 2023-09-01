from .models import EmbeddingModel
from .embeddings_migrations import embeddings_migrations
import json
from sqlite_utils import Database
from sqlite_utils.db import Table
from typing import cast, Any, Dict, List, Tuple, Optional, Union


class Collection:
    def __init__(
        self,
        db: Database,
        name: str,
        *,
        model: Optional[EmbeddingModel] = None,
        model_id: Optional[str] = None,
    ) -> None:
        from llm import get_embedding_model

        self.db = db
        self.name = name
        if model and model_id and model.model_id != model_id:
            raise ValueError("model_id does not match model.model_id")
        if model_id and not model:
            model = get_embedding_model(model_id)
        self.model = model
        self._id: Optional[int] = None

    def id(self) -> int:
        """
        Get the ID of the collection, creating it in the DB if necessary.

        Returns:
            int: ID of the collection
        """
        if self._id is not None:
            return self._id
        if not self.db["collections"].exists():
            embeddings_migrations.apply(self.db)
        rows = self.db["collections"].rows_where("name = ?", [self.name])
        try:
            row = next(rows)
            self._id = row["id"]
        except StopIteration:
            # Create it
            self._id = (
                cast(Table, self.db["collections"])
                .insert(
                    {
                        "name": self.name,
                        "model": cast(EmbeddingModel, self.model).model_id,
                    }
                )
                .last_pk
            )
        return cast(int, self._id)

    def exists(self) -> bool:
        """
        Check if the collection exists in the DB.

        Returns:
            bool: True if exists, False otherwise
        """
        matches = list(
            self.db.query("select 1 from collections where name = ?", (self.name,))
        )
        return bool(matches)

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
        Embed a text and store it in the collection with a given ID.

        Args:
            id (str): ID for the text
            text (str): Text to be embedded
            metadata (dict, optional): Metadata to be stored
            store (bool, optional): Whether to store the text in the content column
        """
        from llm import encode

        embedding = cast(EmbeddingModel, self.model).embed(text)
        cast(Table, self.db["embeddings"]).insert(
            {
                "collection_id": self.id(),
                "id": id,
                "embedding": encode(embedding),
                "content": text if store else None,
                "metadata": json.dumps(metadata) if metadata else None,
            }
        )

    def embed_multi(self, id_text_map: Dict[str, str], store: bool = False) -> None:
        """
        Embed multiple texts and store them in the collection with given IDs.

        Args:
            id_text_map (dict): Dictionary mapping IDs to texts
            store (bool, optional): Whether to store the text in the content column
        """
        raise NotImplementedError

    def embed_multi_with_metadata(
        self,
        id_text_metadata_map: Dict[str, Tuple[str, Dict[str, Union[str, int, float]]]],
    ) -> None:
        """
        Embed multiple texts along with metadata and store them in the collection with given IDs.

        Args:
            id_text_metadata_map (dict): Dictionary mapping IDs to (text, metadata) tuples
        """
        raise NotImplementedError

    def similar_by_id(self, id: str, number: int = 5) -> List[Tuple[str, float]]:
        """
        Find similar items in the collection by a given ID.

        Args:
            id (str): ID to search by
            number (int, optional): Number of similar items to return

        Returns:
            list: List of (id, score) tuples
        """
        raise NotImplementedError

    def similar(self, text: str, number: int = 5) -> List[Tuple[str, float]]:
        """
        Find similar items in the collection by a given text.

        Args:
            text (str): Text to search by
            number (int, optional): Number of similar items to return

        Returns:
            list: List of (id, score) tuples
        """
        raise NotImplementedError
