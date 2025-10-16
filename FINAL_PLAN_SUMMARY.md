# Cost Estimation Feature - FINAL IMPLEMENTATION PLAN

## 🎯 Overview

Add cost estimation to LLM project by:
1. **Fetching** pricing data from llm-prices.com on first use
2. **Caching** in user directory (`~/.local/share/io.datasette.llm/historical-v1.json`)
3. **Integrating** cost display into existing `-u/--usage` flag
4. **Supporting** both sync and async Response classes

## 🔄 Key Changes from Initial Discussion

| Aspect | Initial Plan | Final Plan |
|--------|-------------|-----------|
| Pricing data | Bundle with package | **Fetch on demand** |
| Cache location | Package directory | **`user_dir() / "historical-v1.json"`** |
| Cache refresh | 7 days | **24 hours** |
| Filename | `pricing_data.json` | **`historical-v1.json`** (matches source) |
| CLI | Separate commands | **Integrate with `-u` flag** |
| Async support | Not planned | **AsyncResponse.cost()** method |

## 💡 User Experience

### Before (Current)
```bash
$ llm "Hello" -m gpt-4 -u
Hello! How can I help you?

Token usage: 10 input, 5 output
```

### After (With Cost Estimation)
```bash
$ llm "Hello" -m gpt-4 -u
Hello! How can I help you?

Token usage: 10 input, 5 output, Cost: $0.000450 ($0.000300 input, $0.000150 output)
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  User runs: llm "prompt" -m gpt-4 -u                       │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  token_usage_string() │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  CostEstimator        │
         │  (singleton)          │
         └───────────┬───────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
    First use              Subsequent uses
         │                       │
         ▼                       ▼
  ┌────────────┐          ┌────────────┐
  │ Fetch from │          │ Load from  │
  │ llm-prices │          │ cache file │
  │    .com    │          │  (instant) │
  └─────┬──────┘          └─────┬──────┘
        │                       │
        ▼                       │
  ┌────────────┐                │
  │ Save to    │                │
  │ cache      │                │
  └─────┬──────┘                │
        │                       │
        └───────────┬───────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │  Calculate cost     │
         └──────────┬──────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │  Display with cost  │
         └─────────────────────┘
```

## 📦 What Gets Built

### New Files
```
llm/
└── costs.py                                   # ~400 lines
    ├── CostEstimator (sync)
    ├── AsyncCostEstimator (async)
    ├── Cost dataclass
    ├── PriceInfo dataclass
    └── Helper functions

tests/
└── test_costs.py                              # ~500 lines
    ├── Unit tests
    ├── Integration tests
    └── Mock network tests
```

### Modified Files
```
llm/
├── models.py                                  # +30 lines
│   ├── Response.cost() - sync method
│   └── AsyncResponse.cost() - async method
│
├── utils.py                                   # +40 lines
│   └── token_usage_string() - enhanced with cost
│
├── cli.py                                     # +10 lines
│   └── Update usage display calls (2 places)
│
└── __init__.py                                # +5 lines
    └── Export Cost, CostEstimator, etc.
```

### User Directory (Runtime)
```
~/.local/share/io.datasette.llm/
├── logs.db
├── keys.json
├── aliases.json
└── historical-v1.json            # NEW: Cached pricing data
```

## 🔧 Implementation Details

### 1. CostEstimator (Sync)

```python
class CostEstimator:
    """Synchronous cost estimator with lazy loading."""
    
    _instance = None
    _pricing_data = None
    
    def __init__(self, force_refresh: bool = False):
        self._ensure_pricing_data(force_refresh)
    
    def _ensure_pricing_data(self, force_refresh: bool = False):
        """Fetch/load pricing data with 24-hour cache."""
        cache_path = llm.user_dir() / "historical-v1.json"
        
        # Check if cache exists and is fresh (< 24 hours)
        if not force_refresh and cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < 24 * 3600:
                self._pricing_data = json.loads(cache_path.read_text())
                return
        
        # Fetch fresh data
        try:
            response = httpx.get(
                "https://www.llm-prices.com/historical-v1.json",
                timeout=10.0
            )
            data = response.json()
            cache_path.write_text(json.dumps(data))
            self._pricing_data = data
        except Exception:
            # Fall back to cache if available
            if cache_path.exists():
                self._pricing_data = json.loads(cache_path.read_text())
            else:
                raise
    
    def calculate_cost(...) -> Optional[Cost]:
        """Calculate cost for given tokens and model."""
        # Implementation...
```

### 2. AsyncCostEstimator

```python
class AsyncCostEstimator:
    """Async version for AsyncResponse."""
    
    async def _ensure_pricing_data(self, force_refresh: bool = False):
        """Async fetch/load with same logic."""
        # Similar logic but with:
        # - httpx.AsyncClient for fetching
        # - await for async operations
```

### 3. Response Integration

```python
# llm/models.py

class Response(_BaseResponse):
    def cost(self, estimator=None) -> Optional[Cost]:
        """Sync cost calculation."""
        if estimator is None:
            from .costs import get_default_estimator
            estimator = get_default_estimator()  # May block on first use
        
        return estimator.calculate_cost(
            model_id=self.resolved_model or self.model.model_id,
            input_tokens=self.input_tokens or 0,
            output_tokens=self.output_tokens or 0,
            cached_tokens=self._get_cached_tokens(),
            date=self.datetime_utc()
        )

class AsyncResponse(_BaseResponse):
    async def cost(self, estimator=None) -> Optional[Cost]:
        """Async cost calculation."""
        if estimator is None:
            from .costs import get_async_estimator
            estimator = await get_async_estimator()
        
        return await estimator.calculate_cost(...)
```

### 4. CLI Integration

```python
# llm/utils.py

def token_usage_string(
    input_tokens, 
    output_tokens, 
    token_details,
    model_id: Optional[str] = None,          # NEW
    datetime_utc: Optional[datetime] = None, # NEW
    show_cost: bool = True                   # NEW
) -> str:
    """Enhanced to include cost when model_id provided."""
    bits = []
    # ... existing token formatting ...
    
    if show_cost and model_id:
        try:
            from .costs import get_default_estimator
            cost = get_default_estimator().calculate_cost(...)
            if cost:
                bits.append(f"Cost: ${cost.total_cost:.6f} (...)")
        except Exception:
            pass  # Silently skip cost on error
    
    return ", ".join(bits)
```

## 🚦 Error Handling

### Scenario Matrix

| Scenario | Cache Exists | Network | Behavior |
|----------|--------------|---------|----------|
| First use | ❌ No | ✅ Yes | Fetch → Save → Show cost |
| First use | ❌ No | ❌ No | Skip cost silently |
| Fresh cache | ✅ Yes (< 24h) | N/A | Load cache → Show cost |
| Stale cache | ✅ Yes (> 24h) | ✅ Yes | Fetch → Update → Show cost |
| Stale cache | ✅ Yes (> 24h) | ❌ No | Use stale cache → Show cost |

### Key Principles

1. **Never break the tool** - Missing pricing doesn't prevent usage display
2. **Fail gracefully** - Network errors just skip cost
3. **Use stale data** - Better than nothing if network unavailable
4. **Silent failures** - Don't spam users with pricing errors

## 📊 Performance

### First Use (Cold Start)
```
With network:
├── HTTP request: ~200-500ms
├── JSON parse: ~10ms
├── File write: ~5ms
└── Total delay: ~215-515ms (once)

Without network:
└── No delay (cost skipped)
```

### Subsequent Uses (Warm Cache)
```
Cache fresh (< 24h):
├── File read: ~2ms
├── JSON parse: ~10ms
└── Total delay: ~12ms (negligible)
```

### Cache Refresh (Stale Cache)
```
Background refresh attempt:
├── Try fetch (with timeout)
├── If success: update cache
└── If failure: use stale cache
    (user sees cost either way)
```

## ✅ Implementation Phases

### Phase 1: Core (2 days)
- [ ] Create `llm/costs.py`
- [ ] Implement `CostEstimator` with lazy loading
- [ ] Implement `AsyncCostEstimator`
- [ ] Add cache management (24-hour TTL)
- [ ] Implement cost calculation logic
- [ ] Add model ID matching (exact + fuzzy)
- [ ] Write unit tests

### Phase 2: Integration (0.5 day)
- [ ] Add `Response.cost()` method
- [ ] Add `AsyncResponse.cost()` method
- [ ] Add `_get_cached_tokens()` helper
- [ ] Update exports in `__init__.py`
- [ ] Write integration tests

### Phase 3: CLI Enhancement (0.5 day)
- [ ] Enhance `token_usage_string()` in utils.py
- [ ] Update `llm prompt` command (line ~901)
- [ ] Update `llm logs` command (line ~2182)
- [ ] Write CLI tests

### Phase 4: Documentation & Polish (1 day)
- [ ] Add docstrings
- [ ] Error handling review
- [ ] Performance testing
- [ ] Write user documentation
- [ ] Update README

**Total: 4 days**

## 📝 Testing Strategy

### Unit Tests
```python
test_fetch_pricing_data()
test_cache_saves_correctly()
test_cache_age_detection()
test_load_from_stale_cache_on_network_error()
test_exact_model_match()
test_fuzzy_model_match()
test_calculate_cost_basic()
test_calculate_cost_with_cached_tokens()
test_historical_pricing()
```

### Integration Tests
```python
test_response_cost_sync()
test_response_cost_async()
test_first_use_with_network()
test_first_use_without_network()
test_usage_string_includes_cost()
```

### Manual Testing
```bash
# Test first use
rm ~/.local/share/io.datasette.llm/historical-v1.json
llm "Test" -m gpt-4 -u

# Test cached use
llm "Test" -m gpt-4 -u  # Should be instant

# Test stale cache
touch -t 202401010000 ~/.local/share/io.datasette.llm/historical-v1.json
llm "Test" -m gpt-4 -u  # Should refresh

# Test network failure
# (disconnect network)
llm "Test" -m gpt-4 -u  # Should use stale cache or skip
```

## 🎯 Success Criteria

- [x] Planning complete
- [ ] Cost appears with `-u` flag
- [ ] First fetch works correctly
- [ ] Cache is created in user_dir()
- [ ] 24-hour refresh works
- [ ] Network failures handled gracefully
- [ ] Sync and async versions both work
- [ ] Tests >90% coverage
- [ ] No breaking changes
- [ ] Documentation complete

## 📚 Documentation Files

See `INDEX.md` for complete navigation. Key files:
- **CACHING_UPDATE.md** - Detailed caching implementation
- **IMPLEMENTATION_CHECKLIST_REVISED.md** - Step-by-step tasks
- **COMPARISON.md** - Why this approach vs alternatives

## 🚀 Next Steps

1. Review `CACHING_UPDATE.md` for implementation details
2. Start Phase 1: Create `llm/costs.py`
3. Follow `IMPLEMENTATION_CHECKLIST_REVISED.md`
4. Reference `EXAMPLE_TESTS.py` for test patterns

---

**Ready to implement!** This approach is simple, fast, and robust. 🎉
