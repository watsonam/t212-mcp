import asyncio
import time
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

MIN_INTERVALS = {"account/summary": 5, "positions": 1, "orders": 5, "history/orders": 3, "metadata/instruments": 50, "metadata/exchanges": 30}
SCOPES = {"account/summary": "account", "positions": "portfolio", "orders": "orders:read", "history/orders": "history:orders", "metadata/instruments": "metadata", "metadata/exchanges": "metadata"}


class T212Error(ToolError):
    pass


class T212Client:
    def __init__(self, base_url: str, api_key: str, api_secret: str, min_intervals: dict[str, float] = MIN_INTERVALS, transport: httpx.AsyncBaseTransport | None = None):
        self._http = httpx.AsyncClient(base_url=f"{base_url}/api/v0/equity/", auth=(api_key, api_secret), timeout=20, transport=transport)
        self._min_intervals = min_intervals
        self._last_call: dict[str, float] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, **params: Any) -> Any:
        if (wait := self._last_call.get(path, 0) + self._min_intervals.get(path, 0) - time.monotonic()) > 0:
            await asyncio.sleep(wait)
        self._last_call[path] = time.monotonic()
        response = await self._http.get(path, params={k: v for k, v in params.items() if v is not None})
        if response.is_success:
            return response.json()
        match response.status_code:
            case 401:
                message = "Trading 212 rejected the API key or secret"
            case 403:
                message = f"The API key lacks the '{SCOPES.get(path, 'required')}' permission"
            case 429:
                message = f"Rate limited on {path}; resets at unix time {response.headers.get('x-ratelimit-reset', 'unknown')}"
            case status:
                message = f"Trading 212 returned {status} for {path}: {response.text[:500]}"
        raise T212Error(message)

    async def account_summary(self) -> dict:
        return await self._get("account/summary")

    async def positions(self, ticker: str | None = None) -> list[dict]:
        return await self._get("positions", ticker=ticker)

    async def pending_orders(self) -> list[dict]:
        return await self._get("orders")

    async def order_history(self, cursor: int | None = None, ticker: str | None = None, limit: int | None = None) -> dict:
        return await self._get("history/orders", cursor=cursor, ticker=ticker, limit=limit)

    async def instruments(self) -> list[dict]:
        return await self._get("metadata/instruments")
