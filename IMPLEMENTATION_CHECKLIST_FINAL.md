# Cost Estimation - FINAL Implementation Checklist

## ⚠️ KEY UPDATES
- **Do NOT bundle** pricing data with package
- **Fetch on demand** from llm-prices.com
- **Cache** in `user_dir() / "historical-v1.json"`
- **24-hour** cache refresh
- **Both sync and async** support

## Phase 1: Core Functionality (2 days)

### 1.1 Create `llm/costs.py` - Basic Structure

- [ ] File setup and imports
  ```python
  import httpx
  import json
  import time
  from pathlib import Path
  from typing import Optional
  from datetime import datetime
  from dataclasses import dataclass
  import llm
  ```

- [ ] Define constants
  ```python
  PRICING_URL = "https://www.llm-prices.com/historical-v1.json"
  CACHE_FILENAME = "historical-v1.json"
  CACHE_MAX_AGE_HOURS = 24
  ```

### 1.2 Dataclasses

- [ ] `PriceInfo` dataclass
  ```python
  @dataclass
  class PriceInfo:
      id: str
      vendor: str
      name: str
      input_price: float
      output_price: float
      cached_input_price: Optional[float] = None
      from_date: Optional[datetime] = None
      to_date: Optional[datetime] = None
  ```

- [ ] `Cost` dataclass
  ```python
  @dataclass
  class Cost:
      input_cost: float
      output_cost: float
      cached_cost: float
      total_cost: float
      currency: str = "USD"
      model_id: str = ""
      price_info: Optional[PriceInfo] = None
  ```

### 1.3 CostEstimator (Sync)

- [ ] Class setup with singleton pattern
  ```python
  class CostEstimator:
      _instance = None
      _pricing_data = None
      _last_loaded = None
  ```

- [ ] `_get_cache_path()` method
  ```python
  def _get_cache_path(self) -> Path:
      return llm.user_dir() / CACHE_FILENAME
  ```

- [ ] `_is_cache_fresh()` method
  ```python
  def _is_cache_fresh(self) -> bool:
      cache_path = self._get_cache_path()
      if not cache_path.exists():
          return False
      age = time.time() - cache_path.stat().st_mtime
      return age < (CACHE_MAX_AGE_HOURS * 3600)
  ```

- [ ] `_fetch_pricing_data()` method
  ```python
  def _fetch_pricing_data(self) -> dict:
      response = httpx.get(PRICING_URL, timeout=10.0, follow_redirects=True)
      response.raise_for_status()
      return response.json()
  ```

- [ ] `_load_from_cache()` method
  ```python
  def _load_from_cache(self) -> dict:
      return json.loads(self._get_cache_path().read_text())
  ```

- [ ] `_save_to_cache()` method
  ```python
  def _save_to_cache(self, data: dict):
      cache_path = self._get_cache_path()
      cache_path.parent.mkdir(parents=True, exist_ok=True)
      cache_path.write_text(json.dumps(data))
  ```

- [ ] `_ensure_pricing_data()` method (main logic)
  ```python
  def _ensure_pricing_data(self, force_refresh: bool = False):
      if force_refresh or not self._is_cache_fresh():
          try:
              data = self._fetch_pricing_data()
              self._save_to_cache(data)
              self._pricing_data = data
          except Exception as e:
              if self._get_cache_path().exists():
                  self._pricing_data = self._load_from_cache()
              else:
                  raise Exception(f"Failed to fetch pricing data: {e}")
      else:
          if self._pricing_data is None:
              self._pricing_data = self._load_from_cache()
  ```

- [ ] `_normalize_model_id()` helper
  ```python
  def _normalize_model_id(self, model_id: str) -> str:
      # Strip date suffixes, etc.
  ```

- [ ] `_find_price()` method (exact match)
  ```python
  def _find_price(self, model_id: str, date: Optional[datetime] = None) -> Optional[PriceInfo]:
      # Search in self._pricing_data["prices"]
  ```

- [ ] `_find_price_fuzzy()` method (fuzzy match)
  ```python
  def _find_price_fuzzy(self, model_id: str) -> Optional[PriceInfo]:
      # Try common variations
  ```

- [ ] `get_price()` public method
  ```python
  def get_price(self, model_id: str, date: Optional[datetime] = None) -> Optional[PriceInfo]:
      self._ensure_pricing_data()
      price = self._find_price(model_id, date)
      if not price:
          price = self._find_price_fuzzy(model_id)
      return price
  ```

- [ ] `calculate_cost()` main method
  ```python
  def calculate_cost(
      self,
      model_id: str,
      input_tokens: int,
      output_tokens: int,
      cached_tokens: Optional[int] = None,
      date: Optional[datetime] = None
  ) -> Optional[Cost]:
      price = self.get_price(model_id, date)
      if not price:
          return None
      
      # Calculate costs per million tokens
      input_cost = (input_tokens * price.input_price) / 1_000_000
      output_cost = (output_tokens * price.output_price) / 1_000_000
      
      cached_cost = 0.0
      if cached_tokens and price.cached_input_price:
          cached_cost = (cached_tokens * price.cached_input_price) / 1_000_000
      
      return Cost(
          input_cost=input_cost,
          output_cost=output_cost,
          cached_cost=cached_cost,
          total_cost=input_cost + output_cost + cached_cost,
          model_id=model_id,
          price_info=price
      )
  ```

- [ ] `get_default_estimator()` singleton function
  ```python
  def get_default_estimator() -> CostEstimator:
      if CostEstimator._instance is None:
          CostEstimator._instance = CostEstimator()
      return CostEstimator._instance
  ```

### 1.4 AsyncCostEstimator

- [ ] Copy structure from CostEstimator

- [ ] Make `_fetch_pricing_data()` async
  ```python
  async def _fetch_pricing_data(self) -> dict:
      async with httpx.AsyncClient() as client:
          response = await client.get(PRICING_URL, timeout=10.0)
          response.raise_for_status()
          return response.json()
  ```

- [ ] Make `_ensure_pricing_data()` async
  ```python
  async def _ensure_pricing_data(self, force_refresh: bool = False):
      # Same logic but with await
  ```

- [ ] Make `calculate_cost()` async
  ```python
  async def calculate_cost(...) -> Optional[Cost]:
      await self._ensure_pricing_data()
      # Rest is same as sync version
  ```

- [ ] `get_async_estimator()` function
  ```python
  async def get_async_estimator() -> AsyncCostEstimator:
      if AsyncCostEstimator._instance is None:
          AsyncCostEstimator._instance = AsyncCostEstimator()
          await AsyncCostEstimator._instance._ensure_pricing_data()
      return AsyncCostEstimator._instance
  ```

### 1.5 Unit Tests (`tests/test_costs.py`)

- [ ] Test fixtures
  ```python
  @pytest.fixture
  def mock_pricing_data():
      return {"prices": [...]}
  
  @pytest.fixture
  def temp_user_dir(tmp_path, monkeypatch):
      monkeypatch.setattr(llm, "user_dir", lambda: tmp_path)
      return tmp_path
  ```

- [ ] `test_fetch_pricing_data()` - with mocked httpx
- [ ] `test_cache_saves_to_correct_location()`
- [ ] `test_cache_age_detection_fresh()`
- [ ] `test_cache_age_detection_stale()`
- [ ] `test_load_from_cache()`
- [ ] `test_fallback_to_stale_cache_on_network_error()`
- [ ] `test_error_when_no_cache_and_network_fails()`
- [ ] `test_exact_model_match()`
- [ ] `test_fuzzy_model_match_gpt4()`
- [ ] `test_fuzzy_model_match_claude()`
- [ ] `test_model_not_found_returns_none()`
- [ ] `test_calculate_cost_basic()`
- [ ] `test_calculate_cost_with_cached_tokens()`
- [ ] `test_calculate_cost_no_pricing_returns_none()`
- [ ] `test_calculate_cost_zero_tokens()`
- [ ] `test_historical_pricing_selection()`
- [ ] `test_async_estimator()` - async version tests

## Phase 2: Integration (0.5 day)

### 2.1 Response.cost() Method

- [ ] Add to `Response` class in `llm/models.py`
  ```python
  def cost(
      self, 
      estimator: Optional["CostEstimator"] = None
  ) -> Optional["Cost"]:
      """Calculate cost for this response."""
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
  ```

- [ ] Add `_get_cached_tokens()` helper
  ```python
  def _get_cached_tokens(self) -> Optional[int]:
      if self.token_details:
          return (
              self.token_details.get('cache_read_input_tokens') or
              self.token_details.get('cached_tokens') or
              None
          )
      return None
  ```

### 2.2 AsyncResponse.cost() Method

- [ ] Add async version to `AsyncResponse` class
  ```python
  async def cost(
      self, 
      estimator: Optional["AsyncCostEstimator"] = None
  ) -> Optional["Cost"]:
      """Calculate cost for this response (async)."""
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

### 2.3 Update Exports

- [ ] Add to `llm/__init__.py`
  ```python
  from .costs import CostEstimator, AsyncCostEstimator, Cost, PriceInfo
  ```

- [ ] Add to `__all__` list
  ```python
  __all__ = [
      # ... existing ...
      "Cost",
      "CostEstimator",
      "AsyncCostEstimator",
      "PriceInfo",
  ]
  ```

### 2.4 Integration Tests

- [ ] `test_response_cost_sync()` - Test Response.cost()
- [ ] `test_response_cost_async()` - Test AsyncResponse.cost()
- [ ] `test_response_cost_with_custom_estimator()`
- [ ] `test_response_cost_no_tokens_returns_none()`
- [ ] `test_response_cost_unknown_model_returns_none()`
- [ ] `test_response_cached_tokens_anthropic_format()`

## Phase 3: CLI Enhancement (0.5 day)

### 3.1 Enhance token_usage_string()

- [ ] Update signature in `llm/utils.py`
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

- [ ] Add cost calculation logic
  ```python
  if show_cost and model_id:
      try:
          from .costs import get_default_estimator
          estimator = get_default_estimator()
          
          cached_tokens = None
          if token_details:
              cached_tokens = (
                  token_details.get('cache_read_input_tokens') or
                  token_details.get('cached_tokens')
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
      except Exception:
          pass  # Silently skip on error
  ```

### 3.2 Update llm prompt command

- [ ] Find usage display (~line 901 in `llm/cli.py`)
- [ ] Update call to pass model_id and datetime
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

### 3.3 Update llm logs command

- [ ] Find usage display (~line 2182 in `llm/cli.py`)
- [ ] Update call to pass model_id and datetime
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

- [ ] `test_prompt_with_usage_shows_cost()`
- [ ] `test_prompt_with_usage_unknown_model_no_cost()`
- [ ] `test_prompt_with_usage_network_error_no_cost()`
- [ ] `test_logs_with_usage_shows_cost()`
- [ ] `test_usage_backward_compatibility()`

## Phase 4: Documentation & Polish (1 day)

### 4.1 Docstrings

- [ ] Complete docstrings for all public methods
- [ ] Type hints everywhere
- [ ] Examples in docstrings

### 4.2 Error Handling Review

- [ ] Network timeout handling
- [ ] Graceful degradation
- [ ] Logging (debug level only)
- [ ] Never break existing functionality

### 4.3 Documentation

- [ ] Update README.md with example
- [ ] Create docs/costs.md
- [ ] Update docs/usage.md
- [ ] Document cache location
- [ ] Document 24-hour refresh

### 4.4 Testing

- [ ] Run full test suite
- [ ] Manual testing all scenarios
- [ ] Coverage check (>90%)
- [ ] Performance testing

## Testing Commands

```bash
# Unit tests
pytest tests/test_costs.py -v

# Integration tests
pytest tests/test_costs.py tests/test_cli.py -v

# Coverage
pytest --cov=llm.costs --cov=llm.utils --cov-report=html

# Manual tests
# First use (no cache)
rm ~/.local/share/io.datasette.llm/historical-v1.json
llm "Test" -m gpt-4 -u

# Subsequent use (from cache)
llm "Test" -m gpt-4 -u

# Force stale cache
touch -t 202401010000 ~/.local/share/io.datasette.llm/historical-v1.json
llm "Test" -m gpt-4 -u

# Test offline (should use stale cache or skip cost)
# Disconnect network, then:
llm "Test" -m gpt-4 -u
```

## Success Checklist

- [ ] Pricing data fetches on first use
- [ ] Cache saves to correct location (user_dir/historical-v1.json)
- [ ] Cache refresh works after 24 hours
- [ ] Network errors handled gracefully
- [ ] Sync Response.cost() works
- [ ] Async AsyncResponse.cost() works
- [ ] Cost appears in -u output
- [ ] Unknown models don't crash
- [ ] Tests pass with >90% coverage
- [ ] Documentation complete
- [ ] No breaking changes

---

**Estimated time: 4 days total**
