(telemetry)=
# OpenTelemetry

LLM emits [OpenTelemetry](https://opentelemetry.io/) spans for every model call and every tool call, following the [GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/). It depends on `opentelemetry-api` only, so nothing is recorded or exported unless you configure an OpenTelemetry SDK. Without one, every span is a no-op.

## Turning it on

Install the OpenTelemetry distro into the same environment as LLM and run the `llm` command under `opentelemetry-instrument`. This prints each span to the console:

```bash
pip install opentelemetry-distro
OTEL_TRACES_EXPORTER=console OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none \
  opentelemetry-instrument llm 'Ten names for a pet pelican'
```
To send spans to a collector instead, `pip install opentelemetry-exporter-otlp` and set `OTEL_EXPORTER_OTLP_ENDPOINT`, see the [OpenTelemetry Python documentation](https://opentelemetry.io/docs/zero-code/python/configuration/).

When using LLM {ref}`from Python <python-api>`, install `opentelemetry-sdk` and configure a tracer provider before making calls:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
import llm

provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)

print(llm.get_model("gpt-4.1-mini").prompt("Say hi").text())
```

## Spans

| Span | Kind | Attributes |
|---|---|---|
| `chat {model_id}`, one per model round-trip (a chain with tools makes several) | `CLIENT` | `gen_ai.operation.name` (`chat`), `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.request.stream`, `gen_ai.conversation.id`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.time_to_first_chunk` (streaming only, seconds), `llm.response.id`, `llm.response.outcome`, `error.type` |
| `execute_tool {tool_name}`, one per tool implementation call | `INTERNAL` | `gen_ai.operation.name` (`execute_tool`), `gen_ai.tool.name`, `gen_ai.tool.call.id`, `llm.tool.outcome`, `error.type` |

`gen_ai.provider.name` comes from the plugin that implements the model: `openai` for the default OpenAI models, `anthropic` for `llm-anthropic`, `gcp.gemini` for `llm-gemini` and so on. Models from anywhere else, such as a class defined in your own code, report `unknown`.

Outcomes:

- `ok`: the call completed.
- `error`: the model or tool raised an exception. `error.type` is set to the exception's class name and the span status is `ERROR`.
- `cancelled`: `asyncio.CancelledError` or `KeyboardInterrupt` while waiting on the provider or tool. `error.type` is set but the status is left unset, since cancellation is not a failure.
- `abandoned` (chat spans only): the caller stopped iterating over a streaming response before it finished. No `error.type`, status unset.
- `paused` (tool spans only): the tool raised {ref}`PauseChain <python-api-tools-pause>`. Status unset.

A replayed response, or one loaded from the logs database, does not produce a span.

## How spans nest

A `chat` span is a child of whatever span is current when you start iterating the response. The `chat` span is only current while LLM waits on the model, so spans created by provider SDK or HTTP instrumentation nest inside it. Spans you create between chunks do not.

Tools run between model calls, so an `execute_tool` span is a child of the caller's current span rather than of a `chat` span. The tool span is current while the tool runs, so any spans the tool creates nest inside it.

## Limitations

- An async response abandoned with `break` inside `async for` keeps its `chat` span open. The span ends as `ok` if the response is later completed (for example by `await response.text()`), or as `abandoned` when the response is garbage collected, which may be much later. Abandoned spans are given the end time of their last chunk. If the event loop is closed without `loop.shutdown_asyncgens()`, the span never ends. `asyncio.run()` calls that for you.
- Closing `response.astream_events()` early, or abandoning a sync response, ends the span as `abandoned` straight away.
- `cancelled` only covers cancellation while waiting on the provider. An exception or cancellation in your own loop body shows up as `abandoned`.
- A model plugin whose `execute()` is not a generator does its work before the `chat` span starts.

## Privacy

Spans never include prompt text, system prompts, response text, tool arguments, tool output, attachments, API keys or error messages. They record model IDs, tool names, IDs that LLM generates itself, token counts, timings, outcomes and exception class names.
