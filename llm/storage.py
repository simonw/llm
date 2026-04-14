"""DAG-shaped message storage — see plans/dag-schema.md.

MessageStore writes and reads the immutable, parent-linked message DAG
sitting behind ``llm``'s in-memory ``Message`` values. ``save_chain``
dedups: a prefix that already exists as a chain gets no new rows; only
the unmatched tail is written.

The Python ``Message`` type stays a pure value — identity (ids,
parent links) is a storage concern that lives here.
"""

import base64
import datetime
import json
from typing import Any, Dict, List, Optional

from ._canonical import message_content_hash
from .models import Attachment
from .parts import (
    AttachmentPart,
    Message,
    Part,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
    _attachment_from_dict,
)
from .utils import monotonic_ulid

ROOT_ID = "root"


def _now_iso() -> str:
    return str(datetime.datetime.now(datetime.timezone.utc))


def _new_ulid() -> str:
    return str(monotonic_ulid()).lower()


def _part_to_row(message_id: str, order: int, part: Part) -> Dict[str, Any]:
    """Serialize a Part into a ``message_parts`` row (no id yet)."""
    row: Dict[str, Any] = {"message_id": message_id, "order": order}
    pm = getattr(part, "provider_metadata", None)
    if isinstance(part, TextPart):
        row["part_type"] = "text"
        row["content"] = part.text
        if pm:
            row["content_json"] = json.dumps({"provider_metadata": pm})
    elif isinstance(part, ReasoningPart):
        row["part_type"] = "reasoning"
        row["content"] = part.text
        extra: Dict[str, Any] = {}
        if part.redacted or part.token_count:
            extra["redacted"] = part.redacted
            extra["token_count"] = part.token_count
        if pm:
            extra["provider_metadata"] = pm
        if extra:
            row["content_json"] = json.dumps(extra)
    elif isinstance(part, AttachmentPart):
        row["part_type"] = "attachment"
        if part.attachment:
            att_data: Dict[str, Any] = {}
            if part.attachment.type:
                att_data["type"] = part.attachment.type
            if part.attachment.url:
                att_data["url"] = part.attachment.url
            if part.attachment.path:
                att_data["path"] = part.attachment.path
            if part.attachment.content:
                att_data["content"] = base64.b64encode(
                    part.attachment.content
                ).decode("ascii")
            if pm:
                att_data["provider_metadata"] = pm
            row["content_json"] = json.dumps(att_data)
    elif isinstance(part, ToolCallPart):
        row["part_type"] = "tool_call"
        tc_data: Dict[str, Any] = {
            "name": part.name,
            "arguments": part.arguments,
        }
        if pm:
            tc_data["provider_metadata"] = pm
        row["content_json"] = json.dumps(tc_data)
        row["tool_call_id"] = part.tool_call_id
        row["server_executed"] = 1 if part.server_executed else 0
    elif isinstance(part, ToolResultPart):
        row["part_type"] = "tool_result"
        row["content"] = part.output
        tr_data: Dict[str, Any] = {
            "name": part.name,
            "exception": part.exception,
        }
        if pm:
            tr_data["provider_metadata"] = pm
        row["content_json"] = json.dumps(tr_data)
        row["tool_call_id"] = part.tool_call_id
        row["server_executed"] = 1 if part.server_executed else 0
    else:
        row["part_type"] = "unknown"
        row["content_json"] = json.dumps(part.to_dict())
    return row


def _row_to_part(row: Any) -> Part:
    """Reverse of ``_part_to_row``."""
    part_type = row["part_type"]
    content = row["content"]
    content_json = row["content_json"]
    tool_call_id = row["tool_call_id"]
    server_executed = bool(row["server_executed"])
    data = json.loads(content_json) if content_json else {}
    pm = data.get("provider_metadata")
    if part_type == "text":
        return TextPart(text=content or "", provider_metadata=pm)
    if part_type == "reasoning":
        return ReasoningPart(
            text=content or "",
            redacted=data.get("redacted", False),
            token_count=data.get("token_count"),
            provider_metadata=pm,
        )
    if part_type == "tool_call":
        return ToolCallPart(
            name=data.get("name", ""),
            arguments=data.get("arguments", {}),
            tool_call_id=tool_call_id,
            server_executed=server_executed,
            provider_metadata=pm,
        )
    if part_type == "tool_result":
        return ToolResultPart(
            name=data.get("name", ""),
            output=content or "",
            tool_call_id=tool_call_id,
            server_executed=server_executed,
            exception=data.get("exception"),
            provider_metadata=pm,
        )
    if part_type == "attachment":
        attachment = None
        if data and any(
            data.get(k) for k in ("type", "url", "path", "content")
        ):
            attachment = _attachment_from_dict(data)
        return AttachmentPart(attachment=attachment)
    # Unknown — best-effort round-trip via Part.from_dict.
    return Part.from_dict(data)


class MessageStore:
    """Read/write the message DAG."""

    def __init__(self, db):
        self.db = db

    # -- public API --

    def save_chain(
        self,
        messages: List[Message],
        starting_parent_id: Optional[str] = None,
    ) -> str:
        """Save a chain of messages, deduplicating against existing rows.

        Returns the head message id after saving. ``starting_parent_id``
        is the parent to attach the first message under; ``None`` means
        the chain root (sentinel-rooted).
        """
        parent = starting_parent_id or ROOT_ID
        for msg in messages:
            parent = self._save_one(msg, parent)
        return parent

    def load_chain(self, head_message_id: str) -> List[Message]:
        """Walk ``parent_id`` links from ``head_message_id`` back to the
        sentinel and return the chain in forward order."""
        rows = []
        cur = head_message_id
        while cur != ROOT_ID:
            row = self.db.execute(
                "SELECT id, parent_id, role, provider_metadata_json "
                "FROM messages WHERE id = ?",
                [cur],
            ).fetchone()
            if row is None:
                raise ValueError(f"message {cur!r} not found")
            rows.append(row)
            cur = row[1]
        rows.reverse()
        out: List[Message] = []
        for msg_id, _parent, role, pm_json in rows:
            pm = json.loads(pm_json) if pm_json else None
            part_rows = list(
                self.db.execute(
                    "SELECT part_type, content, content_json, tool_call_id, "
                    'server_executed FROM message_parts WHERE message_id = ? '
                    'ORDER BY "order"',
                    [msg_id],
                ).fetchall()
            )
            parts = [
                _row_to_part(
                    {
                        "part_type": r[0],
                        "content": r[1],
                        "content_json": r[2],
                        "tool_call_id": r[3],
                        "server_executed": r[4],
                    }
                )
                for r in part_rows
            ]
            out.append(Message(role=role, parts=parts, provider_metadata=pm))
        return out

    def find_longest_existing_prefix(
        self, messages: List[Message]
    ) -> "tuple[Optional[str], int]":
        """Return ``(last_matched_message_id, count_matched)``.

        ``last_matched_message_id`` is ``None`` if nothing matched (no
        chain root exists for the first message). Used by stateless-API
        continuation detection — see plans/dag-schema.md.
        """
        parent = ROOT_ID
        matched = 0
        last: Optional[str] = None
        for msg in messages:
            h = message_content_hash(msg)
            row = self.db.execute(
                "SELECT id FROM messages "
                "WHERE parent_id = ? AND content_hash = ? LIMIT 1",
                [parent, h],
            ).fetchone()
            if not row:
                break
            last = row[0]
            parent = last
            matched += 1
        return last, matched

    # -- internals --

    def _save_one(self, msg: Message, parent_id: str) -> str:
        h = message_content_hash(msg)
        existing = self.db.execute(
            "SELECT id FROM messages "
            "WHERE parent_id = ? AND content_hash = ? LIMIT 1",
            [parent_id, h],
        ).fetchone()
        if existing:
            return existing[0]
        new_id = _new_ulid()
        pm_json = (
            json.dumps(msg.provider_metadata, sort_keys=True)
            if msg.provider_metadata
            else None
        )
        self.db["messages"].insert(
            {
                "id": new_id,
                "parent_id": parent_id,
                "content_hash": h,
                "role": msg.role,
                "provider_metadata_json": pm_json,
                "created_at": _now_iso(),
            }
        )
        for order, part in enumerate(msg.parts):
            row = _part_to_row(new_id, order, part)
            row["id"] = _new_ulid()
            self.db["message_parts"].insert(row)
        return new_id
