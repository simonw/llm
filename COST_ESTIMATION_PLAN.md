# Cost Estimation Feature - Implementation Plan

## Overview
Add functionality to calculate cost estimates for LLM prompt responses using pricing data from llm-prices.com. This will NOT store costs in the database, but calculate them on-demand using cached pricing information.

## Data Source Analysis

### Pricing Data Structure
The data from https://www.llm-prices.com/historical-v1.json contains:

```json
{
  "prices": [
    {
      "id": "gpt-4.1",
      "vendor": "openai",
      "name": "GPT-4.1",
      "input": 2.0,           // $ per million tokens
      "output": 8.0,          // $ per million tokens
      "input_cached": 0.5,    // $ per million tokens (optional)
      "from_date": null,      // ISO date or null
      "to_date": null         // ISO date or null
    }
  ]
}
```

**Key observations:**
- 77 total pricing entries
- Prices are in USD per million tokens
- Some models have historical pricing (from_date/to_date)
- Some models support cached input pricing (input_cached)
- Model IDs may not exactly match LLM's internal model_id format

## Architecture

### 1. Module Structure

```
llm/
├── costs.py              # New module for cost estimation
├── models.py             # Modify Response class
└── cli.py                # Add cost-related CLI commands

tests/
├── test_costs.py         # New test file
└── fixtures/
    └── pricing_data.json # Test fixture with sample pricing
```

### 2. Core Components

#### 2.1 Cost Estimator (`llm/costs.py`)

```python
class CostEstimator:
    """
    Manages pricing data and calculates costs for LLM responses.
    """
    
    def __init__(self, pricing_data_path: Optional[str] = None):
        """
        Initialize with optional custom pricing data path.
        Defaults to bundled pricing_data.json
        """
        pass
    
    def get_price(
        self, 
        model_id: str, 
        date: Optional[datetime] = None
    ) -> Optional[PriceInfo]:
        """
        Get pricing info for a model at a specific date.
        Returns None if no pricing found.
        """
        pass
    
    def calculate_cost(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: Optional[int] = None,
        date: Optional[datetime] = None
    ) -> Optional[Cost]:
        """
        Calculate cost for a response.
        """
        pass
    
    def update_pricing_data(self, force: bool = False):
        """
        Download latest pricing data from llm-prices.com
        """
        pass

@dataclass
class PriceInfo:
    """Pricing information for a model"""
    id: str
    vendor: str
    name: str
    input_price: float        # $ per million tokens
    output_price: float       # $ per million tokens
    cached_input_price: Optional[float] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None

@dataclass
class Cost:
    """Calculated cost for a response"""
    input_cost: float
    output_cost: float
    cached_cost: float
    total_cost: float
    currency: str = "USD"
    model_id: str = ""
    price_info: Optional[PriceInfo] = None
```

#### 2.2 Response Integration (`llm/models.py`)

Add methods to the `Response` class:

```python
class Response(_BaseResponse):
    # ... existing code ...
    
    def cost(
        self, 
        estimator: Optional[CostEstimator] = None
    ) -> Optional[Cost]:
        """
        Calculate cost for this response.
        Uses default estimator if not provided.
        Returns None if pricing not available.
        """
        if estimator is None:
            estimator = get_default_estimator()
        
        return estimator.calculate_cost(
            model_id=self.resolved_model or self.model.model_id,
            input_tokens=self.input_tokens or 0,
            output_tokens=self.output_tokens or 0,
            cached_tokens=self._get_cached_tokens(),
            date=self.datetime_utc()
        )
    
    def _get_cached_tokens(self) -> Optional[int]:
        """Extract cached token count from token_details if available"""
        if self.token_details:
            # Look for common keys used by providers
            # e.g., "cache_read_input_tokens" for Anthropic
            return self.token_details.get('cache_read_input_tokens')
        return None
```

#### 2.3 CLI Integration (`llm/cli.py`)

Enhance existing `--usage` / `-u` flag to include cost estimates:

**Current behavior:**
```bash
llm "Hello" -m gpt-4 -u
# Shows: Token usage: 10 input, 5 output
```

**Enhanced behavior:**
```bash
llm "Hello" -m gpt-4 -u
# Shows: Token usage: 10 input, 5 output
#        Cost: $0.000450 ($0.000300 input, $0.000150 output)
```

**Modifications needed:**

1. **Update `token_usage_string()` in `llm/utils.py`**
   - Add optional cost calculation
   - Enhance format to include cost when available
   - Keep backward compatibility

2. **Update `llm prompt` command (line ~901 in cli.py)**
   - Pass model_id and datetime to token_usage_string
   - Display cost in yellow alongside token usage

3. **Update `llm logs` command (line ~2182 in cli.py)**
   - Include cost estimate in usage section
   - Format: "## Token usage\n\n{tokens}\nCost: {cost}"

### 3. Implementation Details

#### 3.1 Enhanced token_usage_string Function

Modify `llm/utils.py::token_usage_string()` to optionally include costs:

```python
def token_usage_string(
    input_tokens, 
    output_tokens, 
    token_details,
    model_id: Optional[str] = None,
    datetime_utc: Optional[datetime] = None,
    show_cost: bool = True
) -> str:
    """
    Format token usage string, optionally including cost estimate.
    
    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens  
        token_details: Additional token details dict
        model_id: Model identifier for cost lookup
        datetime_utc: Response datetime for historical pricing
        show_cost: Whether to include cost estimate
    
    Returns:
        Formatted string like: "10 input, 5 output, Cost: $0.00045"
    """
    bits = []
    if input_tokens is not None:
        bits.append(f"{format(input_tokens, ',')} input")
    if output_tokens is not None:
        bits.append(f"{format(output_tokens, ',')} output")
    if token_details:
        bits.append(json.dumps(token_details))
    
    # Add cost estimate if requested and possible
    if show_cost and model_id:
        from .costs import get_default_estimator
        estimator = get_default_estimator()
        
        cached_tokens = None
        if token_details:
            # Extract cached tokens from various provider formats
            cached_tokens = (
                token_details.get('cache_read_input_tokens') or  # Anthropic
                token_details.get('cached_tokens') or            # Generic
                None
            )
        
        cost = estimator.calculate_cost(
            model_id=model_id,
            input_tokens=input_tokens or 0,
            output_tokens=output_tokens or 0,
            cached_tokens=cached_tokens,
            date=datetime_utc
        )
        
        if cost:
            cost_str = f"${cost.total_cost:.6f}"
            if cost.cached_cost > 0:
                cost_str += f" (${cost.input_cost:.6f} input, ${cost.output_cost:.6f} output, ${cost.cached_cost:.6f} cached)"
            else:
                cost_str += f" (${cost.input_cost:.6f} input, ${cost.output_cost:.6f} output)"
            bits.append(f"Cost: {cost_str}")
    
    return ", ".join(bits)
```

#### 3.2 Pricing Data Management

**Bundled Data:**
- Include a snapshot of pricing_data.json in the package
- Located at `llm/pricing_data.json`
- Updated periodically with package releases

**Caching Strategy:**
- User cache location: `~/.cache/llm/pricing_data.json`
- Check age on first access
- Auto-update if older than 7 days (configurable)
- Manual update via `llm cost-update`

**Model ID Matching:**
- Try exact match first
- Implement fuzzy matching for common variations
- Example: "gpt-4o-2024-08-06" → "gpt-4o"
- Log warnings for unmatched models

#### 3.2 Historical Pricing

When from_date/to_date are specified:
1. Use response datetime to find applicable price
2. Fall back to latest price if no historical match
3. Indicate in output whether historical or current pricing used

#### 3.3 Error Handling

- Gracefully handle missing pricing data
- Return `None` for unavailable costs
- Provide clear error messages
- Don't break existing functionality

### 4. Testing Strategy

#### 4.1 Unit Tests (`tests/test_costs.py`)

```python
def test_load_pricing_data():
    """Test loading and parsing pricing data"""
    
def test_exact_model_match():
    """Test finding price for exact model ID"""
    
def test_fuzzy_model_match():
    """Test fuzzy matching for model variations"""
    
def test_historical_pricing():
    """Test selecting correct price based on date"""
    
def test_cost_calculation():
    """Test basic cost calculation"""
    
def test_cached_tokens():
    """Test cost calculation with cached tokens"""
    
def test_missing_pricing():
    """Test graceful handling of unknown models"""
    
def test_response_cost_method():
    """Test Response.cost() integration"""
```

#### 4.2 Integration Tests

```python
def test_cli_logs_cost():
    """Test llm logs cost command"""
    
def test_cli_cost_update():
    """Test llm cost-update command"""
    
def test_cli_cost_models():
    """Test llm cost-models command"""
```

#### 4.3 Test Fixtures

Create `tests/fixtures/pricing_data.json` with subset of real data for testing.

### 5. Documentation

#### 5.1 User Documentation

Add to `docs/` directory:
- `docs/costs.md` - Complete cost estimation guide
- Update `docs/logging.md` - Add cost section
- Update `docs/cli-reference.md` - Document new commands

#### 5.2 API Documentation

Document in docstrings:
- `CostEstimator` class and methods
- `Response.cost()` method
- `PriceInfo` and `Cost` dataclasses

### 6. Implementation Order

1. **Phase 1: Core functionality**
   - Create `llm/costs.py` with basic structure
   - Implement pricing data loading
   - Implement basic cost calculation
   - Add unit tests

2. **Phase 2: Integration**
   - Add `Response.cost()` method
   - Bundle pricing_data.json
   - Add integration tests

3. **Phase 3: CLI**
   - Implement `llm logs cost` command
   - Implement `llm cost-update` command
   - Implement `llm cost-models` command
   - Add CLI tests

4. **Phase 4: Polish**
   - Add fuzzy model matching
   - Improve error messages
   - Add comprehensive documentation
   - Update examples

### 7. Future Enhancements (Out of Scope)

These could be added later:
- Cost budgets and warnings
- Cost tracking over time with visualizations
- Custom pricing overrides
- Multi-currency support
- Cost prediction for prompts before execution
- Integration with actual provider billing APIs

## Example Usage

### Python API

```python
import llm

# Get a response
model = llm.get_model("gpt-4")
response = model.prompt("Explain quantum computing")

# Get cost estimate
cost = response.cost()
if cost:
    print(f"Input: ${cost.input_cost:.4f}")
    print(f"Output: ${cost.output_cost:.4f}")
    print(f"Total: ${cost.total_cost:.4f}")
else:
    print("Pricing not available for this model")

# Use custom estimator
from llm.costs import CostEstimator

estimator = CostEstimator("/path/to/custom/pricing.json")
cost = response.cost(estimator)
```

### CLI

```bash
# Run a prompt with usage info (includes cost)
llm "Explain quantum computing" -m gpt-4 -u
# Output:
# [response text]
# Token usage: 15 input, 127 output, Cost: $0.004110 ($0.000450 input, $0.003660 output)

# View logged response with usage (includes cost)
llm logs -1 -u
# Shows token usage and cost estimate

# Cost is automatically included whenever -u/--usage flag is used
llm logs list --limit 10 -u
```

## Open Questions

1. **Model ID normalization**: How to handle model ID variations?
   - Decision: Implement simple fuzzy matching with documented mappings
   
2. **Pricing data freshness**: How often to auto-update?
   - Decision: 7 days default, configurable, manual override available

3. **Decimal precision**: How many decimal places for costs?
   - Decision: 4 decimal places for display, full precision in calculations

4. **Missing tokens**: How to handle responses without token counts?
   - Decision: Return None for cost, log info message

## Success Criteria

- [x] Pricing data successfully loaded and cached
- [x] Cost calculated accurately for known models
- [x] Response.cost() method works correctly
- [x] CLI commands provide useful cost information
- [x] Tests achieve >90% coverage for new code
- [x] Documentation is clear and complete
- [x] Existing functionality unaffected
