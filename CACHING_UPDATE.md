# Cost Estimation - Caching & Async Updates

## Key Changes Based on Feedback

### 1. ❌ Do NOT Bundle pricing_data.json

**Original plan:** Bundle pricing_data.json with package
**Updated approach:** Fetch on demand and cache in user directory

### 2. ✅ Cache Location

Use `llm.user_dir() / "historical-v1.json"` (same filename as source)

```python
import llm

pricing_cache = llm.user_dir() / "historical-v1.json"
# e.g., ~/.local/share/io.datasette.llm/historical-v1.json
```

### 3. ✅ Cache Refresh Strategy

- Fetch from https://www.llm-prices.com/historical-v1.json on first use
- Re-fetch if cache is older than 24 hours
- Graceful fallback if network unavailable

### 4. ✅ Sync vs Async for Response.cost()

**Problem:** Cost calculation involves I/O (reading cache file, potentially fetching)

**Solution:** 
- `Response.cost()` - **Synchronous** (blocks on first fetch)
- `AsyncResponse.cost()` - **Async** version using aiofiles/httpx async

## Updated Implementation

### CostEstimator with Lazy Loading

```python
# llm/costs.py

import httpx
import json
import time
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta
import llm

PRICING_URL = "https://www.llm-prices.com/historical-v1.json"
CACHE_FILENAME = "historical-v1.json"
CACHE_MAX_AGE_HOURS = 24

class CostEstimator:
    _instance = None
    _pricing_data = None
    _last_loaded = None
    
    def __init__(self, force_refresh: bool = False):
        """Initialize estimator, fetching pricing data if needed."""
        self._ensure_pricing_data(force_refresh)
    
    def _get_cache_path(self) -> Path:
        """Get path to cached pricing data."""
        return llm.user_dir() / CACHE_FILENAME
    
    def _is_cache_fresh(self) -> bool:
        """Check if cache exists and is less than 24 hours old."""
        cache_path = self._get_cache_path()
        if not cache_path.exists():
            return False
        
        age = time.time() - cache_path.stat().st_mtime
        max_age = CACHE_MAX_AGE_HOURS * 3600
        return age < max_age
    
    def _fetch_pricing_data(self) -> dict:
        """Fetch pricing data from remote URL."""
        response = httpx.get(PRICING_URL, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        return response.json()
    
    def _load_from_cache(self) -> dict:
        """Load pricing data from cache file."""
        cache_path = self._get_cache_path()
        return json.loads(cache_path.read_text())
    
    def _save_to_cache(self, data: dict):
        """Save pricing data to cache file."""
        cache_path = self._get_cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(data))
    
    def _ensure_pricing_data(self, force_refresh: bool = False):
        """Ensure pricing data is loaded, fetching if necessary."""
        # Check if we need to refresh
        if force_refresh or not self._is_cache_fresh():
            try:
                # Try to fetch fresh data
                data = self._fetch_pricing_data()
                self._save_to_cache(data)
                self._pricing_data = data
                self._last_loaded = time.time()
            except Exception as e:
                # Fall back to cache if available
                cache_path = self._get_cache_path()
                if cache_path.exists():
                    self._pricing_data = self._load_from_cache()
                    self._last_loaded = time.time()
                else:
                    # No cache and can't fetch - raise error
                    raise Exception(
                        f"Failed to fetch pricing data and no cache available: {e}"
                    )
        else:
            # Cache is fresh, just load it
            if self._pricing_data is None:
                self._pricing_data = self._load_from_cache()
                self._last_loaded = time.time()
    
    def calculate_cost(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: Optional[int] = None,
        date: Optional[datetime] = None
    ) -> Optional[Cost]:
        """Calculate cost for a response."""
        # Implementation here...
        pass


def get_default_estimator() -> CostEstimator:
    """Get singleton instance of CostEstimator."""
    if CostEstimator._instance is None:
        CostEstimator._instance = CostEstimator()
    return CostEstimator._instance
```

### Async Version

```python
# llm/costs.py (continued)

import httpx

class AsyncCostEstimator:
    """Async version of CostEstimator for use with AsyncResponse."""
    
    _instance = None
    _pricing_data = None
    _last_loaded = None
    
    async def _fetch_pricing_data(self) -> dict:
        """Async fetch pricing data from remote URL."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                PRICING_URL, 
                timeout=10.0, 
                follow_redirects=True
            )
            response.raise_for_status()
            return response.json()
    
    async def _ensure_pricing_data(self, force_refresh: bool = False):
        """Async version - ensure pricing data is loaded."""
        if force_refresh or not self._is_cache_fresh():
            try:
                data = await self._fetch_pricing_data()
                self._save_to_cache(data)
                self._pricing_data = data
                self._last_loaded = time.time()
            except Exception as e:
                cache_path = self._get_cache_path()
                if cache_path.exists():
                    self._pricing_data = self._load_from_cache()
                    self._last_loaded = time.time()
                else:
                    raise Exception(
                        f"Failed to fetch pricing data and no cache available: {e}"
                    )
        else:
            if self._pricing_data is None:
                self._pricing_data = self._load_from_cache()
                self._last_loaded = time.time()
    
    # _is_cache_fresh, _load_from_cache, _save_to_cache are same as sync version
    
    async def calculate_cost(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: Optional[int] = None,
        date: Optional[datetime] = None
    ) -> Optional[Cost]:
        """Async calculate cost for a response."""
        await self._ensure_pricing_data()
        # Same calculation logic as sync version
        pass


async def get_async_estimator() -> AsyncCostEstimator:
    """Get singleton instance of AsyncCostEstimator."""
    if AsyncCostEstimator._instance is None:
        AsyncCostEstimator._instance = AsyncCostEstimator()
    return AsyncCostEstimator._instance
```

### Response.cost() Methods

```python
# llm/models.py

class Response(_BaseResponse):
    def cost(
        self, 
        estimator: Optional["CostEstimator"] = None
    ) -> Optional["Cost"]:
        """
        Calculate cost for this response (synchronous).
        
        First call may block while fetching pricing data.
        Subsequent calls use cached data.
        """
        if estimator is None:
            from .costs import get_default_estimator
            estimator = get_default_estimator()
        
        return estimator.calculate_cost(
            model_id=self.resolved_model or self.model.model_id,
            input_tokens=self.input_tokens or 0,
            output_tokens=self.output_tokens or 0,
            cached_tokens=self._get_cached_tokens(),
            date=self.datetime_utc()
        )


class AsyncResponse(_BaseResponse):
    async def cost(
        self, 
        estimator: Optional["AsyncCostEstimator"] = None
    ) -> Optional["Cost"]:
        """
        Calculate cost for this response (asynchronous).
        
        First call may fetch pricing data asynchronously.
        Subsequent calls use cached data.
        """
        if estimator is None:
            from .costs import get_async_estimator
            estimator = await get_async_estimator()
        
        return await estimator.calculate_cost(
            model_id=self.resolved_model or self.model.model_id,
            input_tokens=self.input_tokens or 0,
            output_tokens=self.output_tokens or 0,
            cached_tokens=self._get_cached_tokens(),
            date=self.datetime_utc()
        )
```

### token_usage_string with Lazy Loading

```python
# llm/utils.py

def token_usage_string(
    input_tokens, 
    output_tokens, 
    token_details,
    model_id: Optional[str] = None,
    datetime_utc: Optional[datetime] = None,
    show_cost: bool = True
) -> str:
    """Format token usage string with optional cost."""
    bits = []
    if input_tokens is not None:
        bits.append(f"{format(input_tokens, ',')} input")
    if output_tokens is not None:
        bits.append(f"{format(output_tokens, ',')} output")
    if token_details:
        bits.append(json.dumps(token_details))
    
    # Add cost estimate if requested
    if show_cost and model_id:
        try:
            from .costs import get_default_estimator
            
            estimator = get_default_estimator()
            
            cached_tokens = None
            if token_details:
                cached_tokens = (
                    token_details.get('cache_read_input_tokens') or
                    token_details.get('cached_tokens') or
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
                    cost_str += (
                        f" (${cost.input_cost:.6f} input, "
                        f"${cost.output_cost:.6f} output, "
                        f"${cost.cached_cost:.6f} cached)"
                    )
                else:
                    cost_str += (
                        f" (${cost.input_cost:.6f} input, "
                        f"${cost.output_cost:.6f} output)"
                    )
                bits.append(f"Cost: {cost_str}")
        except Exception:
            # Silently fail if cost calculation errors
            # (e.g., network error on first fetch)
            pass
    
    return ", ".join(bits)
```

## Error Handling Strategy

### First Use (No Cache)

```
User runs: llm "prompt" -m gpt-4 -u

Scenario A: Network available
├── Fetch historical-v1.json
├── Save to cache
├── Calculate cost
└── Display: "Token usage: ... Cost: $X"

Scenario B: Network unavailable
├── Fetch fails
├── No cache exists
├── Silently skip cost
└── Display: "Token usage: ..." (no cost)

Scenario C: Network slow (timeout)
├── Fetch times out after 10s
├── Silently skip cost
└── Display continues without blocking user
```

### Subsequent Uses (Cache Exists)

```
User runs: llm "prompt" -m gpt-4 -u

Cache < 24 hours old:
├── Load from cache (instant)
├── Calculate cost
└── Display with cost

Cache > 24 hours old:
├── Try to fetch new data (background)
├── If fetch succeeds: update cache
├── If fetch fails: use stale cache
└── Display with cost (from cache)
```

## Updated File Structure

```
llm/
├── costs.py           # CostEstimator and AsyncCostEstimator
├── models.py          # Response.cost() and AsyncResponse.cost()
├── utils.py           # Enhanced token_usage_string()
└── cli.py             # Updated usage display

User directory (~/.local/share/io.datasette.llm/):
├── logs.db
├── keys.json
├── aliases.json
└── historical-v1.json    # NEW: Cached pricing data
```

## Testing Considerations

### Unit Tests

```python
def test_fetch_pricing_data():
    """Test fetching from URL"""
    
def test_cache_saves_correctly():
    """Test saving to user_dir"""
    
def test_cache_age_detection():
    """Test 24-hour freshness check"""
    
def test_load_from_stale_cache_on_network_error():
    """Test fallback to stale cache"""
    
def test_error_when_no_cache_and_no_network():
    """Test error handling"""
```

### Integration Tests

```python
def test_first_use_with_network(monkeypatch):
    """Simulate first use with network available"""
    
def test_first_use_without_network(monkeypatch):
    """Simulate first use with network unavailable"""
    
def test_subsequent_use_with_fresh_cache():
    """Test using fresh cache"""
    
def test_cache_refresh_after_24_hours():
    """Test auto-refresh logic"""
```

## Benefits of This Approach

1. **No bundled data** - Package stays small
2. **Always up-to-date** - Fetches latest pricing
3. **Works offline** - Falls back to cache
4. **Fast** - Cache makes subsequent lookups instant
5. **Async support** - Proper async/await for AsyncResponse
6. **Graceful degradation** - Missing pricing doesn't break the tool

## Migration from Original Plan

### Removed
- ❌ Bundle llm/pricing_data.json in package
- ❌ Update MANIFEST.in

### Added
- ✅ Fetch logic in CostEstimator.__init__
- ✅ Cache management in user_dir()
- ✅ 24-hour refresh logic
- ✅ AsyncCostEstimator class
- ✅ AsyncResponse.cost() method
- ✅ Error handling for network failures

### Changed
- Cache location: `user_dir() / "historical-v1.json"`
- First use may have slight delay (< 1 second typically)
- Subsequent uses are instant (from cache)

