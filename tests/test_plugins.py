from click.testing import CliRunner
import click
import importlib
import json
import llm
from llm import cli, hookimpl, plugins, get_template_loaders, get_fragment_loaders
import pathlib
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
        assert json.loads(result.output) == {
            "prompt": "one:x\ntwo:x\nthree:x",
            "system": "",
            "attachments": [],
            "stream": True,
            "previous": [],
        }
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


def test_register_tools(tmpdir, logs_db):
    def upper(text: str) -> str:
        """Convert text to uppercase."""
        return text.upper()

    def count_character_in_word(text: str, character: str) -> int:
        """Count the number of occurrences of a character in a word."""
        return text.count(character)

    def output_as_json(text: str):
        return {"this_is_in_json": {"nested": text}}

    class ToolsPlugin:
        __name__ = "ToolsPlugin"

        @hookimpl
        def register_tools(self, register):
            register(llm.Tool.function(upper))
            register(count_character_in_word, name="count_chars")
            register(output_as_json)

    try:
        plugins.pm.register(ToolsPlugin(), name="ToolsPlugin")
        tools = llm.get_tools()
        assert tools == {
            "upper": llm.Tool(
                name="upper",
                description="Convert text to uppercase.",
                input_schema={
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                    "type": "object",
                },
                implementation=upper,
                plugin="ToolsPlugin",
            ),
            "count_chars": llm.Tool(
                name="count_chars",
                description="Count the number of occurrences of a character in a word.",
                input_schema={
                    "properties": {
                        "text": {"type": "string"},
                        "character": {"type": "string"},
                    },
                    "required": ["text", "character"],
                    "type": "object",
                },
                implementation=count_character_in_word,
                plugin="ToolsPlugin",
            ),
            "output_as_json": llm.Tool(
                name="output_as_json",
                description=None,
                input_schema={
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                    "type": "object",
                },
                implementation=output_as_json,
                plugin="ToolsPlugin",
            ),
        }
        # Test the CLI command
        runner = CliRunner()
        result = runner.invoke(cli.cli, ["tools", "list"])
        assert result.exit_code == 0
        assert result.output == (
            "upper(text: str) -> str (plugin: ToolsPlugin)\n\n"
            "  Convert text to uppercase.\n\n"
            "count_chars(text: str, character: str) -> int (plugin: ToolsPlugin)\n\n"
            "  Count the number of occurrences of a character in a word.\n\n"
            "output_as_json(text: str) (plugin: ToolsPlugin)\n\n"
        )
        # And --json
        result2 = runner.invoke(cli.cli, ["tools", "list", "--json"])
        assert result2.exit_code == 0
        assert json.loads(result2.output) == {
            "tools": [
                {
                    "name": "upper",
                    "description": "Convert text to uppercase.",
                    "arguments": {
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "type": "object",
                    },
                    "plugin": "ToolsPlugin",
                },
                {
                    "name": "count_chars",
                    "description": "Count the number of occurrences of a character in a word.",
                    "arguments": {
                        "properties": {
                            "text": {"type": "string"},
                            "character": {"type": "string"},
                        },
                        "required": ["text", "character"],
                        "type": "object",
                    },
                    "plugin": "ToolsPlugin",
                },
                {
                    "name": "output_as_json",
                    "description": None,
                    "arguments": {
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "type": "object",
                    },
                    "plugin": "ToolsPlugin",
                },
            ],
            "toolboxes": [],
        }
        # And test the --tools option
        functions_path = str(tmpdir / "functions.py")
        with open(functions_path, "w") as fp:
            fp.write("def example(s: str, i: int):\n    return s + '-' + str(i)")
        result3 = runner.invoke(
            cli.cli,
            [
                "tools",
                "--functions",
                "def reverse(s: str): return s[::-1]",
                "--functions",
                functions_path,
            ],
        )
        assert result3.exit_code == 0
        assert "reverse(s: str)" in result3.output
        assert "example(s: str, i: int)" in result3.output
        # Now run a prompt using a plugin tool and to check it gets logged correctly
        result4 = runner.invoke(
            cli.cli,
            [
                "-m",
                "echo",
                "--tool",
                "upper",
                json.dumps(
                    {"tool_calls": [{"name": "upper", "arguments": {"text": "hi"}}]}
                ),
            ],
            catch_exceptions=False,
        )
        assert result4.exit_code == 0
        assert '"output": "HI"' in result4.output

        # Now check in the database
        tool_row = [row for row in logs_db["tools"].rows][0]
        assert tool_row["name"] == "upper"
        assert tool_row["plugin"] == "ToolsPlugin"

        # The llm logs command should return that, including with the -T upper option
        for args in ([], ["-T", "upper"]):
            logs_result = runner.invoke(cli.cli, ["logs"] + args)
            assert logs_result.exit_code == 0
            assert "HI" in logs_result.output
        # ... but not for -T reverse
        logs_empty_result = runner.invoke(cli.cli, ["logs", "-T", "count_chars"])
        assert logs_empty_result.exit_code == 0
        assert "HI" not in logs_empty_result.output

        # Start with a tool, use llm -c to reuse the same tool
        result5 = runner.invoke(
            cli.cli,
            [
                "prompt",
                "-m",
                "echo",
                "--tool",
                "upper",
                json.dumps(
                    {"tool_calls": [{"name": "upper", "arguments": {"text": "one"}}]}
                ),
            ],
        )
        assert result5.exit_code == 0
        assert (
            runner.invoke(
                cli.cli,
                [
                    "-c",
                    json.dumps(
                        {
                            "tool_calls": [
                                {"name": "upper", "arguments": {"text": "two"}}
                            ]
                        }
                    ),
                ],
            ).exit_code
            == 0
        )
        # Now do it again with llm chat -c
        assert (
            runner.invoke(
                cli.cli,
                ["chat", "-c"],
                input=(
                    json.dumps(
                        {
                            "tool_calls": [
                                {"name": "upper", "arguments": {"text": "three"}}
                            ]
                        }
                    )
                    + "\nquit\n"
                ),
                catch_exceptions=False,
            ).exit_code
            == 0
        )
        # Should have logged those three tool uses in llm logs -c -n 0
        log_rows = json.loads(
            runner.invoke(cli.cli, ["logs", "-c", "-n", "0", "--json"]).output
        )
        # Workaround for bug in https://github.com/simonw/llm/issues/1073 and 1079
        # We use a set and don't check the order, because (esp on Windows) datetime_utc
        # may not be accurate enough to order them correctly.
        log_rows.sort(key=lambda row: row["datetime_utc"])
        results = {
            (log_row["prompt"], json.dumps(log_row["tool_results"]))
            for log_row in log_rows
        }
        assert results == {
            (
                "",
                '[{"id": 4, "tool_id": 1, "name": "upper", "output": "THREE", "tool_call_id": null}]',
            ),
            (
                '{"tool_calls": [{"name": "upper", "arguments": {"text": "three"}}]}',
                "[]",
            ),
            (
                "",
                '[{"id": 3, "tool_id": 1, "name": "upper", "output": "TWO", "tool_call_id": null}]',
            ),
            (
                "",
                '[{"id": 2, "tool_id": 1, "name": "upper", "output": "ONE", "tool_call_id": null}]',
            ),
            ('{"tool_calls": [{"name": "upper", "arguments": {"text": "one"}}]}', "[]"),
            ('{"tool_calls": [{"name": "upper", "arguments": {"text": "two"}}]}', "[]"),
        }
        # Test the --td option
        result6 = runner.invoke(
            cli.cli,
            [
                "prompt",
                "-m",
                "echo",
                "--tool",
                "output_as_json",
                json.dumps(
                    {
                        "tool_calls": [
                            {"name": "output_as_json", "arguments": {"text": "hi"}}
                        ]
                    }
                ),
                "--td",
            ],
        )
        assert result6.exit_code == 0
        assert (
            "Tool call: output_as_json({'text': 'hi'})\n"
            "  {\n"
            '    "this_is_in_json": {\n'
            '      "nested": "hi"\n'
            "    }\n"
            "  }"
        ) in result6.output
    finally:
        plugins.pm.unregister(name="ToolsPlugin")
        assert llm.get_tools() == {}


def test_register_toolbox(tmpdir, logs_db):
    class Memory(llm.Toolbox):
        _memory = None

        def _get_memory(self):
            if self._memory is None:
                self._memory = {}
            return self._memory

        def set(self, key: str, value: str):
            "Set something as a key"
            self._get_memory()[key] = value

        def get(self, key: str):
            "Get something from a key"
            return self._get_memory().get(key) or ""

        def append(self, key: str, value: str):
            "Append something as a key"
            memory = self._get_memory()
            memory[key] = (memory.get(key) or "") + "\n" + value

        def keys(self):
            "Return a list of keys"
            return list(self._get_memory().keys())

    class Filesystem(llm.Toolbox):
        def __init__(self, path: str):
            self.path = path

        def list_files(self):
            return [str(item) for item in pathlib.Path(self.path).glob("*")]

    # Test the Python API
    model = llm.get_model("echo")
    memory = Memory()
    conversation = model.conversation(tools=[memory])
    accumulated = []

    def after_call(tool, tool_call, tool_result):
        accumulated.append((tool.name, tool_call.arguments, tool_result.output))

    conversation.chain(
        json.dumps(
            {
                "tool_calls": [
                    {
                        "name": "Memory_set",
                        "arguments": {"key": "hello", "value": "world"},
                    }
                ]
            }
        ),
        after_call=after_call,
    ).text()
    conversation.chain(
        json.dumps(
            {"tool_calls": [{"name": "Memory_get", "arguments": {"key": "hello"}}]}
        ),
        after_call=after_call,
    ).text()
    assert accumulated == [
        ("Memory_set", {"key": "hello", "value": "world"}, "null"),
        ("Memory_get", {"key": "hello"}, "world"),
    ]
    assert memory._memory == {"hello": "world"}

    # And for the Filesystem with state
    my_dir = pathlib.Path(tmpdir / "mine")
    my_dir.mkdir()
    (my_dir / "doc.txt").write_text("hi", "utf-8")
    conversation = model.conversation(tools=[Filesystem(my_dir)])
    accumulated.clear()
    conversation.chain(
        json.dumps(
            {
                "tool_calls": [
                    {
                        "name": "Filesystem_list_files",
                    }
                ]
            }
        ),
        after_call=after_call,
    ).text()
    assert accumulated == [
        ("Filesystem_list_files", {}, json.dumps([str(my_dir / "doc.txt")]))
    ]

    # Now register them with a plugin and use it through the CLI

    class ToolboxPlugin:
        __name__ = "ToolboxPlugin"

        @hookimpl
        def register_tools(self, register):
            register(Memory)
            register(Filesystem)

    try:
        plugins.pm.register(ToolboxPlugin(), name="ToolboxPlugin")
        tools = llm.get_tools()
        assert tools["Memory"] is Memory

        runner = CliRunner()
        # llm tools --json
        result = runner.invoke(cli.cli, ["tools", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == {
            "tools": [],
            "toolboxes": [
                {
                    "name": "Memory",
                    "tools": [
                        {
                            "name": "append",
                            "description": "Append something as a key",
                            "arguments": {
                                "properties": {
                                    "key": {"type": "string"},
                                    "value": {"type": "string"},
                                },
                                "required": ["key", "value"],
                                "type": "object",
                            },
                        },
                        {
                            "name": "get",
                            "description": "Get something from a key",
                            "arguments": {
                                "properties": {"key": {"type": "string"}},
                                "required": ["key"],
                                "type": "object",
                            },
                        },
                        {
                            "name": "keys",
                            "description": "Return a list of keys",
                            "arguments": {"properties": {}, "type": "object"},
                        },
                        {
                            "name": "set",
                            "description": "Set something as a key",
                            "arguments": {
                                "properties": {
                                    "key": {"type": "string"},
                                    "value": {"type": "string"},
                                },
                                "required": ["key", "value"],
                                "type": "object",
                            },
                        },
                    ],
                },
                {
                    "name": "Filesystem",
                    "tools": [
                        {
                            "name": "list_files",
                            "description": None,
                            "arguments": {"properties": {}, "type": "object"},
                        }
                    ],
                },
            ],
        }

        # llm tools (no JSON)
        result = runner.invoke(cli.cli, ["tools"])
        assert result.exit_code == 0
        assert result.output == (
            "Memory:\n\n"
            "  append(key: str, value: str)\n\n"
            "    Append something as a key\n\n"
            "  get(key: str)\n\n"
            "    Get something from a key\n\n"
            "  keys()\n\n"
            "    Return a list of keys\n\n"
            "  set(key: str, value: str)\n\n"
            "    Set something as a key\n\n"
            "Filesystem:\n\n"
            "  list_files()\n\n"
        )

        # Test the CLI running a toolbox prompt
        result3 = runner.invoke(
            cli.cli,
            [
                "prompt",
                "-T",
                "Memory",
                json.dumps(
                    {
                        "tool_calls": [
                            {
                                "name": "Memory_set",
                                "arguments": {"key": "hi", "value": "two"},
                            },
                            {"name": "Memory_get", "arguments": {"key": "hi"}},
                        ]
                    }
                ),
                "-m",
                "echo",
            ],
        )
        assert result3.exit_code == 0
        tool_results = json.loads(
            "[" + result3.output.split('"tool_results": [')[1].split("]")[0] + "]"
        )
        assert tool_results == [
            {"name": "Memory_set", "output": "null", "tool_call_id": None},
            {"name": "Memory_get", "output": "two", "tool_call_id": None},
        ]

        # Test the CLI running a configured toolbox prompt
        my_dir2 = pathlib.Path(tmpdir / "mine2")
        my_dir2.mkdir()
        other_path = my_dir2 / "other.txt"
        other_path.write_text("hi", "utf-8")
        result4 = runner.invoke(
            cli.cli,
            [
                "prompt",
                "-T",
                'Filesystem("{}")'.format(my_dir2),
                json.dumps({"tool_calls": [{"name": "Filesystem_list_files"}]}),
                "-m",
                "echo",
            ],
        )
        assert result4.exit_code == 0
        tool_results = json.loads(
            "[" + result4.output.split('"tool_results": [')[1].rsplit("]", 1)[0] + "]"
        )
        assert tool_results == [
            {
                "name": "Filesystem_list_files",
                "output": json.dumps([str(other_path)]),
                "tool_call_id": None,
            }
        ]

    finally:
        plugins.pm.unregister(name="ToolboxPlugin")


def test_plugins_command():
    runner = CliRunner()
    result = runner.invoke(cli.cli, ["plugins"])
    assert result.exit_code == 0
    expected = [
        {"name": "EchoModelPlugin", "hooks": ["register_models"]},
        {
            "name": "MockModelsPlugin",
            "hooks": ["register_embedding_models", "register_models"],
        },
    ]
    actual = json.loads(result.output)
    actual.sort(key=lambda p: p["name"])
    assert actual == expected
    # Test the --hook option
    result2 = runner.invoke(cli.cli, ["plugins", "--hook", "register_embedding_models"])
    assert result2.exit_code == 0
    assert json.loads(result2.output) == [
        {
            "name": "MockModelsPlugin",
            "hooks": ["register_embedding_models", "register_models"],
        },
    ]
