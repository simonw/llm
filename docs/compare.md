(compare)=
# Comparing LLM Model Responses

The `compare` command allows you to run identical prompts against multiple language models and examine their responses side-by-side. This is useful for:

- Evaluating model quality differences
- Cost vs. performance analysis
- Testing model outputs on domain-specific tasks
- Building benchmarks for model selection

## Basic Usage

Compare two models with a single prompt:

```bash
llm compare -m gpt-4o-mini -m claude-3-sonnet "What is machine learning?"
```

Both models will receive the same prompt, and their responses will be displayed together for easy comparison.

## Comparing Multiple Prompts

Use the `--batch` option to compare multiple prompts:

```bash
llm compare -m gpt-4o-mini -m claude-3-sonnet \
  --batch \
  "What is machine learning?" \
  "Explain neural networks" \
  "How do transformers work?"
```

Or read prompts from a file (one per line):

```bash
llm compare -m gpt-4o-mini -m claude-3-sonnet \
  --batch \
  --input prompts.txt
```

## Output Options

By default, responses are displayed in the terminal. You can export results:

```bash
llm compare -m gpt-4o-mini -m claude-3-sonnet \
  --output results.json \
  "Your prompt here"
```

The JSON output includes:
- Prompt text
- Model names
- Full responses
- Token counts (if available)
- Execution time for each model

## Viewing Statistics

Add `--stats` to display detailed metrics:

```bash
llm compare -m gpt-4o-mini -m claude-3-sonnet \
  --stats \
  "Your prompt here"
```

This shows:
- Response length (characters/tokens)
- Time taken for each model
- Cost comparison (if pricing data is available)

## Using System Prompts

Apply a system prompt to both models:

```bash
llm compare -m gpt-4o-mini -m claude-3-sonnet \
  -s "You are an expert Python developer" \
  "How would you optimize this code?"
```

## Comparing with Attachments

Include attachments (images, files) in your comparison:

```bash
llm compare -m gpt-4o-mini -m claude-3-sonnet \
  -a document.pdf \
  "Summarize this document"
```

## Export Formats

The `--output` option supports multiple formats:

- **JSON** (`--output results.json`) - Structured data with full details
- **CSV** (`--output results.csv`) - Tabular format for spreadsheet analysis
- **Markdown** (`--output results.md`) - Formatted report for sharing

### JSON Format Example

```json
{
  "prompts": [
    {
      "text": "What is machine learning?",
      "models": [
        {
          "name": "gpt-4o-mini",
          "response": "Machine learning is...",
          "tokens": 150,
          "time_ms": 1200,
          "cost": 0.00025
        },
        {
          "name": "claude-3-sonnet",
          "response": "Machine learning involves...",
          "tokens": 145,
          "time_ms": 980,
          "cost": 0.00045
        }
      ]
    }
  ]
}
```

## Configuration

### Default Comparison Models

Set default models for comparison to avoid typing them every time:

```bash
llm compare --set-defaults gpt-4o-mini claude-3-sonnet
```

View your default comparison models:

```bash
llm compare --show-defaults
```

### Temperature and Other Options

Pass model options to both models:

```bash
llm compare -m gpt-4o-mini -m claude-3-sonnet \
  -o temperature 0.7 \
  "Creative story prompt"
```

Or different options per model using `--model-options`:

```bash
llm compare \
  -m gpt-4o-mini --model-option temperature 0.5 \
  -m claude-3-sonnet --model-option temperature 0.9 \
  "Your prompt"
```

## Logging Comparisons

Comparison results are automatically logged to the LLM database (if logging is enabled). Query your comparison history:

```bash
llm logs -c compare
```

View a specific comparison:

```bash
llm logs -c compare -l 10
```

## Practical Examples

### Model Cost Analysis

```bash
llm compare -m gpt-4o -m gpt-4o-mini \
  --stats \
  --batch \
  --input evaluation_prompts.txt
```

### Quality Assessment

```bash
llm compare -m claude-3-haiku -m claude-3-sonnet \
  -s "You are a technical writer evaluating response quality" \
  "Explain recursion in simple terms"
```

### Batch Processing with Output

```bash
llm compare \
  -m gpt-4o-mini \
  -m gemini-2.0-flash \
  -m claude-3-haiku \
  --batch \
  --input prompts.txt \
  --output comparison_results.json
```

## Limitations

- Comparing more than 3-4 models simultaneously may produce cluttered output
- API rate limits apply to each model independently
- Some models may not return token count information
- Streaming mode (`--stream`) is disabled for compare operations to ensure synchronized output

## Tips

- Use `--json` flag to output raw JSON to stdout for piping to other tools
- Combine with `jq` for advanced result filtering: `llm compare ... --json | jq '.prompts[0].models[1].response'`
- Create comparison templates for repeated evaluations: `llm compare --save-template evaluation`
- Use `--no-cache` to force fresh API calls instead of using cached results