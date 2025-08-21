(http-debugging)=
# HTTP Debugging and Logging

LLM CLI provides comprehensive HTTP logging capabilities to debug requests and responses across all model providers. This feature enables you to see exactly what's being sent to and received from AI APIs, making it invaluable for troubleshooting and understanding model behavior.

## Quick Start

Enable HTTP logging for all providers:

```bash
# Basic HTTP logging (shows requests and responses)
LLM_HTTP_LOGGING=1 llm -m gpt-4o "Hello world"

# Verbose HTTP debugging (includes connection details)
LLM_HTTP_DEBUG=1 llm -m gemini-2.5-pro "Reasoning task"

# Using CLI flags (alternative to environment variables)
llm --http-logging -m claude-4-sonnet "Debug this request"
llm --http-debug -m o3 "Show all HTTP details"

# For development/testing without global install
LLM_HTTP_DEBUG=1 uv run llm -m gpt-4o "Test prompt"
LLM_HTTP_DEBUG=1 python -m llm -m gpt-4o "Test prompt"  # if already installed
```

## Environment Variables

| Variable | Level | Description |
|----------|-------|-------------|
| `LLM_HTTP_LOGGING=1` | INFO | Shows HTTP requests and responses |
| `LLM_HTTP_DEBUG=1` | DEBUG | Shows detailed connection info and headers |
| `LLM_HTTP_VERBOSE=1` | DEBUG | Alias for `LLM_HTTP_DEBUG` |
| `LLM_OPENAI_SHOW_RESPONSES=1` | INFO | Legacy OpenAI-only debugging (still supported) |

## CLI Flags

```bash
llm --http-logging [command]     # Enable INFO-level HTTP logging
llm --http-debug [command]       # Enable DEBUG-level HTTP logging
```

## What Gets Logged

### INFO Level (`LLM_HTTP_LOGGING=1`)

Shows high-level HTTP request information:

```
httpx - INFO - HTTP Request: POST https://api.openai.com/v1/chat/completions "HTTP/1.1 200 OK"
httpx - INFO - HTTP Request: POST https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:streamGenerateContent "HTTP/1.1 200 OK"
```

### DEBUG Level (`LLM_HTTP_DEBUG=1`)

Shows detailed connection and protocol information:

```
httpcore.connection - DEBUG - connect_tcp.started host='api.openai.com' port=443
httpcore.connection - DEBUG - connect_tcp.complete return_value=<httpcore._backends.sync.SyncStream object>
httpcore.connection - DEBUG - start_tls.started ssl_context=<ssl.SSLContext object> server_hostname='api.openai.com'
httpcore.http11 - DEBUG - send_request_headers.started request=<Request [b'POST']>
httpcore.http11 - DEBUG - send_request_body.started request=<Request [b'POST']>
httpcore.http11 - DEBUG - receive_response_headers.started request=<Request [b'POST']>
httpcore.http11 - DEBUG - receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [...headers...])
httpx - INFO - HTTP Request: POST https://api.openai.com/v1/chat/completions "HTTP/1.1 200 OK"
httpcore.http11 - DEBUG - receive_response_body.started request=<Request [b'POST']>
httpcore.http11 - DEBUG - receive_response_body.complete
```

## Provider-Specific Debugging

### OpenAI Models (o1, o3, GPT-4, etc.)

**What you can see:**
- Reasoning token usage: `reasoning_tokens`, `input_tokens`, `output_tokens`
- Request parameters for reasoning models
- Tool calling request/response cycles
- Rate limiting headers

**Example:**
```bash
export LLM_HTTP_DEBUG=1
llm -m o3 "Solve this step by step: What is 15% of 240?"
```
Shows reasoning parameters and token usage in HTTP traffic.

### Gemini Models (including 2.5-pro reasoning)

**What you can see:**
- Thinking budget configuration: `thinking_config: {"thinking_budget": 1000}`
- Response with thinking tokens: `thoughtsTokenCount: 500`
- Streaming response chunks
- Model-specific parameters

**Example:**
```bash
export LLM_HTTP_DEBUG=1
llm -m gemini-2.5-pro "Think carefully about this complex problem"
```
Shows direct HTTP calls to Google's API with thinking parameters.

### Anthropic Claude Models (including reasoning)

**What you can see:**
- Thinking configuration: `thinking: {"type": "enabled", "budget_tokens": 1000}`
- Beta API usage indicators
- Message structure and tool calls
- Thinking parameters in requests

**Example:**
```bash
export LLM_HTTP_DEBUG=1
llm -m claude-4-sonnet "Analyze this problem methodically"
```
Shows Anthropic SDK's HTTP traffic including reasoning config.

## Real-World Use Cases

### Debugging Reasoning Models

See what reasoning parameters are being sent:

```bash
export LLM_HTTP_DEBUG=1

# OpenAI o3 reasoning
llm -m o3 "Complex math problem" --max-tokens 1000

# Gemini with thinking budget
llm -m gemini-2.5-pro "Reasoning task" 

# Claude with thinking enabled
llm -m claude-4-sonnet "Analytical problem"
```

### Investigating API Errors

Debug failed requests:

```bash
export LLM_HTTP_DEBUG=1
llm -m gpt-4o "Test prompt"
# Shows exact error responses, status codes, headers
```

### Understanding Token Usage

See how tokens are calculated:

```bash
export LLM_HTTP_LOGGING=1
llm -m o3-mini "Short prompt"
# Response shows: reasoning_tokens, input_tokens, output_tokens
```

### Monitoring Rate Limits

Track API usage and limits:

```bash
export LLM_HTTP_DEBUG=1
llm -m gpt-4o "Test"
# Shows rate limit headers in response
```

## Advanced Configuration

### Combining with LLM Logging

HTTP logging works alongside LLM's built-in SQLite logging:

```bash
# Enable both HTTP debugging and LLM logging
export LLM_HTTP_LOGGING=1
llm logs on
llm -m gpt-4o "Test prompt"

# View logged interactions
llm logs list --json
```

### Filtering Logs

Focus on specific providers or domains:

```bash
# Only log OpenAI requests
export LLM_HTTP_DEBUG=1
llm -m gpt-4o "Test" 2>&1 | grep "api.openai.com"

# Only log Gemini requests  
llm -m gemini-2.5-pro "Test" 2>&1 | grep "generativelanguage.googleapis.com"
```

### Performance Considerations

HTTP logging adds overhead. For production use:

```bash
# Use INFO level for minimal overhead
export LLM_HTTP_LOGGING=1

# Avoid DEBUG level in production
# export LLM_HTTP_DEBUG=1  # Don't use this in production
```

## Troubleshooting

### Common Issues

**No logs appearing:**
- Verify environment variable is set: `echo $LLM_HTTP_LOGGING`
- Check that the provider actually uses HTTP (not all providers do)
- Some providers may use custom logging that bypasses this system

**Too much output:**
- Use `LLM_HTTP_LOGGING=1` instead of `LLM_HTTP_DEBUG=1`
- Redirect stderr: `llm prompt "test" 2>/dev/null`

**Missing reasoning details:**
- Reasoning chains are generated server-side and not exposed in HTTP logs
- You'll see token counts but not the actual reasoning text
- This is a limitation of the provider APIs, not LLM CLI

### Integration with External Tools

**Using with jq for JSON parsing:**
```bash
export LLM_HTTP_DEBUG=1
llm -m gpt-4o "test" 2>&1 | grep -A 10 "Request:" | jq '.'
```

**Saving logs to files:**
```bash
export LLM_HTTP_LOGGING=1
llm -m gemini-2.5-pro "test" 2>debug.log
```

## Security Considerations

⚠️ **Important Security Notes:**

- HTTP logs may contain API keys in headers (these are automatically redacted)
- Request/response bodies may contain sensitive data
- Never commit log files containing real API interactions
- Use environment variables instead of command-line flags in scripts to avoid shell history

## Backward Compatibility

The new HTTP logging system maintains full backward compatibility.

### Legacy Support

- `LLM_OPENAI_SHOW_RESPONSES=1` still works (OpenAI only)
- New variables extend functionality to all providers
- No breaking changes to existing workflows

### Migration Path

For users currently using OpenAI-specific debugging:
```bash
# Old way (still works)
export LLM_OPENAI_SHOW_RESPONSES=1

# New way (works for all providers)
export LLM_HTTP_LOGGING=1
```

## Related Documentation

- [LLM CLI Documentation](https://llm.datasette.io/)
- [Logging and Storage](logging.md)
- [Provider-Specific Setup](setup.md)
- [Tools and Function Calling](tools.md)
