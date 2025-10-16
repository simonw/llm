# Cost Estimation Feature - Project Summary

This directory contains the complete plan for adding cost estimation capabilities to the LLM project.

## 📋 Documentation Files

1. **COST_ESTIMATION_PLAN.md** (10KB)
   - Comprehensive implementation plan
   - Data source analysis
   - Architecture overview
   - Testing strategy
   - Success criteria

2. **COST_ARCHITECTURE.md**
   - Visual architecture diagrams (Mermaid)
   - Component relationships
   - Data flow sequences
   - Cost calculation logic flowcharts

3. **IMPLEMENTATION_CHECKLIST.md**
   - Step-by-step implementation checklist
   - Organized by implementation phases
   - Code snippets and examples
   - Testing and deployment checklist

4. **EXAMPLE_TESTS.py**
   - Reference test cases
   - Test fixtures
   - Example usage patterns
   - Integration test examples

5. **pricing_data.json** (773 lines)
   - Downloaded from llm-prices.com
   - Contains 77 model pricing entries
   - Will be bundled with the package

## 🎯 Feature Overview

### What It Does
- Calculates cost estimates for LLM API responses
- Uses cached pricing data from llm-prices.com
- Supports historical pricing for date-specific costs
- Handles cached token pricing (e.g., Anthropic's prompt caching)
- No database storage - calculates on-demand

### Key Components

```
llm/
├── costs.py           # NEW: Core cost estimation module
├── models.py          # MODIFIED: Add Response.cost() method
├── cli.py             # MODIFIED: Add cost CLI commands
└── pricing_data.json  # NEW: Bundled pricing data
```

### API Example

```python
import llm

# Get a response
model = llm.get_model("gpt-4")
response = model.prompt("Explain quantum computing")

# Calculate cost
cost = response.cost()
if cost:
    print(f"Total: ${cost.total_cost:.6f}")
    print(f"Input: ${cost.input_cost:.6f} ({response.input_tokens} tokens)")
    print(f"Output: ${cost.output_cost:.6f} ({response.output_tokens} tokens)")
```

### CLI Example

```bash
# Run a prompt
llm "Explain quantum computing" -m gpt-4

# Check the cost
llm logs cost -1

# See all recent costs
llm logs cost --limit 20

# Get total costs by model
llm logs cost --total --group-by model

# Update pricing data
llm cost-update

# List available model pricing
llm cost-models
```

## 📊 Data Structure

Pricing data format from llm-prices.com:
```json
{
  "prices": [
    {
      "id": "gpt-4",
      "vendor": "openai",
      "name": "GPT-4",
      "input": 30.0,           // $ per million tokens
      "output": 60.0,          // $ per million tokens
      "input_cached": null,    // Optional: cached input price
      "from_date": null,       // Optional: historical pricing
      "to_date": null          // Optional: historical pricing
    }
  ]
}
```

## 🏗️ Implementation Phases

### Phase 1: Core Functionality
- Create `llm/costs.py` module
- Implement `CostEstimator` class
- Define `PriceInfo` and `Cost` dataclasses
- Bundle pricing data
- Write unit tests

### Phase 2: Integration
- Add `Response.cost()` method
- Update exports in `__init__.py`
- Write integration tests

### Phase 3: CLI Commands
- Add `llm logs cost` command
- Add `llm cost-update` command
- Add `llm cost-models` command
- Write CLI tests

### Phase 4: Documentation & Polish
- Write user documentation
- Add docstrings and type hints
- Error handling and logging
- Performance optimization

## 🧪 Testing Strategy

### Unit Tests (tests/test_costs.py)
- Pricing data loading
- Model ID matching (exact and fuzzy)
- Cost calculations
- Historical pricing
- Edge cases

### Integration Tests
- Response.cost() method
- Token detail extraction
- Custom estimators

### CLI Tests (tests/test_cli_costs.py)
- All CLI commands
- Output formatting
- Error scenarios

### Target: >90% code coverage

## 🎨 Key Features

1. **Automatic Pricing Updates**
   - Cached pricing data at `~/.cache/llm/pricing_data.json`
   - Auto-update when cache is stale (7 days)
   - Manual update via `llm cost-update`

2. **Fuzzy Model Matching**
   - Handles model version variations
   - Example: "gpt-4-0613" → "gpt-4"
   - "claude-3-opus-20240229" → "claude-3-opus"

3. **Historical Pricing**
   - Matches response date to pricing period
   - Accurate costs for old responses
   - Falls back to current pricing if unavailable

4. **Cached Token Support**
   - Recognizes cached tokens in token_details
   - Applies appropriate cached pricing
   - Currently supports Anthropic's format

5. **Flexible Output**
   - Table, JSON, or CSV formats
   - Grouping and filtering options
   - Summary statistics

## ⚠️ Important Considerations

### Model ID Matching
- LLM's internal model IDs may differ from pricing data IDs
- Fuzzy matching handles common variations
- Unknown models return `None` for cost
- Warnings logged for model mismatches

### Pricing Accuracy
- Prices are estimates based on public data
- May not reflect enterprise/custom pricing
- Historical pricing may be incomplete
- Always verify with actual provider bills

### Token Counting
- Requires response to have token counts
- Costs are `None` if tokens unavailable
- Different providers count tokens differently

### No Database Storage
- Costs calculated on-demand, not stored
- Allows retroactive cost calculation
- Easy to update pricing without migration

## 🔧 Configuration

### Environment Variables (Future)
```bash
# Custom pricing data location
LLM_PRICING_DATA=/path/to/custom/pricing.json

# Cache refresh interval (days)
LLM_PRICING_CACHE_TTL=7

# Enable cost warnings for high-cost requests
LLM_COST_WARNINGS=true
LLM_COST_WARNING_THRESHOLD=1.00
```

## 📈 Future Enhancements

Not included in initial release, but potential additions:

1. **Cost Budgets**
   - Set cost limits per conversation/day/month
   - Warnings when approaching limit
   - Automatic throttling

2. **Cost Tracking**
   - Time-series cost analysis
   - Cost trends and visualizations
   - Export to CSV/JSON

3. **Cost Optimization**
   - Suggest cheaper alternative models
   - Identify high-cost patterns
   - Prompt optimization recommendations

4. **Provider Integration**
   - Direct integration with provider billing APIs
   - Real-time cost tracking
   - Reconciliation with actual bills

5. **Advanced Features**
   - Custom pricing overrides
   - Multi-currency support
   - Cost allocation by project/team
   - Predictive cost estimation

## 📚 Additional Resources

- Pricing data source: https://www.llm-prices.com/
- LLM project: https://github.com/simonw/llm
- LLM documentation: https://llm.datasette.io/

## 🚀 Getting Started

1. **Review the plan**: Read `COST_ESTIMATION_PLAN.md`
2. **Check architecture**: Review `COST_ARCHITECTURE.md` diagrams
3. **Follow checklist**: Use `IMPLEMENTATION_CHECKLIST.md`
4. **Reference tests**: See `EXAMPLE_TESTS.py`
5. **Start coding**: Begin with Phase 1

## ✅ Success Metrics

- [ ] All tests passing (>90% coverage)
- [ ] Cost calculated accurately for major providers
- [ ] CLI commands work as expected
- [ ] Documentation is clear and complete
- [ ] No breaking changes to existing code
- [ ] Performance impact is minimal
- [ ] User feedback is positive

---

**Ready to implement?** Start with Phase 1 in the implementation checklist! 🎉
