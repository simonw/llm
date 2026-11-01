"""Annotated parameter constraints should reach the model's tool schema."""

from typing import Annotated

import pytest
from pydantic import BaseModel, Field

import llm


def test_tool_preserves_annotated_parameter_metadata():
    def search(
        query: Annotated[str, Field(min_length=2, description="Text to search for")],
        limit: Annotated[int, Field(gt=0, le=10, description="Maximum matches")] = 3,
    ) -> str:
        return query

    schema = llm.Tool.function(search).input_schema
    assert schema["properties"]["query"] == {
        "type": "string",
        "minLength": 2,
        "description": "Text to search for",
    }
    assert schema["properties"]["limit"] == {
        "type": "integer",
        "exclusiveMinimum": 0,
        "maximum": 10,
        "description": "Maximum matches",
        "default": 3,
    }
    assert schema["required"] == ["query"]


def test_tool_preserves_nested_annotated_metadata():
    def lookup(
        names: Annotated[
            list[Annotated[str, Field(pattern="^[a-z]+$")]],
            Field(min_length=1, max_length=5),
        ],
    ) -> str:
        return ", ".join(names)

    assert llm.Tool.function(lookup).input_schema["properties"]["names"] == {
        "type": "array",
        "items": {"type": "string", "pattern": "^[a-z]+$"},
        "minItems": 1,
        "maxItems": 5,
    }


def test_tool_resolves_deferred_annotated_types():
    async def search(limit: "Annotated[int, Field(ge=1)]" = 2):
        return limit

    assert llm.Tool.function(search).input_schema["properties"]["limit"] == {
        "type": "integer",
        "minimum": 1,
        "default": 2,
    }


def test_tool_keeps_plain_annotations_and_reserved_context_unchanged():
    def lookup(name: str, llm_tool_call: Annotated[llm.ToolCall, "context"]):
        return name

    schema = llm.Tool.function(lookup).input_schema
    assert schema["properties"] == {"name": {"type": "string"}}
    assert schema["required"] == ["name"]


@pytest.mark.parametrize("model_id", ("gpt-4o-mini", "gpt-5"))
def test_annotated_metadata_is_in_provider_request(model_id):
    def search(limit: Annotated[int, Field(ge=1, le=5, description="Result limit")]):
        return limit

    model = llm.get_model(model_id)
    response = model.prompt("Search", tools=[search])
    if hasattr(model, "_build_responses_kwargs"):
        request = model._build_responses_kwargs(response.prompt, stream=False)
        parameters = request["tools"][0]["parameters"]
    else:
        request = model.build_kwargs(response.prompt, stream=False)
        parameters = request["tools"][0]["function"]["parameters"]
    assert parameters["properties"]["limit"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 5,
        "description": "Result limit",
    }


@pytest.mark.parametrize("default", (None, 4))
def test_python_signature_controls_aliases_and_required_arguments(mock_model, default):
    def lookup(
        count: Annotated[
            int,
            Field(
                alias="other",
                validation_alias="incoming",
                serialization_alias="outgoing",
                ge=1,
            ),
        ],
    ):
        return count

    if default is not None:
        lookup.__defaults__ = (default,)
    tool = llm.Tool.function(lookup)
    schema = tool.input_schema
    assert list(schema["properties"]) == ["count"]
    assert schema["properties"]["count"]["minimum"] == 1
    if default is None:
        assert schema["required"] == ["count"]
    else:
        assert not schema.get("required")
        assert schema["properties"]["count"]["default"] == default
    response = mock_model.prompt("test", tools=[tool])
    result = response.execute_tool_call(
        llm.ToolCall(name="lookup", arguments={"count": 2})
    )
    assert result.exception is None
    assert result.output == "2"


@pytest.mark.parametrize(
    "field", (Field(default=7, ge=1), Field(default_factory=lambda: 7, ge=1))
)
def test_annotation_defaults_do_not_make_required_python_arguments_optional(field):
    def lookup(count: Annotated[int, field]):
        return count

    schema = llm.Tool.function(lookup).input_schema
    assert schema["required"] == ["count"]
    assert schema["properties"]["count"] == {"type": "integer", "minimum": 1}


def test_nested_model_aliases_are_preserved():
    class Person(BaseModel):
        name: str = Field(alias="display_name")

    def lookup(person: Person):
        return person

    schema = llm.Tool.function(lookup).input_schema
    assert schema["$defs"]["Person"]["properties"] == {
        "display_name": {"type": "string"}
    }
    assert schema["$defs"]["Person"]["required"] == ["display_name"]


def test_plain_annotation_with_field_default_is_unchanged():
    def search(limit: int = Field(default=3, ge=1, description="Limit")):
        return limit

    assert llm.Tool.function(search).input_schema["properties"]["limit"] == {
        "type": "integer",
        "default": 3,
        "minimum": 1,
        "description": "Limit",
    }
