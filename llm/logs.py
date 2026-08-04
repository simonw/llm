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

from condense_json import UncondenseError, condense_json, uncondense_json

from .migrations import migrate
from .models import Attachment, ServerSideTool, _conversation_name
from .parts import (
    AttachmentPart,
    Message,
    Part,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from .utils import (
    ensure_fragment,
    ensure_tool,
    ensure_tool_instance,
    make_schema_id,
    monotonic_ulid,
)

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


def _canonical_attachment(attachment) -> dict:
    """The hashed form of an attachment: content identity plus the
    model-visible media type.

    The content hash is recomputed from the actual bytes every time,
    never taken from Attachment.id()'s cache - that is what lets
    verify() notice that a path-backed file changed after logging.
    Path-backed attachments keep no copy of their bytes in the store
    (by design: logs.db does not swallow large media), so their
    fidelity depends on the file staying put; a changed or deleted
    file shows up as a broken hash rather than passing silently.

    The type participates because the model sees it: identical bytes
    sent as image/png and as text/plain are different requests. URL
    attachments hash the URL itself - the log records which URL was
    sent, not whatever it served that day.
    """
    if attachment.content:
        content_id = hashlib.sha256(attachment.content).hexdigest()
    elif attachment.path:
        try:
            with open(attachment.path, "rb") as fp:
                content_id = hashlib.sha256(fp.read()).hexdigest()
        except OSError:
            content_id = f"missing:{attachment.path}"
    else:
        content_id = hashlib.sha256(
            json.dumps({"url": attachment.url}).encode("utf-8")
        ).hexdigest()
    try:
        type_ = attachment.resolve_type()
    except OSError:
        # A deleted path-backed file - the content hash above already
        # carries the missing marker
        type_ = attachment.type
    return {"id": content_id, "type": type_}


def message_hash(message: Message, parent_hash: str | None) -> str:
    """Identity of ``message`` when reached via ``parent_hash``.

    The parent participates, so the same content at a different point in
    a conversation is a different node. That is what makes a shared
    prefix collapse to shared rows without any explicit comparison.

    Attachments are hashed by content id, via _canonical_attachment.
    """
    d: Any = message.to_dict()
    for part, part_dict in zip(message.parts, d["parts"]):
        attachment = getattr(part, "attachment", None)
        if attachment is not None:
            part_dict["attachment"] = _canonical_attachment(attachment)
        attachments = getattr(part, "attachments", None)
        if attachments:
            part_dict["attachments"] = [_canonical_attachment(a) for a in attachments]
    return content_hash({"parent": parent_hash, "message": d})


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
        with self.db.atomic():
            # Another writer can store the same hash between the check
            # above and this insert. Insert-or-ignore settles who won,
            # and only the winner writes the parts.
            cursor = self.db.execute(
                "insert or ignore into messages"
                " (hash, parent_hash, role, provider_metadata)"
                " values (?, ?, ?, ?)",
                [hash, parent_hash, message.role, _dump(message.provider_metadata)],
            )
            if cursor.rowcount:
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
        # The type key is redundant with the type column; readers put it
        # back from there.
        part_type = payload.pop("type")
        attachments = _attachments_of(part)

        # Large content out of the payload and into the tables that
        # already store it once: fragments for text, attachments for
        # bytes. Both are resolved again on the way back out.
        used_fragments = _encode_text_refs(payload, fragment_map)
        if attachments:
            attachment_ids = [
                ensure_attachment(self.db, attachment) for attachment in attachments
            ]
            _encode_attachment_refs(payload, attachment_ids, part_type)
        else:
            attachment_ids = []

        # Pure literal text lives in its own column - raw, unescaped,
        # never parsed - so prose reads as prose in SQL. Text that
        # borrows fragments stays structured in the payload as text_ref.
        text = None
        if part_type in ("text", "reasoning") and "text" in payload:
            text = payload.pop("text")

        part_id = (
            self.db["parts"]
            .insert(
                {
                    "message_hash": message_hash_,
                    "position": position,
                    "type": part_type,
                    "tool_name": payload.get("name"),
                    "text": text,
                    # Plain dumps, not canonical_json: sorting keys is
                    # for hashing. Storage keeps the order the model
                    # produced, so tool call arguments read back as
                    # they were written. NULL when the text column
                    # carries the whole part.
                    "payload": json.dumps(payload) if payload else None,
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
        # Rebuild each part's full dict from its columns: type from the
        # type column, literal text from the text column, everything
        # else from the JSON payload.
        payloads: list[Any] = []
        for row in part_rows:
            payload = json.loads(row["payload"]) if row["payload"] else {}
            payload["type"] = row["type"]
            if row["text"] is not None:
                payload["text"] = row["text"]
            payloads.append(payload)
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
        with self.db.atomic():
            return self._log_in_transaction(response, thread_id)

    def _log_in_transaction(self, response, thread_id: str | None) -> str:
        if thread_id is None:
            conversation = getattr(response, "conversation", None)
            # A response logged outside any conversation still gets a
            # thread of its own, so `llm -c` and `llm logs` can always
            # find it - the same guarantee the conversations table used
            # to provide.
            thread_id = self.ensure_thread(
                conversation.id if conversation else str(monotonic_ulid()).lower(),
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
        own_messages = response._messages_now()
        tip = self.ensure_chain(own_messages, parent=parent)

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
                "response_json": condense_payload(
                    getattr(response, "response_json", None),
                    own_messages,
                    [(tool.name, tool.description) for tool in response.prompt.tools],
                    schema=response.prompt.schema,
                    model_replacements=getattr(
                        response.model, "json_replacements", None
                    ),
                ),
            },
            replace=True,
        )
        for tool in response.prompt.tools:
            # Server-side tools are configured instances themselves. A
            # toolbox-derived tool instead has an implementation method
            # bound to its configured instance. Record either kind as a
            # reference into the shared tool_instances table.
            instance: Any | None
            if isinstance(tool, ServerSideTool):
                instance = tool
                instance_name = tool.__class__.__name__
            else:
                instance = getattr(tool.implementation, "__self__", None)
                instance_name = tool.name.split("_")[0]
            config = getattr(instance, "_config", None)
            self.db["turn_tools"].insert(
                {
                    "turn_id": turn_id,
                    "tool_id": ensure_tool(self.db, tool),
                    "instance_id": (
                        ensure_tool_instance(
                            self.db,
                            instance_name,
                            tool.plugin,
                            json.dumps(config),
                        )
                        if config is not None
                        else None
                    ),
                },
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
        # Which configured toolbox instance served each tool call. This
        # is local execution provenance, so it lives outside the hashed
        # message tree, keyed by the tool_call_id both worlds share.
        for tool_result in response.prompt.tool_results:
            # instance is annotated as Toolbox but a tool built from a
            # bound method can carry an arbitrary __self__ here, so ask
            # for the config rather than trusting the type.
            config = getattr(tool_result.instance, "_config", None)
            if config is None or not tool_result.tool_call_id:
                continue
            self.db["tool_instantiations"].insert(
                {
                    "turn_id": turn_id,
                    "tool_call_id": tool_result.tool_call_id,
                    "instance_id": ensure_tool_instance(
                        self.db,
                        tool_result.name.split("_")[0],
                        next(
                            (
                                tool.plugin
                                for tool in response.prompt.tools
                                if tool.name == tool_result.name
                            ),
                            None,
                        ),
                        json.dumps(config),
                    ),
                },
                replace=True,
            )
        # Refresh this turn's search row. Delete-then-derive rather than
        # replace, so a re-logged turn with a different tip converges on
        # what the turn now says. Derived in SQL from the stored
        # payloads, not from load_chain - resolving references would put
        # fragment content back into the searchable text.
        self.db["turn_search"].delete_where("turn_id = ?", [turn_id])
        self.db.execute(TURN_SEARCH_INSERT_SQL, {"turn_id": turn_id})
        if thread_id is not None:
            self.db["threads"].update(thread_id, {"tip_message_hash": tip})
        return turn_id

    def turn_response_json(self, turn_id: str) -> Any:
        """The raw provider payload recorded for a turn, resolved.

        Returns ``None`` when the turn is unknown or recorded no
        payload. Raises ``condense_json.UncondenseError`` when the
        payload references message content that no longer resolves -
        the payload was recorded but its context is gone.
        """
        row = next(
            iter(
                self.db.query(
                    "select turns.model, turns.parent_message_hash,"
                    " turns.tip_message_hash, turns.response_json,"
                    " schemas.content as schema_json"
                    " from turns"
                    " left join schemas on turns.schema_id = schemas.id"
                    " where turns.id = ?",
                    [turn_id],
                )
            ),
            None,
        )
        if row is None or row["response_json"] is None:
            return None
        inputs = self.load_chain(row["parent_message_hash"])
        outputs = self.load_chain(row["tip_message_hash"])[len(inputs) :]
        return resolve_payload(
            row["response_json"],
            outputs,
            self._turn_tool_pairs(turn_id),
            schema=_load(row["schema_json"]),
            model_replacements=_model_json_replacements(row["model"]),
        )

    def _turn_tool_pairs(self, turn_id: str) -> list[tuple[str, str]]:
        return [
            (row["name"], row["description"])
            for row in self.db.query(TURN_TOOLS_SQL, [turn_id])
        ]

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
        return [
            part
            for part in chain[-1].parts
            if isinstance(part, ToolCallPart) and not part.server_executed
        ]


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


def _encode_attachment_refs(
    payload: dict, attachment_ids: list[str], part_type: str
) -> None:
    "Replace inline attachment dicts with their content-addressed ids."
    if part_type == "attachment":
        payload["attachment"] = {"id": attachment_ids[0]}
    elif part_type == "tool_result":
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


# -- condensed provider payloads ----------------------------------------
#
# The raw response.json() payload mostly duplicates content the store
# already holds: the response text, reasoning summaries and their
# encrypted blobs, long tool arguments, and the tool definitions the
# provider echoes back on every call. The turn stores it condensed
# instead - strings that already live in the turn's own messages or its
# tools are swapped for {"$": key} references (condense-json), leaving
# roughly the provider envelope: ids, usage, fingerprints, settings
# echoes. The replacement dict is never stored; it is rebuilt on the way
# out from the chain segment (hash-frozen) and the turn_tools join
# (per-turn provenance), so the same walk over the same rows produces
# the same dict on both sides of the round trip.

# Below this a {"$": key} marker costs about as much as the string it
# replaces.
_CONDENSE_MIN_LENGTH = 64

# The tools a turn was given, as the (name, description) pairs
# _payload_replacements expects.
TURN_TOOLS_SQL = """
select tools.name, tools.description
from turn_tools join tools on tools.id = turn_tools.tool_id
where turn_tools.turn_id = ?
"""


def _payload_replacements(
    messages, tools=(), schema=None, model_replacements=None
) -> dict[str, Any]:
    """Replacement values for condensing a turn's provider payload.

    ``messages`` is the turn's own contribution - the chain segment
    between its parent and tip. Keys are structural (message offset,
    part position, field path) so the identical dict can be rebuilt
    from the stored segment at read time.

    ``tools`` is the turn's tools as (name, description) pairs -
    ``response.prompt.tools`` on the way in, the ``turn_tools`` join on
    the way out. Descriptions are keyed by tool name; a name carrying
    two different descriptions in one turn is dropped, the same
    order-independent verdict from either side's view of the pairs.
    (Parameter schemas are deliberately not offered: providers echo a
    transformed schema - OpenAI strict mode adds keys - so the stored
    form would not match even structurally.)

    ``schema`` is the turn's JSON schema dict, when one was used - the
    provider echoes it back in the payload (OpenAI ``text.format``) and
    the schemas table already stores it once. It is offered as a
    structural value, so the echo's key order does not matter.

    ``model_replacements`` is the model class's ``json_replacements``
    dictionary of common boilerplate - the zstd-custom-dictionary idea:
    payload fragments the plugin author knows recur in every reply,
    keyed here under an ``m.`` prefix so they can never collide with
    the derived keys. These resolve by looking the model up again at
    read time, so plugins must treat their ``json_replacements`` as
    append-only: removing or changing an entry breaks every payload
    already stored against it.

    Values are strings (matched as substrings) and dicts or lists
    (matched as whole subtrees by condense-json's structural equality).
    Container values inside provider_metadata are offered as well as
    their leaf strings - outermost match wins, so a payload that embeds
    a whole metadata object (a reasoning ``summary`` list, say)
    condenses to one reference instead of one per string.
    """
    replacements: dict[str, Any] = {}

    def add(key: str, value: Any) -> None:
        if isinstance(value, str) and len(value) >= _CONDENSE_MIN_LENGTH:
            replacements[key] = value

    def add_value(key: str, value: Any) -> None:
        if isinstance(value, (dict, list)) and value:
            # The same length bar as strings, applied to the canonical
            # form, so a reference is always a clear win.
            try:
                size = len(json.dumps(value, separators=(",", ":")))
            except (TypeError, ValueError):
                return
            if size >= _CONDENSE_MIN_LENGTH:
                replacements[key] = value

    def walk(prefix: str, obj: Any) -> None:
        if isinstance(obj, dict):
            add_value(prefix, obj)
            for key, value in obj.items():
                walk(f"{prefix}.{key}", value)
        elif isinstance(obj, list):
            add_value(prefix, obj)
            for index, value in enumerate(obj):
                walk(f"{prefix}.{index}", value)
        else:
            add(prefix, obj)

    for mi, message in enumerate(messages):
        message_dict = message.to_dict()
        for pi, part in enumerate(message_dict.get("parts", [])):
            base = f"{mi}.{pi}"
            add(f"{base}.text", part.get("text"))
            add(f"{base}.output", part.get("output"))
            arguments = part.get("arguments")
            if arguments:
                # Providers that carry tool arguments as a JSON-encoded
                # string need a byte-exact serialization - OpenAI uses
                # the compact form, so offer both. Providers that embed
                # them as an object (Anthropic, Gemini) match the dict
                # itself structurally.
                compact = json.dumps(arguments, separators=(",", ":"))
                spaced = json.dumps(arguments)
                add(f"{base}.args", compact)
                if spaced != compact:
                    add(f"{base}.args2", spaced)
                add_value(f"{base}.argsv", arguments)
            walk(f"{base}.pm", part.get("provider_metadata") or {})
        walk(f"{mi}.pm", message_dict.get("provider_metadata") or {})

    descriptions: dict[str, str] = {}
    conflicting = set()
    for name, description in tools:
        if (
            not name
            or not isinstance(description, str)
            or len(description) < _CONDENSE_MIN_LENGTH
        ):
            continue
        if descriptions.get(name, description) != description:
            conflicting.add(name)
            continue
        descriptions[name] = description
    for name, description in descriptions.items():
        if name not in conflicting:
            replacements[f"tool.{name}.description"] = description

    add_value("schema", schema)

    # Model-declared boilerplate passes through as curated: the plugin
    # author chose these entries, so no length threshold applies.
    for key, value in (model_replacements or {}).items():
        replacements[f"m.{key}"] = value
    return replacements


def condense_payload(
    payload: Any, messages, tools=(), schema=None, model_replacements=None
) -> str | None:
    "JSON text of ``payload`` condensed against the turn's stored content."
    if payload is None:
        return None
    return json.dumps(
        condense_json(
            payload,
            _payload_replacements(messages, tools, schema, model_replacements),
        )
    )


def resolve_payload(
    condensed: str | None, messages, tools=(), schema=None, model_replacements=None
) -> Any:
    """Reverse of :func:`condense_payload`.

    Raises ``condense_json.UncondenseError`` when the stored payload
    references content the segment no longer produces.
    """
    if condensed is None:
        return None
    return uncondense_json(
        json.loads(condensed),
        _payload_replacements(messages, tools, schema, model_replacements),
    )


def _model_json_replacements(model_id: str | None):
    """The ``json_replacements`` boilerplate dictionary for a model id.

    Resolved through the registry at read time, so payloads condensed
    against a model's dictionary need that model's plugin installed to
    resolve again. An unknown model returns None; any markers that
    depended on it surface as UncondenseError from resolve_payload.
    """
    if not model_id:
        return None
    from llm import UnknownModelError, get_model

    try:
        model = get_model(model_id)
    except UnknownModelError:
        return None
    return getattr(model, "json_replacements", None)


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
    turns.response_json,
    threads.name as conversation_name,
    turns.model as conversation_model,
    schemas.content as schema_json{rank_select}
from turns
left join threads on turns.thread_id = threads.id
left join schemas on turns.schema_id = schemas.id{join}
{where}
order by {order_by}{limit}
"""

# Literal text of one parts row: the text column when the part's text
# is pure literal, otherwise the literal segments of a text_ref payload
# - fragment content is deliberately not searchable.
TURN_SEARCH_LITERAL = """coalesce(
  parts.text,
  (select group_concat(json_extract(je.value, '$.literal'), '')
     from json_each(parts.payload, '$.text_ref') je
    where json_extract(je.value, '$.literal') is not null)
)"""

# Derives the searchable prompt and response text for turns. Serves both
# the migration backfill (turn_filter="") and the per-turn refresh in
# LogStore.log (turn_filter="and turns.id = :turn_id" - the slot appears
# in three places so the filtered form touches only that turn's chain).
TURN_SEARCH_INSERT_SQL = """
with recursive output_messages(turn_id, hash) as (
    select turns.id, turns.tip_message_hash
      from turns
     where turns.tip_message_hash is not null
       and (turns.parent_message_hash is null
            or turns.tip_message_hash != turns.parent_message_hash)
       and turns.id = :turn_id
    union all
    select om.turn_id, messages.parent_hash
      from output_messages om
      join messages on messages.hash = om.hash
      join turns on turns.id = om.turn_id
     where messages.parent_hash is not null
       and (turns.parent_message_hash is null
            or messages.parent_hash != turns.parent_message_hash)
),
prompt_text as (
    select turns.id as turn_id,
           (select group_concat({LITERAL}, '')
              from parts
             where parts.message_hash = turns.parent_message_hash
               and parts.type = 'text'
             order by parts.position) as text
      from turns
      join messages on messages.hash = turns.parent_message_hash
     where messages.role = 'user' and turns.id = :turn_id
),
response_text as (
    select om.turn_id, group_concat(part_text.text, '') as text
      from output_messages om
      join messages on messages.hash = om.hash and messages.role = 'assistant'
      join (
          select parts.message_hash, parts.position, {LITERAL} as text
            from parts where parts.type = 'text'
      ) part_text on part_text.message_hash = om.hash
     group by om.turn_id
)
insert into turn_search (turn_id, prompt, response)
select turns.id,
       coalesce(prompt_text.text, ''),
       coalesce(response_text.text, '')
  from turns
  left join prompt_text on prompt_text.turn_id = turns.id
  left join response_text on response_text.turn_id = turns.id
 where (coalesce(prompt_text.text, '') != ''
        or coalesce(response_text.text, '') != '') and turns.id = :turn_id
""".replace("{LITERAL}", TURN_SEARCH_LITERAL)

# Relevance ranking for -q. bm25 scores are negative-better, ascending
# order is best-first. The prompt column is weighted well above the
# response: what you typed is a stronger signal of what a turn is about
# than what the model said back.
TURN_SEARCH_RANK = "bm25(turn_search_fts, 10.0, 1.0)"
LEGACY_SEARCH_RANK = "bm25(responses_fts, 10.0, 1.0)"


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

        # The turn's own input is the trailing run of user and tool
        # messages: everything after the last assistant (or system)
        # message belongs to this turn, because a turn's new input
        # never contains an assistant message. A turn carrying both
        # tool results and a fresh user prompt therefore keeps both.
        boundary = len(inputs)
        while boundary and inputs[boundary - 1].role in ("user", "tool"):
            boundary -= 1
        input_messages = inputs[boundary:]

        prompt_parts = [
            part
            for message in input_messages
            if message.role == "user"
            for part in message.parts
        ]
        input_parts = [part for message in input_messages for part in message.parts]
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
        if "_search_rank" in row:
            built["_search_rank"] = row["_search_rank"]
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
                # No longer stored: the chain holds the structure.
                "prompt_json": None,
                # Stored condensed against the turn's own messages;
                # resolved here so the row carries the payload as the
                # provider sent it. A payload whose references no longer
                # resolve renders as absent rather than failing the
                # whole listing.
                "response_json": self._resolve_response_json(row, outputs),
                "_input_parts": input_parts,
                "_output_parts": out_parts,
                # Internal, stripped before rendering - the enrichment
                # needs them to find the parts rows behind these parts.
                "_parent_message_hash": row["parent_message_hash"],
                "_input_message_hashes": self._input_segment_hashes(
                    row["parent_message_hash"]
                ),
                "_tip_message_hash": row["tip_message_hash"],
            }
        )
        return built

    def _resolve_response_json(self, row: dict, outputs) -> str | None:
        condensed = row.get("response_json")
        if not condensed:
            return None
        try:
            return json.dumps(
                resolve_payload(
                    condensed,
                    outputs,
                    self.store._turn_tool_pairs(row["id"]),
                    schema=_load(row.get("schema_json")),
                    model_replacements=_model_json_replacements(row.get("model")),
                )
            )
        except UncondenseError:
            return None

    def _input_segment_hashes(self, parent_hash: str | None) -> list[str]:
        """Hashes of the turn's own input messages - the same trailing
        user/tool run build() derives, walked directly in the table."""
        hashes: list[str] = []
        hash_ = parent_hash
        while hash_:
            message_row = next(
                iter(
                    self.store.db.query(
                        "select parent_hash, role from messages where hash = ?",
                        [hash_],
                    )
                ),
                None,
            )
            if message_row is None or message_row["role"] not in ("user", "tool"):
                break
            hashes.append(hash_)
            hash_ = message_row["parent_hash"]
        hashes.reverse()
        return hashes


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
    ids=(),
    query: str | None = None,
    latest: bool = False,
) -> list[dict]:
    """Rows for `llm logs`, newest first, drawn from the new tables.

    Sees only conversations with turns - merged_log_rows adds the rows
    that exist solely in the legacy `responses` table.

    With ``query`` the rows are the best matches from the turn_search
    index, most relevant first - or newest first when ``latest`` is
    also set.
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
    if ids:
        keys = [f"row_id_{index}" for index in range(len(ids))]
        where.append("turns.id in ({})".format(", ".join(f":{key}" for key in keys)))
        params.update(dict(zip(keys, ids)))

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

    rank_select = ""
    join = ""
    order_by = "turns.id desc"
    if query:
        rank_select = f",\n    {TURN_SEARCH_RANK} as _search_rank"
        join = (
            "\njoin turn_search on turn_search.turn_id = turns.id"
            "\njoin turn_search_fts on turn_search_fts.rowid = turn_search.id"
        )
        where.append("turn_search_fts match :query")
        params["query"] = query
        if not latest:
            order_by = TURN_SEARCH_RANK

    sql = LOG_ROWS_SQL.format(
        rank_select=rank_select,
        join=join,
        where=("where " + " and ".join(where)) if where else "",
        order_by=order_by,
        limit=f" limit {count}" if count else "",
    )
    builder = _LogRowBuilder(store)
    return [builder.build(row) for row in store.db.query(sql, params)]


def _tool_result_clause(extra: str = "") -> str:
    # A turn's tool results sit either in its parent message directly,
    # or - when a fresh user prompt followed the results - in the
    # parent's own parent, one step further up the same input segment.
    return f"""(turns.parent_message_hash in (
        select parts.message_hash from parts
        where parts.type = 'tool_result' {extra}
    ) or turns.parent_message_hash in (
        select messages.hash from messages
        join parts on parts.message_hash = messages.parent_hash
        where messages.role = 'user'
        and parts.type = 'tool_result' {extra}
    ))"""


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
    call_ids = _part_ids(store, [row.get("_tip_message_hash")], "tool_call")
    result_ids = _part_ids(store, row.get("_input_message_hashes") or [], "tool_result")

    # input_schema is rendered as a dict, so decode it here rather than
    # handing the caller the raw JSON text out of the column.
    tools = [
        {
            "id": tool_row["id"],
            "hash": tool_row["hash"],
            "name": tool_row["name"],
            "description": tool_row["description"],
            "input_schema": json.loads(tool_row["input_schema"] or "{}"),
            "instance": (
                {
                    "name": tool_row["instance_name"],
                    "arguments": tool_row["instance_arguments"],
                }
                if tool_row["instance_name"]
                else None
            ),
        }
        for tool_row in store.db.query(
            """
            select tools.id, tools.hash, tools.name, tools.description,
                   tools.input_schema, tool_instances.name as instance_name,
                   tool_instances.arguments as instance_arguments
            from tools join turn_tools on turn_tools.tool_id = tools.id
            left join tool_instances
                on tool_instances.id = turn_tools.instance_id
            where turn_tools.turn_id = ?
            """,
            [row["id"]],
        )
    ]
    # Resolved through this turn's own turn_tools rows - definitions
    # sharing a name can differ between turns, and a global map would
    # attribute the wrong one.
    tool_ids = {tool["name"]: tool["id"] for tool in tools}

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
    result_parts = [
        part for part in row.get("_input_parts", []) if isinstance(part, ToolResultPart)
    ]
    instances = _instances_by_tool_call_id(
        store,
        row["id"],
        [part.tool_call_id for part in result_parts if part.tool_call_id],
    )
    tool_results = [
        {
            "id": result_ids.get(part.tool_call_id),
            "tool_id": tool_ids.get(part.name),
            "name": part.name,
            "output": part.output,
            "tool_call_id": part.tool_call_id,
            "exception": part.exception,
            "instance": instances.get(part.tool_call_id),
            "attachments": [_attachment_summary(a) for a in part.attachments],
        }
        for part in result_parts
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


def _part_ids(store: "LogStore", message_hashes: list, type: str) -> dict:
    "Map tool_call_id to the parts row id, across the given messages."
    message_hashes = [hash_ for hash_ in message_hashes if hash_]
    if not message_hashes:
        return {}
    placeholders = ",".join("?" * len(message_hashes))
    return {
        json.loads(part_row["payload"]).get("tool_call_id"): part_row["id"]
        for part_row in store.db.query(
            f"select id, payload from parts"
            f" where message_hash in ({placeholders}) and type = ?",
            message_hashes + [type],
        )
    }


def _instances_by_tool_call_id(
    store: "LogStore", turn_id: str, tool_call_ids: list
) -> dict:
    """Which configured toolbox instance served each call, for display.

    Scoped to the turn: providers with per-request counters can reuse
    the same tool_call_id across independent turns.
    """
    if not tool_call_ids:
        return {}
    placeholders = ",".join("?" * len(tool_call_ids))
    return {
        row["tool_call_id"]: {
            "name": row["name"],
            "plugin": row["plugin"],
            "arguments": row["arguments"],
        }
        for row in store.db.query(
            f"""
            select tool_instantiations.tool_call_id, tool_instances.name,
                   tool_instances.plugin, tool_instances.arguments
            from tool_instantiations
            join tool_instances
                on tool_instances.id = tool_instantiations.instance_id
            where tool_instantiations.turn_id = ?
            and tool_instantiations.tool_call_id in ({placeholders})
            """,
            [turn_id] + tool_call_ids,
        )
    }


# -- legacy rows ---------------------------------------------------------
#
# History logged by older versions of llm lives only in the `responses`
# table. Those rows are merged into `llm logs` output, shaped like the
# rows _LogRowBuilder produces. A response whose id also exists in
# `turns` is suppressed - that is what a dual-write-era row or a
# backfilled conversation looks like, and the turn is the richer record.

LEGACY_LOG_ROWS_SQL = """
select
    responses.id,
    responses.model,
    responses.resolved_model,
    responses.prompt,
    responses.system,
    responses.prompt_json,
    responses.options_json,
    responses.response,
    responses.reasoning,
    responses.response_json,
    responses.conversation_id,
    responses.duration_ms,
    responses.datetime_utc,
    responses.input_tokens,
    responses.output_tokens,
    responses.token_details,
    conversations.name as conversation_name,
    conversations.model as conversation_model,
    schemas.content as schema_json{rank_select}
from responses
left join schemas on responses.schema_id = schemas.id
left join conversations on responses.conversation_id = conversations.id{join}
where responses.id not in (select id from turns){extra_where}
order by {order_by}{limit}
"""


def legacy_log_rows(
    db,
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
    ids=(),
    query: str | None = None,
    latest: bool = False,
) -> list[dict]:
    """Rows for `llm logs` that exist only in the legacy tables.

    Applies the same filters as log_rows, translated to the legacy
    schema. Thread ids are conversation ids, so the two filters match
    the same conversations on either side of the upgrade.
    """
    if query and "responses_fts" not in db.table_names():
        # A database that never saw legacy llm has no legacy index.
        return []
    where: list[str] = []
    params: dict[str, Any] = {}

    if model_id:
        where.append("(responses.model = :model or responses.resolved_model = :model)")
        params["model"] = model_id
    if thread_id:
        where.append("responses.conversation_id = :thread_id")
        params["thread_id"] = thread_id
    if id_gt:
        where.append("responses.id > :id_gt")
        params["id_gt"] = id_gt
    if id_gte:
        where.append("responses.id >= :id_gte")
        params["id_gte"] = id_gte
    if schema_id:
        where.append("responses.schema_id = :schema_id")
        params["schema_id"] = schema_id
    if ids:
        keys = [f"row_id_{index}" for index in range(len(ids))]
        where.append(
            "responses.id in ({})".format(", ".join(f":{key}" for key in keys))
        )
        params.update(dict(zip(keys, ids)))

    for index, fragment_hash in enumerate(fragment_hashes):
        key = f"fragment_{index}"
        where.append(f"""(
                exists (
                    select 1 from prompt_fragments
                    where prompt_fragments.response_id = responses.id
                    and prompt_fragments.fragment_id in (
                        select fragments.id from fragments where hash = :{key}
                    )
                )
                or exists (
                    select 1 from system_fragments
                    where system_fragments.response_id = responses.id
                    and system_fragments.fragment_id in (
                        select fragments.id from fragments where hash = :{key}
                    )
                )
            )""")
        params[key] = fragment_hash

    if any_tools:
        where.append("""exists (
                select 1 from tool_results
                where tool_results.response_id = responses.id
            )""")
    for index, tool_name in enumerate(tool_names):
        key = f"tool_{index}"
        where.append(f"""exists (
                select 1 from tool_results
                join tools on tools.id = tool_results.tool_id
                where tool_results.response_id = responses.id
                and tools.name = :{key}
            )""")
        params[key] = tool_name

    rank_select = ""
    join = ""
    order_by = "responses.id desc"
    if query:
        rank_select = f",\n    {LEGACY_SEARCH_RANK} as _search_rank"
        join = "\njoin responses_fts on responses_fts.rowid = responses.rowid"
        where.append("responses_fts match :query")
        params["query"] = query
        if not latest:
            order_by = LEGACY_SEARCH_RANK

    sql = LEGACY_LOG_ROWS_SQL.format(
        rank_select=rank_select,
        join=join,
        extra_where=(" and " + " and ".join(where)) if where else "",
        order_by=order_by,
        limit=f" limit {count}" if count else "",
    )
    rows = [dict(row) for row in db.query(sql, params)]
    for row in rows:
        row["_legacy"] = True
    return rows


def merged_log_rows(
    store: "LogStore",
    *,
    count: int | None = None,
    query: str | None = None,
    latest: bool = False,
    **filters,
):
    """Rows for `llm logs`: the new tables plus legacy-only responses.

    Both sides are newest-first and ids are ULIDs on both sides of the
    upgrade, so a straight sort interleaves the two histories
    chronologically and the top ``count`` of the union is always within
    the top ``count`` of each side.

    With ``query``, each side returns its best matches and the union is
    ordered most-relevant first. The two bm25 scores come from separate
    indexes so the interleave is approximate - close enough in practice,
    since both index the same kind of corpus with the same tokenizer.
    ``latest`` makes the query a pure filter and keeps recency order.
    """
    rows = log_rows(store, count=count, query=query, latest=latest, **filters)
    rows.extend(
        legacy_log_rows(store.db, count=count, query=query, latest=latest, **filters)
    )
    if query and not latest:
        rows.sort(key=lambda row: row["_search_rank"])
    else:
        rows.sort(key=lambda row: row["id"], reverse=True)
    if count:
        rows = rows[:count]
    return rows


LEGACY_ATTACHMENTS_SQL = """
select
    response_id,
    attachments.id,
    attachments.type,
    attachments.path,
    attachments.url,
    length(attachments.content) as content_length
from attachments
join prompt_attachments
    on attachments.id = prompt_attachments.attachment_id
where prompt_attachments.response_id in ({placeholders})
order by prompt_attachments."order"
"""

LEGACY_FRAGMENTS_SQL = """
select
    {table}.response_id,
    fragments.hash,
    fragments.id as fragment_id,
    fragments.content,
    (
        select json_group_array(fragment_aliases.alias)
        from fragment_aliases
        where fragment_aliases.fragment_id = fragments.id
    ) as aliases
from {table}
join fragments on {table}.fragment_id = fragments.id
where {table}.response_id in ({placeholders})
order by {table}."order"
"""

LEGACY_TOOLS_SQL = """
select responses.id,
    coalesce(
        (select json_group_array(json_object(
            'id', t.id,
            'hash', t.hash,
            'name', t.name,
            'description', t.description,
            'input_schema', json(t.input_schema),
            'instance', null
        ))
        from tools t
        join tool_responses tr on t.id = tr.tool_id
        where tr.response_id = responses.id
        ),
        '[]'
    ) as tools,
    coalesce(
        (select json_group_array(json_object(
            'id', tc.id,
            'tool_id', tc.tool_id,
            'name', tc.name,
            'arguments', json(tc.arguments),
            'tool_call_id', tc.tool_call_id
        ))
        from tool_calls tc
        where tc.response_id = responses.id
        ),
        '[]'
    ) as tool_calls,
    coalesce(
        (select json_group_array(json_object(
            'id', tr.id,
            'tool_id', tr.tool_id,
            'name', tr.name,
            'output', tr.output,
            'tool_call_id', tr.tool_call_id,
            'exception', tr.exception,
            'instance', case when ti.id is not null then json_object(
                'name', ti.name,
                'plugin', ti.plugin,
                'arguments', ti.arguments
            ) else null end,
            'attachments', coalesce(
                (select json_group_array(json_object(
                    'id', a.id,
                    'type', a.type,
                    'path', a.path,
                    'url', a.url,
                    'content', a.content
                ))
                from tool_results_attachments tra
                join attachments a on tra.attachment_id = a.id
                where tra.tool_result_id = tr.id
                ),
                '[]'
            )
        ))
        from tool_results tr
        left join tool_instances ti on tr.instance_id = ti.id
        where tr.response_id = responses.id
        ),
        '[]'
    ) as tool_results
from responses
where id in ({placeholders})
"""


def legacy_log_row_extras(db, ids: list[str]) -> dict[str, dict]:
    """Extras for legacy rows, batch-fetched, keyed by response id.

    Same shape as log_row_extras, with each entry shaped the way the
    pre-turns `llm logs` rendered it.
    """
    extras: dict[str, dict] = {
        id: {
            "attachments": [],
            "prompt_fragments": [],
            "system_fragments": [],
            "tools": [],
            "tool_calls": [],
            "tool_results": [],
        }
        for id in ids
    }
    if not ids:
        return extras
    placeholders = ",".join("?" * len(ids))

    for attachment in db.query(
        LEGACY_ATTACHMENTS_SQL.format(placeholders=placeholders), ids
    ):
        attachment = dict(attachment)
        response_id = attachment.pop("response_id")
        extras[response_id]["attachments"].append(attachment)

    for table in ("prompt_fragments", "system_fragments"):
        for fragment in db.query(
            LEGACY_FRAGMENTS_SQL.format(table=table, placeholders=placeholders), ids
        ):
            fragment = dict(fragment)
            response_id = fragment.pop("response_id")
            extras[response_id][table].append(fragment)

    for row in db.query(LEGACY_TOOLS_SQL.format(placeholders=placeholders), ids):
        extras[row["id"]].update(
            {
                "tools": json.loads(row["tools"]),
                "tool_calls": json.loads(row["tool_calls"]),
                "tool_results": json.loads(row["tool_results"]),
            }
        )

    return extras
