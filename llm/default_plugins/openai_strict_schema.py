"""Convert JSON schemas to OpenAI Structured Outputs strict-compatible form.

OpenAI's ``strict: true`` Structured Outputs mode only accepts a restricted
JSON Schema subset:

- Every object must declare ``additionalProperties: false``.
- Every property of an object must be listed in ``required``.
- Only a small set of keywords is supported - for example ``minItems``,
  ``maxItems`` and ``allOf`` are rejected.
- Schemas must not rely on ``$ref``/``$defs`` pointers.

This module rewrites a schema (for example one produced by a Pydantic model
via ``model.model_json_schema()``) into a form compliant with those rules.
Rather than silently dropping constraints the API cannot enforce, the
converter raises a clear error for unsupported keywords.
"""

from __future__ import annotations

from typing import Any

# Keywords OpenAI's strict Structured Outputs mode does not support. Raising a
# clear error here is safer than silently weakening the user's schema - e.g.
# dropping ``minItems`` would let the model return fewer items than requested.
_UNSUPPORTED_KEYS = frozenset(
    {
        "allOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "patternProperties",
        "propertyNames",
        "contains",
        "prefixItems",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "multipleOf",
        "unevaluatedProperties",
        "dependentRequired",
        "dependentSchemas",
    }
)

# Keywords that can be removed without changing the constraints the schema
# places on the output.
_STRIP_KEYS = frozenset(
    {
        "title",
        "examples",
        "example",
        "default",
        "deprecated",
        "readOnly",
        "writeOnly",
        "xml",
        "$schema",
        "$defs",
        "definitions",
    }
)


class UnsupportedStrictSchemaError(ValueError):
    """Raised when a schema cannot be made compatible with OpenAI strict mode."""


def to_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return ``schema`` rewritten to satisfy OpenAI's strict mode rules.

    The input schema is never mutated. ``$defs`` definitions are inlined,
    object schemas gain ``additionalProperties: false`` and a complete
    ``required`` list, and null unions are preserved. Keywords OpenAI strict
    mode cannot represent raise :class:`UnsupportedStrictSchemaError`.
    """
    defs = schema.get("$defs") or {}
    return _to_strict(schema, defs, ref_stack=frozenset())


def _to_strict(node: Any, defs: dict, ref_stack: frozenset) -> Any:
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        return _resolve_ref(node, defs, ref_stack)

    unsupported = sorted(_UNSUPPORTED_KEYS & node.keys())
    if unsupported:
        raise UnsupportedStrictSchemaError(
            "Schema keyword(s) not supported by OpenAI strict mode: "
            + ", ".join(unsupported)
            + ". Remove them or disable the strict_schema option."
        )

    any_of = node.get("anyOf")
    if any_of is not None:
        return _to_nullable_any_of(node, any_of, defs, ref_stack)

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _STRIP_KEYS:
            continue
        if key == "properties":
            if not isinstance(value, dict):
                out[key] = value
                continue
            props = {
                name: _to_strict(prop, defs, ref_stack) for name, prop in value.items()
            }
            additional = node.get("additionalProperties")
            if additional not in (None, False):
                raise UnsupportedStrictSchemaError(
                    "additionalProperties: true is incompatible with OpenAI strict mode - every object must set additionalProperties: false."
                )
            required = [k for k in node.get("required", []) if k in value]
            missing = [k for k in value if k not in required]
            out[key] = props
            out["required"] = required + missing
            out["additionalProperties"] = False
            continue
        if key == "items":
            out[key] = _to_strict(value, defs, ref_stack)
            continue
        if key in ("required", "additionalProperties"):
            continue
        out[key] = value
    return out


def _to_nullable_any_of(
    node: dict, any_of: list, defs: dict, ref_stack: frozenset
) -> dict:
    nulls = [b for b in any_of if b == {"type": "null"}]
    non_null = [b for b in any_of if b != {"type": "null"}]
    if len(non_null) != 1 or not nulls:
        raise UnsupportedStrictSchemaError(
            "Schema defines a union (anyOf/oneOf) OpenAI strict mode cannot represent. Only Optional-style 'anyOf: [T, {type: null}]' unions are supported."
        )
    out: dict[str, Any] = {
        "anyOf": [_to_strict(non_null[0], defs, ref_stack), {"type": "null"}]
    }
    for key, value in node.items():
        if key == "anyOf":
            continue
        if key in _STRIP_KEYS:
            continue
        if key in ("properties", "items", "required", "additionalProperties"):
            raise UnsupportedStrictSchemaError(
                f"Keyword {key!r} is not allowed alongside a union (anyOf)."
            )
        out[key] = value
    return out


def _resolve_ref(node: dict, defs: dict, ref_stack: frozenset) -> dict:
    ref = node["$ref"]
    if not ref.startswith("#/$defs/"):
        raise UnsupportedStrictSchemaError(
            f"Unsupported $ref: {ref}. OpenAI strict mode only supports '#/$defs/Name' pointers into the schema's own $defs."
        )
    name = ref[len("#/$defs/") :]
    if "/" in name:
        raise UnsupportedStrictSchemaError(
            f"Unsupported $ref: {ref}. Nested pointers inside $defs are not supported."
        )
    if name in ref_stack:
        raise UnsupportedStrictSchemaError(
            f"Schema contains a recursive $ref cycle ({name}) which OpenAI strict mode cannot represent."
        )
    definition = defs.get(name)
    if definition is None:
        raise UnsupportedStrictSchemaError(
            f"Unresolvable $ref: {ref}. No matching $defs entry found."
        )
    resolved = _to_strict(definition, defs, ref_stack | {name})
    for key, value in node.items():
        if key == "$ref":
            continue
        if key in _STRIP_KEYS:
            continue
        resolved[key] = value
    return resolved
