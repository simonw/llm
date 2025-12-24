from click.testing import CliRunner
import llm
from llm import cli, plugins
from llm.context import ContextProvider, Context, ContextMetadata


class DummyProvider(ContextProvider):
    name = "dummy"

    def initialize_context(self, conversation_id: str) -> Context:
        return Context(
            data={},
            metadata=ContextMetadata(provider_name=self.name, context_id=conversation_id),
        )

    def update_context(self, conversation_id, response, previous_context=None) -> Context:
        return previous_context or self.initialize_context(conversation_id)

    def get_context(self, conversation_id):
        return None


class ContextPlugin:
    __name__ = "ContextPlugin"

    @llm.hookimpl
    def register_context_providers(self, register):
        register(DummyProvider())


def test_register_context_providers():
    try:
        plugins.pm.register(ContextPlugin(), name="ContextPlugin")
        providers = llm.get_context_providers()
        names = [p.name for p in providers]
        assert "dummy" in names
        runner = CliRunner()
        result = runner.invoke(cli.cli, ["context"])
        assert result.exit_code == 0
        assert "dummy" in result.output
    finally:
        plugins.pm.unregister(name="ContextPlugin")
        assert all(p.name != "dummy" for p in llm.get_context_providers())
