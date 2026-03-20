from io import StringIO
import re

import llm.cli

from tools.mdstream import StreamingMarkdownRenderer


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\r", "")


def test_task_lists_images_links_and_escaping():
    renderer = StreamingMarkdownRenderer(padding=0)

    checked = strip_ansi(renderer.render_line("- [x] done\n"))
    unchecked = strip_ansi(renderer.render_line("- [ ] todo\n"))
    image = strip_ansi(renderer.render_line("![Alt](https://example.com/image.png)\n"))
    link = strip_ansi(renderer.render_line("[OpenAI](https://openai.com)\n"))
    escaped = strip_ansi(renderer.render_line("\\*not italic\\* and https://example.com\n"))

    assert checked == "  ☑ done\n"
    assert unchecked == "  ☐ todo\n"
    assert image == "Image: Alt (https://example.com/image.png)\n"
    assert link == "OpenAI (https://openai.com)\n"
    assert escaped == "*not italic* and https://example.com\n"


def test_nested_blockquotes_and_lists():
    renderer = StreamingMarkdownRenderer(padding=0)

    first = strip_ansi(renderer.render_line("> tip\n"))
    blank = strip_ansi(renderer.render_line(">\n"))
    nested = strip_ansi(renderer.render_line("> - item\n"))
    deep = strip_ansi(renderer.render_line("> > 1. nested\n"))

    assert first == "  │ tip\n"
    assert blank == "  │\n"
    assert nested == "  │   • item\n"
    assert deep == "  │ │   1. nested\n"


def test_headings_do_not_add_extra_blank_lines():
    renderer = StreamingMarkdownRenderer(padding=0)

    top_heading = strip_ansi(renderer.render_line("## Basic Formatting\n"))
    explicit_blank = strip_ansi(renderer.render_line("\n"))
    nested_heading = strip_ansi(renderer.render_line("### Text Styles\n"))
    paragraph = strip_ansi(renderer.render_line("Paragraph\n"))
    following_heading = strip_ansi(renderer.render_line("## Next Section\n"))

    assert not top_heading.startswith("\n")
    assert explicit_blank == "\n"
    assert not nested_heading.startswith("\n")
    assert following_heading.startswith("\n")


def test_table_promotion_alignment_and_repaint():
    renderer = StreamingMarkdownRenderer(padding=0)

    first = renderer.render_line("| Language | Score |\n")
    promoted = renderer.render_line("| :--- | ---: |\n")
    repainted = renderer.render_line("| Python | 10 |\n")
    closed = renderer.render_line("after\n")

    assert strip_ansi(first) == "| Language | Score |\n"
    clean_promoted = strip_ansi(promoted)
    clean_repainted = strip_ansi(repainted)
    assert "\033[1A\r\033[J" in promoted
    assert "\033[2A\r\033[J" in repainted
    assert " Language │ Score " in clean_promoted
    assert "━━━━━━━━━━┿━━━━━━━" in clean_promoted
    assert " Python   │    10 " in clean_repainted
    assert strip_ansi(closed) == "after\n"


def test_color_writer_uses_renderer_repaint(monkeypatch):
    class FakeTTY(StringIO):
        def isatty(self):
            return True

        def flush(self):
            pass

    fake_stdout = FakeTTY()
    monkeypatch.setattr(llm.cli.sys, "stdout", fake_stdout)

    writer = llm.cli._ColorWriter("mdstream")
    writer.renderer._term_width = lambda: 120
    writer.write("| A | B |\n")
    writer.write("| --- | --- |\n")
    writer.write("| x | y |\n")
    writer.finish()

    output = fake_stdout.getvalue()
    assert "\033[1A\r\033[J" in output
    assert "\033[2A\r\033[J" in output
    assert " A │ B " in strip_ansi(output)
    assert " x │ y " in strip_ansi(output)
