import json

import pytest
from click.testing import CliRunner

from llm.cli import cli
from llm.migrations import migrate


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(
    "value,flatten",
    [
        (None, False),
        (0, False),
        (False, False),
        ("", False),
        ({}, False),
        ({"name": "one"}, False),
        ([{"name": "one"}, "two"], False),
        ([], True),
        ([{"name": "one"}, {"name": "two"}], True),
    ],
)
def test_data_key_only_flattens_object_arrays(
    mock_model, logs_db, legacy, value, flatten
):
    payload = {"items": value, "source": "keep unless flattened"}
    runner = CliRunner()
    if legacy:
        migrate(logs_db)
        logs_db["responses"].insert(
            {
                "id": "01aaaaaaaaaaaaaaaaaaaaaaaa",
                "prompt": "return data",
                "response": json.dumps(payload),
                "model": "mock",
                "datetime_utc": "2026-01-01T00:00:00",
            }
        )
    else:
        mock_model.enqueue([json.dumps(payload)])
        result = runner.invoke(cli, ["-m", "mock", "return data"])
        assert result.exit_code == 0, result.output

    result = runner.invoke(cli, ["logs", "--data-key", "items", "--data-array"])
    assert result.exit_code == 0, (result.output, result.exception)
    assert json.loads(result.output) == (value if flatten else [payload])
