import asyncio
import time
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

MIN_INTERVALS = {
    "account/summary": 5, "positions": 1, "orders": 5, "orders/id": 1, "orders/cancel": 1.2, "history/orders": 3,
    "metadata/instruments": 50, "orders/market": 1.2, "orders/limit": 2, "orders/stop": 2, "orders/stop_limit": 2,
}
MAX_RATE_LIMIT_WAIT = 60


class T212Error(ToolError):
    def __init__(self, message: str, response_text: str = ""):
        super().__init__(message)
        self.response_text = response_text


class T212NoAnswer(T212Error):
    pass


class T212Client:
    def __init__(self, base_url: str, api_key: str, api_secret: str, min_intervals: Mapping[str, float] = MIN_INTERVALS, transport: httpx.AsyncBaseTransport | None = None):
        self._http = httpx.AsyncClient(base_url=f"{base_url}/api/v0/equity/", auth=(api_key, api_secret), timeout=20, transport=transport)
        self._min_intervals = min_intervals
        self._next_allowed: dict[str, float] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _wait_turn(self, rate_key: str) -> None:
        async with self._locks[rate_key]:
            if (wait := self._next_allowed.get(rate_key, 0) - time.monotonic()) > 0:
                await asyncio.sleep(wait)
            self._next_allowed[rate_key] = time.monotonic() + self._min_intervals.get(rate_key, 0)

    def _note_rate_limit(self, rate_key: str, response: httpx.Response) -> None:
        if response.headers.get("x-ratelimit-remaining") != "0":
            return
        try:
            reset = float(response.headers.get("x-ratelimit-reset", ""))
        except ValueError:
            return
        wait = min(max(reset - time.time(), 0), MAX_RATE_LIMIT_WAIT)
        self._next_allowed[rate_key] = max(self._next_allowed.get(rate_key, 0), time.monotonic() + wait)

    async def _request(self, method: str, path: str, scope: str, rate_key: str | None = None, json: dict[str, Any] | None = None, **params: Any) -> Any:
        rate_key = rate_key or path
        await self._wait_turn(rate_key)
        response = await self._http.request(method, path, json=json, params={k: v for k, v in params.items() if v is not None})
        self._note_rate_limit(rate_key, response)
        if response.is_success:
            return response.json() if response.content else None
        text = response.text[:500]
        match response.status_code:
            case 401:
                raise T212Error("Trading 212 rejected the API key or secret", text)
            case 403:
                raise T212Error(f"The API key lacks the '{scope}' permission", text)
            case 429:
                raise T212Error(f"Rate limited on {path}; resets at unix time {response.headers.get('x-ratelimit-reset', 'unknown')}", text)
            case status if status == 408 or status >= 500:
                raise T212NoAnswer(f"Trading 212 returned {status} for {path}", text)
            case status:
                raise T212Error(f"Trading 212 returned {status} for {path}: {text}", text)

    async def account_summary(self) -> dict[str, Any]:
        return await self._request("GET", "account/summary", "account")

    async def positions(self, ticker: str | None = None) -> list[dict[str, Any]]:
        return await self._request("GET", "positions", "portfolio", ticker=ticker)

    async def pending_orders(self) -> list[dict[str, Any]]:
        return await self._request("GET", "orders", "orders:read")

    async def order(self, order_id: int) -> dict[str, Any]:
        return await self._request("GET", f"orders/{order_id}", "orders:read", "orders/id")

    async def order_history(self, cursor: int | None = None, ticker: str | None = None, limit: int | None = None) -> dict[str, Any]:
        return await self._request("GET", "history/orders", "history:orders", cursor=cursor, ticker=ticker, limit=limit)

    async def instruments(self) -> list[dict[str, Any]]:
        return await self._request("GET", "metadata/instruments", "metadata")

    async def place_order(self, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"orders/{kind}", "orders:execute", json=body)

    async def cancel_order(self, order_id: int) -> None:
        await self._request("DELETE", f"orders/{order_id}", "orders:execute", "orders/cancel")
