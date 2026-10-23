import json

import llm


class BaseNotes(llm.Toolbox):
    def __init__(self, path="notes"):
        self.path = path


class ScopedNotes(BaseNotes):
    def __init__(self, path="notes", *, scope="public"):
        super().__init__(path)
        self.scope = scope

    def read(self) -> str:
        return f"{self.path}/{self.scope}"


def test_derived_toolbox_configuration():
    notes = ScopedNotes("work", scope="private")
    assert notes.read() == "work/private"
    assert notes._config == {"path": "work", "scope": "private"}
    assert ScopedNotes()._config == {"path": "notes", "scope": "public"}


def test_log_keeps_distinct_derived_toolbox_configurations(db_factory, mock_model):
    db = db_factory(memory=True)
    for scope in ("public", "private"):
        mock_model.enqueue(["ok"])
        response = mock_model.prompt(
            "read notes", tools=[ScopedNotes("work", scope=scope)]
        )
        response.text()
        response.log_to_db(db)

    instances = list(db["tool_instances"].rows)
    assert len(instances) == 2
    assert {json.loads(row["arguments"])["scope"] for row in instances} == {
        "public",
        "private",
    }
    assert len({row["instance_id"] for row in db["turn_tools"].rows}) == 2
