from click.testing import CliRunner
import click
import importlib
import llm
from llm import cli, hookimpl, plugins, get_template_loaders, get_fragment_loaders
import textwrap


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


def test_register_fragment_loaders(logs_db, httpx_mock):
    httpx_mock.add_response(
        method="HEAD",
        url="https://example.com/attachment.png",
        content=b"attachment",
        headers={"Content-Type": "image/png"},
        is_reusable=True,
    )

    assert get_fragment_loaders() == {}

    def single_fragment(argument):
        "This is the fragment documentation"
        return llm.Fragment("single", "single")

    def three_fragments(argument):
        return [
            llm.Fragment(f"one:{argument}", "one"),
            llm.Fragment(f"two:{argument}", "two"),
            llm.Fragment(f"three:{argument}", "three"),
        ]

    def fragment_and_attachment(argument):
        return [
            llm.Fragment(f"one:{argument}", "one"),
            llm.Attachment(url="https://example.com/attachment.png"),
        ]

    class FragmentLoadersPlugin:
        __name__ = "FragmentLoadersPlugin"

        @hookimpl
        def register_fragment_loaders(self, register):
            register("single", single_fragment)
            register("three", three_fragments)
            register("mixed", fragment_and_attachment)

    try:
        plugins.pm.register(FragmentLoadersPlugin(), name="FragmentLoadersPlugin")
        loaders = get_fragment_loaders()
        assert loaders == {
            "single": single_fragment,
            "three": three_fragments,
            "mixed": fragment_and_attachment,
        }

        # Test the CLI command
        runner = CliRunner()
        result = runner.invoke(
            cli.cli, ["-m", "echo", "-f", "three:x"], catch_exceptions=False
        )
        assert result.exit_code == 0
        expected = "prompt:\n" "one:x\n" "two:x\n" "three:x\n"
        assert expected in result.output
        # And the llm fragments loaders command:
        result2 = runner.invoke(cli.cli, ["fragments", "loaders"])
        assert result2.exit_code == 0
        expected2 = (
            "single:\n"
            "  This is the fragment documentation\n"
            "\n"
            "three:\n"
            "  Undocumented\n"
            "\n"
            "mixed:\n"
            "  Undocumented\n"
        )
        assert result2.output == expected2

        # Test the one that includes an attachment
        result3 = runner.invoke(
            cli.cli, ["-m", "echo", "-f", "mixed:x"], catch_exceptions=False
        )
        assert result3.exit_code == 0
        result3.output.strip == textwrap.dedent(
            """\
            system:


            prompt:
            one:x

            attachments:
            - https://example.com/attachment.png
            """
        ).strip()

    finally:
        plugins.pm.unregister(name="FragmentLoadersPlugin")
        assert get_fragment_loaders() == {}

    # Let's check the database
    assert list(logs_db.query("select content, source from fragments")) == [
        {"content": "one:x", "source": "one"},
        {"content": "two:x", "source": "two"},
        {"content": "three:x", "source": "three"},
    ]
