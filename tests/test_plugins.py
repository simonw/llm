from click.testing import CliRunner
import click
import importlib
from llm import cli, hookimpl, plugins
import pytest


def test_register_commands():
    importlib.reload(cli)
    assert plugins.get_plugins() == []

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

        assert plugins.get_plugins() == [
            {"name": "HelloWorldPlugin", "hooks": ["register_commands"]}
        ]

        runner = CliRunner()
        result = runner.invoke(cli.cli, ["hello-world"])
        assert result.exit_code == 0
        assert result.output == "Hello world!\n"

    finally:
        plugins.pm.unregister(name="HelloWorldPlugin")
        importlib.reload(cli)
        assert plugins.get_plugins() == []
