#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.10"
# dependencies = ["pygments"]
# ///
"""
mdstream — Streaming Markdown Renderer

A pipe-through tool for real-time markdown rendering in the terminal.

Design:
    Tokens stream to the terminal as they arrive (byte-by-byte feel).
    When a newline completes a line, the raw text is erased and replaced
    with a fully rendered version (syntax highlighting, heading styles,
    inline formatting). This gives instant streaming UX with rendered
    final output — the best of both worlds.

    History lines (above the cursor) are frozen and fully rendered.
    The current line (at the cursor) streams raw tokens live.

Usage:
    llm "prompt" | mdstream          # standalone pipe
    llm "prompt" --color mdstream    # integrated via llm CLI
    cat README.md | mdstream         # render any markdown

Environment:
    MDSTREAM_PADDING  Left padding in spaces (default: 4)
"""

import os
import re
import sys

from pygments import highlight as _pygments_highlight
from pygments.formatters import TerminalTrueColorFormatter
from pygments.lexers import TextLexer, get_lexer_by_name

# ── ANSI escape codes ────────────────────────────────────────────────────────
# Standard SGR attributes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"
STRIKETHROUGH = "\033[9m"

# Standard 4-bit colors (used for inline formatting)
BRIGHT_BLUE = "\033[94m"
BRIGHT_CYAN = "\033[96m"

# Dark gray background for inline code spans
BG_CODE = "\033[48;5;236m"

# ── Language colors for code fence labels ────────────────────────────────────
# Each language gets an iconic color. Unlisted languages fall back to dim white.
_LANG_COLORS = {
    "rust":       "\033[38;2;255;140;60m",   # orange (Rust logo)
    "c":          "\033[38;2;100;160;255m",  # blue-gray
    "cpp":        "\033[38;2;100;160;255m",  # blue-gray (same family as C)
    "python":     "\033[38;2;80;180;255m",   # sky blue
    "py":         "\033[38;2;80;180;255m",   # alias
    "javascript": "\033[38;2;255;220;60m",   # yellow (JS logo)
    "js":         "\033[38;2;255;220;60m",   # alias
    "typescript": "\033[38;2;50;150;255m",   # blue (TS logo)
    "ts":         "\033[38;2;50;150;255m",   # alias
    "ruby":       "\033[38;2;220;60;60m",    # red (Ruby logo)
    "go":         "\033[38;2;0;173;216m",    # cyan (Go gopher)
    "java":       "\033[38;2;240;130;50m",   # warm orange
    "swift":      "\033[38;2;255;100;50m",   # orange-red (Swift logo)
    "kotlin":     "\033[38;2;180;100;255m",  # purple (Kotlin logo)
    "html":       "\033[38;2;255;100;50m",   # orange (HTML5)
    "css":        "\033[38;2;50;130;255m",   # blue (CSS3)
    "sql":        "\033[38;2;200;200;100m",  # muted yellow
    "bash":       "\033[38;2;190;150;80m",   # warm brown
    "sh":         "\033[38;2;190;150;80m",   # alias
    "shell":      "\033[38;2;190;150;80m",   # alias
    "fish":       "\033[38;2;190;150;80m",   # alias
    "zsh":        "\033[38;2;100;200;100m",  # alias
    "json":       "\033[38;2;180;180;180m",  # light gray
    "yaml":       "\033[38;2;180;180;180m",  # light gray
    "toml":       "\033[38;2;180;180;180m",  # light gray
    "markdown":   "\033[38;2;180;180;180m",  # light gray
    "md":         "\033[38;2;180;180;180m",  # alias
    "lua":        "\033[38;2;50;50;200m",    # deep blue (Lua logo)
    "php":        "\033[38;2;120;120;200m",  # lavender (PHP logo)
    "r":          "\033[38;2;40;100;200m",   # blue (R logo)
    "elixir":     "\033[38;2;120;80;160m",   # purple (Elixir logo)
    "haskell":    "\033[38;2;120;100;160m",  # muted purple
    "zig":        "\033[38;2;255;180;50m",   # amber (Zig logo)
    "nim":        "\033[38;2;255;220;80m",   # golden
    "dart":       "\033[38;2;0;180;220m",    # teal (Dart logo)
    "scala":      "\033[38;2;200;50;50m",    # red (Scala logo)
}

# ── Heading color palette ────────────────────────────────────────────────────
# Rainbow gradient with decreasing luminance per level.
# 24-bit true color: \033[38;2;R;G;Bm
_H_COLORS = [
    "\033[38;2;255;100;100m",  # H1: vivid red-pink
    "\033[38;2;255;170;80m",   # H2: warm orange
    "\033[38;2;100;220;100m",  # H3: fresh green
    "\033[38;2;100;180;255m",  # H4: sky blue
    "\033[38;2;180;140;255m",  # H5: soft violet
    "\033[38;2;200;120;180m",  # H6: muted rose
]

# Heading text styles (all bold, color varies by level)
HEADING_STYLES = [f"{BOLD}{c}" for c in _H_COLORS]

# ── Pygments syntax highlighting ─────────────────────────────────────────────
# Monokai theme with 24-bit true color output for code blocks.
_formatter = TerminalTrueColorFormatter(style="monokai")
_lexer_cache: dict[str, object] = {}


def _get_lexer(lang: str):
    """Get a cached Pygments lexer by language name. Falls back to plain text."""
    if lang not in _lexer_cache:
        try:
            _lexer_cache[lang] = get_lexer_by_name(lang)
        except Exception:
            _lexer_cache[lang] = TextLexer()
    return _lexer_cache[lang]


# ── Inline markdown formatting ───────────────────────────────────────────────
# Regex rules applied in order to format inline markdown elements.
# Each rule: (compiled_pattern, ANSI replacement string)
_INLINE_RULES = [
    (re.compile(r"\*\*\*(.*?)\*\*\*"), f"{BOLD}{ITALIC}\\1{RESET}"),
    (re.compile(r"\*\*(.*?)\*\*"), f"{BOLD}\\1{RESET}"),
    (re.compile(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)"), f"{ITALIC}\\1{RESET}"),
    (re.compile(r"~~(.*?)~~"), f"{STRIKETHROUGH}\\1{RESET}"),
    (re.compile(r"`([^`]+)`"), f"{BG_CODE}{BRIGHT_CYAN}\\1{RESET}"),
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), f"{UNDERLINE}{BRIGHT_BLUE}\\1{RESET}"),
]


def _format_inline(text: str) -> str:
    """Apply inline markdown formatting (bold, italic, code, links, etc.)."""
    for pattern, replacement in _INLINE_RULES:
        text = pattern.sub(replacement, text)
    return text


# ── Streaming renderer ───────────────────────────────────────────────────────


class StreamingMarkdownRenderer:
    """
    Line-oriented streaming markdown renderer.

    Maintains state for code blocks (language, accumulated lines for
    context-aware syntax highlighting). Renders each completed line
    independently with full markdown formatting.
    """

    def __init__(self, padding: int = None):
        self.in_code_block = False
        self.code_lang = ""
        self.code_lines = []    # accumulated code lines for highlighting context
        self.code_line_num = 0  # current line number within code block
        self.partial = ""       # current incomplete line displayed raw on screen
        if padding is None:
            padding = int(os.environ.get("MDSTREAM_PADDING", "4"))
        self.pad = " " * padding
        # Line numbers in code blocks: enabled by default, disable with MDSTREAM_NO_LINENO=1
        self.show_lineno = not os.environ.get("MDSTREAM_NO_LINENO")

    def render_line(self, line: str) -> str:
        """
        Render a single completed line with full markdown formatting.

        Returns the ANSI-formatted string including trailing newline.
        Handles: code fences, code content, headings (H1-H6), horizontal
        rules, blockquotes, ordered/unordered lists, and inline formatting.
        """
        stripped = line.rstrip("\n")
        p = self.pad

        # ── Code fences (``` or ~~~) ─────────────────────────────────────
        fence_match = re.match(r"^(\s*)(```+|~~~+)(.*)", stripped)
        if fence_match:
            if not self.in_code_block:
                # Opening fence: extract language, show labeled separator
                self.code_lang = (
                    fence_match.group(3).strip().split()[0]
                    if fence_match.group(3).strip()
                    else ""
                )
                self.in_code_block = True
                self.code_lines = []
                self.code_line_num = 0
                if self.code_lang:
                    lang_color = _LANG_COLORS.get(self.code_lang.lower(), DIM)
                    label = f"{RESET} {lang_color}{BOLD}{self.code_lang}{RESET} "
                    return f"{p}{DIM}{'─' * 2}{label}{DIM}{'─' * max(1, 38 - len(self.code_lang) - 2)}{RESET}\n"
                else:
                    return f"{p}{DIM}{'─' * 40}{RESET}\n"
            else:
                # Closing fence: reset state, show closing separator
                self.in_code_block = False
                self.code_lang = ""
                self.code_lines = []
                return f"{p}{DIM}{'─' * 40}{RESET}\n"

        # ── Code block content ───────────────────────────────────────────
        # Accumulate all lines and re-highlight from the start so that
        # multi-line constructs (strings, comments) get correct coloring.
        # Only the last highlighted line is emitted (previous lines are
        # already frozen on screen).
        if self.in_code_block:
            self.code_lines.append(stripped)
            self.code_line_num += 1
            full_code = "\n".join(self.code_lines) + "\n"
            lexer = _get_lexer(self.code_lang)
            hl_full = _pygments_highlight(full_code, lexer, _formatter).rstrip("\n")
            hl_last = hl_full.rsplit("\n", 1)[-1]
            if self.show_lineno:
                ln = f"{DIM}{self.code_line_num:>3}  {RESET}"
                return f"{p}{ln}{hl_last}\n"
            return f"{p}  {hl_last}\n"

        # ── Headings ─────────────────────────────────────────────────────
        # Strip # markers, render as bold+color. H1 gets a solid underline
        # (━━━), H2 gets a dim dashed underline (───). H3+ are text only.
        heading_match = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            text = heading_match.group(2).rstrip("#").rstrip()
            style = HEADING_STYLES[min(level - 1, len(HEADING_STYLES) - 1)]
            color = _H_COLORS[min(level - 1, len(_H_COLORS) - 1)]
            heading = f"\n{p}{style}{text}{RESET}\n"
            if level == 1:
                return heading + f"{p}{color}{'━' * len(text)}{RESET}\n"
            if level == 2:
                return heading + f"{p}{DIM}{color}{'─' * len(text)}{RESET}\n"
            return heading

        # ── Horizontal rule (---, ***, ___) ──────────────────────────────
        if re.match(r"^(\s*[-*_]\s*){3,}$", stripped):
            return f"{p}{DIM}{'─' * 40}{RESET}\n"

        # ── Blockquote (> text) ──────────────────────────────────────────
        if stripped.startswith("> "):
            return f"{p}  {DIM}│{RESET} {_format_inline(stripped[2:])}\n"
        if stripped == ">":
            return f"{p}  {DIM}│{RESET}\n"

        # ── Unordered list (-, *, +) ─────────────────────────────────────
        list_match = re.match(r"^(\s*)([-*+])\s+(.*)", stripped)
        if list_match:
            indent = list_match.group(1)
            return f"{p}{indent}  • {_format_inline(list_match.group(3))}\n"

        # ── Ordered list (1. 2. 3.) ──────────────────────────────────────
        ol_match = re.match(r"^(\s*)(\d+)\.\s+(.*)", stripped)
        if ol_match:
            indent = ol_match.group(1)
            num = ol_match.group(2)
            return f"{p}{indent}  {DIM}{num}.{RESET} {_format_inline(ol_match.group(3))}\n"

        # ── Regular paragraph text ───────────────────────────────────────
        if stripped:
            return f"{p}{_format_inline(stripped)}\n"

        # ── Blank line ───────────────────────────────────────────────────
        return "\n"

    # ── Terminal helpers ──────────────────────────────────────────────────

    def _term_width(self):
        """Get current terminal width, defaulting to 80 if unavailable."""
        try:
            return os.get_terminal_size().columns
        except OSError:
            return 80

    def _erase_partial(self, out):
        """
        Erase the raw partial line from the terminal.

        If the partial line was long enough to wrap across multiple
        terminal rows, we move the cursor up and clear from there.
        For single-row lines, a simple \\r\\033[K suffices.
        """
        if not self.partial:
            return
        display_len = len(self.partial) + len(self.pad)
        w = self._term_width()
        rows = max(1, -(-display_len // w))  # ceil division
        if rows <= 1:
            out.write("\r\033[K")
        else:
            out.write(f"\033[{rows - 1}A\r\033[J")

    # ── Main streaming loop ──────────────────────────────────────────────

    def run(self):
        """
        Read from stdin and render markdown in real-time.

        Tokens are echoed raw as they arrive (live partial line).
        When a newline completes a line, the raw text is erased and
        replaced with the fully rendered version. This gives token-speed
        streaming UX with fully formatted final output.
        """
        out = sys.stdout
        buf = b""
        p = self.pad

        # Breathing room between shell prompt and rendered output
        out.write("\n")
        out.flush()

        while True:
            try:
                chunk = os.read(0, 4096)
            except OSError:
                break
            if not chunk:
                break

            buf += chunk
            # Decode UTF-8, keeping incomplete multi-byte sequences for next read
            try:
                text = buf.decode("utf-8")
                buf = b""
            except UnicodeDecodeError:
                try:
                    text = buf[:-1].decode("utf-8")
                    buf = buf[-1:]
                except UnicodeDecodeError:
                    continue

            parts = text.split("\n")

            if len(parts) == 1:
                # No newline — append token to live partial line
                if not self.partial:
                    out.write(p)
                self.partial += parts[0]
                out.write(parts[0])
                out.flush()
                continue

            # Newline arrived — complete the partial line and render it
            first_complete = self.partial + parts[0]
            self._erase_partial(out)
            self.partial = ""
            out.write(self.render_line(first_complete + "\n"))

            # Render any additional complete lines in this chunk
            for part in parts[1:-1]:
                out.write(self.render_line(part + "\n"))

            # Start new partial line with any trailing content
            self.partial = parts[-1]
            if self.partial:
                out.write(p)
                out.write(self.partial)

            out.flush()

        # Render any remaining partial at EOF
        if self.partial:
            self._erase_partial(out)
            out.write(self.render_line(self.partial + "\n"))
            out.flush()


# ── CLI entry point ──────────────────────────────────────────────────────────


def main():
    if sys.stdin.isatty():
        print("mdstream — Streaming Markdown Renderer", file=sys.stderr)
        print("", file=sys.stderr)
        print("  Real-time token streaming with rendered markdown output.", file=sys.stderr)
        print("  Partial lines stream raw; completed lines render fully.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Usage:", file=sys.stderr)
        print('  llm "prompt" | mdstream', file=sys.stderr)
        print('  llm "prompt" --color mdstream', file=sys.stderr)
        print("  cat README.md | mdstream", file=sys.stderr)
        print("", file=sys.stderr)
        print("Environment:", file=sys.stderr)
        print("  MDSTREAM_PADDING  Left padding in spaces (default: 4)", file=sys.stderr)
        sys.exit(1)

    renderer = StreamingMarkdownRenderer()
    try:
        renderer.run()
    except (KeyboardInterrupt, BrokenPipeError):
        pass


if __name__ == "__main__":
    main()
