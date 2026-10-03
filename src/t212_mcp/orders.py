import json
import math
import os
import secrets
import sys
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver.exceptions import ToolError

from t212_mcp.client import T212Client, T212Error, T212NoAnswer
from t212_mcp.config import TradingRules

if sys.platform != "win32":
    import fcntl

OrderKind = Literal["market", "limit", "stop", "stop_limit"]
FIXED_RATES = {"GBP": 1.0, "GBX": 0.01}
MARKET_PRICE_BUFFER = 1.05
MIN_PRICING_VALUE_GBP = 1.0
DISABLED = "Live trading is off. Set T212_LIVE_TRADING=1 in the server's environment to enable order tools."
DECLINED = "Not approved, so nothing was sent. Preview the order again to retry."
NO_ANSWER = "No usable answer from Trading 212, so the order may or may not have been placed. Do not resend it. Check get_pending_orders and get_order_history first."
CANCEL_NO_ANSWER = "No usable answer from Trading 212, so the order may or may not have been cancelled. Check get_order or get_pending_orders."


def position_price_gbp(position: dict[str, Any]) -> float:
    return position["walletImpact"]["currentValue"] / position["quantity"]


def can_price(position: dict[str, Any]) -> bool:
    return position["quantity"] > 0 and position["walletImpact"]["currentValue"] >= MIN_PRICING_VALUE_GBP


@dataclass(frozen=True)
class PendingOrder:
    kind: OrderKind
    body: dict[str, Any]
    value_gbp: float
    expires: float
    summary: str


class OrderDesk:
    def __init__(self, client: T212Client, instruments: Callable[[], Awaitable[list[dict[str, Any]]]], log_path: Path, rules: TradingRules, token_seconds: float):
        self._client = client
        self._instruments = instruments
        self._log_path = log_path
        self._rules = rules
        self._token_seconds = token_seconds
        self._pending: dict[str, PendingOrder] = {}
        self._account_currency: str | None = None

    def _log(self, event: str, sync: bool = False, **fields: Any) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"time": datetime.now().astimezone().isoformat(), "event": event, **fields}) + "\n"
        with self._log_path.open("a+b") as log:
            if log.seek(0, os.SEEK_END):
                log.seek(-1, os.SEEK_END)
                if log.read(1) != b"\n":
                    line = "\n" + line
            log.write(line.encode("utf-8"))
            if sync:
                log.flush()
                os.fsync(log.fileno())

    @contextmanager
    def _log_lock(self) -> Iterator[None]:
        if sys.platform == "win32":
            yield
            return
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _log_entries(self) -> Iterator[dict[str, Any]]:
        if not self._log_path.exists():
            return
        for line in self._log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                yield entry

    def spent_today(self) -> float:
        today = datetime.now().astimezone().date().isoformat()
        entries = list(self._log_entries())
        rejected = {e["token"] for e in entries if e.get("event") == "rejected" and e.get("token")}
        sent = [e for e in entries if e.get("event") == "sent" and str(e.get("time", "")).startswith(today) and e.get("token") not in rejected]
        if bad := [e for e in sent if isinstance(e.get("valueGbp"), bool) or not isinstance(e.get("valueGbp"), int | float)]:
            raise ToolError(f"The order log {self._log_path} has a 'sent' entry without a valid valueGbp ({bad[0]}); fix or remove it before trading")
        return sum(e["valueGbp"] for e in sent)

    def _check_caps(self, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ToolError(f"Cannot cap an order with an estimated value of {value}")
        if value > self._rules.max_order_gbp:
            raise ToolError(f"Estimated £{value:,.2f} is over the per-order cap of £{self._rules.max_order_gbp:,.2f}")
        if (spent := self.spent_today()) + value > self._rules.max_daily_gbp:
            raise ToolError(f"Estimated £{value:,.2f} on top of £{spent:,.2f} today is over the daily cap of £{self._rules.max_daily_gbp:,.2f}")
        return spent

    def _require_enabled(self) -> None:
        if not self._rules.enabled:
            raise ToolError(DISABLED)

    async def _require_gbp_account(self) -> None:
        if self._account_currency is None:
            self._account_currency = (await self._client.account_summary())["currency"]
        if self._account_currency != "GBP":
            raise ToolError(f"The account currency is {self._account_currency}; order tools only support GBP accounts")

    async def preview(self, kind: OrderKind, ticker: str, quantity: float, terms: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        if not math.isfinite(quantity) or quantity == 0:
            raise ToolError("quantity must be a non-zero number: positive buys, negative sells")
        if bad := [key for key in ("limitPrice", "stopPrice") if key in terms and not (math.isfinite(terms[key]) and terms[key] > 0)]:
            raise ToolError(f"{' and '.join(bad)} must be above zero")
        await self._require_gbp_account()
        instrument = next((i for i in await self._instruments() if i["ticker"] == ticker), None)
        if instrument is None:
            raise ToolError(f"Unknown ticker {ticker}; find it with search_instruments")
        positions = await self._client.positions()
        held = next((p for p in positions if p["instrument"]["ticker"] == ticker and p["quantity"]), None)
        if quantity < 0 and (held is None or -quantity > held["quantityAvailableForTrading"]):
            raise ToolError(f"Cannot sell {-quantity:g} of {ticker}: {held['quantityAvailableForTrading'] if held else 0} available")
        value = abs(quantity) * self._price_gbp(kind, quantity, terms, instrument, held, positions)
        spent = self._check_caps(value)
        body = {"ticker": ticker, "quantity": quantity, **terms}
        side = "BUY" if quantity > 0 else "SELL"
        currency = "pence" if instrument["currencyCode"] == "GBX" else instrument["currencyCode"]
        details = [f"{label} {terms[key]:g} {currency}" for key, label in (("limitPrice", "limit"), ("stopPrice", "stop")) if key in terms]
        details += [{"DAY": "day only", "GOOD_TILL_CANCEL": "good till cancelled"}[terms["timeValidity"]]] if "timeValidity" in terms else []
        details += ["extended hours"] if terms.get("extendedHours") else []
        summary = f"{side} {abs(quantity):g} x {instrument['name']} ({ticker}), {kind.replace('_', '-')} order{''.join(', ' + d for d in details)}, about £{value:,.2f}. Place this order?"
        now = time.monotonic()
        self._pending = {t: p for t, p in self._pending.items() if p.expires > now}
        token = secrets.token_urlsafe(8)
        self._pending[token] = PendingOrder(kind, body, value, now + self._token_seconds, summary)
        preview = {"token": token, "type": kind, "name": instrument["name"], "side": side, **body, "estimatedValueGbp": round(value, 2), "spentTodayGbp": round(spent, 2), "expiresInSeconds": self._token_seconds}
        self._log("preview", **preview)
        return preview

    def _price_gbp(self, kind: OrderKind, quantity: float, terms: dict[str, Any], instrument: dict[str, Any], held: dict[str, Any] | None, positions: list[dict[str, Any]]) -> float:
        if "limitPrice" in terms:
            return terms["limitPrice"] * self._rate(instrument["currencyCode"], positions)
        if kind == "stop" and quantity > 0:
            raise ToolError("A stop buy has no price bound, so its cost cannot be capped; use a stop-limit order")
        if held is None:
            raise ToolError(f"There is no price quote for {instrument['ticker']}, which is not held, so a market buy cannot be capped; use a limit order")
        if not can_price(held):
            raise ToolError(f"The holding of {instrument['ticker']} is too small to price reliably, so the order cannot be capped; use a limit order")
        return position_price_gbp(held) * MARKET_PRICE_BUFFER

    @staticmethod
    def _rate(currency: str, positions: list[dict[str, Any]]) -> float:
        if currency in FIXED_RATES:
            return FIXED_RATES[currency]
        priced = [p for p in positions if p["instrument"]["currency"] == currency and p["currentPrice"] and can_price(p)]
        if not priced:
            raise ToolError(f"No GBP rate for {currency}: no holding worth at least £{MIN_PRICING_VALUE_GBP:g} is priced in it, so the cost cannot be capped")
        largest = max(priced, key=lambda p: p["walletImpact"]["currentValue"])
        return position_price_gbp(largest) / largest["currentPrice"]

    def _live_pending(self, token: str) -> PendingOrder:
        pending = self._pending.get(token)
        if pending is None or pending.expires <= time.monotonic():
            raise ToolError("Unknown, used or expired token; preview the order again")
        return pending

    def question(self, token: str) -> str:
        self._require_enabled()
        pending = self._live_pending(token)
        self._check_caps(pending.value_gbp)
        return pending.summary

    def cancel_question(self, order_id: int) -> str:
        self._require_enabled()
        return f"Cancel pending order {order_id}?"

    async def confirm(self, token: str, approved: bool) -> dict[str, Any]:
        self._require_enabled()
        pending = self._live_pending(token)
        del self._pending[token]
        if not approved:
            self._log("declined", token=token)
            raise ToolError(DECLINED)
        with self._log_lock():
            self._check_caps(pending.value_gbp)
            self._log("sent", sync=True, token=token, kind=pending.kind, body=pending.body, valueGbp=pending.value_gbp)
        try:
            order = await self._client.place_order(pending.kind, pending.body)
        except T212NoAnswer as error:
            self._log_quietly("unknown", token=token, error=str(error), response=error.response_text)
            raise ToolError(NO_ANSWER) from error
        except T212Error as error:
            self._log_quietly("rejected", token=token, error=str(error), response=error.response_text)
            raise
        except Exception as error:
            self._log_quietly("unknown", token=token, error=repr(error))
            raise ToolError(NO_ANSWER) from error
        self._log_quietly("placed", token=token, response=order)
        return order if isinstance(order, dict) else {"status": "placed", "response": order}

    def _log_quietly(self, event: str, **fields: Any) -> None:
        try:
            self._log(event, **fields)
        except (OSError, TypeError, ValueError):
            pass

    async def cancel(self, order_id: int, approved: bool) -> str:
        self._require_enabled()
        if not approved:
            self._log("declined", orderId=order_id)
            raise ToolError("Not approved, so the order was not cancelled.")
        self._log("cancel", orderId=order_id)
        try:
            await self._client.cancel_order(order_id)
        except T212NoAnswer as error:
            self._log_quietly("cancel-unknown", orderId=order_id, error=str(error), response=error.response_text)
            raise ToolError(CANCEL_NO_ANSWER) from error
        except T212Error as error:
            self._log_quietly("cancel-failed", orderId=order_id, error=str(error), response=error.response_text)
            raise
        except Exception as error:
            self._log_quietly("cancel-unknown", orderId=order_id, error=repr(error))
            raise ToolError(CANCEL_NO_ANSWER) from error
        self._log_quietly("cancelled", orderId=order_id)
        return f"Cancellation of order {order_id} accepted; it may still fill if it was already filling. Check with get_order."
