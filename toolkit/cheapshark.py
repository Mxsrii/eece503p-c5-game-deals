"""Minimal CheapShark client (https://www.cheapshark.com, free, no API key).

Polite by default: identifying User-Agent (set on the injected httpx client), a small
throttle between requests, and a short-lived cache so repeated lookups cost nothing
but prices never go more than a few minutes stale.
"""

import asyncio
import time
from typing import Any

import httpx

CACHE_SIZE = 256
CACHE_TTL_S = 600.0  # prices change, so cached answers expire after 10 minutes


class CheapSharkError(Exception):
    """The price service could not answer (unreachable, rate-limited, bad response)."""


class CheapSharkClient:
    def __init__(
        self,
        base_url: str,
        http: httpx.AsyncClient,
        min_interval_s: float = 0.3,
        cache_ttl_s: float = CACHE_TTL_S,
    ):
        self._base_url = base_url
        self._http = http
        self._min_interval_s = min_interval_s
        self._cache_ttl_s = cache_ttl_s
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._cache: dict[tuple, tuple[float, Any]] = {}  # key -> (expires_at, data)

    async def _get(self, path: str, params: dict[str, str | int]) -> Any:
        """GET a JSON endpoint. Returns None for 404 (unknown id)."""
        key = (path, tuple(sorted(params.items())))
        cached = self._cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        async with self._lock:
            while (wait := self._min_interval_s - (time.monotonic() - self._last_request)) > 0:
                await asyncio.sleep(wait)
            try:
                resp = await self._http.get(f"{self._base_url}/{path}", params=params)
            except httpx.HTTPError as exc:
                raise CheapSharkError(
                    f"The game price service is unreachable ({type(exc).__name__}). Try again shortly."
                ) from exc
            finally:
                self._last_request = time.monotonic()

        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            raise CheapSharkError("The game price service is rate-limiting us. Wait a minute and retry.")
        if resp.status_code != 200:
            raise CheapSharkError(f"The game price service returned HTTP {resp.status_code}.")
        try:
            data = resp.json()
        except ValueError as exc:
            raise CheapSharkError("The game price service returned an unreadable response.") from exc

        self._cache.pop(key, None)
        if len(self._cache) >= CACHE_SIZE:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (time.monotonic() + self._cache_ttl_s, data)
        return data

    async def search_games(self, title: str, limit: int = 20) -> list[dict]:
        """Games whose title matches (fuzzy). Each has gameID, external (title), cheapest."""
        return await self._get("games", {"title": title, "limit": limit}) or []

    async def game_details(self, game_id: str) -> dict | None:
        """info, cheapestPriceEver and every store's current deal, or None if unknown."""
        return await self._get("games", {"id": game_id})

    async def store_names(self) -> dict[str, str]:
        stores = await self._get("stores", {}) or []
        return {s["storeID"]: s["storeName"] for s in stores}
