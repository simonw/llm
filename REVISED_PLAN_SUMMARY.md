# Cost Estimation Feature - REVISED PLAN SUMMARY

## 🎯 Key Change: Integration with `-u/--usage` Flag

**Original Plan:** Separate `llm logs cost` commands
**Revised Plan:** Integrate cost estimates into existing `-u/--usage` flag

## Why This Approach is Better

1. **More intuitive** - Users already use `-u` to see token usage
2. **Less code** - No new CLI commands to maintain
3. **Better UX** - Cost appears right when you want usage info
4. **Consistent** - Works the same in `llm prompt` and `llm logs`

## What Gets Built

### ✅ Core Components (Unchanged)

```
llm/
├── costs.py              # NEW - CostEstimator, Cost, PriceInfo
├── models.py             # MODIFIED - Add Response.cost()
├── utils.py              # MODIFIED - Enhance token_usage_string()
└── pricing_data.json     # NEW - Bundled pricing data
```

### ✅ Python API (Unchanged)

```python
import llm

model = llm.get_model("gpt-4")
response = model.prompt("Hello")

# Direct cost access
cost = response.cost()
if cost:
    print(f"Total: ${cost.total_cost:.6f}")
```

### ⚡ CLI Integration (NEW APPROACH)

**Before:**
```bash
llm "Hello" -m gpt-4 -u
# Token usage: 10 input, 5 output
```

**After:**
```bash
llm "Hello" -m gpt-4 -u
# Token usage: 10 input, 5 output, Cost: $0.000450 ($0.000300 input, $0.000150 output)
```

**With logs:**
```bash
llm logs -1 -u
# Shows response with token usage and cost
```

## Implementation Overview

### Phase 1: Core (llm/costs.py)
- `CostEstimator` class
- `PriceInfo` and `Cost` dataclasses
- Model ID matching (exact + fuzzy)
- Historical pricing support
- Bundle pricing_data.json

### Phase 2: Integration
- Add `Response.cost()` method
- Update exports in `__init__.py`

### Phase 3: CLI Enhancement
- Modify `token_usage_string()` in utils.py
  - Add optional `model_id` parameter
  - Add optional `datetime_utc` parameter
  - Calculate and append cost if available
- Update `llm prompt` command (~line 901)
- Update `llm logs` command (~line 2182)

### Phase 4: Polish
- Documentation
- Tests (>90% coverage)
- Error handling

## Key Files to Modify

| File | Change | Complexity |
|------|--------|------------|
| `llm/costs.py` | Create new | High |
| `llm/models.py` | Add Response.cost() | Medium |
| `llm/utils.py` | Enhance token_usage_string() | Medium |
| `llm/cli.py` | Update 2 call sites | Low |
| `llm/__init__.py` | Add exports | Low |
| `tests/test_costs.py` | Create new | High |

## Example Output

### Basic prompt with -u
```bash
$ llm "Explain quantum computing" -m gpt-4 -u
Quantum computing uses quantum mechanical phenomena like superposition 
and entanglement to perform computations that would be impractical on 
classical computers.

Token usage: 15 input, 127 output, Cost: $0.004110 ($0.000450 input, $0.003660 output)
```

### Prompt with cached tokens (Anthropic)
```bash
$ llm "Follow-up question" -m claude-3-opus -u
[response]

Token usage: 1,000 input, 500 output, {"cache_read_input_tokens": 2000}, Cost: $0.052500 ($0.015000 input, $0.037500 output, $0.003000 cached)
```

### Unknown model (graceful)
```bash
$ llm "Hello" -m unknown-model -u
Hello! How can I help you?

Token usage: 10 input, 5 output
# No cost shown - pricing not available
```

### Logs with usage
```bash
$ llm logs -1 -u
## Response
Hello! How can I help you?

## Token usage
10 input, 5 output, Cost: $0.000015 ($0.000010 input, $0.000005 output)
```

## What's NOT Being Built

### ❌ Removed from Original Plan

1. **`llm logs cost` command** - Cost integrated into `-u` instead
2. **`llm cost-update` command** - Manual updates not needed initially
3. **`llm cost-models` command** - Can be added later if needed
4. **Cost aggregation/reporting** - Future enhancement
5. **Auto-update pricing cache** - Start with bundled data

## Implementation Checklist

See `IMPLEMENTATION_CHECKLIST_REVISED.md` for detailed tasks.

**High-level phases:**
- [x] Planning complete
- [ ] Phase 1: Core functionality (llm/costs.py)
- [ ] Phase 2: Integration (Response.cost())
- [ ] Phase 3: CLI enhancement (token_usage_string)
- [ ] Phase 4: Documentation & tests

## Testing Strategy

### Unit Tests
- Pricing data loading
- Model ID matching (exact + fuzzy)
- Cost calculations
- Historical pricing
- Edge cases

### Integration Tests
- Response.cost() method
- CLI output with -u flag
- Backward compatibility

### Manual Testing
```bash
# Test various models
llm "Test" -m gpt-4 -u
llm "Test" -m claude-3-opus -u
llm "Test" -m gpt-3.5-turbo -u

# Test logs
llm logs -1 -u
llm logs list -n 5 -u

# Test unknown model
llm "Test" -m fake-model -u

# Python API
python -c "import llm; r = llm.get_model('gpt-4').prompt('Hi'); print(r.cost())"
```

## Success Criteria

- [x] Plan revised and documented
- [ ] Cost appears when using `-u` flag
- [ ] Cost calculation is accurate
- [ ] Unknown models handled gracefully
- [ ] No breaking changes
- [ ] Tests >90% coverage
- [ ] Documentation complete
- [ ] Performance impact minimal

## Timeline Estimate

| Phase | Estimated Time | Complexity |
|-------|----------------|------------|
| Phase 1: Core | 1-2 days | High |
| Phase 2: Integration | 0.5 day | Medium |
| Phase 3: CLI | 0.5 day | Low |
| Phase 4: Polish | 1 day | Medium |
| **Total** | **3-4 days** | |

## Next Steps

1. **Start Phase 1**: Create `llm/costs.py` with core functionality
2. **Follow checklist**: Use `IMPLEMENTATION_CHECKLIST_REVISED.md`
3. **Reference examples**: See `EXAMPLE_TESTS.py`
4. **Check plan details**: See `COST_ESTIMATION_PLAN.md` (updated)

---

**Ready to implement!** The revised approach is simpler, more intuitive, and easier to maintain. 🚀
