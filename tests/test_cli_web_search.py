import json
from click.testing import CliRunner
from llm import cli
from unittest.mock import MagicMock, patch

def test_cli_web_search_tool():
    runner = CliRunner()
    
    with patch("duckduckgo_search.DDGS") as mock_ddgs_cls:
        mock_ddgs = MagicMock()
        mock_ddgs_cls.return_value.__enter__.return_value = mock_ddgs
        
        mock_ddgs.text.return_value = [
            {"title": "CLI Result", "href": "http://cli.example.com", "body": "CLI Summary"}
        ]

        # simulate the tool call
        result = runner.invoke(
            cli.cli,
            [
                "-m",
                "echo",
                "-T",
                "web_search",
                json.dumps({"tool_calls": [{"name": "web_search", "arguments": {"query": "test cli"}}]}),
            ],
        )
        
        assert result.exit_code == 0
        assert "Title: CLI Result" in result.output
        assert "URL: http://cli.example.com" in result.output
