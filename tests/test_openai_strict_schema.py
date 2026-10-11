import copy

import pytest

from llm.default_plugins.openai_strict_schema import (
    UnsupportedStrictSchemaError,
    to_strict_json_schema,
)


def test_adds_additional_properties_false_and_fills_required():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
    }
    assert to_strict_json_schema(schema) == {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
        "required": ["name", "age"],
        "additionalProperties": False,
    }


def test_keeps_existing_required_order_and_appends_missing():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "bio": {"type": "string"},
        },
        "required": ["age"],
        "additionalProperties": False,
    }
    assert to_strict_json_schema(schema) == {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "bio": {"type": "string"},
        },
        "required": ["age", "name", "bio"],
        "additionalProperties": False,
    }


def test_preserves_supported_existing_required():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    }
    assert to_strict_json_schema(schema) == schema


def test_inlines_defs():
    schema = {
        "$defs": {
            "Dog": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            }
        },
        "type": "object",
        "properties": {"dog": {"$ref": "#/$defs/Dog"}},
        "required": ["dog"],
    }
    assert to_strict_json_schema(schema) == {
        "type": "object",
        "properties": {
            "dog": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            }
        },
        "required": ["dog"],
        "additionalProperties": False,
    }


def test_preserves_null_any_of_union():
    schema = {
        "type": "object",
        "properties": {"note": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
    }
    result = to_strict_json_schema(schema)
    assert result["properties"]["note"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}]
    }


def test_recursive_arrays_nested_objects():
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            }
        },
        "required": ["items"],
    }
    result = to_strict_json_schema(schema)
    assert result["properties"]["items"]["items"] == {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    }


@pytest.mark.parametrize(
    "schema",
    [
        {"minItems": 1, "type": "array", "items": {"type": "string"}},
        {"allOf": [{"type": "string"}]},
        {"oneOf": [{"type": "string"}, {"type": "integer"}]},
        {"multipleOf": 2, "type": "integer"},
        {"patternProperties": {"^x": {"type": "string"}}, "type": "object"},
    ],
)
def test_raises_on_unsupported_keywords(schema):
    with pytest.raises(UnsupportedStrictSchemaError):
        to_strict_json_schema(schema)


def test_raises_on_multi_branch_any_of():
    schema = {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]}
    with pytest.raises(UnsupportedStrictSchemaError):
        to_strict_json_schema(schema)


def test_raises_on_additional_properties_true():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "additionalProperties": True,
    }
    with pytest.raises(UnsupportedStrictSchemaError):
        to_strict_json_schema(schema)


def test_strips_cosmetic_keys():
    schema = {
        "type": "object",
        "title": "A dog",
        "properties": {"name": {"type": "string", "description": "the dog's name"}},
        "$schema": "https://json-schema.org/draft/2020-12/schema",
    }
    result = to_strict_json_schema(schema)
    assert "title" not in result
    assert "$schema" not in result
    assert result["properties"]["name"] == {
        "type": "string",
        "description": "the dog's name",
    }


def test_does_not_mutate_input():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
    }
    before = copy.deepcopy(schema)
    to_strict_json_schema(schema)
    assert schema == before


def test_raises_on_recursive_ref_cycle():
    schema = {
        "$defs": {"Node": {"$ref": "#/$defs/Node"}},
        "$ref": "#/$defs/Node",
    }
    with pytest.raises(UnsupportedStrictSchemaError):
        to_strict_json_schema(schema)


def test_raises_on_unresolvable_ref():
    schema = {"$ref": "#/$defs/Missing"}
    with pytest.raises(UnsupportedStrictSchemaError):
        to_strict_json_schema(schema)


def test_raises_on_non_defs_ref():
    schema = {"$ref": "#/definitions/Thing"}
    with pytest.raises(UnsupportedStrictSchemaError):
        to_strict_json_schema(schema)


def test_pydantic_style_optional_field_schema():
    """The shape produced by Pydantic for an Optional field stays in strict form."""
    schema = {
        "type": "object",
        "properties": {
            "nickname": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Nickname",
            }
        },
        "title": "Person",
    }
    result = to_strict_json_schema(schema)
    assert result == {
        "type": "object",
        "properties": {"nickname": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        "required": ["nickname"],
        "additionalProperties": False,
    }
