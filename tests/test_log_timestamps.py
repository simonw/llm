import pytest
import yaml
from click.testing import CliRunner

from llm.cli import cli
from llm.migrations import migrate
from llm.utils import monotonic_ulid


@pytest.mark.parametrize("short", (False, True))
def test_logs_with_missing_timestamp(db_factory, tmp_path, short):
    log_path = str(tmp_path / "logs.db")
    db = db_factory(log_path)
    migrate(db)
    db["responses"].insert_all(
        {
            "id": str(monotonic_ulid()).lower(),
            "conversation_id": "abc123",
            "model": "echo",
            "prompt": prompt,
            "response": f"response for {prompt}",
            "datetime_utc": timestamp,
        }
        for prompt, timestamp in (
            ("undated record", None),
            ("dated record", "2026-01-02T03:04:05.123456+00:00"),
        )
    )

    args = ["logs", "list", "--path", log_path]
    if short:
        args.append("--short")
    result = CliRunner().invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0
    if short:
        assert [
            (row["prompt"], row["datetime"]) for row in yaml.safe_load(result.output)
        ] == [
            ("undated record", None),
            ("dated record", "2026-01-02T03:04:05"),
        ]
    else:
        assert "# Unknown time    conversation: abc123" in result.output
        assert "# 2026-01-02T03:04:05    conversation: abc123" in result.output
        assert "response for undated record" in result.output
        assert "response for dated record" in result.output
