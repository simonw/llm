"""Content-addressed storage for structured message trees.

This module is the public, stable API for persisting ``llm.Message``
objects (and full ``Response`` turns) to a SQLite logs database with
full structural fidelity - every Part, including reasoning parts and
``provider_metadata``, survives a round-trip. Plugins are encouraged to
use it for their own logging needs.

Three tables (created by the ``m023_message_trees`` migration):

- ``messages`` - one row per unique message, keyed by a content hash.
- ``message_nodes`` - Merkle-style chain nodes. A node is
  ``(parent_node, message)`` and its id is a hash of both, so a node id
  identifies an entire message chain (the message plus everything
  before it). Conversations that share a prefix share nodes: storing
  the same chain twice inserts nothing new, and storing a chain that
  extends an existing one inserts only the new tail.
- ``response_nodes`` - links a row in the existing ``responses`` table
  to the node heads for its input chain and its output chain.

Hashing scheme
--------------

``canonical_json(value)`` is::

    json.dumps(value, sort_keys=True, separators=(",", ":"),
               ensure_ascii=False).encode("utf-8")

A message is stored (and hashed) as the dict returned by
``Message.to_dict()`` with one substitution: attachments are replaced
by references into the existing content-addressed ``attachments``
table. An attachment part becomes ``{"type": "attachment",
"attachment_id": ...}`` and a tool result part's ``attachments`` list
becomes ``attachment_ids``. The attachment id is ``Attachment.id()``
(itself a SHA-256 of the attachment content).

Then::

    message id = sha256(canonical_json(stored_message_dict)).hexdigest()
    node id = sha256("{parent_node_id}:{message_id}".encode("utf-8")).hexdigest()

where ``parent_node_id`` is the empty string for the first message in a
chain. Anything that writes to these tables - this module, plugins, or
code in other languages - must hash identically or deduplication
breaks; treat the definitions above as part of the schema.
"""

import datetime
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple, cast

from sqlite_utils.db import NotFoundError

from .migrations import migrate
from .models import Attachment

__all__ = (
    "canonical_json",
    "ensure_tables",
    "message_hash",
    "node_hash",
    "store_message",
    "store_messages",
    "load_messages",
    "log_response",
    "load_response",
    "hydrate_response_messages",
)


def ensure_tables(db):
    """Create the message store tables if they do not exist yet.

    Idempotent and safe on both migrated and unmigrated databases -
    the store functions call this automatically. Rows in these tables
    are immutable: the id of a message or node is a hash of its
    content, so identical messages (and identical conversation
    prefixes) are stored once no matter how many responses share them.
    """
    if not db["attachments"].exists():
        # Same schema as the m012_attachments_tables migration, so a
        # standalone message-store database can hold attachments too.
        db["attachments"].create(
            {
                "id": str,
                "type": str,
                "path": str,
                "url": str,
                "content": bytes,
            },
            pk="id",
        )
    if not db["messages"].exists():
        db["messages"].create(
            {
                "id": str,  # message_hash() of the stored form
                "role": str,
                "parts": str,  # JSON list of part dicts, attachments by id
                "provider_metadata": str,  # JSON, message-level metadata
                "first_seen_utc": str,
            },
            pk="id",
        )
    if not db["message_nodes"].exists():
        db["message_nodes"].create(
            {
                "id": str,  # node_hash(parent_id, message_id)
                "parent_id": str,  # NULL for the first message in a chain
                "message_id": str,
                "depth": int,  # 1 for root nodes
                "first_seen_utc": str,
            },
            pk="id",
            foreign_keys=(
                ("parent_id", "message_nodes", "id"),
                ("message_id", "messages", "id"),
            ),
        )
        db["message_nodes"].create_index(["parent_id"])
    if not db["response_nodes"].exists():
        foreign_keys = [
            ("input_node_id", "message_nodes", "id"),
            ("output_node_id", "message_nodes", "id"),
        ]
        if db["responses"].exists():
            # Standalone message-store databases have no responses table
            foreign_keys.insert(0, ("response_id", "responses", "id"))
        db["response_nodes"].create(
            {
                "response_id": str,
                "input_node_id": str,  # head of the chain sent to the model
                "output_node_id": str,  # head after appending output messages
            },
            pk="response_id",
            foreign_keys=foreign_keys,
        )


def canonical_json(value: Any) -> bytes:
    "Canonical JSON encoding used for content hashes."
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def message_hash(message) -> str:
    "Content hash of a Message - its id in the messages table."
    return hashlib.sha256(canonical_json(_stored_message_dict(message))).hexdigest()


def node_hash(parent_node_id: Optional[str], message_id: str) -> str:
    "Id of the chain node for message_id following parent_node_id."
    return hashlib.sha256(
        "{}:{}".format(parent_node_id or "", message_id).encode("utf-8")
    ).hexdigest()


def _now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _stored_part_dict(part) -> Tuple[Dict[str, Any], List[Attachment]]:
    """The dict stored (and hashed) for a Part, plus the attachments it
    references so store_message() can persist them."""
    d = dict(part.to_dict())
    attachments: List[Attachment] = []
    if d.get("type") == "attachment":
        d.pop("attachment", None)
        attachment = getattr(part, "attachment", None)
        if attachment is not None:
            d["attachment_id"] = attachment.id()
            attachments.append(attachment)
    elif d.get("type") == "tool_result":
        d.pop("attachments", None)
        part_attachments = getattr(part, "attachments", None) or []
        if part_attachments:
            d["attachment_ids"] = [a.id() for a in part_attachments]
            attachments.extend(part_attachments)
    return d, attachments


def _stored_message(message) -> Tuple[Dict[str, Any], List[Attachment]]:
    stored_parts = []
    attachments: List[Attachment] = []
    for part in message.parts:
        part_dict, part_attachments = _stored_part_dict(part)
        stored_parts.append(part_dict)
        attachments.extend(part_attachments)
    d: Dict[str, Any] = {"role": message.role, "parts": stored_parts}
    if message.provider_metadata:
        d["provider_metadata"] = message.provider_metadata
    return d, attachments


def _stored_message_dict(message) -> Dict[str, Any]:
    return _stored_message(message)[0]


def _ensure_attachment(db, attachment: Attachment) -> str:
    attachment_id = attachment.id()
    try:
        db["attachments"].get(attachment_id)
    except NotFoundError:
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


def _load_attachment(db, attachment_id: str) -> Attachment:
    try:
        row = db["attachments"].get(attachment_id)
    except NotFoundError:
        raise ValueError(
            "Message references attachment {} which is not present in the "
            "attachments table".format(attachment_id)
        )
    return Attachment.from_row(row)


def _part_from_stored_dict(db, d: Dict[str, Any]):
    from .parts import AttachmentPart, Part, ToolResultPart
    from .serialization import PartDict

    d = dict(d)
    if d.get("type") == "attachment":
        attachment_id = d.pop("attachment_id", None)
        return AttachmentPart(
            attachment=(_load_attachment(db, attachment_id) if attachment_id else None),
            provider_metadata=d.get("provider_metadata"),
        )
    if d.get("type") == "tool_result":
        attachment_ids = d.pop("attachment_ids", [])
        part = cast(ToolResultPart, Part.from_dict(cast(PartDict, d)))
        part.attachments = [_load_attachment(db, aid) for aid in attachment_ids]
        return part
    return Part.from_dict(cast(PartDict, d))


def store_message(db, message) -> str:
    """Store a single Message, returning its content-hash id.

    Idempotent: storing the same message twice inserts nothing new.
    Attachments referenced by the message are persisted to the
    attachments table.
    """
    ensure_tables(db)
    stored, attachments = _stored_message(message)
    message_id = hashlib.sha256(canonical_json(stored)).hexdigest()
    for attachment in attachments:
        _ensure_attachment(db, attachment)
    db["messages"].insert(
        {
            "id": message_id,
            "role": stored["role"],
            "parts": json.dumps(stored["parts"]),
            "provider_metadata": (
                json.dumps(stored["provider_metadata"])
                if stored.get("provider_metadata")
                else None
            ),
            "first_seen_utc": _now_utc(),
        },
        ignore=True,
    )
    return message_id


def store_messages(db, messages, parent_node_id: Optional[str] = None) -> Optional[str]:
    """Store a list of Messages as a chain, returning the head node id.

    Pass ``parent_node_id`` to extend an existing chain. Chains sharing
    a prefix share nodes, so re-storing a conversation that was stored
    before only inserts the messages and nodes that are new. Returns
    ``parent_node_id`` unchanged if ``messages`` is empty.
    """
    ensure_tables(db)
    node_id = parent_node_id
    depth = 0
    if node_id is not None:
        depth = db["message_nodes"].get(node_id)["depth"]
    for message in messages:
        message_id = store_message(db, message)
        depth += 1
        next_node_id = node_hash(node_id, message_id)
        db["message_nodes"].insert(
            {
                "id": next_node_id,
                "parent_id": node_id,
                "message_id": message_id,
                "depth": depth,
                "first_seen_utc": _now_utc(),
            },
            ignore=True,
        )
        node_id = next_node_id
    return node_id


_NODE_CHAIN_SQL = """
with recursive chain(id, parent_id, message_id, depth) as (
    select id, parent_id, message_id, depth
    from message_nodes where id = :node_id
    union all
    select message_nodes.id, message_nodes.parent_id,
        message_nodes.message_id, message_nodes.depth
    from message_nodes join chain on message_nodes.id = chain.parent_id
)
select chain.depth, messages.role, messages.parts, messages.provider_metadata
from chain join messages on messages.id = chain.message_id
order by chain.depth
"""


def load_messages(db, node_id: str) -> List[Any]:
    """Load the full Message chain identified by a node id.

    Returns every message from the root of the chain up to and
    including the node itself, in conversation order.
    """
    from .parts import Message

    rows = list(db.query(_NODE_CHAIN_SQL, {"node_id": node_id}))
    if not rows:
        raise ValueError("Unknown message node: {}".format(node_id))
    return [
        Message(
            role=row["role"],
            parts=[
                _part_from_stored_dict(db, part_dict)
                for part_dict in json.loads(row["parts"])
            ],
            provider_metadata=(
                json.loads(row["provider_metadata"])
                if row["provider_metadata"]
                else None
            ),
        )
        for row in rows
    ]


def _write_response_nodes(db, response) -> None:
    """Store a response's input and output message chains and link them
    to its row in the responses table.

    Called automatically at the end of Response.log_to_db()."""
    input_node_id = store_messages(db, response.prompt.messages)
    output_node_id = store_messages(
        db, response._messages_now(), parent_node_id=input_node_id
    )
    db["response_nodes"].insert(
        {
            "response_id": response.id,
            "input_node_id": input_node_id,
            "output_node_id": output_node_id,
        },
        replace=True,
    )


def hydrate_response_messages(db, response) -> bool:
    """Restore a from_row() response's structured messages from the
    message store.

    Returns True if the response had a response_nodes row - in which
    case ``response.prompt.messages`` is the exact input chain and
    ``response.messages()`` returns the exact output messages, with
    reasoning parts and provider_metadata intact. Returns False for
    responses logged before the message store existed, leaving the
    legacy from_row() reconstruction untouched.
    """
    if not db["response_nodes"].exists():
        return False
    try:
        node_row = db["response_nodes"].get(response.id)
    except NotFoundError:
        return False
    input_messages: List[Any] = []
    if node_row["input_node_id"]:
        input_messages = load_messages(db, node_row["input_node_id"])
    output_messages: List[Any] = []
    if node_row["output_node_id"]:
        full_chain = load_messages(db, node_row["output_node_id"])
        output_messages = full_chain[len(input_messages) :]
    response.prompt._explicit_messages = input_messages
    response._loaded_messages = output_messages
    return True


def log_response(db, response) -> str:
    """Log a Response (or awaited AsyncResponse) to a logs database.

    Applies any pending schema migrations, then performs the same full
    write as the ``llm`` CLI: the legacy tables (responses, tool_calls,
    tool_results, attachments, fragments) plus the structured message
    store. Returns the response id.
    """
    from .models import AsyncResponse

    migrate(db)
    if isinstance(response, AsyncResponse):
        import asyncio

        response = asyncio.run(response.to_sync_response())
    response.log_to_db(db)
    return response.id


def load_response(db, response_id: str, *, async_: bool = False):
    """Load a logged response by id at full fidelity.

    Uses the structured message store when the response was logged with
    it, falling back to the legacy columns for older rows. Pass
    ``async_=True`` for an AsyncResponse.
    """
    from .models import AsyncResponse, Response

    row = db["responses"].get(response_id)
    cls = AsyncResponse if async_ else Response
    response = cls.from_row(db, row)
    hydrate_response_messages(db, response)
    return response
