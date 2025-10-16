# Cost Estimation Feature - Implementation Checklist

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
  - [ ] `list_models()` - Return all models with pricing
  - [ ] `update_pricing_data()` - Download from llm-prices.com

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

## Phase 3: CLI Commands ✓

### 3.1 Add `llm logs cost` command

- [ ] Modify `llm/cli.py`
- [ ] Add new command group or subcommand
- [ ] Options:
  - [ ] `--limit N` - Show last N responses
  - [ ] `--total` - Show total cost
  - [ ] `--group-by [model|date]` - Group results
  - [ ] `--since DATE` - Filter by date
  - [ ] `--until DATE` - Filter by date
  - [ ] `--format [table|json|csv]` - Output format
  - [ ] `[RESPONSE_ID]` - Optional specific response

- [ ] Output formatting:
  - [ ] Table view with columns: ID, Model, Input, Output, Total
  - [ ] JSON output option
  - [ ] Summary line with totals

### 3.2 Add `llm cost-update` command

- [ ] New command to update pricing data
- [ ] Options:
  - [ ] `--force` - Force update even if recent
  - [ ] `--quiet` - Minimal output

- [ ] Show update status and timestamp

### 3.3 Add `llm cost-models` command

- [ ] List all models with available pricing
- [ ] Options:
  - [ ] `--vendor NAME` - Filter by vendor
  - [ ] `--format [table|json]` - Output format

- [ ] Show: ID, Vendor, Name, Input Price, Output Price

### 3.4 CLI Tests

- [ ] Test cases in `tests/test_cli_costs.py`:
  - [ ] `test_logs_cost_single_response()`
  - [ ] `test_logs_cost_last_n()`
  - [ ] `test_logs_cost_total()`
  - [ ] `test_logs_cost_group_by_model()`
  - [ ] `test_logs_cost_date_filter()`
  - [ ] `test_logs_cost_json_output()`
  - [ ] `test_cost_update()`
  - [ ] `test_cost_models()`
  - [ ] `test_cost_models_vendor_filter()`

## Phase 4: Documentation ✓

### 4.1 API Documentation

- [ ] Create `docs/costs.md`
  - [ ] Overview and introduction
  - [ ] How pricing data works
  - [ ] Python API examples
  - [ ] CLI examples
  - [ ] Model ID matching explained
  - [ ] Historical pricing explained
  - [ ] Limitations and caveats

### 4.2 Update existing docs

- [ ] `docs/logging.md`
  - [ ] Add section on cost estimation
  - [ ] Link to costs.md

- [ ] `docs/cli-reference.md`
  - [ ] Document `llm logs cost`
  - [ ] Document `llm cost-update`
  - [ ] Document `llm cost-models`

- [ ] `docs/python-api.md`
  - [ ] Document `Response.cost()`
  - [ ] Document `CostEstimator` class

- [ ] `README.md`
  - [ ] Add cost estimation to feature list
  - [ ] Add quick example

### 4.3 Docstrings

- [ ] Complete docstrings for all public classes/methods
- [ ] Include examples in docstrings
- [ ] Type hints everywhere

## Phase 5: Polish ✓

### 5.1 Error Handling

- [ ] Graceful handling of missing pricing data
- [ ] Clear error messages for network failures
- [ ] Warnings for model ID mismatches
- [ ] Handle missing token counts

### 5.2 Logging

- [ ] Debug logs for model matching
- [ ] Info logs for cache updates
- [ ] Warning logs for missing pricing

### 5.3 Performance

- [ ] Cache parsed pricing data in memory
- [ ] Lazy load pricing data
- [ ] Efficient model lookup (dict, not list iteration)

### 5.4 Code Quality

- [ ] Run mypy: `mypy llm/costs.py`
- [ ] Run ruff: `ruff llm/costs.py`
- [ ] Run pytest with coverage: `pytest --cov=llm.costs`
- [ ] Aim for >90% test coverage

## Testing Checklist

### Run all tests
```bash
# Unit tests
pytest tests/test_costs.py -v

# Integration tests
pytest tests/test_costs.py tests/test_cli_costs.py -v

# All tests with coverage
pytest --cov=llm.costs --cov-report=html

# Type checking
mypy llm/costs.py

# Linting
ruff llm/costs.py
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

# Test CLI
llm "Hello world" -m gpt-3.5-turbo
llm logs cost -1
llm cost-models
llm cost-update
```

## Example Code Snippets

### Basic usage
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

### List all models with pricing
```python
from llm.costs import get_default_estimator

estimator = get_default_estimator()
models = estimator.list_models()
for model in models:
    print(f"{model.id}: ${model.input_price}/1M input, ${model.output_price}/1M output")
```

## Deployment Checklist

- [ ] All tests passing
- [ ] Coverage >90%
- [ ] Documentation complete
- [ ] CHANGELOG.md updated
- [ ] Version bumped in pyproject.toml
- [ ] pricing_data.json bundled with package
- [ ] README.md examples tested
- [ ] Clean git history

## Future Enhancements (Not for Initial Release)

- Cost budgets and warnings
- Cost tracking over time
- Visualizations/charts
- Custom pricing overrides
- Multi-currency support
- Cost prediction before execution
- Integration with provider billing APIs
- Cost optimization suggestions

