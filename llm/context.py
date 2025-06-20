from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time

from .embeddings import Collection, Entry


@dataclass
class ContextMetadata:
    """Metadata for a context."""

    provider_name: str
    context_id: str
    created_at: Optional[float] = None
    updated_at: Optional[float] = None


@dataclass
class ContextItem:
    """A single item in a context."""

    content: str
    role: str
    timestamp: float
    relevance: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class Context:
    """Context for a conversation."""

    data: Dict[str, Any]
    metadata: ContextMetadata
    items: List[ContextItem] = field(default_factory=list)


class ContextProvider:
    """Base class for context providers."""

    name: str = "base"

    def initialize_context(self, conversation_id: str) -> Context:
        raise NotImplementedError

    def update_context(
        self,
        conversation_id: str,
        response: Any,
        previous_context: Optional[Context] = None,
    ) -> Context:
        raise NotImplementedError

    def get_context(self, conversation_id: str) -> Optional[Context]:
        raise NotImplementedError

    def format_for_prompt(
        self,
        context: Optional[Context],
        fragments: Optional[List[str]] = None,
    ) -> str:
        return ""

    def search_context(
        self, conversation_id: str, query: str, limit: int = 5
    ) -> List[ContextItem]:
        return []


class EmbeddingsContextProvider(ContextProvider):
    """Context provider that stores conversation turns using embeddings."""

    name = "embeddings"

    def __init__(self, db=None, model_id: Optional[str] = None) -> None:
        self.db = db
        self.model_id = model_id

    def _collection(self, conversation_id: str) -> Collection:
        name = f"context-{conversation_id}"
        return Collection(name, db=self.db, model_id=self.model_id)

    def initialize_context(self, conversation_id: str) -> Context:
        return Context(
            data={},
            metadata=ContextMetadata(
                provider_name=self.name,
                context_id=conversation_id,
                created_at=time.time(),
                updated_at=time.time(),
            ),
        )

    def update_context(
        self,
        conversation_id: str,
        response: Any,
        previous_context: Optional[Context] = None,
    ) -> Context:
        collection = self._collection(conversation_id)
        text = getattr(response, "text", None)
        if callable(text):
            text = text()
        elif text is None:
            text = str(response)
        item_id = str(time.time())
        collection.embed(item_id, text, metadata={"role": "assistant"})
        item = ContextItem(content=text, role="assistant", timestamp=time.time())
        context = previous_context or self.initialize_context(conversation_id)
        context.items.append(item)
        context.metadata.updated_at = time.time()
        return context

    def get_context(self, conversation_id: str) -> Optional[Context]:
        collection = self._collection(conversation_id)
        if not Collection.exists(collection.db, collection.name):
            return None
        items = []
        for row in collection.db.query(
            "select id, content, metadata from embeddings where collection_id = ? order by id",
            [collection.id],
        ):
            metadata = {}  # parse metadata JSON
            if row["metadata"]:
                import json

                metadata = json.loads(row["metadata"])
            items.append(
                ContextItem(
                    content=row["content"],
                    role=metadata.get("role", "assistant"),
                    timestamp=float(row["id"]),
                )
            )
        return Context(
            data={},
            metadata=ContextMetadata(
                provider_name=self.name,
                context_id=conversation_id,
            ),
            items=items,
        )

    def search_context(self, conversation_id: str, query: str, limit: int = 5) -> List[ContextItem]:
        collection = self._collection(conversation_id)
        results: List[Entry] = collection.similar(query, limit)
        items = []
        for entry in results:
            role = None
            if entry.metadata:
                role = entry.metadata.get("role")
            items.append(
                ContextItem(
                    content=entry.content or "",
                    role=role or "assistant",
                    timestamp=float(entry.id),
                    relevance=entry.score,
                    metadata=entry.metadata,
                )
            )
        return items


class FragmentsContextProvider(ContextProvider):
    """Context provider that searches stored fragments using embeddings."""

    name = "fragments"

    def __init__(self, db=None, model_id: Optional[str] = None) -> None:
        self.db = db
        self.model_id = model_id

    def _collection(self) -> Collection:
        return Collection("fragments", db=self.db, model_id=self.model_id)

    def _ensure_indexed(self) -> None:
        collection = self._collection()
        for row in self._collection().db.query(
            "select id, hash, content, source from fragments"
        ):
            if not collection.db["embeddings"].count_where(
                "collection_id = ? and id = ?", [collection.id, str(row["id"])]
            ):
                collection.embed(
                    str(row["id"]),
                    row["content"],
                    metadata={"hash": row["hash"], "source": row["source"]},
                    store=True,
                )

    def initialize_context(self, conversation_id: str) -> Context:
        return Context(
            data={},
            metadata=ContextMetadata(
                provider_name=self.name, context_id=conversation_id
            ),
        )

    def update_context(
        self,
        conversation_id: str,
        response: Any,
        previous_context: Optional[Context] = None,
    ) -> Context:
        return previous_context or self.initialize_context(conversation_id)

    def get_context(self, conversation_id: str) -> Optional[Context]:
        return None

    def search_context(self, conversation_id: str, query: str, limit: int = 5) -> List[ContextItem]:
        self._ensure_indexed()
        collection = self._collection()
        results: List[Entry] = collection.similar(query, limit)
        items = []
        for entry in results:
            items.append(
                ContextItem(
                    content=entry.content or "",
                    role="fragment",
                    timestamp=float(entry.id),
                    relevance=entry.score,
                    metadata=entry.metadata,
                )
            )
        return items
