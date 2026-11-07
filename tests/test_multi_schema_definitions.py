import copy
import json

import pytest
from click.testing import CliRunner
from pydantic import BaseModel

from llm.cli import cli
from llm.utils import multi_schema


@pytest.mark.parametrize("keyword", ["$defs", "definitions"])
def test_multi_schema_keeps_root_definition_references(keyword):
    schema = {
        "type": "object",
        "properties": {"address": {"$ref": f"#/{keyword}/Address"}},
        keyword: {"Address": {"type": "string"}},
    }
    original = copy.deepcopy(schema)
    wrapped = multi_schema(schema)
    assert wrapped[keyword] == {"Address": {"type": "string"}}
    item_schema = wrapped["properties"]["items"]["items"]
    assert item_schema["properties"]["address"]["$ref"] == f"#/{keyword}/Address"
    assert keyword not in item_schema
    assert schema == original


def test_multi_schema_preserves_identified_resource():
    schema = {
        "$id": "https://example.com/address.json",
        "$defs": {"Address": {"type": "string"}},
        "$ref": "#/$defs/Address",
    }
    wrapped = multi_schema(schema)
    assert wrapped["properties"]["items"]["items"] == schema
    assert "$defs" not in wrapped


def test_schema_multi_with_pydantic_definitions(tmp_path, mock_model):
    class Address(BaseModel):
        city: str

    class Person(BaseModel):
        address: Address

    schema = Person.model_json_schema()
    schema_path = tmp_path / "person.json"
    schema_path.write_text(json.dumps(schema))
    result = CliRunner().invoke(
        cli,
        ["-m", "mock", "--schema-multi", str(schema_path), "people", "--no-log"],
    )
    assert result.exit_code == 0, result.output
    sent_schema = mock_model.history[0][0].schema
    assert sent_schema["$defs"]["Address"] == schema["$defs"]["Address"]
    item_schema = sent_schema["properties"]["items"]["items"]
    assert item_schema["properties"]["address"]["$ref"] == "#/$defs/Address"
    assert "$defs" not in item_schema
