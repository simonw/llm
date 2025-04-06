from click.testing import CliRunner
import click
import importlib
import llm
from llm import cli, hookimpl, plugins, get_template_loaders, get_fragment_loaders


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


def test_register_fragment_loaders(logs_db):
    assert get_fragment_loaders() == {}

    def single_fragment(argument):
        return llm.Fragment("single", "single")

    def three_fragments(argument):
        return [
            llm.Fragment(f"one:{argument}", "one"),
            llm.Fragment(f"two:{argument}", "two"),
            llm.Fragment(f"three:{argument}", "three"),
        ]

    class FragmentLoadersPlugin:
        __name__ = "FragmentLoadersPlugin"

        @hookimpl
        def register_fragment_loaders(self, register):
            register("single", single_fragment)
            register("three", three_fragments)

    try:
        plugins.pm.register(FragmentLoadersPlugin(), name="FragmentLoadersPlugin")
        loaders = get_fragment_loaders()
        assert loaders == {
            "single": single_fragment,
            "three": three_fragments,
        }

        # Test the CLI command
        runner = CliRunner()
        result = runner.invoke(
            cli.cli, ["-m", "echo", "-f", "three:x"], catch_exceptions=False
        )
        assert result.exit_code == 0
        expected = "prompt:\n" "one:x\n" "two:x\n" "three:x\n"
        assert expected in result.output
    finally:
        plugins.pm.unregister(name="FragmentLoadersPlugin")
        assert get_fragment_loaders() == {}

    # Let's check the database
    assert list(logs_db.query("select content, source from fragments")) == [
        {"content": "one:x", "source": "one"},
        {"content": "two:x", "source": "two"},
        {"content": "three:x", "source": "three"},
    ]
