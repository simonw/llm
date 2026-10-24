import json

import pytest
from click.testing import CliRunner

from llm.cli import cli
from llm.logs import LogStore

SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}}


@pytest.mark.parametrize("output", [[], ["--full"], ["--json"], ["--nl"]])
def test_schema_listing_includes_new_turns(db_factory, mock_model, tmp_path, output):
    path = tmp_path / "logs.db"
    store = LogStore(db_factory(path))
    mock_model.enqueue(['{"name": "Ada"}'])
    store.log(mock_model.prompt("name", schema=SCHEMA))
    assert store.db["responses"].count == 0
    schema_id = next(store.db["schemas"].rows)["id"]

    result = CliRunner().invoke(cli, ["schemas", "list", "-d", str(path), *output])
    assert result.exit_code == 0, result.output
    assert schema_id in result.output
    if output in (["--json"], ["--nl"]):
        data = json.loads(result.output)
        row = data[0] if isinstance(data, list) else data
        assert row["times_used"] == 1
        assert row["content"] == SCHEMA
    else:
        assert "1 time, most recently" in result.output


def test_schema_usage_combines_legacy_rows_without_double_counting(
    db_factory, mock_model, tmp_path
):
    path = tmp_path / "logs.db"
    store = LogStore(db_factory(path))
    turn_ids = []
    for day in (2, 3):
        mock_model.enqueue(['{"name": "Ada"}'])
        turn_id = store.log(mock_model.prompt("name", schema=SCHEMA))
        turn_ids.append(turn_id)
        store.db["turns"].update(turn_id, {"datetime_utc": f"2026-01-0{day}T00:00:00Z"})
    schema_id = next(store.db["schemas"].rows)["id"]
    for response_id, day in (("legacy-only", 1), (turn_ids[0], 9)):
        store.db["responses"].insert(
            {
                "id": response_id,
                "schema_id": schema_id,
                "datetime_utc": f"2026-01-0{day}T00:00:00Z",
            }
        )

    result = CliRunner().invoke(
        cli, ["schemas", "list", "-d", str(path), "--json", "-q", "name"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [
        {
            "id": schema_id,
            "content": SCHEMA,
            "recently_used": "2026-01-03T00:00:00Z",
            "times_used": 3,
        }
    ]
