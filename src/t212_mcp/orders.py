import json
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from t212_mcp.client import T212Client, T212NoAnswer

FIXED_RATES = {"GBP": 1.0, "GBX": 0.01}
DISABLED = "Live trading is off. Set T212_LIVE_TRADING=1 in the server's environment to enable order tools."
DECLINED = "Not approved, so nothing was sent. Preview the order again to retry."
NO_ANSWER = "No answer from Trading 212, so the order may or may not have been placed. Do not resend it. Check get_pending_orders and get_order_history first."


Approve = Callable[[str], Awaitable[bool]]


@dataclass(frozen=True)
class PendingOrder:
    kind: str
    body: dict
    value_gbp: float
    expires: float
    summary: str


class OrderDesk:
    def __init__(self, client: T212Client, instruments: Callable[[], Awaitable[list[dict]]], log_path: Path, enabled: bool, max_order_gbp: float, max_daily_gbp: float, token_seconds: float):
        self._client = client
        self._instruments = instruments
        self._log_path = log_path
        self._enabled = enabled
        self._max_order_gbp = max_order_gbp
        self._max_daily_gbp = max_daily_gbp
        self._token_seconds = token_seconds
        self._pending: dict[str, PendingOrder] = {}

    def _log(self, event: str, **fields) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a") as log:
            log.write(json.dumps({"time": datetime.now().astimezone().isoformat(), "event": event, **fields}) + "\n")

    def spent_today(self) -> float:
        if not self._log_path.exists():
            return 0.0
        today = datetime.now().astimezone().date().isoformat()
        entries = [json.loads(line) for line in self._log_path.read_text().splitlines()]
        rejected = {e["token"] for e in entries if e["event"] == "rejected"}
        return sum(e["valueGbp"] for e in entries if e["event"] == "sent" and e["time"].startswith(today) and e["token"] not in rejected)

    def _check_caps(self, value: float) -> float:
        if value > self._max_order_gbp:
            raise ToolError(f"Estimated £{value:,.2f} is over the per-order cap of £{self._max_order_gbp:,.2f}")
        if (spent := self.spent_today()) + value > self._max_daily_gbp:
            raise ToolError(f"Estimated £{value:,.2f} on top of £{spent:,.2f} today is over the daily cap of £{self._max_daily_gbp:,.2f}")
        return spent

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise ToolError(DISABLED)

    async def preview(self, kind: str, ticker: str, quantity: float, limit_price: float | None = None, stop_price: float | None = None, time_validity: str | None = None, extended_hours: bool = False) -> dict:
        self._require_enabled()
        if quantity == 0:
            raise ToolError("quantity must not be zero: positive buys, negative sells")
        instrument = next((i for i in await self._instruments() if i["ticker"] == ticker), None)
        if instrument is None:
            raise ToolError(f"Unknown ticker {ticker}; find it with search_instruments")
        positions = await self._client.positions()
        held = next((p for p in positions if p["instrument"]["ticker"] == ticker), None)
        if quantity < 0 and (held is None or -quantity > held["quantityAvailableForTrading"]):
            raise ToolError(f"Cannot sell {-quantity} of {ticker}: {held['quantityAvailableForTrading'] if held else 0} available")
        value = abs(quantity) * self._price_gbp(kind, quantity, limit_price, instrument, held, positions)
        spent = self._check_caps(value)
        body = {"ticker": ticker, "quantity": quantity}
        body |= {"extendedHours": extended_hours} if kind == "market" else {"stopPrice": stop_price, "limitPrice": limit_price, "timeValidity": time_validity}
        body = {k: v for k, v in body.items() if v is not None}
        token = secrets.token_urlsafe(8)
        side = "BUY" if quantity > 0 else "SELL"
        prices = ", ".join(f"{label} {body[key]}" for key, label in (("limitPrice", "limit"), ("stopPrice", "stop")) if key in body)
        summary = f"{side} {abs(quantity):g} x {instrument['name']} ({ticker}), {kind.replace('_', '-')} order{', ' + prices if prices else ''}, about £{value:,.2f}. Place this order?"
        self._pending[token] = PendingOrder(kind, body, value, time.monotonic() + self._token_seconds, summary)
        preview = {"token": token, "type": kind, "name": instrument["name"], "side": side, **body, "estimatedValueGbp": round(value, 2), "spentTodayGbp": round(spent, 2), "expiresInSeconds": self._token_seconds}
        self._log("preview", **preview)
        return preview

    def _price_gbp(self, kind: str, quantity: float, limit_price: float | None, instrument: dict, held: dict | None, positions: list[dict]) -> float:
        if kind in ("limit", "stop_limit"):
            return limit_price * self._rate(instrument["currencyCode"], positions)
        if kind == "stop" and quantity > 0:
            raise ToolError("A stop buy has no price bound, so its cost cannot be capped; use a stop-limit order")
        if held is None:
            raise ToolError(f"There is no price quote for {instrument['ticker']}, which is not held, so a market buy cannot be capped; use a limit order")
        return held["walletImpact"]["currentValue"] / held["quantity"]

    @staticmethod
    def _rate(currency: str, positions: list[dict]) -> float:
        if currency in FIXED_RATES:
            return FIXED_RATES[currency]
        for p in positions:
            if p["instrument"]["currency"] == currency and p["quantity"] and p["currentPrice"]:
                return p["walletImpact"]["currentValue"] / (p["quantity"] * p["currentPrice"])
        raise ToolError(f"No GBP rate for {currency}: no held position is priced in it, so the cost cannot be capped")

    async def confirm(self, token: str, approve: Approve) -> dict:
        self._require_enabled()
        pending = self._pending.pop(token, None)
        if pending is None or pending.expires <= time.monotonic():
            raise ToolError("Unknown, used or expired token; preview the order again")
        self._check_caps(pending.value_gbp)
        if not await approve(pending.summary):
            self._log("declined", token=token)
            raise ToolError(DECLINED)
        if pending.expires <= time.monotonic():
            raise ToolError("The token expired while waiting for approval; preview the order again")
        self._check_caps(pending.value_gbp)
        self._log("sent", token=token, kind=pending.kind, body=pending.body, valueGbp=pending.value_gbp)
        try:
            order = await self._client.place_order(pending.kind, pending.body)
        except (httpx.TransportError, T212NoAnswer) as error:
            self._log("unknown", token=token, error=repr(error))
            raise ToolError(NO_ANSWER) from error
        except ToolError as error:
            self._log("rejected", token=token, error=str(error))
            raise
        self._log("placed", token=token, response=order)
        return order

    async def cancel(self, order_id: int, approve: Approve) -> str:
        self._require_enabled()
        if not await approve(f"Cancel pending order {order_id}?"):
            self._log("declined", orderId=order_id)
            raise ToolError("Not approved, so the order was not cancelled.")
        self._log("cancel", orderId=order_id)
        await self._client.cancel_order(order_id)
        return f"Cancellation of order {order_id} accepted; it may still fill if it was already filling. Check with get_order."
