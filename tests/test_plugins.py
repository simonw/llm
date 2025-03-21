from click.testing import CliRunner
import click
import importlib
import llm
from llm import cli, hookimpl, plugins, get_template_loaders


def test_register_commands():
    importlib.reload(cli)

    def plugin_names():
        return [plugin["name"] for plugin in llm.get_plugins()]

    assert "HelloWorldPlugin" not in plugin_names()

    class HelloWorldPlugin:
        __name__ = "HelloWorldPlugin"

        @hookimpl
        def register_commands(self, cli):
            @cli.command(name="hello-world")
            def hello_world():
                "Print hello world"
                click.echo("Hello world!")

    try:
        plugins.pm.register(HelloWorldPlugin(), name="HelloWorldPlugin")
        importlib.reload(cli)

        assert "HelloWorldPlugin" in plugin_names()

        runner = CliRunner()
        result = runner.invoke(cli.cli, ["hello-world"])
        assert result.exit_code == 0
        assert result.output == "Hello world!\n"

    finally:
        plugins.pm.unregister(name="HelloWorldPlugin")
        importlib.reload(cli)
        assert "HelloWorldPlugin" not in plugin_names()


def test_register_template_loaders():
    assert get_template_loaders() == {}

    def one_loader(template_path):
        return llm.Template(name="one:" + template_path, prompt=template_path)

    def two_loader(template_path):
        "Docs for two"
        return llm.Template(name="two:" + template_path, prompt=template_path)

    def dupe_two_loader(template_path):
        "Docs for two dupe"
        return llm.Template(name="two:" + template_path, prompt=template_path)

    class TemplateLoadersPlugin:
        __name__ = "TemplateLoadersPlugin"

        @hookimpl
        def register_template_loaders(self, register):
            register("one", one_loader)
            register("two", two_loader)
            register("two", dupe_two_loader)

    try:
        plugins.pm.register(TemplateLoadersPlugin(), name="TemplateLoadersPlugin")
        loaders = get_template_loaders()
        assert loaders == {
            "one": one_loader,
            "two": two_loader,
            "two_1": dupe_two_loader,
        }

        # Test the CLI command
        runner = CliRunner()
        result = runner.invoke(cli.cli, ["templates", "loaders"])
        assert result.exit_code == 0
        assert result.output == (
            "one:\n"
            "  Undocumented\n"
            "two:\n"
            "  Docs for two\n"
            "two_1:\n"
            "  Docs for two dupe\n"
        )

    finally:
        plugins.pm.unregister(name="TemplateLoadersPlugin")
        assert get_template_loaders() == {}
