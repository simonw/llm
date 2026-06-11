"""Convert legacy logged data into the node-tree schema.

Reads responses_archive and the legacy satellite tables (tool_calls,
tool_results, prompt_attachments, prompt_fragments, system_fragments,
tool_responses) and feeds synthesized Message values through the
standard storage write path, preserving response and conversation ids.

Three properties keep this safe to run inside a migration:

- Plugin-free: messages are built directly from rows. get_model() is
  never called and Options are never validated, so responses logged by
  models from since-uninstalled plugins convert fine.
- Defensive: each conversation converts inside a try/except. A failure
  is recorded in _conversion_errors and skipped - the migration never
  raises because of one malformed row. ``llm logs backfill`` retries.
- Idempotent: converted responses keep their ids, content hashes
  deduplicate messages, and ensure_node deduplicates positions, so
  re-running is a no-op.

The synthesized messages mirror exactly what Response.from_row +
load_conversation fabricated from the flattened columns before the
cutover: nothing is lost that existed, and nothing is invented that
did not.
"""

import datetime
import json
import sys
from typing import Any, Dict, List, Optional, Tuple

from .models import Attachment, _combine_system
from .parts import (
    AttachmentPart,
    Message,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from . import storage

PROGRESS_THRESHOLD = 500


def _table_exists(db, name):
    return db[name].exists()


def _legacy_fragments(db, response_id: str) -> Dict[str, List[Dict[str, Any]]]:
    "Fragment rows for a legacy response, keyed by prompt/system type."
    result: Dict[str, List[Dict[str, Any]]] = {"prompt": [], "system": []}
    for fragment_type, table in (
        ("prompt", "prompt_fragments"),
        ("system", "system_fragments"),
    ):
        if not _table_exists(db, table):
            continue
        result[fragment_type] = list(
            db.query(
                f"""
                select fragments.content, {table}.fragment_id, {table}."order"
                from {table}
                join fragments on fragments.id = {table}.fragment_id
                where {table}.response_id = ?
                order by {table}."order"
                """,
                [response_id],
            )
        )
    return result


def _input_messages(
    db, row: Dict[str, Any], fragments: Dict[str, List[Dict[str, Any]]]
) -> Tuple[List[Message], Dict[str, int]]:
    """Synthesize this turn's new input messages from a legacy row -
    the same shapes Prompt.messages produced from the legacy kwargs."""
    messages: List[Message] = []
    instance_ids: Dict[str, int] = {}

    system_text = _combine_system(
        row.get("system"), [f["content"] for f in fragments["system"]]
    )
    if system_text:
        messages.append(Message(role="system", parts=[TextPart(text=system_text)]))

    tool_result_parts = []
    if _table_exists(db, "tool_results"):
        for tr in db.query(
            "select * from tool_results where response_id = ? order by id", [row["id"]]
        ):
            attachments = []
            if _table_exists(db, "tool_results_attachments"):
                attachments = [
                    Attachment.from_row(attachment_row)
                    for attachment_row in db.query(
                        """
                        select attachments.* from attachments
                        join tool_results_attachments
                            on attachments.id = tool_results_attachments.attachment_id
                        where tool_results_attachments.tool_result_id = ?
                        order by tool_results_attachments."order"
                        """,
                        [tr["id"]],
                    )
                ]
            tool_result_parts.append(
                ToolResultPart(
                    name=tr["name"] or "",
                    output=tr["output"] or "",
                    tool_call_id=tr["tool_call_id"],
                    exception=tr["exception"],
                    attachments=attachments,
                )
            )
            if tr["tool_call_id"] and tr["instance_id"]:
                instance_ids[tr["tool_call_id"]] = tr["instance_id"]
    if tool_result_parts:
        messages.append(Message(role="tool", parts=tool_result_parts))

    user_parts: List[Any] = []
    prompt_bits = [f["content"] for f in fragments["prompt"]]
    if row.get("prompt"):
        prompt_bits.append(row["prompt"])
    if prompt_bits:
        user_parts.append(TextPart(text="\n".join(prompt_bits)))
    if _table_exists(db, "prompt_attachments"):
        for attachment_row in db.query(
            """
            select attachments.* from attachments
            join prompt_attachments
                on attachments.id = prompt_attachments.attachment_id
            where prompt_attachments.response_id = ?
            order by prompt_attachments."order"
            """,
            [row["id"]],
        ):
            user_parts.append(
                AttachmentPart(attachment=Attachment.from_row(attachment_row))
            )
    if user_parts:
        messages.append(Message(role="user", parts=user_parts))

    return messages, instance_ids


def _output_messages(db, row: Dict[str, Any]) -> List[Message]:
    "Synthesize the assistant output message from a legacy row."
    parts: List[Any] = []
    if row.get("reasoning"):
        parts.append(ReasoningPart(text=row["reasoning"]))
    if row.get("response"):
        parts.append(TextPart(text=row["response"]))
    if _table_exists(db, "tool_calls"):
        for tc in db.query(
            "select * from tool_calls where response_id = ? order by id", [row["id"]]
        ):
            parts.append(
                ToolCallPart(
                    name=tc["name"] or "",
                    arguments=json.loads(tc["arguments"] or "{}"),
                    tool_call_id=tc["tool_call_id"],
                )
            )
    if not parts:
        return []
    return [Message(role="assistant", parts=parts)]


def _convert_conversation(db, conversation_id: Optional[str]) -> int:
    "Convert one conversation's responses in order. Returns count converted."
    rows = list(
        db.query(
            "select * from responses_archive where conversation_id is ? order by id",
            [conversation_id],
        )
    )
    converted = 0
    previous_leaf: Optional[str] = None
    for row in rows:
        existing = db.execute(
            "select output_node_id, input_node_id from responses where id = ?",
            [row["id"]],
        ).fetchone()
        if existing:
            # Already converted - just pick up the chain where it ends
            previous_leaf = existing[0] or existing[1] or previous_leaf
            continue

        fragments = _legacy_fragments(db, row["id"])
        new_input, instance_ids = _input_messages(db, row, fragments)
        output = _output_messages(db, row)

        input_nodes = storage.append_messages(
            db, previous_leaf, new_input, instance_ids=instance_ids
        )
        input_leaf = input_nodes[-1] if input_nodes else previous_leaf
        output_nodes = storage.append_messages(db, input_leaf, output)
        output_leaf = output_nodes[-1] if output_nodes else None

        db["responses"].insert(
            {
                "id": row["id"],
                "model": row.get("model"),
                "resolved_model": row.get("resolved_model"),
                "conversation_id": row.get("conversation_id"),
                "input_node_id": input_leaf,
                "first_input_node_id": input_nodes[0] if input_nodes else None,
                "output_node_id": output_leaf,
                "prompt": row.get("prompt"),
                "system": row.get("system"),
                "response": row.get("response"),
                "reasoning": row.get("reasoning"),
                "options_json": row.get("options_json"),
                "schema_id": row.get("schema_id"),
                "prompt_json": row.get("prompt_json"),
                "response_json": row.get("response_json"),
                "duration_ms": row.get("duration_ms"),
                "datetime_utc": row.get("datetime_utc"),
                "input_tokens": row.get("input_tokens"),
                "output_tokens": row.get("output_tokens"),
                "token_details": row.get("token_details"),
            }
        )

        # Fragment provenance, merged into the single relation
        fragment_rows = []
        for fragment_type in ("prompt", "system"):
            for i, fragment in enumerate(fragments[fragment_type]):
                fragment_rows.append(
                    {
                        "response_id": row["id"],
                        "fragment_id": fragment["fragment_id"],
                        "fragment_type": fragment_type,
                        "order": (
                            fragment["order"] if fragment["order"] is not None else i
                        ),
                    }
                )
        if fragment_rows:
            db["response_fragments"].insert_all(fragment_rows, replace=True)

        # Tool definitions offered
        if _table_exists(db, "tool_responses"):
            tool_rows = [
                {"response_id": row["id"], "tool_id": tool_row["tool_id"]}
                for tool_row in db.query(
                    "select tool_id from tool_responses where response_id = ?",
                    [row["id"]],
                )
            ]
            if tool_rows:
                db["response_tools"].insert_all(tool_rows, replace=True)

        previous_leaf = output_leaf or input_leaf
        converted += 1
    return converted


def convert_legacy_data(db, retry_errors: bool = False) -> Tuple[int, int]:
    """Convert everything in responses_archive that has not already been
    converted. Returns (converted_count, error_count).

    With retry_errors=True, conversations recorded in _conversion_errors
    have their error rows cleared and are attempted again.
    """
    if not db["responses_archive"].exists():
        return 0, 0
    if retry_errors and db["_conversion_errors"].exists():
        db.execute("delete from _conversion_errors")

    total = db["responses_archive"].count
    show_progress = total > PROGRESS_THRESHOLD
    conversation_ids = [
        row["conversation_id"]
        for row in db.query(
            "select distinct conversation_id from responses_archive order by conversation_id"
        )
    ]
    converted = 0
    errors = 0
    for i, conversation_id in enumerate(conversation_ids):
        if not retry_errors:
            already_failed = db.execute(
                "select 1 from _conversion_errors where conversation_id is ?",
                [conversation_id],
            ).fetchone()
            if already_failed:
                continue
        try:
            converted += _convert_conversation(db, conversation_id)
        except Exception as exception:
            errors += 1
            # A partially converted conversation leaves only orphan
            # value/node rows behind (harmless, content-addressed); the
            # responses row is inserted last so a retry starts clean
            db["_conversion_errors"].insert(
                {
                    "conversation_id": conversation_id,
                    "response_id": None,
                    "error": "{}: {}".format(
                        exception.__class__.__name__, str(exception)
                    ),
                    "datetime_utc": datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(),
                }
            )
        if show_progress and i and i % 100 == 0:
            sys.stderr.write(
                f"Converting legacy logs: {i}/{len(conversation_ids)} conversations\n"
            )
    if show_progress:
        sys.stderr.write(
            "Converted {} legacy response(s) to the new schema{}\n".format(
                converted, f", {errors} error(s)" if errors else ""
            )
        )
    return converted, errors
