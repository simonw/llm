"""
Files that users author by hand - templates, fragments and --functions code - are
decoded as UTF-8, because that is what llm itself writes (see "llm templates
edit") and what most editors produce. Using the locale default encoding instead
breaks on systems where that is not UTF-8, such as Windows with a legacy code
page.
"""

import json
import pathlib

import pytest
from click.testing import CliRunner

from llm.cli import cli


@pytest.fixture
def non_utf8_locale(monkeypatch):
    # Simulate a system whose locale encoding cannot decode UTF-8 bytes - e.g. a
    # Windows machine using a legacy code page. Path.read_text() falls back to
    # that encoding whenever no encoding is passed.
    original_read_text = pathlib.Path.read_text

    def read_text(self, encoding=None, errors=None):
        return original_read_text(self, encoding=encoding or "ascii", errors=errors)

    monkeypatch.setattr(pathlib.Path, "read_text", read_text)


def test_template_file_with_non_ascii_is_read_as_utf8(tmp_path, user_path, non_utf8_locale):
    template_path = tmp_path / "non-ascii.yaml"
    template_path.write_text("prompt: 用一个中文模板测试", "utf-8")
    result = CliRunner().invoke(cli, ["-t", str(template_path), "-m", "echo"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["prompt"] == "用一个中文模板测试"


def test_fragment_file_with_non_ascii_is_read_as_utf8(tmp_path, user_path, non_utf8_locale):
    fragment_path = tmp_path / "fragment.md"
    fragment_path.write_text("这是一个中文片段", "utf-8")
    result = CliRunner().invoke(cli, ["prompt", "-m", "echo", "-f", str(fragment_path)], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["prompt"] == "这是一个中文片段"


def test_functions_file_with_non_ascii_is_read_as_utf8(tmp_path, user_path, non_utf8_locale):
    functions_path = tmp_path / "functions.py"
    functions_path.write_text('def greet(name):\n    "打招呼"\n    return f"你好 {name}"\n', "utf-8")
    result = CliRunner().invoke(cli, ["-m", "echo", "--functions", str(functions_path), "hi"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
