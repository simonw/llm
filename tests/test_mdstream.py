from io import StringIO
import re

import llm.cli

from tools.mdstream import StreamingMarkdownRenderer

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\r", "")


class FakeStreamTerminal:
    """
    Minimal terminal emulator for mdstream streaming tests.

    It understands the single-line erase sequence used for partial-line
    streaming (`\\r\\033[K`) and ignores style ANSI escapes. That is enough
    to assert the final visible text for non-table streaming behavior.
    """

    def __init__(self):
        self.lines = []
        self.current = ""

    def write(self, text):
        i = 0
        while i < len(text):
            if text.startswith("\r\033[K", i):
                self.current = ""
                i += 4
                continue
            char = text[i]
            if char == "\n":
                self.lines.append(self.current)
                self.current = ""
            elif char == "\r":
                self.current = ""
            elif char == "\033":
                match = ANSI_RE.match(text, i)
                if match:
                    i = match.end()
                    continue
                i += 1
                continue
            else:
                self.current += char
            i += 1

    def flush(self):
        pass

    def rendered(self):
        if self.current:
            return "\n".join([*self.lines, self.current])
        return "\n".join(self.lines)


def test_task_lists_images_links_and_escaping():
    renderer = StreamingMarkdownRenderer(padding=0)

    checked = strip_ansi(renderer.render_line("- [x] done\n"))
    unchecked = strip_ansi(renderer.render_line("- [ ] todo\n"))
    image = strip_ansi(renderer.render_line("![Alt](https://example.com/image.png)\n"))
    link = strip_ansi(renderer.render_line("[OpenAI](https://openai.com)\n"))
    escaped = strip_ansi(
        renderer.render_line("\\*not italic\\* and https://example.com\n")
    )

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


def test_nested_unordered_lists_use_depth_specific_bullets():
    renderer = StreamingMarkdownRenderer(padding=0)

    rendered = [
        strip_ansi(renderer.render_line("- one\n")),
        strip_ansi(renderer.render_line("  - two\n")),
        strip_ansi(renderer.render_line("    - three\n")),
        strip_ansi(renderer.render_line("      - four\n")),
    ]

    assert rendered == [
        "  • one\n",
        "  │ ◦ two\n",
        "  │ │ ▪ three\n",
        "  │ │ │ ‣ four\n",
    ]


def test_nested_ordered_lists_render_hierarchical_markers():
    renderer = StreamingMarkdownRenderer(padding=0)

    rendered = [
        strip_ansi(renderer.render_line("1. one\n")),
        strip_ansi(renderer.render_line("  1. two\n")),
        strip_ansi(renderer.render_line("    1. three\n")),
        strip_ansi(renderer.render_line("      2. four\n")),
    ]

    assert rendered == [
        "  1. one\n",
        "  │ 1.1 two\n",
        "  │ │ 1.1.1 three\n",
        "  │ │ │ 1.1.1.2 four\n",
    ]


def test_vertical_list_guides_are_on_by_default_and_opt_out_via_env(monkeypatch):
    monkeypatch.delenv("MDSTREAM_NO_LIST_GUIDES", raising=False)
    default_renderer = StreamingMarkdownRenderer(padding=0)
    default_rendered = "".join(
        strip_ansi(default_renderer.render_line(line))
        for line in [
            "1. launch\n",
            "  1. plan\n",
            "    1. build\n",
        ]
    )

    monkeypatch.setenv("MDSTREAM_NO_LIST_GUIDES", "1")
    opted_out_renderer = StreamingMarkdownRenderer(padding=0)
    opted_out_rendered = "".join(
        strip_ansi(opted_out_renderer.render_line(line))
        for line in [
            "1. launch\n",
            "  1. plan\n",
            "    1. build\n",
        ]
    )

    assert "│" in default_rendered
    assert "│" not in opted_out_rendered


def test_hierarchical_ordered_lists_emphasize_only_last_segment():
    renderer = StreamingMarkdownRenderer(padding=0)

    strip_ansi(renderer.render_line("1. launch\n"))
    strip_ansi(renderer.render_line("  2. plan\n"))
    strip_ansi(renderer.render_line("    1. build\n"))
    rendered = renderer.render_line("      4. verify\n")

    assert strip_ansi(rendered) == "  │ │ │ 1.2.1.4 verify\n"
    assert re.search(r"\x1b\[2m1\.2\.1\x1b\[0m\x1b\[1m\.4\x1b\[0m", rendered)


def test_list_continuation_lines_align_under_item_text():
    renderer = StreamingMarkdownRenderer(padding=0)

    rendered = [
        strip_ansi(renderer.render_line("- one\n")),
        strip_ansi(renderer.render_line("  continuation\n")),
        strip_ansi(renderer.render_line("  still same item\n")),
        strip_ansi(renderer.render_line("- two\n")),
    ]

    assert rendered == [
        "  • one\n",
        "    continuation\n",
        "    still same item\n",
        "  • two\n",
    ]


def test_headings_do_not_add_extra_blank_lines():
    renderer = StreamingMarkdownRenderer(padding=0)

    top_heading = strip_ansi(renderer.render_line("## Basic Formatting\n"))
    explicit_blank = strip_ansi(renderer.render_line("\n"))
    nested_heading = strip_ansi(renderer.render_line("### Text Styles\n"))
    strip_ansi(renderer.render_line("Paragraph\n"))
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


def test_inline_styles_autolinks_code_spans_and_rules():
    renderer = StreamingMarkdownRenderer(padding=0)

    styled = strip_ansi(
        renderer.render_line(
            "***both*** **bold** *italic* ~~gone~~ `code` <https://a.test> https://b.test\n"
        )
    )
    rule = strip_ansi(renderer.render_line("---\n"))

    assert styled == "both bold italic gone code https://a.test https://b.test\n"
    assert rule == "────────────────────────────────────────\n"


def test_headings_h1_h2_and_blockquote_heading_passthrough():
    renderer = StreamingMarkdownRenderer(padding=0)

    h1 = strip_ansi(renderer.render_line("# Title\n"))
    h2 = strip_ansi(renderer.render_line("## Subtitle\n"))
    quoted_heading = strip_ansi(renderer.render_line("> ## not a heading\n"))

    assert h1 == "Title\n━━━━━\n"
    assert h2.startswith("\nSubtitle\n────────\n")
    assert quoted_heading == "  │ ## not a heading\n"


def test_code_fences_render_language_labels_and_line_numbers():
    renderer = StreamingMarkdownRenderer(padding=0)

    start = strip_ansi(renderer.render_line("```python\n"))
    first = strip_ansi(renderer.render_line("print('hello')\n"))
    second = strip_ansi(renderer.render_line("x = 1\n"))
    end = strip_ansi(renderer.render_line("```\n"))

    assert "python" in start
    assert "──" in start
    assert "  1  print('hello')" in first
    assert "  2  x = 1" in second
    assert end == "────────────────────────────────────────\n"


def test_code_fences_can_disable_line_numbers(monkeypatch):
    monkeypatch.setenv("MDSTREAM_NO_LINENO", "1")
    renderer = StreamingMarkdownRenderer(padding=0)

    renderer.render_line("```python\n")
    line = strip_ansi(renderer.render_line("print('hello')\n"))

    assert line == "  print('hello')\n"


def test_write_chunk_and_finish_render_streaming_output():
    renderer = StreamingMarkdownRenderer(padding=0)
    out = FakeStreamTerminal()

    renderer.write_chunk("Hello", out)
    assert renderer.partial == "Hello"
    assert out.rendered() == "Hello"

    renderer.write_chunk(" world\nNext", out)
    assert renderer.partial == "Next"
    assert out.rendered() == "Hello world\nNext"

    renderer.finish(out)
    assert renderer.partial == ""
    assert out.rendered() == "Hello world\nNext"


def test_run_handles_chunked_utf8_and_flushes_final_partial(monkeypatch):
    renderer = StreamingMarkdownRenderer(padding=0)
    out = FakeStreamTerminal()
    chunks = iter([b"caf\xc3", b"\xa9\nna", b"\xc3\xafve", b""])

    monkeypatch.setattr("tools.mdstream.sys.stdout", out)
    monkeypatch.setattr(
        "tools.mdstream.os.read",
        lambda _fd, _size: next(chunks),
    )

    renderer.run()

    assert out.rendered() == "\ncaf\xe9\nna\xefve"


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
