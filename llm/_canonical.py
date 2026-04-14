"""Canonical message serialization and content hashing.

The output of ``canonical_message_json`` is a hash contract. Once shipped,
changing the canonicalization breaks dedup for every existing database.
Treat any edit to this module as a migration and update the snapshot tests
in ``tests/test_canonical.py`` deliberately.

``include_provider_metadata`` parameter exists so a future ``semantic_hash``
column (see ``plans/dag-provider-metadata-hashing.md``) can be added
without refactoring — pass ``False`` to get a hash that ignores opaque
provider tokens like Anthropic signatures and OpenAI ``encrypted_content``.
"""

import hashlib
import json
from typing import Any, Dict

from .parts import Message, Part


def _check_no_floats(value: Any, path: str = "provider_metadata") -> None:
    if isinstance(value, float):
        raise TypeError(
            f"floats are not permitted inside {path}; use int or str instead"
        )
    if isinstance(value, dict):
        for k, v in value.items():
            _check_no_floats(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _check_no_floats(v, f"{path}[{i}]")


def _canonical_part_dict(
    part: Part, *, include_provider_metadata: bool
) -> Dict[str, Any]:
    d = part.to_dict()
    if "provider_metadata" in d:
        if include_provider_metadata:
            _check_no_floats(d["provider_metadata"])
        else:
            d.pop("provider_metadata")
    return d


def canonical_message_dict(
    msg: Message, *, include_provider_metadata: bool = True
) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "role": msg.role,
        "parts": [
            _canonical_part_dict(
                p, include_provider_metadata=include_provider_metadata
            )
            for p in msg.parts
        ],
    }
    if include_provider_metadata and msg.provider_metadata:
        _check_no_floats(msg.provider_metadata)
        d["provider_metadata"] = msg.provider_metadata
    return d


def canonical_message_json(
    msg: Message, *, include_provider_metadata: bool = True
) -> bytes:
    """Return the deterministic JSON bytes for a Message.

    The result feeds ``message_content_hash``. Stable under: key reordering
    in dicts, unicode input (kept raw, not \\u-escaped), and empty-vs-missing
    ``provider_metadata``.
    """
    return json.dumps(
        canonical_message_dict(
            msg, include_provider_metadata=include_provider_metadata
        ),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def message_content_hash(msg: Message) -> str:
    """sha256 hex digest of the full canonical serialization of a Message."""
    return hashlib.sha256(canonical_message_json(msg)).hexdigest()
