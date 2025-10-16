# Cost Estimation Feature - Implementation Checklist (REVISED)

## ⚠️ IMPORTANT CHANGE
**Costs are integrated into existing `-u/--usage` flag, NOT separate commands**

## Quick Start

1. **Review the pricing data structure**
   ```bash
   cat pricing_data.json | python3 -c "import json, sys; d=json.load(sys.stdin); print(json.dumps(d['prices'][0], indent=2))"
   ```

2. **Set up development environment**
   ```bash
   pip install -e '.[test]'
   pytest tests/
   ```

## Phase 1: Core Functionality ✓

### 1.1 Create `llm/costs.py`

- [ ] Define `PriceInfo` dataclass
  - Fields: id, vendor, name, input_price, output_price, cached_input_price, from_date, to_date

- [ ] Define `Cost` dataclass
  - Fields: input_cost, output_cost, cached_cost, total_cost, currency, model_id, price_info

- [ ] Implement `CostEstimator` class
  - [ ] `__init__()` - Load pricing data from file
  - [ ] `_load_pricing_data()` - Parse JSON, validate structure
  - [ ] `_find_price()` - Exact model ID match
  - [ ] `_find_price_fuzzy()` - Fuzzy model ID match
  - [ ] `get_price()` - Public method, handles historical dates
  - [ ] `calculate_cost()` - Main cost calculation
  - [ ] `list_models()` - Return all models with pricing (for debugging)

- [ ] Implement helper functions
  - [ ] `get_default_estimator()` - Singleton pattern
  - [ ] `_normalize_model_id()` - Model ID cleanup
  - [ ] `_match_historical_price()` - Date range matching

### 1.2 Bundle pricing data

- [ ] Download and save to `llm/pricing_data.json`
  ```bash
  curl -s https://www.llm-prices.com/historical-v1.json -o llm/pricing_data.json
  ```

- [ ] Update `MANIFEST.in` to include pricing_data.json
  ```
  include llm/pricing_data.json
  ```

### 1.3 Unit Tests

- [ ] Create `tests/test_costs.py`
- [ ] Create `tests/fixtures/pricing_data.json` (subset for testing)
- [ ] Test cases:
  - [ ] `test_load_pricing_data_success()`
  - [ ] `test_load_pricing_data_missing_file()`
  - [ ] `test_load_pricing_data_invalid_json()`
  - [ ] `test_exact_model_match()`
  - [ ] `test_fuzzy_model_match_gpt4()`
  - [ ] `test_fuzzy_model_match_claude()`
  - [ ] `test_model_not_found()`
  - [ ] `test_calculate_cost_basic()`
  - [ ] `test_calculate_cost_with_cached()`
  - [ ] `test_calculate_cost_no_pricing()`
  - [ ] `test_calculate_cost_zero_tokens()`
  - [ ] `test_historical_pricing_in_range()`
  - [ ] `test_historical_pricing_before_range()`
  - [ ] `test_historical_pricing_after_range()`
  - [ ] `test_list_models()`
  - [ ] `test_list_models_by_vendor()`

## Phase 2: Integration ✓

### 2.1 Modify `llm/models.py`

- [ ] Add to `Response` class:
  ```python
  def cost(self, estimator: Optional[CostEstimator] = None) -> Optional[Cost]:
      """Calculate cost for this response"""
  ```

- [ ] Add helper method:
  ```python
  def _get_cached_tokens(self) -> Optional[int]:
      """Extract cached token count from token_details"""
  ```

- [ ] Import CostEstimator in models.py
  ```python
  from .costs import CostEstimator, Cost
  ```

### 2.2 Update exports

- [ ] Add to `llm/__init__.py`:
  ```python
  from .costs import CostEstimator, Cost, PriceInfo
  ```

- [ ] Add to `__all__` list

### 2.3 Integration Tests

- [ ] Test cases in `tests/test_costs.py`:
  - [ ] `test_response_cost_method()`
  - [ ] `test_response_cost_with_custom_estimator()`
  - [ ] `test_response_cost_no_tokens()`
  - [ ] `test_response_cost_unknown_model()`
  - [ ] `test_response_cached_tokens_anthropic()`

## Phase 3: CLI Integration ✓

### 3.1 Enhance `token_usage_string()` in `llm/utils.py`

**Current signature:**
```python
def token_usage_string(input_tokens, output_tokens, token_details) -> str:
```

**New signature (backward compatible):**
```python
def token_usage_string(
    input_tokens, 
    output_tokens, 
    token_details,
    model_id: Optional[str] = None,
    datetime_utc: Optional[datetime] = None,
    show_cost: bool = True
) -> str:
```

**Implementation tasks:**
- [ ] Add new parameters with defaults
- [ ] Add cost calculation logic:
  - [ ] Import `get_default_estimator` from `.costs`
  - [ ] Extract cached tokens from `token_details` if present
  - [ ] Call `estimator.calculate_cost()`
  - [ ] Format cost string with breakdown
- [ ] Maintain backward compatibility (all new params optional)
- [ ] Handle errors gracefully (if cost calculation fails, just skip it)

**Example output format:**
```
"1,000 input, 500 output, Cost: $0.004500 ($0.003000 input, $0.001500 output)"
```

### 3.2 Update `llm prompt` command in `llm/cli.py`

**Location:** Around line 901

**Current code:**
```python
if usage:
    for response_object in responses:
        click.echo(
            click.style(
                "Token usage: {}".format(response_object.token_usage()),
                fg="yellow",
                bold=True,
            ),
            err=True,
        )
```

**Modify to:**
- [ ] Pass model_id to token_usage_string
- [ ] Pass datetime_utc to token_usage_string
- [ ] Access via `response_object.resolved_model` or `response_object.model.model_id`
- [ ] Access via `response_object.datetime_utc()`

**Suggested change:**
```python
if usage:
    for response_object in responses:
        usage_str = token_usage_string(
            response_object.input_tokens,
            response_object.output_tokens,
            response_object.token_details,
            model_id=response_object.resolved_model or response_object.model.model_id,
            datetime_utc=response_object.datetime_utc()
        )
        click.echo(
            click.style(
                "Token usage: {}".format(usage_str),
                fg="yellow",
                bold=True,
            ),
            err=True,
        )
```

### 3.3 Update `llm logs` command in `llm/cli.py`

**Location:** Around line 2182

**Current code:**
```python
if usage:
    token_usage = token_usage_string(
        row["input_tokens"],
        row["output_tokens"],
        json.loads(row["token_details"]) if row["token_details"] else None,
    )
    if token_usage:
        click.echo("## Token usage\n\n{}\n".format(token_usage))
```

**Modify to:**
- [ ] Pass model_id from `row["model"]`
- [ ] Parse and pass datetime from `row["datetime_utc"]`

**Suggested change:**
```python
if usage:
    from datetime import datetime as dt
    token_usage = token_usage_string(
        row["input_tokens"],
        row["output_tokens"],
        json.loads(row["token_details"]) if row["token_details"] else None,
        model_id=row.get("resolved_model") or row["model"],
        datetime_utc=dt.fromisoformat(row["datetime_utc"]) if row.get("datetime_utc") else None
    )
    if token_usage:
        click.echo("## Token usage\n\n{}\n".format(token_usage))
```

### 3.4 CLI Tests

- [ ] Test cases in `tests/test_cli_costs.py` (or `tests/test_costs.py`):
  - [ ] `test_prompt_usage_shows_cost()` - Verify cost appears with -u flag
  - [ ] `test_prompt_usage_unknown_model()` - Verify graceful handling
  - [ ] `test_logs_usage_shows_cost()` - Verify cost in logs -u output
  - [ ] `test_logs_usage_with_cached_tokens()` - Verify cached token costs
  - [ ] `test_usage_backward_compatibility()` - Old calls still work
  - [ ] `test_usage_without_model_id()` - Verify no crash if model_id missing

## Phase 4: Documentation ✓

### 4.1 API Documentation

- [ ] Create `docs/costs.md`
  - [ ] Overview: costs integrated into -u/--usage
  - [ ] How pricing data works
  - [ ] Python API examples (Response.cost())
  - [ ] CLI examples (with -u flag)
  - [ ] Model ID matching explained
  - [ ] Historical pricing explained
  - [ ] Limitations and caveats

### 4.2 Update existing docs

- [ ] `docs/logging.md`
  - [ ] Add section on cost estimation with -u flag
  - [ ] Link to costs.md

- [ ] `docs/usage.md` or `docs/cli-reference.md`
  - [ ] Update `-u/--usage` documentation
  - [ ] Show examples with cost output
  - [ ] Explain what costs mean

- [ ] `docs/python-api.md`
  - [ ] Document `Response.cost()` method
  - [ ] Document `CostEstimator` class
  - [ ] Document `Cost` and `PriceInfo` dataclasses

- [ ] `README.md`
  - [ ] Add cost estimation to feature list
  - [ ] Add quick example with -u flag

### 4.3 Docstrings

- [ ] Complete docstrings for all public classes/methods
- [ ] Include examples in docstrings
- [ ] Type hints everywhere
- [ ] Explain what happens when pricing unavailable

## Phase 5: Polish ✓

### 5.1 Error Handling

- [ ] Graceful handling of missing pricing data
- [ ] Clear error messages for network failures (future feature)
- [ ] Warnings for model ID mismatches (debug level)
- [ ] Handle missing token counts (just don't show cost)
- [ ] Handle circular import issues (costs importing from models)

### 5.2 Logging

- [ ] Debug logs for model matching
- [ ] Info logs for using bundled vs custom pricing
- [ ] Warning logs for missing pricing (debug only, not user-facing)

### 5.3 Performance

- [ ] Cache parsed pricing data in memory (singleton pattern)
- [ ] Lazy load pricing data (only when needed)
- [ ] Efficient model lookup (dict, not list iteration)
- [ ] Don't slow down non-usage queries

### 5.4 Code Quality

- [ ] Run mypy: `mypy llm/costs.py llm/utils.py`
- [ ] Run ruff: `ruff llm/costs.py llm/utils.py`
- [ ] Run pytest with coverage: `pytest --cov=llm.costs --cov=llm.utils`
- [ ] Aim for >90% test coverage

## Testing Checklist

### Run all tests
```bash
# Unit tests
pytest tests/test_costs.py -v

# All tests with coverage
pytest --cov=llm.costs --cov=llm.utils --cov-report=html

# Type checking
mypy llm/costs.py llm/utils.py

# Linting
ruff llm/costs.py llm/utils.py
```

### Manual testing
```bash
# Test Python API
python -c "
import llm
model = llm.get_model('gpt-3.5-turbo')
response = model.prompt('Hello')
cost = response.cost()
print(f'Cost: \${cost.total_cost:.6f}' if cost else 'No pricing')
"

# Test CLI with usage flag
llm "Hello world" -m gpt-3.5-turbo -u
# Should show: Token usage: X input, Y output, Cost: $Z

# Test logs with usage flag
llm logs -1 -u
# Should show token usage and cost

# Test with unknown model
llm "Hello" -m some-unknown-model -u
# Should show tokens but no cost
```

## Example Code Snippets

### Basic usage with -u flag
```bash
llm "Explain quantum computing" -m gpt-4 -u
# Output includes:
# Token usage: 15 input, 127 output, Cost: $0.004110 ($0.000450 input, $0.003660 output)
```

### Python API
```python
import llm

# Get response
model = llm.get_model("gpt-4")
response = model.prompt("Explain quantum computing in one sentence")

# Get cost
cost = response.cost()
if cost:
    print(f"Cost: ${cost.total_cost:.6f}")
    print(f"  Input:  ${cost.input_cost:.6f} ({response.input_tokens} tokens)")
    print(f"  Output: ${cost.output_cost:.6f} ({response.output_tokens} tokens)")
```

### Custom estimator
```python
from llm.costs import CostEstimator

# Use custom pricing data
estimator = CostEstimator("/path/to/custom/pricing.json")
cost = response.cost(estimator)
```

## Key Differences from Original Plan

### ❌ Removed Features
- `llm logs cost` command - NOT implementing
- `llm cost-update` command - NOT implementing  
- `llm cost-models` command - NOT implementing
- Separate cost reporting interface

### ✅ Simplified Approach
- Cost estimates appear automatically when using `-u/--usage`
- Integration into existing workflow
- Less code to maintain
- More intuitive for users

### 🎯 Core Feature Remains
- Python API: `response.cost()` - YES, still implementing
- Cost calculation engine - YES, core functionality
- Pricing data management - YES, bundled with package
- Model ID matching - YES, fuzzy matching included
- Historical pricing - YES, date-based pricing

## Deployment Checklist

- [ ] All tests passing
- [ ] Coverage >90%
- [ ] Documentation complete and accurate
- [ ] CHANGELOG.md updated
- [ ] Version bumped in pyproject.toml
- [ ] pricing_data.json bundled with package
- [ ] README.md examples tested
- [ ] `-u` flag behavior documented
- [ ] Clean git history

## Success Metrics

- [ ] Cost appears correctly with `-u` flag for known models
- [ ] Cost calculation is accurate
- [ ] No cost shown (gracefully) for unknown models
- [ ] Response.cost() Python API works
- [ ] No breaking changes to existing code
- [ ] Performance impact is negligible
- [ ] Tests achieve >90% coverage
- [ ] User experience is seamless

