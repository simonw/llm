import pytest
from unittest.mock import MagicMock, patch
import sys

# We need to make sure we import web_search. 
# It is in llm.tools, but if we mock sys.modules for ImportError test, 
# we need to be careful not to break other things.

from llm.tools import web_search

def test_web_search_success():
    with patch("duckduckgo_search.DDGS") as mock_ddgs_cls:
        mock_ddgs = MagicMock()
        mock_ddgs_cls.return_value.__enter__.return_value = mock_ddgs
        
        mock_ddgs.text.return_value = [
            {"title": "Result 1", "href": "http://example.com/1", "body": "Summary 1"},
            {"title": "Result 2", "href": "http://example.com/2", "body": "Summary 2"}
        ]
        
        result = web_search("test query")
        
        assert "Title: Result 1" in result
        assert "URL: http://example.com/1" in result
        assert "Summary: Summary 1" in result
        assert "Title: Result 2" in result
        
        mock_ddgs.text.assert_called_with("test query", max_results=5)

def test_web_search_import_error():
    # Simulate ImportError by removing duckduckgo_search from sys.modules
    # and preventing it from being imported
    with patch.dict(sys.modules, {"duckduckgo_search": None}):
        result = web_search("test query")
        assert "Error: duckduckgo-search module is not installed" in result

def test_web_search_exception():
    with patch("duckduckgo_search.DDGS") as mock_ddgs_cls:
        mock_ddgs = MagicMock()
        mock_ddgs_cls.return_value.__enter__.return_value = mock_ddgs
        mock_ddgs.text.side_effect = Exception("Search failed")
        
        result = web_search("test query")
        assert "Error performing search: Search failed" in result
