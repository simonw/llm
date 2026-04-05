import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from llm import cli, Attachment
from llm.clipboard import (
    ClipboardError,
    resolve_clipboard,
    get_clipboard_image,
    get_clipboard_text,
)

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\xa6\x00\x00\x01\x1a"
    b"\x02\x03\x00\x00\x00\xe6\x99\xc4^\x00\x00\x00\tPLTE\xff\xff\xff"
    b"\x00\xff\x00\xfe\x01\x00\x12t\x01J\x00\x00\x00GIDATx\xda\xed\xd81\x11"
    b"\x000\x08\xc0\xc0.]\xea\xaf&Q\x89\x04V\xe0>\xf3+\xc8\x91Z\xf4\xa2\x08EQ\x14E"
    b"Q\x14EQ\x14EQ\xd4B\x91$I3\xbb\xbf\x08EQ\x14EQ\x14EQ\x14E\xd1\xa5"
    b"\xd4\x17\x91\xc6\x95\x05\x15\x0f\x9f\xc5\t\x9f\xa4\x00\x00\x00\x00IEND\xaeB`"
    b"\x82"
)


class TestResolveClipboard:
    """Tests for the resolve_clipboard function."""

    def test_resolve_clipboard_with_image(self):
        """Test that clipboard with image returns an Attachment."""
        with patch("llm.clipboard.get_clipboard_image") as mock_get_image:
            mock_get_image.return_value = TINY_PNG

            result = resolve_clipboard()

            assert isinstance(result, Attachment)
            assert result.content == TINY_PNG
            assert result.type == "image/png"
            assert result.path is None
            assert result.url is None

    def test_resolve_clipboard_with_text(self):
        """Test that clipboard with text (no image) returns a string."""
        with patch("llm.clipboard.get_clipboard_image") as mock_get_image:
            with patch("llm.clipboard.get_clipboard_text") as mock_get_text:
                mock_get_image.return_value = None
                mock_get_text.return_value = "Hello from clipboard"

                result = resolve_clipboard()

                assert isinstance(result, str)
                assert result == "Hello from clipboard"

    def test_resolve_clipboard_empty(self):
        """Test that empty clipboard raises ClipboardError."""
        with patch("llm.clipboard.get_clipboard_image") as mock_get_image:
            with patch("llm.clipboard.get_clipboard_text") as mock_get_text:
                mock_get_image.return_value = None
                mock_get_text.return_value = None

                with pytest.raises(ClipboardError) as exc_info:
                    resolve_clipboard()

                assert "Clipboard is empty" in str(exc_info.value)

    def test_resolve_clipboard_image_priority(self):
        """Test that image takes priority over text."""
        with patch("llm.clipboard.get_clipboard_image") as mock_get_image:
            with patch("llm.clipboard.get_clipboard_text") as mock_get_text:
                mock_get_image.return_value = TINY_PNG
                mock_get_text.return_value = "Some text"

                result = resolve_clipboard()

                # Should get the image, not the text
                assert isinstance(result, Attachment)
                mock_get_text.assert_not_called()


class TestClipboardCLI:
    """Tests for clipboard CLI integration."""

    def test_prompt_with_clipboard_image(self, mock_model):
        """Test the --clipboard flag with an image in clipboard."""
        runner = CliRunner()
        mock_model.enqueue(["I see an image"])

        with patch("llm.cli.resolve_clipboard") as mock_resolve:
            mock_resolve.return_value = Attachment(
                type="image/png",
                path=None,
                url=None,
                content=TINY_PNG,
            )

            result = runner.invoke(
                cli.cli,
                ["prompt", "-m", "mock", "describe this", "--clipboard"],
                catch_exceptions=False,
            )

            assert result.exit_code == 0, result.output
            assert "I see an image" in result.output
            # Verify the attachment was passed to the model
            assert len(mock_model.history[0][0].attachments) == 1
            assert mock_model.history[0][0].attachments[0].type == "image/png"

    def test_prompt_with_clipboard_text(self, mock_model):
        """Test the --clipboard flag with text in clipboard."""
        runner = CliRunner()
        mock_model.enqueue(["Summarized content"])

        with patch("llm.cli.resolve_clipboard") as mock_resolve:
            mock_resolve.return_value = "This is clipboard text content"

            result = runner.invoke(
                cli.cli,
                ["prompt", "-m", "mock", "summarize", "-C"],
                catch_exceptions=False,
            )

            assert result.exit_code == 0, result.output
            assert "Summarized content" in result.output
            # Verify the clipboard text was prepended to the prompt
            prompt_text = mock_model.history[0][0].prompt
            assert "This is clipboard text content" in prompt_text
            assert "summarize" in prompt_text

    def test_prompt_with_clipboard_empty(self):
        """Test the --clipboard flag with empty clipboard."""
        runner = CliRunner()

        with patch("llm.cli.resolve_clipboard") as mock_resolve:
            mock_resolve.side_effect = ClipboardError("Clipboard is empty")

            result = runner.invoke(
                cli.cli,
                ["prompt", "-m", "mock", "describe", "--clipboard"],
            )

            assert result.exit_code != 0
            assert "Clipboard is empty" in result.output

    def test_prompt_clipboard_with_other_attachments(self, mock_model, tmp_path):
        """Test combining --clipboard with -a attachments."""
        runner = CliRunner()
        mock_model.enqueue(["Multiple attachments processed"])

        # Create a test file with different content than clipboard
        test_file = tmp_path / "test.png"
        # Use a different PNG to avoid duplicate attachment hash
        different_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc"
            b"\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        test_file.write_bytes(different_png)

        with patch("llm.cli.resolve_clipboard") as mock_resolve:
            mock_resolve.return_value = Attachment(
                type="image/png",
                path=None,
                url=None,
                content=TINY_PNG,
            )

            result = runner.invoke(
                cli.cli,
                [
                    "prompt",
                    "-m",
                    "mock",
                    "compare images",
                    "-a",
                    str(test_file),
                    "--clipboard",
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 0, result.output
            # Should have 2 attachments: one from -a and one from clipboard
            assert len(mock_model.history[0][0].attachments) == 2

    def test_prompt_short_flag(self, mock_model):
        """Test the -C short flag for clipboard."""
        runner = CliRunner()
        mock_model.enqueue(["Response"])

        with patch("llm.cli.resolve_clipboard") as mock_resolve:
            mock_resolve.return_value = "Text from clipboard"

            result = runner.invoke(
                cli.cli,
                ["prompt", "-m", "mock", "process", "-C"],
                catch_exceptions=False,
            )

            assert result.exit_code == 0


class TestClipboardTextFallback:
    def test_text_prepended_to_prompt(self, mock_model):
        runner = CliRunner()
        mock_model.enqueue(["OK"])

        with patch("llm.cli.resolve_clipboard") as mock_resolve:
            mock_resolve.return_value = "Clipboard content here"

            result = runner.invoke(
                cli.cli,
                ["prompt", "-m", "mock", "User question", "--clipboard"],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            prompt_text = mock_model.history[0][0].prompt
            # Clipboard text should come before user's question
            clipboard_pos = prompt_text.find("Clipboard content here")
            question_pos = prompt_text.find("User question")
            assert clipboard_pos < question_pos

    def test_text_only_no_user_prompt(self, mock_model):
        runner = CliRunner()
        mock_model.enqueue(["Response"])

        with patch("llm.cli.resolve_clipboard") as mock_resolve:
            mock_resolve.return_value = "Just clipboard text"

            result = runner.invoke(
                cli.cli,
                ["prompt", "-m", "mock", "--clipboard"],
                input="",  # No stdin
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            prompt_text = mock_model.history[0][0].prompt
            assert prompt_text == "Just clipboard text"
