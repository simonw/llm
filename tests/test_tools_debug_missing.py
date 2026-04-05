"""Test for issue #1151: No tool debug output when tool doesn't exist"""
import json
import textwrap
from click.testing import CliRunner
import llm
import llm.cli
from llm.plugins import pm


def test_chat_tools_debug_output_when_tool_missing(logs_db):
    """Test that --td flag produces debug output when model calls a non-existent tool.
    
    This is a regression test for https://github.com/simonw/llm/issues/1151
    When a model tries to call a tool that doesn't exist, the --td flag should
    still show the attempted tool call and the error.
    """
    runner = CliRunner()
    
    # Define a tool function
    functions = textwrap.dedent(
        """
    def upper(text: str) -> str:
        "Convert text to upper case"
        return text.upper()                         
    """
    )
    
    # Run chat with --td (tools debug) flag
    # The model will try to call "nonexistent_tool" which is not registered
    result = runner.invoke(
        llm.cli.cli,
        ["chat", "-m", "echo", "--functions", functions, "--td"],
        input="\n".join([
            json.dumps({
                "prompt": "Test",
                "tool_calls": [{"name": "nonexistent_tool", "arguments": {"text": "hello"}}]
            }),
            "quit",
        ]),
        catch_exceptions=False,
    )
    
    assert result.exit_code == 0
    # The debug output should show the attempted tool call even though it doesn't exist
    assert "Tool call: nonexistent_tool" in result.output
    assert "does not exist" in result.output


def test_prompt_tools_debug_output_when_tool_missing():
    """Test that --td flag produces debug output when model calls a non-existent tool via prompt."""
    runner = CliRunner()
    
    functions = textwrap.dedent(
        """
    def upper(text: str) -> str:
        "Convert text to upper case"
        return text.upper()                         
    """
    )
    
    result = runner.invoke(
        llm.cli.cli,
        [
            "prompt",
            "-m", "echo",
            "--functions", functions,
            "--td",
            json.dumps({
                "prompt": "Test",
                "tool_calls": [{"name": "nonexistent_tool", "arguments": {"text": "hello"}}]
            }),
        ],
        catch_exceptions=False,
    )
    
    assert result.exit_code == 0
    assert "Tool call: nonexistent_tool" in result.output
    assert "does not exist" in result.output
