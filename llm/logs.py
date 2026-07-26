"""Content-addressed storage for conversation message trees.

A conversation is a parent-linked chain of :class:`llm.Message` objects.
Each message is identified by a hash over its own canonical content plus
its parent's hash, so two conversations that share a prefix share the
rows that store it. Forking a conversation, or re-sending a history from
a client that holds the conversation state itself, both write only the
messages that are genuinely new.

The identity of a message is its *resolved* content. Storage may still
be by reference — a text part sourced from a fragment stores a
``fragment_id`` rather than a second copy of the text, and attachments
reuse the existing content-addressed ``attachments`` table — but the
hash always covers the content as the model saw it.
"""

import datetime
import hashlib
import json
from typing import Any

from .migrations import migrate
from .models import Attachment, _conversation_name
from .parts import (
    AttachmentPart,
    Message,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from .utils import ensure_tool, make_schema_id, monotonic_ulid

__all__ = [
    "HASH_PREFIX",
    "LogStore",
    "canonical_json",
    "content_hash",
    "message_hash",
]

# Hashes are tagged with the algorithm that produced them so a future
# change to the canonical form or the digest is detectable rather than
# silently splitting the dedup space into two incompatible halves.
HASH_PREFIX = "b2:"

_DIGEST_SIZE = 16


def canonical_json(obj: Any) -> str:
    """Serialize to the canonical JSON form used for hashing.

    Keys sorted, no insignificant whitespace, non-ASCII left as-is. This
    form is part of the documented contract: changing it changes every
    hash.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def content_hash(obj: Any) -> str:
    "Tagged hash of the canonical JSON form of ``obj``."
    canonical = canonical_json(obj)
    digest = hashlib.blake2b(
        canonical.encode("utf-8"), digest_size=_DIGEST_SIZE
    ).hexdigest()
    return f"{HASH_PREFIX}{digest}"


def message_hash(message: Message, parent_hash: str | None) -> str:
    """Identity of ``message`` when reached via ``parent_hash``.

    The parent participates, so the same content at a different point in
    a conversation is a different node. That is what makes a shared
    prefix collapse to shared rows without any explicit comparison.
    """
    return content_hash({"parent": parent_hash, "message": message.to_dict()})


class LogStore:
    """Read and write conversation history in a SQLite database.

    Wraps a ``sqlite_utils.Database`` and applies any outstanding
    migrations on construction, so a fresh database and an existing one
    are handled the same way::

        store = LogStore(sqlite_utils.Database("logs.db"))
    """

    def __init__(self, db):
        self.db = db
        migrate(db)

    # -- writing -------------------------------------------------------

    def ensure_chain(self, messages, parent: str | None = None) -> str | None:
        """Store ``messages`` as a chain and return the hash of the tip.

        Messages already present are left alone, so a caller that
        re-sends a whole conversation - a client holding the state
        itself, or a fork of an existing thread - writes only the
        messages that are new. Passing ``parent`` appends to an existing
        chain instead of starting a new one.
        """
        tip = parent
        for message in messages:
            tip = self._ensure_message(message, tip)
        return tip

    def _ensure_message(self, message: Message, parent_hash: str | None) -> str:
        hash = message_hash(message, parent_hash)
        if self.db["messages"].count_where("hash = ?", [hash]):
            # Already stored - and because the hash covers the parent,
            # everything below it is stored too.
            return hash
        with self.db.conn:
            self.db["messages"].insert(
                {
                    "hash": hash,
                    "parent_hash": parent_hash,
                    "role": message.role,
                    "provider_metadata": _dump(message.provider_metadata),
                }
            )
            for position, part in enumerate(message.parts):
                self._write_part(hash, position, part)
        return hash

    def _write_part(self, message_hash_: str, position: int, part) -> None:
        row: dict[str, Any] = {
            "message_hash": message_hash_,
            "position": position,
            "provider_metadata": _dump(getattr(part, "provider_metadata", None)),
        }
        attachments: list[Any] = []

        if isinstance(part, TextPart):
            row["type"] = "text"
            row.update(self._text_columns(part.text))
        elif isinstance(part, ReasoningPart):
            row["type"] = "reasoning"
            row.update(self._text_columns(part.text))
            row["redacted"] = int(part.redacted)
        elif isinstance(part, ToolCallPart):
            row["type"] = "tool_call"
            row["name"] = part.name
            row["arguments"] = json.dumps(part.arguments)
            row["tool_call_id"] = part.tool_call_id
            row["server_executed"] = int(part.server_executed)
        elif isinstance(part, ToolResultPart):
            row["type"] = "tool_result"
            row["name"] = part.name
            row["output"] = part.output
            row["tool_call_id"] = part.tool_call_id
            row["server_executed"] = int(part.server_executed)
            row["exception"] = part.exception
            attachments = list(part.attachments)
        elif isinstance(part, AttachmentPart):
            row["type"] = "attachment"
            if part.attachment is not None:
                attachments = [part.attachment]
        else:
            raise TypeError(f"Cannot store {part!r}")

        part_id = self.db["parts"].insert(row).last_pk
        for order, attachment in enumerate(attachments):
            self.db["part_attachments"].insert(
                {
                    "part_id": part_id,
                    "attachment_id": ensure_attachment(self.db, attachment),
                    "order": order,
                }
            )

    def _text_columns(self, text: str) -> dict[str, Any]:
        """Store text by reference when the same content is already a
        fragment, otherwise inline.

        The hash always covers the resolved text either way - this only
        decides where the bytes live.
        """
        if text:
            rows = list(
                self.db.query(
                    "select id from fragments where hash = ?",
                    [hashlib.sha256(text.encode("utf-8")).hexdigest()],
                )
            )
            if rows:
                return {"text": None, "fragment_id": rows[0]["id"]}
        return {"text": text, "fragment_id": None}

    # -- reading -------------------------------------------------------

    def load_chain(self, tip: str | None) -> list[Message]:
        """Return the full chain ending at ``tip``, oldest message first.

        Raises ``KeyError`` if ``tip`` is not in the store.
        """
        if tip is None:
            return []
        rows = []
        hash: str | None = tip
        while hash is not None:
            found = list(self.db.query("select * from messages where hash = ?", [hash]))
            if not found:
                raise KeyError(hash)
            rows.append(found[0])
            hash = found[0]["parent_hash"]
        rows.reverse()
        parts_by_message = self._load_parts([row["hash"] for row in rows])
        return [
            Message(
                role=row["role"],
                parts=parts_by_message.get(row["hash"], []),
                provider_metadata=_load(row["provider_metadata"]),
            )
            for row in rows
        ]

    def _load_parts(self, message_hashes: list[str]) -> dict[str, list[Any]]:
        if not message_hashes:
            return {}
        placeholders = ",".join("?" * len(message_hashes))
        part_rows = list(
            self.db.query(
                f"""
                select parts.*, fragments.content as fragment_content
                from parts
                left join fragments on parts.fragment_id = fragments.id
                where parts.message_hash in ({placeholders})
                order by parts.message_hash, parts.position
                """,
                message_hashes,
            )
        )
        attachments = self._load_part_attachments([row["id"] for row in part_rows])
        out: dict[str, list[Any]] = {}
        for row in part_rows:
            out.setdefault(row["message_hash"], []).append(
                _part_from_row(row, attachments.get(row["id"], []))
            )
        return out

    def _load_part_attachments(self, part_ids: list[int]) -> dict[int, list[Any]]:
        if not part_ids:
            return {}
        placeholders = ",".join("?" * len(part_ids))
        out: dict[int, list[Any]] = {}
        for row in self.db.query(
            f"""
            select part_attachments.part_id, attachments.*
            from part_attachments
            join attachments on part_attachments.attachment_id = attachments.id
            where part_attachments.part_id in ({placeholders})
            order by part_attachments.part_id, part_attachments."order"
            """,
            part_ids,
        ):
            out.setdefault(row["part_id"], []).append(Attachment.from_row(row))
        return out

    # -- threads -------------------------------------------------------

    def create_thread(
        self,
        name: str | None = None,
        tip: str | None = None,
        forked_from: str | None = None,
        id: str | None = None,
    ) -> str:
        "Create a named pointer at a message and return its id."
        thread_id = id or str(monotonic_ulid()).lower()
        self.db["threads"].insert(
            {
                "id": thread_id,
                "name": name,
                "tip_message_hash": tip,
                "forked_from": forked_from,
                "datetime_utc": _now(),
            }
        )
        return thread_id

    def ensure_thread(self, thread_id: str, name: str | None = None) -> str:
        """Return the thread with this id, creating it if it is new.

        Threads created from a conversation reuse the conversation's id,
        so the two identifier spaces line up while both sets of tables
        are being written.
        """
        if not self.db["threads"].count_where("id = ?", [thread_id]):
            self.create_thread(name=name, id=thread_id)
        return thread_id

    def fork(
        self,
        message_hash_: str,
        name: str | None = None,
        forked_from: str | None = None,
    ) -> str:
        """Start a new thread from an existing message.

        Nothing is copied - the new thread points at a message that is
        already stored, so its whole history is shared with the thread it
        came from until the two diverge.
        """
        if not self.db["messages"].count_where("hash = ?", [message_hash_]):
            raise KeyError(message_hash_)
        return self.create_thread(name=name, tip=message_hash_, forked_from=forked_from)

    def thread_tip(self, thread_id: str) -> str | None:
        "The message a thread currently points at."
        rows = list(self.db.query("select * from threads where id = ?", [thread_id]))
        if not rows:
            raise KeyError(thread_id)
        return rows[0]["tip_message_hash"]

    def thread_messages(self, thread_id: str) -> list[Message]:
        "The full history of a thread, oldest message first."
        return self.load_chain(self.thread_tip(thread_id))

    def append(self, thread_id: str, messages) -> str | None:
        "Add messages to the end of a thread and return the new tip."
        tip = self.ensure_chain(messages, parent=self.thread_tip(thread_id))
        self.db["threads"].update(thread_id, {"tip_message_hash": tip})
        return tip

    # -- turns ---------------------------------------------------------

    def log(self, response, thread_id: str | None = None) -> str:
        """Record a completed response.

        The input chain and the response's own output are stored as
        messages; everything that is specific to this particular call -
        timings, usage, which model answered - goes on the turn, because
        message rows are shared and so cannot carry provenance.
        """
        if thread_id is None:
            conversation = getattr(response, "conversation", None)
            if conversation is not None:
                thread_id = self.ensure_thread(
                    conversation.id,
                    name=_conversation_name(
                        response.prompt.prompt or response.prompt.system or ""
                    ),
                )

        parent = self.ensure_chain(response.prompt.messages)
        # _messages_now() rather than messages(), which is a coroutine on
        # AsyncResponse.
        tip = self.ensure_chain(response._messages_now(), parent=parent)

        schema_id = None
        if response.prompt.schema:
            schema_id, schema_json = make_schema_id(response.prompt.schema)
            self.db["schemas"].insert(
                {"id": schema_id, "content": schema_json}, ignore=True
            )

        turn_id = response.id or str(monotonic_ulid()).lower()
        self.db["turns"].insert(
            {
                "id": turn_id,
                "thread_id": thread_id,
                "parent_message_hash": parent,
                "tip_message_hash": tip,
                "model": response.model.model_id,
                "resolved_model": response.resolved_model,
                "options_json": _dump(
                    {
                        key: value
                        for key, value in dict(response.prompt.options).items()
                        if value is not None
                    }
                ),
                "schema_id": schema_id,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "token_details": _dump(response.token_details),
                "duration_ms": response.duration_ms(),
                "datetime_utc": response.datetime_utc(),
                "response_json": _dump(response.response_json),
            },
            replace=True,
        )
        for tool in response.prompt.tools:
            self.db["turn_tools"].insert(
                {"turn_id": turn_id, "tool_id": ensure_tool(self.db, tool)},
                replace=True,
            )
        if thread_id is not None:
            self.db["threads"].update(thread_id, {"tip_message_hash": tip})
        return turn_id

    # -- pending work --------------------------------------------------

    def pending_tool_calls(self, tip: str | None) -> list[Any]:
        """Tool calls at the tip of a chain that have no result yet.

        A chain ending in tool calls with nothing after them is a paused
        conversation waiting to be resumed - it needs no separate record.
        """
        chain = self.load_chain(tip)
        if not chain:
            return []
        return [part for part in chain[-1].parts if isinstance(part, ToolCallPart)]


def ensure_attachment(db, attachment) -> str:
    "Store an attachment, returning its content-addressed id."
    attachment_id = attachment.id()
    db["attachments"].insert(
        {
            "id": attachment_id,
            "type": attachment.resolve_type(),
            "path": attachment.path,
            "url": attachment.url,
            "content": attachment.content,
        },
        replace=True,
    )
    return attachment_id


def _part_from_row(row: dict, attachments: list[Any]):
    type = row["type"]
    provider_metadata = _load(row["provider_metadata"])
    text = row["fragment_content"] if row["fragment_id"] else row["text"]
    if type == "text":
        return TextPart(text=text or "", provider_metadata=provider_metadata)
    if type == "reasoning":
        return ReasoningPart(
            text=text or "",
            redacted=bool(row["redacted"]),
            provider_metadata=provider_metadata,
        )
    if type == "tool_call":
        return ToolCallPart(
            name=row["name"] or "",
            arguments=json.loads(row["arguments"] or "{}"),
            tool_call_id=row["tool_call_id"],
            server_executed=bool(row["server_executed"]),
            provider_metadata=provider_metadata,
        )
    if type == "tool_result":
        return ToolResultPart(
            name=row["name"] or "",
            output=row["output"] or "",
            tool_call_id=row["tool_call_id"],
            server_executed=bool(row["server_executed"]),
            exception=row["exception"],
            attachments=attachments,
            provider_metadata=provider_metadata,
        )
    if type == "attachment":
        return AttachmentPart(
            attachment=attachments[0] if attachments else None,
            provider_metadata=provider_metadata,
        )
    raise ValueError(f"Unknown part type: {type!r}")


def _dump(value: dict | None) -> str | None:
    return json.dumps(value) if value else None


def _load(value: str | None) -> dict | None:
    return json.loads(value) if value else None


def _now() -> str:
    return str(datetime.datetime.now(datetime.timezone.utc))
