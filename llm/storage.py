"""Persistence layer for Message/Part values and conversation tree nodes.

Two layers, mirroring the principle in llm.parts that Messages are pure
values and identity is a storage concern:

- Values: ``messages`` and ``parts`` rows are content-addressed — the
  message id is a sha256 of the canonical JSON form, so identical
  content is stored exactly once no matter how many conversations it
  appears in. Attachments inside messages are stored in the existing
  content-addressed ``attachments`` table and referenced by id.

- Identity: ``nodes`` rows give content a position. Each node points at
  its parent node and the message occupying that position; a
  conversation chain is the path from a root (parent NULL) to a leaf.
  Two chains that share a prefix share those node rows.

The round-trip contract: ``load_message(db, ensure_message(db, m))``
returns a Message whose ``to_dict()`` equals ``m.to_dict()``.
"""

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from .models import Attachment
from .parts import (
    AttachmentPart,
    Message,
    Part,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from .utils import monotonic_ulid


def _canonical_part_dict(part: Part) -> Dict[str, Any]:
    """part.to_dict() with attachment payloads replaced by their
    content-addressed ids, so multi-megabyte binaries hash fast and
    identical content dedupes regardless of whether it arrived via
    path, url or content."""
    d: Dict[str, Any] = dict(part.to_dict())
    if isinstance(part, AttachmentPart) and part.attachment is not None:
        d["attachment"] = {"id": part.attachment.id()}
    if isinstance(part, ToolResultPart) and part.attachments:
        d["attachments"] = [{"id": a.id()} for a in part.attachments]
    return d


def _canonical_message_json(message: Message) -> str:
    d: Dict[str, Any] = {
        "role": message.role,
        "parts": [_canonical_part_dict(p) for p in message.parts],
    }
    if message.provider_metadata:
        d["provider_metadata"] = message.provider_metadata
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


def message_hash(message: Message) -> str:
    "Content hash used as the messages table primary key."
    return hashlib.sha256(_canonical_message_json(message).encode("utf-8")).hexdigest()


def _ensure_attachment(db, attachment: Attachment) -> str:
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


def _part_to_row(message_id: str, order: int, part: Part) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "message_id": message_id,
        "order": order,
        "type": None,
        "text": None,
        "redacted": None,
        "name": None,
        "arguments": None,
        "output": None,
        "tool_call_id": None,
        "server_executed": None,
        "exception": None,
        "instance_id": None,
        "attachment_id": None,
        "provider_metadata": (
            json.dumps(part.provider_metadata) if part.provider_metadata else None
        ),
    }
    if isinstance(part, TextPart):
        row["type"] = "text"
        row["text"] = part.text
    elif isinstance(part, ReasoningPart):
        row["type"] = "reasoning"
        row["text"] = part.text
        row["redacted"] = 1 if part.redacted else 0
    elif isinstance(part, ToolCallPart):
        row["type"] = "tool_call"
        row["name"] = part.name
        row["arguments"] = json.dumps(part.arguments)
        row["tool_call_id"] = part.tool_call_id
        row["server_executed"] = 1 if part.server_executed else 0
    elif isinstance(part, ToolResultPart):
        row["type"] = "tool_result"
        row["name"] = part.name
        row["output"] = part.output
        row["tool_call_id"] = part.tool_call_id
        row["server_executed"] = 1 if part.server_executed else 0
        row["exception"] = part.exception
    elif isinstance(part, AttachmentPart):
        row["type"] = "attachment"
    else:
        raise ValueError(f"Cannot store part of type {type(part)!r}")
    return row


def _row_to_part(db, row: Dict[str, Any]) -> Part:
    provider_metadata = (
        json.loads(row["provider_metadata"]) if row["provider_metadata"] else None
    )
    type_ = row["type"]
    if type_ == "text":
        return TextPart(text=row["text"] or "", provider_metadata=provider_metadata)
    if type_ == "reasoning":
        return ReasoningPart(
            text=row["text"] or "",
            redacted=bool(row["redacted"]),
            provider_metadata=provider_metadata,
        )
    if type_ == "tool_call":
        return ToolCallPart(
            name=row["name"] or "",
            arguments=json.loads(row["arguments"] or "{}"),
            tool_call_id=row["tool_call_id"],
            server_executed=bool(row["server_executed"]),
            provider_metadata=provider_metadata,
        )
    if type_ == "tool_result":
        attachments = [
            Attachment.from_row(attachment_row)
            for attachment_row in db.query(
                """
                select attachments.* from attachments
                join part_attachments on attachments.id = part_attachments.attachment_id
                where part_attachments.part_id = ?
                order by part_attachments."order"
                """,
                [row["id"]],
            )
        ]
        return ToolResultPart(
            name=row["name"] or "",
            output=row["output"] or "",
            tool_call_id=row["tool_call_id"],
            server_executed=bool(row["server_executed"]),
            exception=row["exception"],
            attachments=attachments,
            provider_metadata=provider_metadata,
        )
    if type_ == "attachment":
        attachment = None
        if row["attachment_id"]:
            attachment_row = db["attachments"].get(row["attachment_id"])
            attachment = Attachment.from_row(attachment_row)
        return AttachmentPart(
            attachment=attachment, provider_metadata=provider_metadata
        )
    raise ValueError(f"Unknown part type in parts table: {type_!r}")


def ensure_message(
    db,
    message: Message,
    instance_ids: Optional[Dict[str, int]] = None,
) -> str:
    """Insert a message and its parts if not already stored; return its id.

    ``instance_ids`` maps tool_call_id to a tool_instances id; it is
    applied to tool_result parts only when the message is first
    inserted — instance tracking is best-effort audit data, not part of
    the message value or the round trip.
    """
    message_id = message_hash(message)
    if db.execute("select 1 from messages where id = ?", [message_id]).fetchone():
        return message_id
    with db.conn:
        db["messages"].insert(
            {
                "id": message_id,
                "role": message.role,
                "provider_metadata": (
                    json.dumps(message.provider_metadata)
                    if message.provider_metadata
                    else None
                ),
            },
            ignore=True,
        )
        for order, part in enumerate(message.parts):
            row = _part_to_row(message_id, order, part)
            if isinstance(part, AttachmentPart) and part.attachment is not None:
                row["attachment_id"] = _ensure_attachment(db, part.attachment)
            if (
                isinstance(part, ToolResultPart)
                and instance_ids
                and part.tool_call_id in instance_ids
            ):
                row["instance_id"] = instance_ids[part.tool_call_id]
            part_id = db["parts"].insert(row).last_pk
            if isinstance(part, ToolResultPart):
                for att_order, attachment in enumerate(part.attachments):
                    db["part_attachments"].insert(
                        {
                            "part_id": part_id,
                            "attachment_id": _ensure_attachment(db, attachment),
                            "order": att_order,
                        }
                    )
    return message_id


def load_messages(db, message_ids: List[str]) -> List[Message]:
    "Load Message values by id, preserving the order of message_ids."
    if not message_ids:
        return []
    unique_ids = list(dict.fromkeys(message_ids))
    placeholders = ",".join("?" * len(unique_ids))
    message_rows = {
        row["id"]: row
        for row in db.query(
            f"select * from messages where id in ({placeholders})", unique_ids
        )
    }
    parts_by_message: Dict[str, List[Dict[str, Any]]] = {}
    for part_row in db.query(
        f'select * from parts where message_id in ({placeholders}) order by "order"',
        unique_ids,
    ):
        parts_by_message.setdefault(part_row["message_id"], []).append(part_row)
    messages = []
    for message_id in message_ids:
        if message_id not in message_rows:
            raise KeyError(f"No message stored with id {message_id!r}")
        row = message_rows[message_id]
        messages.append(
            Message(
                role=row["role"],
                parts=[
                    _row_to_part(db, part_row)
                    for part_row in parts_by_message.get(message_id, [])
                ],
                provider_metadata=(
                    json.loads(row["provider_metadata"])
                    if row["provider_metadata"]
                    else None
                ),
            )
        )
    return messages


def load_message(db, message_id: str) -> Message:
    "Load a single Message value by id."
    return load_messages(db, [message_id])[0]


def ensure_node(db, parent_id: Optional[str], message_id: str) -> Tuple[str, bool]:
    """Look up or insert the node for (parent_id, message_id).

    Returns (node_id, created). Nodes are immutable and deduplicated on
    the (parent, message) pair: two chains extending the same leaf with
    the same message share a node.
    """
    row = db.execute(
        "select id from nodes where parent_id is ? and message_id = ?",
        [parent_id, message_id],
    ).fetchone()
    if row:
        return row[0], False
    depth = 0
    if parent_id is not None:
        parent = db.execute(
            "select depth from nodes where id = ?", [parent_id]
        ).fetchone()
        if parent is None:
            raise ValueError(f"No node with id {parent_id!r}")
        depth = parent[0] + 1
    node_id = str(monotonic_ulid()).lower()
    db["nodes"].insert(
        {
            "id": node_id,
            "parent_id": parent_id,
            "message_id": message_id,
            "depth": depth,
        }
    )
    return node_id, True


def append_chain(
    db,
    parent_id: Optional[str],
    messages: List[Message],
    instance_ids: Optional[Dict[str, int]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Walk messages down the tree from parent_id, creating value and
    node rows only for what does not already exist.

    Returns (leaf_node_id, first_new_node_id). first_new_node_id is
    None when every message was already present at its position — e.g.
    an identical chain replayed.
    """
    first_new: Optional[str] = None
    for message in messages:
        message_id = ensure_message(db, message, instance_ids=instance_ids)
        parent_id, created = ensure_node(db, parent_id, message_id)
        if created and first_new is None:
            first_new = parent_id
    return parent_id, first_new


NODE_PATH_SQL = """
with recursive path(id, parent_id, message_id, depth) as (
    select id, parent_id, message_id, depth from nodes where id = :leaf
    union all
    select nodes.id, nodes.parent_id, nodes.message_id, nodes.depth
    from nodes join path on nodes.id = path.parent_id
)
select id as node_id, message_id, depth from path order by depth
"""


def node_path(db, leaf_id: str) -> List[Dict[str, Any]]:
    "Return node rows from root to leaf_id inclusive, ordered by depth."
    return list(db.query(NODE_PATH_SQL, {"leaf": leaf_id}))


def load_chain(db, leaf_id: Optional[str]) -> List[Message]:
    "Load the Message values along the path from root to leaf_id."
    if leaf_id is None:
        return []
    path = node_path(db, leaf_id)
    return load_messages(db, [row["message_id"] for row in path])
