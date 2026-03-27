(http-debugging)=
# HTTP Debugging and Logging

LLM CLI provides HTTP logging to debug requests and responses across all model providers. See exactly what's being sent to and received from AI APIs — invaluable for troubleshooting and understanding model behavior.

## Quick Start

```bash
# Level 1: show requests and responses
LLM_HTTP_DEBUG=1 llm -m gpt-4o "Hello world"

# Level 2: verbose (includes headers, connection details)
LLM_HTTP_DEBUG=2 llm -m gemini-2.5-pro "Reasoning task"

# Using CLI flags (equivalent to environment variable)
llm --debug 1 -m claude-4-sonnet "Debug this request"
llm --debug 2 -m o3 "Show all HTTP details"

# For development/testing without global install
LLM_HTTP_DEBUG=1 uv run llm -m gpt-4o "Test prompt"
```

## Configuration

### Environment Variables

| Value | Level | Description |
|-------|-------|-------------|
| `LLM_HTTP_DEBUG=1` | INFO | Shows HTTP requests and responses |
| `LLM_HTTP_DEBUG=2` | DEBUG | Verbose: connection info, headers, timing |
| `LLM_OPENAI_SHOW_RESPONSES=1` | INFO | Legacy OpenAI-only debugging (still supported) |

### CLI Flags

```bash
llm --debug 1 [command]     # INFO-level HTTP logging
llm --debug 2 [command]     # DEBUG-level HTTP logging
```

## What Gets Logged

### Level 1 (`LLM_HTTP_DEBUG=1`)

Shows high-level HTTP request information:

```
[18:29:28.100] llm.http
  HTTP logging enabled at INFO level
[18:29:28.200] openai._base_client
── POST /chat/completions [gpt-4o]
```

### Level 2 (`LLM_HTTP_DEBUG=2`)

Shows detailed connection and protocol information with request correlation:

```
[18:29:28.100] llm.http
  HTTP logging enabled at DEBUG level
[18:29:28.200] openai._base_client
── POST /chat/completions [gpt-4o]
    Payload:
  { "model": "gpt-4o", "messages": [...] }

[18:29:28.210] llm.http
── ➔ REQUEST [req-001] POST https://api.openai.com/v1/chat/completions
    Headers:
  content-type: application/json
  authorization: Bearer sk-...

[18:29:28.300] llm.http
── ⚡ Connection [req-001]
  host: api.openai.com
  port: 443

[18:29:28.400] llm.http
── ↓ Response Start [req-001] ✓ 200 OK (POST https://api.openai.com/v1/chat/completions)
    Headers:
  x-request-id: req_abc123

── ▼ Stream Start [req-001] 18:29:28.401 ──────
(model output appears here)

── ■ Stream End [req-001] 18:29:28.788 ──────
── ✓ Response Complete [req-001] 18:29:28.789 ──────
```

## Correlated TUI Events

When the OpenAI TUI HTTP client is active, `llm.http` becomes the
authoritative source for user-facing request lifecycle output.

- `➔ REQUEST [req-NNN]` identifies the outgoing request
- `⚡ Connection [req-NNN]` and `⚡ TLS Handshake [req-NNN]` show transport setup
- `↓ Response Start [req-NNN]` shows the status line and response headers
- `▼ Stream Start [req-NNN]`, `■ Stream End [req-NNN]`, and `✓ Response Complete [req-NNN]` bracket the streamed body

This avoids ambiguous marker attribution when tool calls or chained
requests interleave within a single command.

## Provider-Specific Debugging

### OpenAI Models (o1, o3, GPT-4, etc.)

**What you can see:**
- Reasoning token usage: `reasoning_tokens`, `input_tokens`, `output_tokens`
- Request parameters for reasoning models
- Tool calling request/response cycles
- Rate limiting headers

```bash
LLM_HTTP_DEBUG=2 llm -m o3 "Solve this step by step: What is 15% of 240?"
```

### Gemini Models (including reasoning models)

**What you can see:**
- Thinking budget configuration: `thinking_config: {"thinking_budget": 1000}`
- Response with thinking tokens: `thoughtsTokenCount: 500`
- Streaming response chunks

```bash
LLM_HTTP_DEBUG=2 llm -m gemini-2.5-pro "Think carefully about this complex problem"
```

### Anthropic Claude Models (including reasoning)

**What you can see:**
- Thinking configuration: `thinking: {"type": "enabled", "budget_tokens": 1000}`
- Beta API usage indicators
- Message structure and tool calls

```bash
LLM_HTTP_DEBUG=2 llm -m claude-4-sonnet "Analyze this problem methodically"
```

## Real-World Use Cases

### Debugging Reasoning Models

```bash
# OpenAI o3 reasoning
LLM_HTTP_DEBUG=2 llm -m o3 "Complex math problem" --max-tokens 1000

# Gemini with thinking budget
LLM_HTTP_DEBUG=2 llm -m gemini-2.5-pro "Reasoning task"

# Claude with thinking enabled
LLM_HTTP_DEBUG=2 llm -m claude-4-sonnet "Analytical problem"
```

### Investigating API Errors

```bash
LLM_HTTP_DEBUG=2 llm -m gpt-4o "Test prompt"
# Shows exact error responses, status codes, headers
```

### Understanding Token Usage

```bash
LLM_HTTP_DEBUG=1 llm -m o3-mini "Short prompt"
# Response shows: reasoning_tokens, input_tokens, output_tokens
```

### Monitoring Rate Limits

```bash
LLM_HTTP_DEBUG=2 llm -m gpt-4o "Test"
# Shows rate limit headers in response
```

## Advanced Configuration

### Combining with LLM Logging

HTTP logging works alongside LLM's built-in SQLite logging:

```bash
llm logs on
LLM_HTTP_DEBUG=1 llm -m gpt-4o "Test prompt"
llm logs list --json
```

### Filtering Logs

```bash
# Only log OpenAI requests
LLM_HTTP_DEBUG=2 llm -m gpt-4o "Test" 2>&1 | grep "api.openai.com"

# Only log Gemini requests
LLM_HTTP_DEBUG=2 llm -m gemini-2.5-pro "Test" 2>&1 | grep "generativelanguage.googleapis.com"
```

### Performance Considerations

```bash
# Use level 1 for minimal overhead
LLM_HTTP_DEBUG=1 llm -m gpt-4o "Test"

# Level 2 adds more overhead — avoid in production
```

### Disabling Colors and Gutter

```bash
# Disable colored output
NO_COLOR=1 LLM_HTTP_DEBUG=2 llm -m gpt-4o "Test"

# Disable the left │ gutter
LLM_HTTP_UI_MINIMAL=1 LLM_HTTP_DEBUG=2 llm -m gpt-4o "Test"
```

### Truncation Controls

HTTP debug output truncates long payloads by default, but it now does that in two stages:

- long JSON string values are truncated first, so nearby fields like `model` stay visible
- the final rendered body is still capped to avoid flooding the terminal

```bash
# Change the final rendered body limit (default: 500 chars)
LLM_HTTP_MAX_BODY_CHARS=1200 LLM_HTTP_DEBUG=2 llm -m gpt-4o "Test"

# Change the per-string JSON value limit (default: 160 chars)
LLM_HTTP_MAX_VALUE_CHARS=300 LLM_HTTP_DEBUG=2 llm -m gpt-4o "Test"

# Disable all HTTP debug truncation
LLM_HTTP_NO_TRUNCATE=1 LLM_HTTP_DEBUG=2 llm -m gpt-4o "Test"

# Or disable one limit at a time using -1
LLM_HTTP_MAX_BODY_CHARS=-1 LLM_HTTP_DEBUG=2 llm -m gpt-4o "Test"
LLM_HTTP_MAX_VALUE_CHARS=-1 LLM_HTTP_DEBUG=2 llm -m gpt-4o "Test"
```

### Spinner Controls

Interactive color mode uses a request-phase spinner by default. With `LLM_HTTP_DEBUG=2`, the spinner also leaves a dim history line in scrollback by default so each request phase stays visible between debug blocks.

```bash
# Opt out of persisted spinner history
LLM_SPINNER_PERSIST=0 LLM_HTTP_DEBUG=2 llm -m gpt-4o "Test"

# Customize the persisted symbol/string and spacing
LLM_SPINNER_PERSIST=1 \
LLM_SPINNER_PERSIST_TEXT=">" \
LLM_SPINNER_PADDING_BEFORE=1 \
LLM_SPINNER_PADDING_AFTER=1 \
llm -C "Test"

# Legacy inverse alias still supported
LLM_SPINNER_CLEAR=1 llm -C "Test"
```

## Troubleshooting

### Common Issues

**No logs appearing:**
- Verify environment variable is set: `echo $LLM_HTTP_DEBUG`
- Check that the provider actually uses HTTP (not all providers do)

**Too much output:**
- Use level 1 instead of level 2: `LLM_HTTP_DEBUG=1`
- Redirect stderr: `llm "test" 2>/dev/null`

**Missing reasoning details:**
- Reasoning chains are generated server-side and not exposed in HTTP logs
- You'll see token counts but not the actual reasoning text
- This is a limitation of the provider APIs, not LLM CLI

### Integration with External Tools

**Saving logs to files:**
```bash
LLM_HTTP_DEBUG=2 llm -m gpt-4o "test" 2>debug.log
```

## Security Considerations

**Important Security Notes:**

- HTTP logs may contain API keys in headers
- Request/response bodies may contain sensitive data
- Never commit log files containing real API interactions
- Use environment variables instead of command-line flags in scripts to avoid shell history exposure

## Backward Compatibility

- `LLM_OPENAI_SHOW_RESPONSES=1` still works (maps to level 1)
- No breaking changes to existing workflows using that variable

### Migration Path

```bash
# Old way (still works)
export LLM_OPENAI_SHOW_RESPONSES=1

# New way (works for all providers)
export LLM_HTTP_DEBUG=1
```

## Related Documentation

- [LLM CLI Documentation](https://llm.datasette.io/)
- [Colored Markdown Output](color-output.md)
- [Logging and Storage](logging.md)
- [Provider-Specific Setup](setup.md)
- [Tools and Function Calling](tools.md)
