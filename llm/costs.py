"""
Cost estimation for LLM API usage.

Fetches pricing data from llm-prices.com and caches it locally
in the user directory with a 24-hour TTL.
"""

import httpx
import json
import time
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
from dataclasses import dataclass

PRICING_URL = "https://www.llm-prices.com/historical-v1.json"
CACHE_FILENAME = "historical-v1.json"
CACHE_MAX_AGE_HOURS = 24


@dataclass
class PriceInfo:
    """Pricing information for a specific model."""

    id: str
    vendor: str
    name: str
    input_price: float  # $ per million tokens
    output_price: float  # $ per million tokens
    cached_input_price: Optional[float] = None  # $ per million tokens
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None


@dataclass
class Cost:
    """Calculated cost for a response."""

    input_cost: float
    output_cost: float
    cached_cost: float
    total_cost: float
    currency: str = "USD"
    model_id: str = ""
    price_info: Optional[PriceInfo] = None


class CostEstimator:
    """
    Synchronous cost estimator with lazy loading and caching.

    Fetches pricing data from llm-prices.com on first use and caches
    it in user_dir()/historical-v1.json. Re-fetches if cache is older
    than 24 hours.
    """

    _instance: Optional["CostEstimator"] = None
    _pricing_data: Optional[dict] = None
    _last_loaded: Optional[float] = None

    def __init__(self, force_refresh: bool = False):
        """Initialize estimator, loading pricing data if needed."""
        self._ensure_pricing_data(force_refresh)

    def _get_cache_path(self) -> Path:
        """Get path to cached pricing data."""
        import llm

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
            except Exception:
                # Fall back to cache if available
                cache_path = self._get_cache_path()
                if cache_path.exists():
                    self._pricing_data = self._load_from_cache()
                    self._last_loaded = time.time()
                else:
                    # No cache and can't fetch - pricing unavailable
                    self._pricing_data = None
        else:
            # Cache is fresh, just load it
            if self._pricing_data is None:
                self._pricing_data = self._load_from_cache()
                self._last_loaded = time.time()

    def _normalize_model_id(self, model_id: str) -> str:
        """Normalize model ID by removing common suffixes."""
        # Remove date-based suffixes like -0613, -20240229, etc.
        import re

        # Remove patterns like -YYYYMMDD or -MMDD or -0613
        normalized = re.sub(r"-\d{4,8}$", "", model_id)
        # Remove patterns like -preview, -turbo-preview
        normalized = re.sub(r"-(preview|turbo-preview)$", "", normalized)
        return normalized

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO date string to datetime."""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None

    def _find_price(
        self, model_id: str, date: Optional[datetime] = None
    ) -> Optional[PriceInfo]:
        """Find exact price match for model ID."""
        if not self._pricing_data or "prices" not in self._pricing_data:
            return None

        matches = []
        for price_data in self._pricing_data["prices"]:
            if price_data.get("id") != model_id:
                continue

            # Check date range if specified
            from_date = self._parse_date(price_data.get("from_date"))
            to_date = self._parse_date(price_data.get("to_date"))

            # If no date range, this is current pricing
            if from_date is None and to_date is None:
                matches.append((price_data, 0))  # Priority 0 for current
            elif date:
                # Check if date falls within range
                if from_date and date < from_date:
                    continue
                if to_date and date >= to_date:
                    continue
                matches.append((price_data, 1))  # Priority 1 for historical
            else:
                # No date specified, use current pricing
                if from_date is None and to_date is None:
                    matches.append((price_data, 0))

        if not matches:
            return None

        # Sort by priority and return best match
        matches.sort(key=lambda x: x[1])
        price_data = matches[0][0]

        return PriceInfo(
            id=price_data["id"],
            vendor=price_data["vendor"],
            name=price_data["name"],
            input_price=price_data["input"],
            output_price=price_data["output"],
            cached_input_price=price_data.get("input_cached"),
            from_date=self._parse_date(price_data.get("from_date")),
            to_date=self._parse_date(price_data.get("to_date")),
        )

    def _find_price_fuzzy(self, model_id: str) -> Optional[PriceInfo]:
        """Try fuzzy matching for common model variations."""
        # Try normalized version
        normalized = self._normalize_model_id(model_id)
        if normalized != model_id:
            price = self._find_price(normalized)
            if price:
                return price

        # Try common base model patterns
        patterns = [
            # GPT models
            (r"^gpt-4o-.*", "gpt-4o"),
            (r"^gpt-4-turbo-.*", "gpt-4-turbo"),
            (r"^gpt-4-.*", "gpt-4"),
            (r"^gpt-3.5-turbo-.*", "gpt-3.5-turbo"),
            # Claude models
            (r"^claude-3-opus-.*", "claude-3-opus"),
            (r"^claude-3-sonnet-.*", "claude-3-sonnet"),
            (r"^claude-3-haiku-.*", "claude-3-haiku"),
            (r"^claude-3.5-sonnet-.*", "claude-3.5-sonnet"),
            # Gemini models
            (r"^gemini-1.5-flash-.*", "gemini-1.5-flash"),
            (r"^gemini-1.5-pro-.*", "gemini-1.5-pro"),
        ]

        import re

        for pattern, base_model in patterns:
            if re.match(pattern, model_id):
                price = self._find_price(base_model)
                if price:
                    return price

        return None

    def get_price(
        self, model_id: str, date: Optional[datetime] = None
    ) -> Optional[PriceInfo]:
        """
        Get pricing information for a model.

        Args:
            model_id: Model identifier
            date: Optional date for historical pricing

        Returns:
            PriceInfo if pricing available, None otherwise
        """
        self._ensure_pricing_data()

        if not self._pricing_data:
            return None

        # Try exact match first
        price = self._find_price(model_id, date)
        if price:
            return price

        # Try fuzzy match
        return self._find_price_fuzzy(model_id)

    def calculate_cost(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: Optional[int] = None,
        date: Optional[datetime] = None,
    ) -> Optional[Cost]:
        """
        Calculate cost for a response.

        Args:
            model_id: Model identifier
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cached_tokens: Optional number of cached tokens
            date: Optional date for historical pricing

        Returns:
            Cost object if pricing available, None otherwise
        """
        price = self.get_price(model_id, date)
        if not price:
            return None

        # Calculate costs (prices are per million tokens)
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
            price_info=price,
        )

    def list_models(self, vendor: Optional[str] = None) -> List[PriceInfo]:
        """
        List all models with available pricing.

        Args:
            vendor: Optional vendor filter

        Returns:
            List of PriceInfo objects
        """
        self._ensure_pricing_data()

        if not self._pricing_data or "prices" not in self._pricing_data:
            return []

        models = []
        seen = set()

        for price_data in self._pricing_data["prices"]:
            if vendor and price_data.get("vendor") != vendor:
                continue

            # Only include current pricing (no date range)
            if price_data.get("from_date") or price_data.get("to_date"):
                continue

            model_id = price_data["id"]
            if model_id in seen:
                continue
            seen.add(model_id)

            models.append(
                PriceInfo(
                    id=price_data["id"],
                    vendor=price_data["vendor"],
                    name=price_data["name"],
                    input_price=price_data["input"],
                    output_price=price_data["output"],
                    cached_input_price=price_data.get("input_cached"),
                    from_date=None,
                    to_date=None,
                )
            )

        return models


class AsyncCostEstimator:
    """
    Asynchronous cost estimator for use with AsyncResponse.

    Same functionality as CostEstimator but with async I/O.
    """

    _instance: Optional["AsyncCostEstimator"] = None
    _pricing_data: Optional[dict] = None
    _last_loaded: Optional[float] = None

    def __init__(self):
        """Initialize async estimator."""
        pass

    def _get_cache_path(self) -> Path:
        """Get path to cached pricing data."""
        import llm

        return llm.user_dir() / CACHE_FILENAME

    def _is_cache_fresh(self) -> bool:
        """Check if cache exists and is less than 24 hours old."""
        cache_path = self._get_cache_path()
        if not cache_path.exists():
            return False

        age = time.time() - cache_path.stat().st_mtime
        max_age = CACHE_MAX_AGE_HOURS * 3600
        return age < max_age

    async def _fetch_pricing_data(self) -> dict:
        """Fetch pricing data from remote URL (async)."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                PRICING_URL, timeout=10.0, follow_redirects=True
            )
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

    async def _ensure_pricing_data(self, force_refresh: bool = False):
        """Ensure pricing data is loaded, fetching if necessary (async)."""
        if force_refresh or not self._is_cache_fresh():
            try:
                data = await self._fetch_pricing_data()
                self._save_to_cache(data)
                self._pricing_data = data
                self._last_loaded = time.time()
            except Exception:
                cache_path = self._get_cache_path()
                if cache_path.exists():
                    self._pricing_data = self._load_from_cache()
                    self._last_loaded = time.time()
                else:
                    self._pricing_data = None
        else:
            if self._pricing_data is None:
                self._pricing_data = self._load_from_cache()
                self._last_loaded = time.time()

    # Reuse sync methods for non-I/O operations
    _normalize_model_id = CostEstimator._normalize_model_id
    _parse_date = CostEstimator._parse_date
    _find_price = CostEstimator._find_price
    _find_price_fuzzy = CostEstimator._find_price_fuzzy

    async def get_price(
        self, model_id: str, date: Optional[datetime] = None
    ) -> Optional[PriceInfo]:
        """Get pricing information for a model (async)."""
        await self._ensure_pricing_data()

        if not self._pricing_data:
            return None

        price = self._find_price(model_id, date)
        if price:
            return price

        return self._find_price_fuzzy(model_id)

    async def calculate_cost(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: Optional[int] = None,
        date: Optional[datetime] = None,
    ) -> Optional[Cost]:
        """Calculate cost for a response (async)."""
        price = await self.get_price(model_id, date)
        if not price:
            return None

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
            price_info=price,
        )


def get_default_estimator() -> CostEstimator:
    """Get or create singleton instance of CostEstimator."""
    if CostEstimator._instance is None:
        CostEstimator._instance = CostEstimator()
    return CostEstimator._instance


async def get_async_estimator() -> AsyncCostEstimator:
    """Get or create singleton instance of AsyncCostEstimator."""
    if AsyncCostEstimator._instance is None:
        AsyncCostEstimator._instance = AsyncCostEstimator()
        await AsyncCostEstimator._instance._ensure_pricing_data()
    return AsyncCostEstimator._instance
