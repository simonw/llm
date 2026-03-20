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

import math
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
BRIGHT_GREEN = "\033[92m"
BRIGHT_MAGENTA = "\033[95m"

# Dark gray background for inline code spans
BG_CODE = "\033[48;5;236m"

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
PLACEHOLDER_PREFIX = "\u0000MDSTREAM"

# ── Language colors for code fence labels ────────────────────────────────────
# Each language gets an iconic color. Unlisted languages fall back to dim white.
_LANG_COLORS = {
    "rust": "\033[38;2;255;140;60m",  # orange (Rust logo)
    "c": "\033[38;2;100;160;255m",  # blue-gray
    "cpp": "\033[38;2;100;160;255m",  # blue-gray (same family as C)
    "python": "\033[38;2;80;180;255m",  # sky blue
    "py": "\033[38;2;80;180;255m",  # alias
    "javascript": "\033[38;2;255;220;60m",  # yellow (JS logo)
    "js": "\033[38;2;255;220;60m",  # alias
    "typescript": "\033[38;2;50;150;255m",  # blue (TS logo)
    "ts": "\033[38;2;50;150;255m",  # alias
    "ruby": "\033[38;2;220;60;60m",  # red (Ruby logo)
    "go": "\033[38;2;0;173;216m",  # cyan (Go gopher)
    "java": "\033[38;2;240;130;50m",  # warm orange
    "swift": "\033[38;2;255;100;50m",  # orange-red (Swift logo)
    "kotlin": "\033[38;2;180;100;255m",  # purple (Kotlin logo)
    "html": "\033[38;2;255;100;50m",  # orange (HTML5)
    "css": "\033[38;2;50;130;255m",  # blue (CSS3)
    "sql": "\033[38;2;200;200;100m",  # muted yellow
    "bash": "\033[38;2;190;150;80m",  # warm brown
    "sh": "\033[38;2;190;150;80m",  # alias
    "shell": "\033[38;2;190;150;80m",  # alias
    "fish": "\033[38;2;190;150;80m",  # alias
    "zsh": "\033[38;2;100;200;100m",  # alias
    "json": "\033[38;2;180;180;180m",  # light gray
    "yaml": "\033[38;2;180;180;180m",  # light gray
    "toml": "\033[38;2;180;180;180m",  # light gray
    "markdown": "\033[38;2;180;180;180m",  # light gray
    "md": "\033[38;2;180;180;180m",  # alias
    "lua": "\033[38;2;50;50;200m",  # deep blue (Lua logo)
    "php": "\033[38;2;120;120;200m",  # lavender (PHP logo)
    "r": "\033[38;2;40;100;200m",  # blue (R logo)
    "elixir": "\033[38;2;120;80;160m",  # purple (Elixir logo)
    "haskell": "\033[38;2;120;100;160m",  # muted purple
    "zig": "\033[38;2;255;180;50m",  # amber (Zig logo)
    "nim": "\033[38;2;255;220;80m",  # golden
    "dart": "\033[38;2;0;180;220m",  # teal (Dart logo)
    "scala": "\033[38;2;200;50;50m",  # red (Scala logo)
}

# ── Heading color palette ────────────────────────────────────────────────────
# Rainbow gradient with decreasing luminance per level.
# 24-bit true color: \033[38;2;R;G;Bm
_H_COLORS = [
    "\033[38;2;255;100;100m",  # H1: vivid red-pink
    "\033[38;2;255;170;80m",  # H2: warm orange
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

_TEXT_STYLE_RULES = [
    (re.compile(r"\*\*\*(.+?)\*\*\*"), f"{BOLD}{ITALIC}\\1{RESET}"),
    (re.compile(r"\*\*(.+?)\*\*"), f"{BOLD}\\1{RESET}"),
    (re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"), f"{ITALIC}\\1{RESET}"),
    (re.compile(r"~~(.+?)~~"), f"{STRIKETHROUGH}\\1{RESET}"),
]

_CODE_SPAN_RE = re.compile(r"`([^`]+)`")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_LINK_RE = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^)]+)\)")
_AUTOLINK_RE = re.compile(r"<(https?://[^>\s]+)>")
_BARE_URL_RE = re.compile(r"(?<![\w/])https?://[^\s<>()]+")
_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>~|])")
_TASK_RE = re.compile(r"^(\s*)([-*+])\s+\[([ xX])\]\s+(.*)")
_LIST_RE = re.compile(r"^(\s*)([-*+])\s+(.*)")
_ORDERED_RE = re.compile(r"^(\s*)(\d+)\.\s+(.*)")
_TABLE_CANDIDATE_RE = re.compile(r"^\s*\|?.+\|.+\|?\s*$")
_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")


def _get_lexer(lang: str):
    """Get a cached Pygments lexer by language name. Falls back to plain text."""
    if lang not in _lexer_cache:
        try:
            _lexer_cache[lang] = get_lexer_by_name(lang)
        except Exception:
            _lexer_cache[lang] = TextLexer()
    return _lexer_cache[lang]


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _visible_width(text: str) -> int:
    return len(_strip_ansi(text))


def _stash_placeholder(value: str, placeholders: dict[str, str]) -> str:
    key = f"{PLACEHOLDER_PREFIX}{len(placeholders)}\u0000"
    placeholders[key] = value
    return key


def _restore_placeholders(text: str, placeholders: dict[str, str]) -> str:
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text


def _render_link(label: str, url: str) -> str:
    return f"{UNDERLINE}{BRIGHT_BLUE}{label}{RESET}{DIM} ({url}){RESET}"


def _render_image(alt: str, url: str) -> str:
    label = alt or url
    return f"{DIM}Image:{RESET} {BRIGHT_MAGENTA}{label}{RESET}{DIM} ({url}){RESET}"


def _apply_text_styles(text: str) -> str:
    for pattern, replacement in _TEXT_STYLE_RULES:
        text = pattern.sub(replacement, text)
    return text


def _format_inline(text: str) -> str:
    """Apply inline markdown formatting (bold, italic, code, links, etc.)."""
    placeholders: dict[str, str] = {}

    def stash(value: str) -> str:
        return _stash_placeholder(value, placeholders)

    text = _ESCAPE_RE.sub(lambda match: stash(match.group(1)), text)
    text = _CODE_SPAN_RE.sub(
        lambda match: stash(f"{BG_CODE}{BRIGHT_CYAN}{match.group(1)}{RESET}"), text
    )
    text = _IMAGE_RE.sub(
        lambda match: stash(_render_image(match.group(1), match.group(2))),
        text,
    )
    text = _LINK_RE.sub(
        lambda match: stash(_render_link(match.group(1), match.group(2))),
        text,
    )
    text = _AUTOLINK_RE.sub(
        lambda match: stash(f"{UNDERLINE}{BRIGHT_BLUE}{match.group(1)}{RESET}"),
        text,
    )
    text = _BARE_URL_RE.sub(
        lambda match: stash(f"{UNDERLINE}{BRIGHT_BLUE}{match.group(0)}{RESET}"),
        text,
    )
    text = _apply_text_styles(text)
    return _restore_placeholders(text, placeholders)


def _split_blockquote(stripped: str) -> tuple[int, str]:
    match = re.match(r"^(\s*(?:>\s*)+)(.*)$", stripped)
    if not match:
        return 0, stripped
    return match.group(1).count(">"), match.group(2)


def _split_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if "|" not in stripped:
        return None
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells = [cell.strip() for cell in stripped.split("|")]
    if len(cells) < 2:
        return None
    return cells


def _parse_table_separator(line: str) -> list[str] | None:
    cells = _split_table_row(line)
    if not cells:
        return None
    alignments: list[str] = []
    for cell in cells:
        if not _TABLE_SEPARATOR_CELL_RE.match(cell):
            return None
        if cell.startswith(":") and cell.endswith(":"):
            alignments.append("center")
        elif cell.endswith(":"):
            alignments.append("right")
        else:
            alignments.append("left")
    return alignments


def _looks_like_table_row(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped and _TABLE_CANDIDATE_RE.match(stripped))


def _align_cell(text: str, width: int, align: str) -> str:
    pad = max(0, width - _visible_width(text))
    if align == "right":
        return f"{' ' * pad}{text}"
    if align == "center":
        left = pad // 2
        right = pad - left
        return f"{' ' * left}{text}{' ' * right}"
    return f"{text}{' ' * pad}"


def _block_prefix(base_pad: str, quote_depth: int) -> str:
    if quote_depth <= 0:
        return base_pad
    return base_pad + "  " + "".join(f"{DIM}│{RESET} " for _ in range(quote_depth))


class StreamingMarkdownRenderer:
    """
    Streaming markdown renderer with repaint support for live table blocks.

    Code blocks are still rendered line-by-line for low-latency syntax
    highlighting. Pipe tables are upgraded in place as additional table rows
    arrive, so the current bottom block can be repainted without disturbing
    earlier output.
    """

    def __init__(self, padding: int = None):
        self.in_code_block = False
        self.code_lang = ""
        self.code_lines: list[str] = []
        self.code_line_num = 0
        self.partial = ""
        self.previous_was_blank = True
        self.pending_table_header: str | None = None
        self.pending_table_rows = 0
        self.table_lines: list[str] = []
        self.table_alignments: list[str] = []
        self.table_render_rows = 0
        if padding is None:
            padding = int(os.environ.get("MDSTREAM_PADDING", "4"))
        self.pad = " " * padding
        # Line numbers in code blocks: enabled by default, disable with MDSTREAM_NO_LINENO=1
        self.show_lineno = not os.environ.get("MDSTREAM_NO_LINENO")

    def render_line(self, line: str) -> str:
        """
        Render a single completed line with full markdown formatting.

        Returns the ANSI-formatted string including trailing newline and any
        cursor movement needed to repaint the current live table block.
        """
        stripped = line.rstrip("\n")

        if self.in_code_block:
            rendered = self._render_code_line(stripped)
        elif self.table_lines:
            maybe_table = self._maybe_extend_table(stripped)
            if maybe_table is not None:
                rendered = maybe_table
            elif self.pending_table_header is not None:
                maybe_promoted = self._maybe_promote_table(stripped)
                rendered = (
                    maybe_promoted
                    if maybe_promoted is not None
                    else self._render_noncode_line(stripped)
                )
            else:
                rendered = self._render_noncode_line(stripped)
        elif self.pending_table_header is not None:
            maybe_promoted = self._maybe_promote_table(stripped)
            rendered = (
                maybe_promoted
                if maybe_promoted is not None
                else self._render_noncode_line(stripped)
            )
        else:
            rendered = self._render_noncode_line(stripped)

        self.previous_was_blank = stripped == ""
        return rendered

    def _render_noncode_line(self, stripped: str) -> str:
        fence_match = re.match(r"^(\s*)(```+|~~~+)(.*)", stripped)
        if fence_match:
            return self._render_code_fence(fence_match)

        if _looks_like_table_row(stripped):
            rendered = self._render_structured_line(stripped)
            self.pending_table_header = stripped
            self.pending_table_rows = self._measure_rendered_rows(rendered)
            return rendered

        return self._render_structured_line(stripped)

    def _render_code_fence(self, fence_match: re.Match[str]) -> str:
        p = self.pad
        if not self.in_code_block:
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
                return (
                    f"{p}{DIM}{'─' * 2}{label}"
                    f"{DIM}{'─' * max(1, 38 - len(self.code_lang) - 2)}{RESET}\n"
                )
            return f"{p}{DIM}{'─' * 40}{RESET}\n"

        self.in_code_block = False
        self.code_lang = ""
        self.code_lines = []
        self.code_line_num = 0
        return f"{p}{DIM}{'─' * 40}{RESET}\n"

    def _render_code_line(self, stripped: str) -> str:
        p = self.pad
        fence_match = re.match(r"^(\s*)(```+|~~~+)(.*)", stripped)
        if fence_match:
            return self._render_code_fence(fence_match)
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

    def _maybe_promote_table(self, stripped: str) -> str | None:
        alignments = _parse_table_separator(stripped)
        header_cells = _split_table_row(self.pending_table_header or "")
        if alignments and header_cells and len(alignments) == len(header_cells):
            self.table_lines = [self.pending_table_header or "", stripped]
            self.table_alignments = alignments
            rendered_table = self._render_table()
            erase = self._erase_rendered_rows(self.pending_table_rows)
            self.pending_table_header = None
            self.pending_table_rows = 0
            self.table_render_rows = self._measure_rendered_rows(rendered_table)
            return erase + rendered_table

        self.pending_table_header = None
        self.pending_table_rows = 0
        return None

    def _maybe_extend_table(self, stripped: str) -> str | None:
        row_cells = _split_table_row(stripped)
        header_cells = _split_table_row(self.table_lines[0])
        if (
            row_cells
            and header_cells
            and len(row_cells) == len(header_cells)
            and not _parse_table_separator(stripped)
        ):
            self.table_lines.append(stripped)
            rendered_table = self._render_table()
            erase = self._erase_rendered_rows(self.table_render_rows)
            self.table_render_rows = self._measure_rendered_rows(rendered_table)
            return erase + rendered_table

        self.table_lines = []
        self.table_alignments = []
        self.table_render_rows = 0
        return None

    def _render_structured_line(self, stripped: str) -> str:
        quote_depth, inner = _split_blockquote(stripped)
        prefix = _block_prefix(self.pad, quote_depth)
        if quote_depth and inner == "":
            return f"{prefix.rstrip()}\n"

        if quote_depth:
            return self._render_content_line(inner, prefix, allow_headings=False)
        return self._render_content_line(stripped, prefix, allow_headings=True)

    def _render_content_line(
        self, text: str, prefix: str, allow_headings: bool
    ) -> str:
        if allow_headings:
            heading_match = re.match(r"^(#{1,6})\s+(.*)", text)
            if heading_match:
                level = len(heading_match.group(1))
                value = heading_match.group(2).rstrip("#").rstrip()
                style = HEADING_STYLES[min(level - 1, len(HEADING_STYLES) - 1)]
                color = _H_COLORS[min(level - 1, len(_H_COLORS) - 1)]
                leading_gap = "" if self.previous_was_blank else "\n"
                heading = f"{leading_gap}{self.pad}{style}{value}{RESET}\n"
                if level == 1:
                    return heading + f"{self.pad}{color}{'━' * len(value)}{RESET}\n"
                if level == 2:
                    return heading + f"{self.pad}{DIM}{color}{'─' * len(value)}{RESET}\n"
                return heading

        if re.match(r"^(\s*[-*_]\s*){3,}$", text):
            return f"{prefix}{DIM}{'─' * 40}{RESET}\n"

        task_match = _TASK_RE.match(text)
        if task_match:
            indent, _, status, body = task_match.groups()
            checkbox = (
                f"{BRIGHT_GREEN}{BOLD}☑{RESET}"
                if status.lower() == "x"
                else f"{DIM}☐{RESET}"
            )
            return f"{prefix}{indent}  {checkbox} {_format_inline(body)}\n"

        list_match = _LIST_RE.match(text)
        if list_match:
            indent = list_match.group(1)
            return f"{prefix}{indent}  • {_format_inline(list_match.group(3))}\n"

        ordered_match = _ORDERED_RE.match(text)
        if ordered_match:
            indent, number, body = ordered_match.groups()
            return f"{prefix}{indent}  {DIM}{number}.{RESET} {_format_inline(body)}\n"

        if text:
            return f"{prefix}{_format_inline(text)}\n"

        return "\n"

    def _render_table(self) -> str:
        header = _split_table_row(self.table_lines[0]) or []
        body_rows = [_split_table_row(line) or [] for line in self.table_lines[2:]]
        widths = [0] * len(header)

        styled_header = [f"{BOLD}{_format_inline(cell)}{RESET}" for cell in header]
        styled_rows = [[_format_inline(cell) for cell in row] for row in body_rows]

        for idx, cell in enumerate(styled_header):
            widths[idx] = max(widths[idx], _visible_width(cell))
        for row in styled_rows:
            for idx, cell in enumerate(row):
                widths[idx] = max(widths[idx], _visible_width(cell))

        def separator(char: str, joiner: str, dim: bool) -> str:
            style = DIM if dim else ""
            parts = [char * (width + 2) for width in widths]
            return f"{self.pad}{style}{joiner.join(parts)}{RESET}\n"

        def render_row(cells: list[str], alignments: list[str]) -> str:
            padded_cells: list[str] = []
            for idx, cell in enumerate(cells):
                aligned = _align_cell(cell, widths[idx], alignments[idx])
                padded_cells.append(f" {aligned} ")
            row = f"{DIM}│{RESET}".join(padded_cells)
            return f"{self.pad}{row}\n"

        lines = []
        header_alignments = ["center"] * len(header)
        lines.append(render_row(styled_header, header_alignments))
        lines.append(separator("━", "┿", dim=False))
        for idx, row in enumerate(styled_rows):
            lines.append(render_row(row, self.table_alignments))
            if idx < len(styled_rows) - 1:
                lines.append(separator("─", "┼", dim=True))
        return "".join(lines)

    # ── Terminal helpers ──────────────────────────────────────────────────

    def _term_width(self):
        """Get current terminal width, defaulting to 80 if unavailable."""
        try:
            return os.get_terminal_size().columns
        except OSError:
            return 80

    def _measure_rendered_rows(self, rendered: str) -> int:
        width = max(1, self._term_width())
        total = 0
        for line in rendered.splitlines():
            visible = max(1, _visible_width(line))
            total += max(1, math.ceil(visible / width))
        return max(1, total)

    def _erase_rendered_rows(self, rows: int) -> str:
        if rows <= 0:
            return ""
        return f"\033[{rows}A\r\033[J"

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
