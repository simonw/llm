(color-output)=
# Colored Markdown Output

LLM CLI can render streaming output with syntax-highlighted code blocks, styled headings, and inline formatting using the built-in `mdstream` renderer.

## Quick Start

```bash
# Enable colored output with the --color flag (or -C)
llm "explain rust vs c with code examples" --color

# Explicit renderer name (mdstream is the default)
llm "explain rust" --color mdstream

# Works with chat too
llm chat --color
```

## How It Works

The `mdstream` renderer uses a **hybrid streaming approach**:

1. **Tokens stream live** — as the LLM generates output, each token appears immediately on screen (raw text, no delay)
2. **Lines render on completion** — when a newline arrives, the raw partial line is erased and replaced with the fully formatted version (headings, bold, code highlighting)
3. **History is frozen** — completed lines above the cursor are fully rendered and never change

This gives you the best of both worlds: instant token-by-token streaming feedback with polished final output.

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
| `MDSTREAM_PADDING` | `4` | Left padding in spaces |
| `MDSTREAM_NO_LINENO` | unset | Set to `1` to disable line numbers in code blocks |

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
