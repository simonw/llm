(compare)=

# Comparing LLM Model Responses

The `compare` command allows you to run the same prompt against multiple language models and compare their responses from the command line.

This is useful when you want to:

* Compare responses from different models
* Evaluate model behavior on the same prompt
* Compare model quality for a particular task
* Test multiple models before choosing one
* Run the same input through several models

## Basic Usage

The `compare` command requires at least two models.

```bash
llm compare -m MODEL_1 -m MODEL_2 "Your prompt here"
```

For example:

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  "Explain how machine learning works"
```

Both models receive the same prompt and their responses are displayed for comparison.

## Comparing Two Models

When exactly two models are specified, their responses are displayed side-by-side.

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  "What are the advantages of using Python?"
```

The output is arranged into two columns, with each column showing the model name and its response.

The side-by-side layout adapts to the available terminal width. Long lines are truncated to prevent one response from breaking the layout.

## Comparing Multiple Models

You can compare more than two models by specifying `-m` multiple times:

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  -m gemini-2.5-flash \
  "Explain the difference between batch and streaming processing"
```

When three or more models are provided, their responses are displayed one after another.

The models are displayed in the same order in which they were provided on the command line.

## Using a System Prompt

Use `-s` or `--system` to provide the same system prompt to every model:

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  -s "You are an expert Python developer" \
  "How would you improve this code?"
```

This is useful when you want to compare models under the same system-level instructions.

## Passing Model Options

Use `-o` or `--option` to provide model options.

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  -o temperature 0.7 \
  "Write a creative story about space exploration"
```

The specified options are applied to each model. Options are validated against each model's supported options.

If an option is invalid for a particular model, that model reports the validation error while the other models can continue producing results.

## Comparing with Attachments

Attachments can be included using `-a` or `--attachment`.

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  -a document.pdf \
  "Summarize this document"
```

The same attachment is provided to each model, allowing you to compare how different models handle the same input.

Attachments can also use the existing attachment mechanisms supported by `llm`.

## Using Fragments

Fragments can be included using `-f` or `--fragment`:

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  -f my-fragment \
  "Summarize the provided information"
```

Fragments are resolved using the existing `llm` fragment functionality and provided to each model.

This makes it possible to compare models using the same stored or referenced content.

## Reading Prompts from Standard Input

The `compare` command can read prompts from standard input.

For example:

```bash
echo "Explain Apache Spark" | \
  llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet
```

This also allows `compare` to be used as part of a shell pipeline:

```bash
cat question.txt | \
  llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet
```

If both standard input and a prompt argument are provided, the standard input is combined with the command-line prompt.

This makes the command useful for scripting and integrating model comparisons into existing command-line workflows.

## JSON Output

Use `--json` to return comparison results as JSON:

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  --json \
  "Explain machine learning"
```

The output is a JSON array containing one object for each model.

A successful comparison looks like:

```json
[
  {
    "model": "gpt-4o-mini",
    "response": "Machine learning is..."
  },
  {
    "model": "claude-3-sonnet",
    "response": "Machine learning is a..."
  }
]
```

If a model encounters an error, the corresponding object contains an `error` field:

```json
[
  {
    "model": "gpt-4o-mini",
    "response": "Machine learning is..."
  },
  {
    "model": "unknown-model",
    "error": "Unknown model..."
  }
]
```

The JSON output makes it possible to process comparison results with other command-line tools.

For example, you can use `jq` to extract a particular model's response:

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  --json \
  "Explain machine learning" | \
  jq '.[0].response'
```

## Using a Custom Database

The `-d` or `--database` option can be used to specify a custom log database:

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  -d comparison.db \
  "Explain machine learning"
```

If no database is specified, the standard `llm` log database is used.

When logging is enabled, successful model responses are recorded in the database and can be queried using the existing `llm logs` functionality.

## Error Handling

Each model is executed independently.

If a model cannot be resolved, does not support a supplied option, or encounters another error, the error is associated with that model's result rather than preventing the other models from being executed.

For example:

```text
Model: model-a
----------------
Successful response...

Model: model-b
----------------
ERROR
Unknown model: model-b
```

When using `--json`, errors are represented in the corresponding model's JSON object.

## Parallel Execution

Model requests are executed concurrently rather than waiting for one model to finish before starting the next.

The implementation uses a thread pool with up to eight workers.

Despite running concurrently, results are returned in the same order as the `-m/--model` arguments.

This means:

```bash
llm compare \
  -m model-a \
  -m model-b \
  -m model-c \
  "Your prompt"
```

will always present the results as:

1. `model-a`
2. `model-b`
3. `model-c`

regardless of which model finishes first.

## Streaming

Streaming output is currently disabled for `compare`.

Comparison requests are executed as complete model responses so that the results can be collected and displayed together. This allows the two-model side-by-side output and JSON output to remain synchronized and predictable.

## Command Options

The following options are currently supported:

| Option               | Description                                                                    |
| -------------------- | ------------------------------------------------------------------------------ |
| `-m`, `--model`      | Model to include in the comparison. Can be specified multiple times.           |
| `-s`, `--system`     | System prompt applied to all models.                                           |
| `-o`, `--option`     | Key/value model option applied to the models. Can be specified multiple times. |
| `-a`, `--attachment` | Attachment to include with the prompt. Can be specified multiple times.        |
| `-f`, `--fragment`   | Fragment to include with the prompt. Can be specified multiple times.          |
| `--json`             | Output comparison results as JSON.                                             |
| `-d`, `--database`   | Path to the log database.                                                      |

At least two models must be specified.

## Practical Examples

### Compare General-Purpose Models

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  "Explain the CAP theorem"
```

### Compare Several Models

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  -m gemini-2.5-flash \
  "Explain how vector databases work"
```

### Compare with a System Prompt

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  -s "Answer as a senior data engineer" \
  "How would you design a data pipeline for 1TB of daily data?"
```

### Compare an Attached Document

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  -a report.pdf \
  "Summarize this report and identify its key findings"
```

### Use JSON for Further Processing

```bash
llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet \
  --json \
  "Explain the difference between REST and GraphQL"
```

### Use Standard Input

```bash
cat prompt.txt | \
  llm compare \
  -m gpt-4o-mini \
  -m claude-3-sonnet
```

## Limitations

The current implementation has a few intentional limitations:

* At least two models must be provided.
* Streaming output is not currently supported.
* Two models are displayed side-by-side; three or more models are displayed sequentially.
* Model options supplied with `--option` are applied to each model and must be supported by the individual model.
* Comparison requests are limited to eight concurrent workers.
* JSON output contains the model identifier and response or error; additional comparison metrics such as latency, cost, or token usage are not currently included.

## Future Improvements

Potential future enhancements could include:

* Batch comparison of multiple prompts
* Per-model options
* Response latency and token-usage statistics
* Cost comparisons
* Additional output formats
* More flexible comparison layouts
* Streaming support
* Automated evaluation or scoring of responses

These are not currently part of the `compare` command.
