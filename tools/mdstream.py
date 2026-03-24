#!/usr/bin/env python3
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

Architecture:
    mdstream is intentionally not a full Markdown parser. Instead, it is a
    small line-oriented state machine tuned for streaming terminal output:

    1. Raw chunks arrive and are shown immediately on the current line.
    2. When a newline arrives, that completed line is re-rendered with
       markdown styling.
    3. A small amount of state tracks code fences, candidate tables, and
       the currently visible partial line.

    This architecture keeps latency low while still supporting richer output
    for completed lines. The only structure that is repainted after the fact
    is the current table block at the bottom of the terminal.

Usage:
    llm "prompt" | mdstream          # standalone pipe
    llm "prompt" --color             # integrated via llm CLI
    cat README.md | mdstream         # render any markdown

Environment:
    MDSTREAM_PADDING             Left padding in spaces (default: 0)
    MDSTREAM_NO_LIST_GUIDES      Disable nested list guides
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
_ORDERED_RE = re.compile(r"^(\s*)((?:\d+\.)*\d+)\.?\s+(.*)")
_TABLE_CANDIDATE_RE = re.compile(r"^\s*\|?.+\|.+\|?\s*$")
_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
_LIST_BULLETS = ("•", "◦", "▪", "‣")


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


def _indent_columns(indent: str) -> int:
    total = 0
    for char in indent:
        if char == "\t":
            total = ((total // 4) + 1) * 4
        else:
            total += 1
    return total


class StreamingMarkdownRenderer:
    """
    Stateful markdown renderer for terminal streaming.

    The renderer owns two distinct responsibilities:

    1. Track stream state across chunks and lines:
       - raw partial text on the current terminal line
       - whether we are inside a fenced code block
       - whether the most recent line might become a pipe table
    2. Convert completed lines into ANSI-formatted terminal output.

    Code blocks are rendered line-by-line for low-latency syntax
    highlighting. Pipe tables are upgraded in place as additional rows
    arrive, so only the live bottom block is repainted without disturbing
    earlier output.
    """

    def __init__(self, padding: int = None):
        # Code fence state. We keep every prior line in the current fenced
        # block so Pygments can re-highlight with full lexer context and we
        # can emit only the latest rendered line.
        self.in_code_block = False
        self.code_lang = ""
        self.code_lines: list[str] = []
        self.code_line_num = 0

        # The current in-progress terminal line. This is echoed raw as chunks
        # arrive and replaced with a rendered version once a newline lands.
        self.partial = ""

        # Heading rendering inserts a leading blank line unless the previous
        # line was already blank. This keeps headings visually separated
        # without double-spacing explicit blank lines.
        self.previous_was_blank = True

        # Two-phase table detection:
        # - pending_table_header remembers a line that *might* be the first
        #   row of a pipe table.
        # - table_lines/alignments take over once a valid separator row
        #   confirms that we should repaint as a formatted table.
        self.pending_table_header: str | None = None
        self.pending_table_rows = 0
        self.table_lines: list[str] = []
        self.table_alignments: list[str] = []
        self.table_render_rows = 0
        self.list_indent_stack: list[int] = []
        self.list_level_meta: list[dict[str, object]] = []
        self.active_list_context: dict[str, object] | None = None
        if padding is None:
            # Default to 0 — no left padding. Override with MDSTREAM_PADDING=N.
            padding = int(os.environ.get("MDSTREAM_PADDING", "0"))
        self.pad = " " * padding
        # Line numbers in code blocks: enabled by default, disable with MDSTREAM_NO_LINENO=1
        self.show_lineno = not os.environ.get("MDSTREAM_NO_LINENO")
        self.show_list_guides = not os.environ.get("MDSTREAM_NO_LIST_GUIDES")

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

    def write_chunk(self, chunk: str, out) -> None:
        """
        Consume decoded text from the stream and write terminal output.

        The algorithm is the core of mdstream's "hybrid" behavior:

        - incomplete lines are echoed raw immediately for token-speed UX
        - completed lines are erased and re-rendered with markdown styling

        Both the standalone CLI entrypoint and llm's `_ColorWriter` call this
        method so the streaming behavior is defined in one place.
        """
        parts = chunk.split("\n")
        if len(parts) == 1:
            # No newline yet. Keep extending the live raw line at the cursor.
            if not self.partial:
                out.write(self.pad)
            self.partial += parts[0]
            out.write(parts[0])
            return

        # The first item completes the current partial line.
        first_complete = self.partial + parts[0]
        self._erase_partial(out)
        self.partial = ""
        out.write(self.render_line(first_complete + "\n"))

        # Any middle items are complete lines entirely contained in this chunk.
        for part in parts[1:-1]:
            out.write(self.render_line(part + "\n"))

        # The final item is the new in-progress raw line, if any.
        self.partial = parts[-1]
        if self.partial:
            out.write(self.pad)
            out.write(self.partial)

    def finish(self, out) -> None:
        """
        Flush any trailing partial line at end-of-stream.

        Streaming sources often terminate without a final newline. We still
        render that last line so the terminal ends in the same fully rendered
        state as newline-terminated output.
        """
        if self.partial:
            partial = self.partial
            self._erase_partial(out)
            self.partial = ""
            out.write(self.render_line(partial + "\n"))

    def _render_noncode_line(self, stripped: str) -> str:
        fence_match = re.match(r"^(\s*)(```+|~~~+)(.*)", stripped)
        if fence_match:
            self._clear_list_state()
            return self._render_code_fence(fence_match)

        if _looks_like_table_row(stripped):
            # Render the line immediately so streaming stays snappy. If the
            # next line proves this is really a table separator, we will
            # repaint this bottom block in-place as a formatted table.
            self._clear_list_state()
            rendered = self._render_structured_line(stripped)
            self.pending_table_header = stripped
            self.pending_table_rows = self._measure_rendered_rows(rendered)
            return rendered

        return self._render_structured_line(stripped)

    def _clear_list_state(self) -> None:
        self.list_indent_stack = []
        self.list_level_meta = []
        self.active_list_context = None

    def _list_depth(self, indent: str) -> tuple[int, int]:
        width = _indent_columns(indent)
        if not self.list_indent_stack:
            self.list_indent_stack = [width]
            return 0, width

        while len(self.list_indent_stack) > 1 and width < self.list_indent_stack[-1]:
            self.list_indent_stack.pop()

        if width < self.list_indent_stack[0]:
            self.list_indent_stack = [width]
            return 0, width

        if width > self.list_indent_stack[-1]:
            self.list_indent_stack.append(width)

        return max(0, len(self.list_indent_stack) - 1), width

    def _list_level_prefix(self, depth: int) -> str:
        if depth <= 0 or not self.show_list_guides:
            return "  " * (depth + 1)
        return "  " + "".join(f"{DIM}│{RESET} " for _ in range(depth))

    def _set_list_context(
        self, rendered_prefix: str, source_indent_width: int, marker_width: int
    ) -> None:
        self.active_list_context = {
            "source_indent_width": source_indent_width,
            "continuation_prefix": rendered_prefix + (" " * (marker_width + 1)),
        }

    def _remember_list_level(
        self, depth: int, *, kind: str, path: list[str] | None = None
    ) -> None:
        self.list_level_meta = self.list_level_meta[:depth]
        entry: dict[str, object] = {"kind": kind}
        if path is not None:
            entry["path"] = list(path)
        self.list_level_meta.append(entry)

    def _ordered_path(self, depth: int, marker: str) -> list[str]:
        parts = marker.split(".")
        if len(parts) > 1:
            return parts

        if (
            depth > 0
            and depth <= len(self.list_level_meta)
            and self.list_level_meta[depth - 1].get("kind") == "ordered"
        ):
            parent_path = list(self.list_level_meta[depth - 1]["path"])
            return [*parent_path, parts[0]]

        return parts

    def _format_ordered_marker(self, path: list[str]) -> tuple[str, int]:
        if len(path) == 1:
            marker = f"{path[0]}."
            return f"{BOLD}{path[0]}{RESET}.", len(marker)

        faded = ".".join(path[:-1])
        bright = f".{path[-1]}"
        return (
            f"{DIM}{faded}{RESET}{BOLD}{bright}{RESET}",
            len(faded) + len(bright),
        )

    def _render_list_item(
        self,
        prefix: str,
        indent: str,
        marker: str,
        body: str,
        *,
        kind: str,
    ) -> str:
        depth, source_indent_width = self._list_depth(indent)
        rendered_prefix = prefix + self._list_level_prefix(depth)

        marker_text = marker
        marker_width = _visible_width(marker_text)
        if kind == "unordered":
            marker_text = _LIST_BULLETS[depth % len(_LIST_BULLETS)]
            marker_width = len(marker_text)
            self._remember_list_level(depth, kind=kind)
        elif kind == "ordered":
            ordered_path = self._ordered_path(depth, marker)
            marker_text, marker_width = self._format_ordered_marker(ordered_path)
            self._remember_list_level(depth, kind=kind, path=ordered_path)
        else:
            self._remember_list_level(depth, kind=kind)

        self._set_list_context(rendered_prefix, source_indent_width, marker_width)
        rendered_body = _format_inline(body)
        return f"{rendered_prefix}{marker_text} {rendered_body}\n"

    def _render_list_continuation(self, prefix: str, text: str) -> str | None:
        if not self.active_list_context or not text.strip():
            return None

        match = re.match(r"^(\s+)(.*)$", text)
        if not match:
            return None

        indent_width = _indent_columns(match.group(1))
        source_indent_width = int(self.active_list_context["source_indent_width"])
        if indent_width <= source_indent_width:
            return None

        body = match.group(2)
        continuation_prefix = str(self.active_list_context["continuation_prefix"])
        return f"{continuation_prefix}{_format_inline(body)}\n"

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
        # Re-highlight the whole block every time so lexer state is correct for
        # multi-line constructs such as strings or comments, then emit only the
        # final highlighted line to preserve low-latency streaming.
        hl_full = _pygments_highlight(full_code, lexer, _formatter).rstrip("\n")
        hl_last = hl_full.rsplit("\n", 1)[-1]
        if self.show_lineno:
            ln = f"{DIM}{self.code_line_num:>3}  {RESET}"
            return f"{p}{ln}{hl_last}\n"
        return f"{p}  {hl_last}\n"

    def _maybe_promote_table(self, stripped: str) -> str | None:
        """
        Upgrade a previously rendered candidate header into a live table block.

        We only commit to table rendering after seeing a valid separator row.
        At that point we erase the previously printed header line and replace
        it with a formatted table.
        """
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
        """
        Extend the current live table block if the next line is another row.

        Tables are the one place where mdstream intentionally repaints already
        rendered output. We keep the active table at the bottom of the screen,
        recalculate widths, erase the prior rendering, and print the larger
        table in its place.
        """
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
                self._clear_list_state()
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
            self._clear_list_state()
            return f"{prefix}{DIM}{'─' * 40}{RESET}\n"

        task_match = _TASK_RE.match(text)
        if task_match:
            indent, _, status, body = task_match.groups()
            checkbox = (
                f"{BRIGHT_GREEN}{BOLD}☑{RESET}"
                if status.lower() == "x"
                else f"{DIM}☐{RESET}"
            )
            return self._render_list_item(
                prefix, indent, checkbox, body, kind="task"
            )

        list_match = _LIST_RE.match(text)
        if list_match:
            indent, _, body = list_match.groups()
            return self._render_list_item(prefix, indent, "•", body, kind="unordered")

        ordered_match = _ORDERED_RE.match(text)
        if ordered_match:
            indent, number, body = ordered_match.groups()
            return self._render_list_item(prefix, indent, number, body, kind="ordered")

        continuation = self._render_list_continuation(prefix, text)
        if continuation is not None:
            return continuation

        if text:
            self._clear_list_state()
            return f"{prefix}{_format_inline(text)}\n"

        self._clear_list_state()
        return "\n"

    def _render_table(self) -> str:
        """Render the current promoted pipe table as an ANSI-styled grid."""
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
            # Column dividers use full brightness (no DIM) so they match
            # the header separator line — avoids a visual glitch where
            # dimmed dividers looked disconnected from bright separators.
            row = "│".join(padded_cells)
            return f"{self.pad}{row}\n"

        lines = []
        header_alignments = ["center"] * len(header)
        lines.append(render_row(styled_header, header_alignments))
        # Header separator: thick lines (━) with ┿ crossings
        lines.append(separator("━", "┿", dim=False))
        for idx, row in enumerate(styled_rows):
            lines.append(render_row(row, self.table_alignments))
            if idx < len(styled_rows) - 1:
                # Body separator: thin lines (─) with ┼ crossings,
                # same brightness as header for visual consistency
                lines.append(separator("─", "┼", dim=False))
        return "".join(lines)

    # ── Terminal helpers ──────────────────────────────────────────────────

    def _term_width(self):
        """Get current terminal width, defaulting to 80 if unavailable."""
        try:
            return os.get_terminal_size().columns
        except OSError:
            return 80

    def _measure_rendered_rows(self, rendered: str) -> int:
        """
        Estimate how many terminal rows a rendered block currently occupies.

        Repaint operations need row counts rather than logical line counts
        because wide rendered lines can wrap. We strip ANSI first so width
        calculations reflect what the terminal actually displays.
        """
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

            self.write_chunk(text, out)
            out.flush()

        # Render any remaining partial at EOF
        if self.partial:
            self.finish(out)
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
        print("  MDSTREAM_PADDING             Left padding in spaces (default: 0)", file=sys.stderr)
        print("  MDSTREAM_NO_LIST_GUIDES      Disable nested list guides", file=sys.stderr)
        sys.exit(1)

    renderer = StreamingMarkdownRenderer()
    try:
        renderer.run()
    except (KeyboardInterrupt, BrokenPipeError):
        pass


if __name__ == "__main__":
    main()
