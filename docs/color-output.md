(color-output)=
# Colored Markdown Output

LLM CLI can render streaming output with syntax-highlighted code blocks, styled headings, and inline formatting using the built-in `mdstream` renderer.

## Quick Start

```bash
# Enable colored output with the --color flag (or -C)
llm "explain rust vs c with code examples" --color

# Works with chat too
llm chat --color
```

## How It Works

The `mdstream` renderer uses a **hybrid streaming approach**:

1. **Tokens stream live** — as the LLM generates output, each token appears immediately on screen (raw text, no delay)
2. **Lines render on completion** — when a newline arrives, the raw partial line is erased and replaced with the fully formatted version (headings, bold, code highlighting)
3. **History is frozen** — completed lines above the cursor are fully rendered and never change

This gives you the best of both worlds: instant token-by-token streaming feedback with polished final output.

## Architecture

`mdstream` is deliberately split into three layers:

1. **Model streaming**: `llm` models yield raw text chunks as they arrive.
2. **CLI adapter**: `llm.cli._ColorWriter` forwards those chunks into the renderer when `--color` is enabled.
3. **Renderer state machine**: `tui/renderers/mdstream.py` tracks the current partial line, code-fence state, and live table state, then converts completed lines into ANSI-formatted output.

That split matters because `mdstream` does not participate in model execution, API calls, or tool use. It is purely a terminal presentation layer.

### Why It Is Line-Oriented

`mdstream` does **not** build a full Markdown AST. Instead, it optimizes for low-latency terminal rendering:

- Partial lines are shown immediately as raw text.
- Completed lines are reformatted once enough context exists.
- Tables are the one exception: the renderer can repaint the active bottom table block after detecting the separator row and additional table rows.

This approach keeps streaming responsive while still supporting headings, lists, links, code fences, and table upgrades.

### Code Blocks

Code fences are rendered incrementally, one line at a time. To preserve syntax-highlighting correctness for multi-line strings and comments, `mdstream` re-highlights the entire fenced block each time a new code line arrives, then prints only the latest highlighted line.

This is a deliberate tradeoff:

- You get immediate output instead of waiting for the whole block to finish.
- Pygments still sees full block context, so highlighting remains correct.

### Tables

Pipe tables are detected in two phases:

1. A possible header row is rendered immediately as normal text.
2. If the following line is a valid separator row, the renderer repaints that bottom block as a formatted table.

As more matching rows arrive, the table is re-rendered in place with recalculated column widths. Earlier output above that active table block remains unchanged.

## Features

### Headings

Markdown `#` markers are stripped and headings are rendered with rainbow colors:
- **H1**: Bold red-pink with ━━━ solid underline
- **H2**: Bold orange with ─── dashed underline
- **H3**: Bold green
- **H4**: Bold sky blue
- **H5**: Bold violet
- **H6**: Bold muted rose

### Code Blocks

Fenced code blocks get:
- **Language-colored labels** — each language has an iconic color (Rust=orange, Python=sky blue, JavaScript=yellow, C=blue, etc.)
- **Syntax highlighting** — powered by Pygments with the Monokai theme and 24-bit true color
- **Context-aware highlighting** — multi-line strings and comments highlight correctly across lines
- **Line numbers** — dim gray, right-aligned (disable with `MDSTREAM_NO_LINENO=1`)

### Inline Formatting

- **Bold** (`**text**`) → ANSI bold
- *Italic* (`*text*`) → ANSI italic
- ~~Strikethrough~~ (`~~text~~`) → ANSI strikethrough
- `Inline code` (`` `text` ``) → cyan on dark background
- [Links]() (`[text](url)`) → blue underline

### Lists and Blockquotes

- Unordered lists: `- item` → `  • item`
- Ordered lists: `1. item` → `  1. item` (dim number)
- Blockquotes: `> text` → `  │ text`
- Horizontal rules: `---` → `────────`

## Pipe Usage

`mdstream` also works as a standalone pipe-through tool:

```bash
# Pipe from llm
llm "explain rust" | mdstream

# Pipe from any command
cat README.md | mdstream

# Pipe from curl
curl -s https://raw.githubusercontent.com/.../README.md | mdstream
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MDSTREAM_PADDING` | `0` | Left padding in spaces |
| `MDSTREAM_NO_LINENO` | unset | Set to `1` to disable line numbers in code blocks |
| `LLM_SPINNER` | auto | Enable/disable the interactive spinner (`0` disables, `1` forces on) |
| `LLM_SPINNER_PERSIST` | `0` (`1` automatically for `LLM_HTTP_DEBUG=2`) | Keep a static spinner line in scrollback when the spinner stops |
| `LLM_SPINNER_PERSIST_TEXT` | auto | Override the default persisted symbol/string |
| `LLM_SPINNER_PADDING_BEFORE` | `1` when persisting | Blank lines before the persisted spinner line |
| `LLM_SPINNER_PADDING_AFTER` | `1` when persisting | Blank lines after the persisted spinner line |

## Spinner Behavior

In interactive color mode, `llm` shows a spinner while requests are in flight.

- Request-phase spinner states track connection and waiting phases
- The spinner stops at response start, before streamed content begins
- By default the spinner clears on stop
- In `LLM_HTTP_DEBUG=2`, a dim persisted history line is kept by default
- Set `LLM_SPINNER_PERSIST=1` to keep a static history line instead
- Set `LLM_SPINNER_PERSIST=0` or `LLM_SPINNER_CLEAR=1` to opt out of persistence

Example:

```bash
LLM_SPINNER_PERSIST=1 \
LLM_SPINNER_PERSIST_TEXT=">" \
LLM_SPINNER_PADDING_BEFORE=1 \
LLM_SPINNER_PADDING_AFTER=1 \
llm -C "Explain Rust lifetimes briefly"
```

## Comparison with Other Renderers

You can also pipe LLM output through external renderers:

```bash
# bat: syntax highlighting, line-by-line streaming, no structural rendering
llm "prompt" | bat --paging=never --style=plain --language=markdown

# mdriver: full markdown rendering, but block-buffered (code blocks appear all at once)
llm "prompt" | mdriver --color=always --width 9999
```

| Renderer | Streaming | Code Highlighting | Structural Rendering | Install |
|----------|-----------|-------------------|---------------------|---------|
| `--color` (mdstream) | Token-by-token | Pygments (Monokai) | Yes (headings, lists, etc.) | Built-in |
| `bat -pp -lmd` | Line-by-line | syntect (nested) | No (raw markdown visible) | `brew install bat` |
| `mdriver` | Block-buffered | syntect | Yes (full GFM) | `brew install llimllib/tap/mdriver` |
