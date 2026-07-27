"""Content-addressed storage for conversation message trees.

A conversation is a parent-linked chain of :class:`llm.Message` objects.
Each message is identified by a hash over its own canonical content plus
its parent's hash, so two conversations that share a prefix share the
rows that store it. Forking a conversation, or re-sending a history from
a client that holds the conversation state itself, both write only the
messages that are genuinely new.

The identity of a message is its *resolved* content, but storage is by
reference: text that borrows from a fragment stores the fragment's id in
place of a copy, and attachments store an id into the existing
content-addressed ``attachments`` table. Ask a hundred questions about a
novel and the novel is stored once. Reading resolves the references
again, so the hash always covers the content as the model saw it -
``LogStore.verify()`` re-derives it to prove that stays true.
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
    Part,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from .utils import ensure_fragment, ensure_tool, make_schema_id, monotonic_ulid

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

    def ensure_chain(
        self,
        messages,
        parent: str | None = None,
        fragments=None,
    ) -> str | None:
        """Store ``messages`` as a chain and return the hash of the tip.

        Messages already present are left alone, so a caller that
        re-sends a whole conversation - a client holding the state
        itself, or a fork of an existing thread - writes only the
        messages that are new. Passing ``parent`` appends to an existing
        chain instead of starting a new one.

        ``fragments`` is an optional list of fragment contents that may
        appear inside these messages. Any that do are stored as a
        reference rather than a copy, which is the point of the fragments
        feature: ask a hundred questions about a novel and the novel is
        stored once. It never affects the hashes - identity is always the
        resolved text.
        """
        fragment_map = self._fragment_map(fragments)
        tip = parent
        for message in messages:
            tip = self._ensure_message(message, tip, fragment_map)
        return tip

    def _fragment_map(self, fragments) -> dict[str, int]:
        "Map fragment content to its id, registering any that are new."
        if not fragments:
            return {}
        return {
            str(fragment): ensure_fragment(self.db, fragment)
            for fragment in fragments
            if str(fragment)
        }

    def _ensure_message(
        self,
        message: Message,
        parent_hash: str | None,
        fragment_map: dict[str, int],
    ) -> str:
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
                self._write_part(hash, position, part, fragment_map)
        return hash

    def _write_part(
        self,
        message_hash_: str,
        position: int,
        part,
        fragment_map: dict[str, int],
    ) -> None:
        payload = part.to_dict()
        attachments = _attachments_of(part)

        # Large content out of the payload and into the tables that
        # already store it once: fragments for text, attachments for
        # bytes. Both are resolved again on the way back out.
        used_fragments = _encode_text_refs(payload, fragment_map)
        if attachments:
            attachment_ids = [
                ensure_attachment(self.db, attachment) for attachment in attachments
            ]
            _encode_attachment_refs(payload, attachment_ids)
        else:
            attachment_ids = []

        part_id = (
            self.db["parts"]
            .insert(
                {
                    "message_hash": message_hash_,
                    "position": position,
                    "type": payload["type"],
                    "tool_name": payload.get("name"),
                    # Plain dumps, not canonical_json: sorting keys is
                    # for hashing. Storage keeps the order the model
                    # produced, so tool call arguments read back as
                    # they were written.
                    "payload": json.dumps(payload),
                }
            )
            .last_pk
        )
        for order, attachment_id in enumerate(attachment_ids):
            self.db["part_attachments"].insert(
                {
                    "part_id": part_id,
                    "attachment_id": attachment_id,
                    "order": order,
                }
            )
        for order, fragment_id in enumerate(used_fragments):
            self.db["part_fragments"].insert(
                {
                    "part_id": part_id,
                    "fragment_id": fragment_id,
                    "order": order,
                }
            )

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
                select * from parts
                where message_hash in ({placeholders})
                order by message_hash, position
                """,
                message_hashes,
            )
        )
        payloads = [json.loads(row["payload"]) for row in part_rows]
        # Resolve the references put in on the way in. Both lookups are
        # batched across the whole chain rather than done per part.
        fragments = self._load_fragments(payloads)
        attachments = self._load_attachments(payloads)
        out: dict[str, list[Any]] = {}
        for row, payload in zip(part_rows, payloads):
            _decode_text_refs(payload, fragments)
            # Strip the attachment references before rebuilding, then
            # hang the resolved objects back on.
            ids = _attachment_ids(payload)
            payload.pop("attachment", None)
            payload.pop("attachments", None)
            part = Part.from_dict(payload)
            _resolve_attachments(part, ids, attachments)
            out.setdefault(row["message_hash"], []).append(part)
        return out

    def _load_fragments(self, payloads: list[dict]) -> dict[int, str]:
        ids = sorted({id for payload in payloads for id in _fragment_ids(payload)})
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        return {
            row["id"]: row["content"]
            for row in self.db.query(
                f"select id, content from fragments where id in ({placeholders})",
                ids,
            )
        }

    def _load_attachments(self, payloads: list[dict]) -> dict[str, Any]:
        ids = sorted({id for payload in payloads for id in _attachment_ids(payload)})
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        return {
            row["id"]: Attachment.from_row(row)
            for row in self.db.query(
                f"select * from attachments where id in ({placeholders})", ids
            )
        }

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

        prompt_fragments = list(response.prompt.fragments or [])
        system_fragments = list(response.prompt.system_fragments or [])

        parent = self.ensure_chain(
            response.prompt.messages,
            fragments=prompt_fragments + system_fragments,
        )
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
            },
            replace=True,
        )
        for tool in response.prompt.tools:
            self.db["turn_tools"].insert(
                {"turn_id": turn_id, "tool_id": ensure_tool(self.db, tool)},
                replace=True,
            )
        # Which fragments this call was given - provenance, so it belongs
        # on the turn rather than on the shared message rows. This is what
        # answers "show me everything that used fragment X".
        for kind, fragments in (
            ("prompt", prompt_fragments),
            ("system", system_fragments),
        ):
            for order, fragment in enumerate(fragments):
                self.db["turn_fragments"].insert(
                    {
                        "turn_id": turn_id,
                        "fragment_id": ensure_fragment(self.db, fragment),
                        "order": order,
                        "kind": kind,
                    },
                    replace=True,
                )
        if thread_id is not None:
            self.db["threads"].update(thread_id, {"tip_message_hash": tip})
        return turn_id

    # -- verification --------------------------------------------------

    def verify(self) -> list[str]:
        """Re-hash every stored message and return those that disagree.

        Reads resolve references - fragment text and attachment bytes are
        stitched back in - so a bug there, or a fragment deleted out from
        under a message, produces a chain that differs from the one that
        was hashed. Nothing else would notice: the wrong text would just
        be silently sent to the model. Re-deriving the hash from what
        comes back out catches the whole class.

        An empty list means every message on disk still resolves to the
        content its hash was taken over.
        """
        broken = []
        for row in self.db.query("select hash, parent_hash from messages"):
            parts = self._load_parts([row["hash"]]).get(row["hash"], [])
            message_row = next(
                iter(
                    self.db.query(
                        "select * from messages where hash = ?", [row["hash"]]
                    )
                )
            )
            message = Message(
                role=message_row["role"],
                parts=parts,
                provider_metadata=_load(message_row["provider_metadata"]),
            )
            if message_hash(message, row["parent_hash"]) != row["hash"]:
                broken.append(row["hash"])
        return broken

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


# -- reference encoding ------------------------------------------------
#
# A stored payload is Part.to_dict() with large content swapped for a
# reference: fragment ids in place of text, attachment ids in place of
# bytes. Resolving it reproduces the wire form exactly, which is what
# makes it safe for the hash to be taken over the resolved content and
# never over what is on disk.


def _attachments_of(part) -> list[Any]:
    "The Attachment objects a part carries, in order."
    if isinstance(part, ToolResultPart):
        return list(part.attachments)
    if isinstance(part, AttachmentPart) and part.attachment is not None:
        return [part.attachment]
    return []


def _encode_text_refs(payload: dict, fragment_map: dict[str, int]) -> list[int]:
    """Replace ``text`` with a ``text_ref`` list of fragments and
    literals. Returns the fragment ids used, in order.

    Nothing is replaced unless a fragment actually occurs in the text, so
    a part that borrows no fragments keeps its plain ``text`` key.
    """
    text = payload.get("text")
    if not text or not fragment_map:
        return []
    pieces: list[dict] = []
    used: list[int] = []
    remaining = text
    while remaining:
        # Earliest occurrence wins; on a tie the longer fragment does, so
        # a fragment that is a prefix of another cannot mask it.
        best: tuple[int, str] | None = None
        for content in fragment_map:
            index = remaining.find(content)
            if index == -1:
                continue
            if best is None or (index, -len(content)) < (best[0], -len(best[1])):
                best = (index, content)
        if best is None:
            pieces.append({"literal": remaining})
            break
        index, content = best
        if index:
            pieces.append({"literal": remaining[:index]})
        pieces.append({"fragment": fragment_map[content]})
        used.append(fragment_map[content])
        remaining = remaining[index + len(content) :]
    if not used:
        return []
    del payload["text"]
    payload["text_ref"] = pieces
    return used


def _decode_text_refs(payload: dict, fragments: dict[int, str]) -> None:
    "Reverse of _encode_text_refs, restoring the exact original text."
    pieces = payload.pop("text_ref", None)
    if pieces is None:
        return
    payload["text"] = "".join(
        (
            piece["literal"]
            if "literal" in piece
            else fragments.get(piece["fragment"], "")
        )
        for piece in pieces
    )


def _fragment_ids(payload: dict) -> list[int]:
    return [
        piece["fragment"]
        for piece in payload.get("text_ref") or []
        if "fragment" in piece
    ]


def _encode_attachment_refs(payload: dict, attachment_ids: list[str]) -> None:
    "Replace inline attachment dicts with their content-addressed ids."
    if payload["type"] == "attachment":
        payload["attachment"] = {"id": attachment_ids[0]}
    elif payload["type"] == "tool_result":
        payload["attachments"] = [{"id": id} for id in attachment_ids]


def _resolve_attachments(part, ids: list[str], attachments: dict[str, Any]) -> None:
    """Hang the resolved Attachment objects back on a part.

    Done after ``Part.from_dict`` rather than by putting them back into
    the payload, so the bytes are never round-tripped through base64 and
    the objects keep the content-addressed id they were stored under.
    """
    if not ids:
        return
    if isinstance(part, AttachmentPart):
        part.attachment = attachments[ids[0]]
    elif isinstance(part, ToolResultPart):
        part.attachments = [attachments[id] for id in ids]


def _attachment_ids(payload: dict) -> list[str]:
    if payload["type"] == "attachment" and "attachment" in payload:
        return [payload["attachment"]["id"]]
    if payload["type"] == "tool_result":
        return [ref["id"] for ref in payload.get("attachments") or []]
    return []


def _dump(value: dict | None) -> str | None:
    return json.dumps(value) if value else None


def _load(value: str | None) -> dict | None:
    return json.loads(value) if value else None


def _now() -> str:
    return str(datetime.datetime.now(datetime.timezone.utc))


# -- llm logs support ---------------------------------------------------
#
# Rows shaped like the ones the older `responses` query produced, so the
# existing rendering in llm.cli works unchanged, but derived entirely
# from the content-addressed tables.

LOG_ROWS_SQL = """
select
    turns.id,
    turns.model,
    turns.resolved_model,
    turns.options_json,
    turns.thread_id as conversation_id,
    turns.duration_ms,
    turns.datetime_utc,
    turns.input_tokens,
    turns.output_tokens,
    turns.token_details,
    turns.parent_message_hash,
    turns.tip_message_hash,
    threads.name as conversation_name,
    turns.model as conversation_model,
    schemas.content as schema_json
from turns
left join threads on turns.thread_id = threads.id
left join schemas on turns.schema_id = schemas.id
{where}
order by turns.id desc{limit}
"""


def _text_of(parts, kind) -> str:
    "Concatenated text of every part of ``kind`` in order."
    return "".join(part.text for part in parts if isinstance(part, kind) and part.text)


class _LogRowBuilder:
    """Turns a turn row into the shape `llm logs` renders.

    A turn's prompt is the last message it was given and its response is
    whatever it appended, so both are derived from the parent/tip pair
    rather than stored a second time. The chain up to the parent is a
    prefix of the chain up to the tip, so splitting them is a matter of
    length.
    """

    def __init__(self, store: "LogStore"):
        self.store = store

    def build(self, row: dict) -> dict:
        inputs = self.store.load_chain(row["parent_message_hash"])
        outputs = self.store.load_chain(row["tip_message_hash"])[len(inputs) :]

        prompt_parts = inputs[-1].parts if inputs else []
        system_parts = inputs[0].parts if inputs and inputs[0].role == "system" else []
        out_parts = [part for message in outputs for part in message.parts]

        built = {
            key: row[key]
            for key in (
                "id",
                "model",
                "resolved_model",
                "options_json",
                "conversation_id",
                "duration_ms",
                "datetime_utc",
                "input_tokens",
                "output_tokens",
                "token_details",
                "conversation_name",
                "conversation_model",
                "schema_json",
            )
        }
        built.update(
            {
                # The turn stores null when no options were set; the
                # responses table always recorded "{}".
                "options_json": row["options_json"] or "{}",
                "prompt": _text_of(prompt_parts, TextPart),
                # None rather than "" when there was no system
                # message, matching what was recorded before.
                "system": _text_of(system_parts, TextPart) or None,
                "response": _text_of(out_parts, TextPart),
                "reasoning": _text_of(out_parts, ReasoningPart) or None,
                # Neither is stored any more: the chain holds the
                # structure, and the raw provider payload was dropped as
                # redundant with it.
                "prompt_json": None,
                "response_json": None,
                "_input_parts": prompt_parts,
                "_output_parts": out_parts,
                # Internal, stripped before rendering - the enrichment
                # needs them to find the parts rows behind these parts.
                "_parent_message_hash": row["parent_message_hash"],
                "_tip_message_hash": row["tip_message_hash"],
            }
        )
        return built


def log_rows(
    store: "LogStore",
    *,
    count: int | None = None,
    model_id: str | None = None,
    thread_id: str | None = None,
    fragment_hashes=(),
    tool_names=(),
    any_tools: bool = False,
    schema_id: str | None = None,
    id_gt: str | None = None,
    id_gte: str | None = None,
) -> list[dict]:
    """Rows for `llm logs`, newest first, drawn from the new tables.

    Deliberately blind to anything logged before this schema existed -
    those conversations have no turns, so they simply do not appear.
    """
    where: list[str] = []
    params: dict[str, Any] = {}

    if model_id:
        where.append("(turns.model = :model or turns.resolved_model = :model)")
        params["model"] = model_id
    if thread_id:
        where.append("turns.thread_id = :thread_id")
        params["thread_id"] = thread_id
    if id_gt:
        where.append("turns.id > :id_gt")
        params["id_gt"] = id_gt
    if id_gte:
        where.append("turns.id >= :id_gte")
        params["id_gte"] = id_gte
    if schema_id:
        where.append("turns.schema_id = :schema_id")
        params["schema_id"] = schema_id

    # Fragments come from turn_fragments - what this call was given -
    # rather than from the message text, so it matches what -f means.
    for index, fragment_hash in enumerate(fragment_hashes):
        key = f"fragment_{index}"
        where.append(f"""turns.id in (
                select turn_fragments.turn_id from turn_fragments
                join fragments on fragments.id = turn_fragments.fragment_id
                where fragments.hash = :{key}
            )""")
        params[key] = fragment_hash

    # A turn "used" a tool when a tool result was among its inputs,
    # matching what -T has always meant: the result came back and was
    # fed to the model. The result sits in the turn's parent message.
    if any_tools:
        where.append(_tool_result_clause())
    for index, tool_name in enumerate(tool_names):
        key = f"tool_{index}"
        where.append(_tool_result_clause(f"and parts.tool_name = :{key}"))
        params[key] = tool_name

    sql = LOG_ROWS_SQL.format(
        where=("where " + " and ".join(where)) if where else "",
        limit=f" limit {count}" if count else "",
    )
    builder = _LogRowBuilder(store)
    return [builder.build(row) for row in store.db.query(sql, params)]


def _tool_result_clause(extra: str = "") -> str:
    return f"""turns.parent_message_hash in (
        select parts.message_hash from parts
        where parts.type = 'tool_result' {extra}
    )"""


def log_row_extras(store: "LogStore", row: dict) -> dict:
    """Attachments, fragments and tool info for one `llm logs` row.

    Attachments and tool calls come from the row's parts, which the row
    builder kept hold of. Fragments come from turn_fragments - what the
    call was given - so `-f` and the displayed list agree.
    """
    attachments = [
        _attachment_summary(part.attachment)
        for part in row.get("_input_parts", [])
        if isinstance(part, AttachmentPart) and part.attachment is not None
    ]

    # parts.id and tools.id stand in for the row ids the old
    # tool_calls / tool_results tables exposed, so the JSON shape of
    # `llm logs` is unchanged.
    call_ids = _part_ids(store, row.get("_tip_message_hash"), "tool_call")
    result_ids = _part_ids(store, row.get("_parent_message_hash"), "tool_result")
    tool_ids = _tool_ids_by_name(store)

    tool_calls = [
        {
            "id": call_ids.get(part.tool_call_id),
            "tool_id": tool_ids.get(part.name),
            "name": part.name,
            "arguments": part.arguments,
            "tool_call_id": part.tool_call_id,
        }
        for part in row.get("_output_parts", [])
        if isinstance(part, ToolCallPart)
    ]
    tool_results = [
        {
            "id": result_ids.get(part.tool_call_id),
            "tool_id": tool_ids.get(part.name),
            "name": part.name,
            "output": part.output,
            "tool_call_id": part.tool_call_id,
            "exception": part.exception,
            "attachments": [_attachment_summary(a) for a in part.attachments],
        }
        for part in row.get("_input_parts", [])
        if isinstance(part, ToolResultPart)
    ]

    # input_schema is rendered as a dict, so decode it here rather than
    # handing the caller the raw JSON text out of the column.
    tools = [
        {**tool_row, "input_schema": json.loads(tool_row["input_schema"] or "{}")}
        for tool_row in store.db.query(
            """
            select tools.id, tools.hash, tools.name, tools.description,
                   tools.input_schema
            from tools join turn_tools on turn_tools.tool_id = tools.id
            where turn_tools.turn_id = ?
            """,
            [row["id"]],
        )
    ]

    fragments: dict[str, list[dict]] = {
        "prompt_fragments": [],
        "system_fragments": [],
    }
    for fragment_row in store.db.query(
        """
        select turn_fragments.kind, fragments.hash, fragments.content,
               (select json_group_array(fragment_aliases.alias)
                  from fragment_aliases
                 where fragment_aliases.fragment_id = fragments.id) as aliases
        from turn_fragments
        join fragments on fragments.id = turn_fragments.fragment_id
        where turn_fragments.turn_id = ?
        order by turn_fragments."order"
        """,
        [row["id"]],
    ):
        key = f"{fragment_row['kind']}_fragments"
        fragments[key].append(dict(fragment_row))

    return {
        "attachments": attachments,
        "tools": tools,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        **fragments,
    }


def _attachment_summary(attachment) -> dict:
    "The attachment shape `llm logs` renders."
    content = attachment.content or b""
    return {
        "id": attachment.id(),
        "type": attachment.resolve_type(),
        "path": attachment.path,
        "url": attachment.url,
        "content": bool(content) or None,
        "content_length": len(content) or None,
    }


def _part_ids(store: "LogStore", message_hash: str | None, type: str) -> dict:
    "Map tool_call_id to the parts row id, for one message."
    if not message_hash:
        return {}
    return {
        json.loads(part_row["payload"]).get("tool_call_id"): part_row["id"]
        for part_row in store.db.query(
            "select id, payload from parts where message_hash = ? and type = ?",
            [message_hash, type],
        )
    }


def _tool_ids_by_name(store: "LogStore") -> dict:
    return {
        tool_row["name"]: tool_row["id"]
        for tool_row in store.db.query("select id, name from tools")
    }
