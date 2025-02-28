import json
import pytest
from click.testing import CliRunner
from llm.cli import cli


def test_embed_score_with_content():
    """Test the embed-score command with content parameters"""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "embed-score",
            "-c1",
            "This is text one",
            "-c2",
            "This is text seven",
            "-m",
            "embed-demo",
        ],
    )
    assert result.exit_code == 0
    assert float(result.output.strip()) == pytest.approx(0.9734171683335759)

    # Test with JSON output format
    result = runner.invoke(
        cli,
        [
            "embed-score",
            "-c1",
            "This is text one",
            "-c2",
            "This is text seven",
            "-f",
            "json",
            "-m",
            "embed-demo",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.output.strip()) == {
        "score": pytest.approx(0.9734171683335759),
        "content1": [4, 2, 4, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "content2": [4, 2, 4, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    }


def test_embed_score_with_files(tmp_path):
    """Test the embed-score command with file inputs"""
    # Create temporary test files
    file1 = tmp_path / "file1.txt"
    file2 = tmp_path / "file2.txt"
    file1.write_text("This is text one")
    file2.write_text("This is text seven")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["embed-score", "-i1", str(file1), "-i2", str(file2), "-m", "embed-demo"],
    )
    assert result.exit_code == 0
    assert float(result.output.strip()) == pytest.approx(0.9734171683335759)


def test_embed_score_binary_input(tmp_path):
    """Test the embed-score command with binary inputs"""
    # Create temporary binary files
    file1 = tmp_path / "file1.bin"
    file2 = tmp_path / "file2.bin"
    file1.write_bytes(b"\x00\x01\x02")
    file2.write_bytes(b"\x03\x04\x05")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "embed-score",
            "-i1",
            str(file1),
            "-i2",
            str(file2),
            "-m",
            "embed-demo",
            "--binary",
        ],
    )
    assert result.exit_code == 0
    assert float(result.output.strip()) == pytest.approx(1.0)


def test_embed_score_missing_inputs():
    """Test the embed-score command with missing inputs"""
    runner = CliRunner()

    # Missing first input
    result = runner.invoke(
        cli, ["embed-score", "-c2", "This is text two", "-m", "embed-demo"]
    )
    assert result.exit_code != 0
    assert "No content provided for first input" in result.output

    # Missing second input
    result = runner.invoke(
        cli, ["embed-score", "-c1", "This is text one", "-m", "embed-demo"]
    )
    assert result.exit_code != 0
    assert "No content provided for second input" in result.output
