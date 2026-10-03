import asyncio
import time
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

MIN_INTERVALS = {
    "account/summary": 5, "positions": 1, "orders": 5, "orders/id": 1, "orders/cancel": 1.2, "history/orders": 3,
    "metadata/instruments": 50, "metadata/exchanges": 30, "orders/market": 1.2, "orders/limit": 2, "orders/stop": 2, "orders/stop_limit": 2,
}


class T212Error(ToolError):
    pass


class T212NoAnswer(T212Error):
    pass


class T212Client:
    def __init__(self, base_url: str, api_key: str, api_secret: str, min_intervals: dict[str, float] = MIN_INTERVALS, transport: httpx.AsyncBaseTransport | None = None):
        self._http = httpx.AsyncClient(base_url=f"{base_url}/api/v0/equity/", auth=(api_key, api_secret), timeout=20, transport=transport)
        self._min_intervals = min_intervals
        self._last_call: dict[str, float] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, scope: str, rate_key: str | None = None, json: dict | None = None, **params: Any) -> Any:
        rate_key = rate_key or path
        if (wait := self._last_call.get(rate_key, 0) + self._min_intervals.get(rate_key, 0) - time.monotonic()) > 0:
            await asyncio.sleep(wait)
        self._last_call[rate_key] = time.monotonic()
        response = await self._http.request(method, path, json=json, params={k: v for k, v in params.items() if v is not None})
        if response.is_success:
            return response.json() if response.content else None
        match response.status_code:
            case 401:
                raise T212Error("Trading 212 rejected the API key or secret")
            case 403:
                raise T212Error(f"The API key lacks the '{scope}' permission")
            case 429:
                raise T212Error(f"Rate limited on {path}; resets at unix time {response.headers.get('x-ratelimit-reset', 'unknown')}")
            case status if status == 408 or status >= 500:
                raise T212NoAnswer(f"Trading 212 returned {status} for {path}")
            case status:
                raise T212Error(f"Trading 212 returned {status} for {path}: {response.text[:500]}")

    async def account_summary(self) -> dict:
        return await self._request("GET", "account/summary", "account")

    async def positions(self, ticker: str | None = None) -> list[dict]:
        return await self._request("GET", "positions", "portfolio", ticker=ticker)

    async def pending_orders(self) -> list[dict]:
        return await self._request("GET", "orders", "orders:read")

    async def order(self, order_id: int) -> dict:
        return await self._request("GET", f"orders/{order_id}", "orders:read", "orders/id")

    async def order_history(self, cursor: int | None = None, ticker: str | None = None, limit: int | None = None) -> dict:
        return await self._request("GET", "history/orders", "history:orders", cursor=cursor, ticker=ticker, limit=limit)

    async def instruments(self) -> list[dict]:
        return await self._request("GET", "metadata/instruments", "metadata")

    async def place_order(self, kind: str, body: dict) -> dict:
        return await self._request("POST", f"orders/{kind}", "orders:execute", json=body)

    async def cancel_order(self, order_id: int) -> None:
        await self._request("DELETE", f"orders/{order_id}", "orders:execute", "orders/cancel")
