import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from pydantic import BaseModel

from t212_mcp.client import T212Client
from t212_mcp.config import Settings, TradingRules, load_settings
from t212_mcp.orders import Approve, OrderDesk, position_price_gbp

INSTRUMENT_CACHE_SECONDS = 86400
TimeValidity = Literal["DAY", "GOOD_TILL_CANCEL"]
INSTRUCTIONS = (
    "Trading 212 Stocks ISA. Tickers look like AAPL_US_EQ; find them with search_instruments, never guess. "
    "Orders are by share quantity: positive buys, negative sells. Every preview_* tool returns a preview and a token. "
    "Show the preview to the user, then call confirm_order; the server asks the user to approve every order and cancellation itself. "
    "Never confirm an order twice or resend one after an error."
)


class Approval(BaseModel):
    approve: bool


def next_cursor(next_page_path: str | None) -> int | None:
    if not next_page_path or not (cursor := parse_qs(urlparse(next_page_path).query).get("cursor")):
        return None
    return int(cursor[0])


def user_approval(ctx: Context) -> Approve:
    async def approve(question: str) -> bool:
        try:
            answer = await ctx.elicit(question, Approval)
        except MCPError as error:
            raise ToolError(f"Could not ask the user to approve, so nothing was sent ({error}). The MCP client must support elicitation.") from error
        return answer.action == "accept" and answer.data.approve
    return approve


def create_server(client: T212Client, instrument_cache: Path, order_log: Path, rules: TradingRules = TradingRules(), token_seconds: float = 300) -> MCPServer:
    server = MCPServer("trading212", instructions=INSTRUCTIONS)

    async def instruments() -> list[dict[str, Any]]:
        if instrument_cache.exists() and time.time() - instrument_cache.stat().st_mtime < INSTRUMENT_CACHE_SECONDS:
            try:
                return json.loads(instrument_cache.read_text(encoding="utf-8"))
            except ValueError:
                pass
        items = await client.instruments()
        instrument_cache.parent.mkdir(parents=True, exist_ok=True)
        partial = instrument_cache.with_suffix(f".{os.getpid()}.tmp")
        partial.write_text(json.dumps(items), encoding="utf-8")
        partial.replace(instrument_cache)
        return items

    desk = OrderDesk(client, instruments, order_log, rules, token_seconds)

    @server.tool()
    async def get_account_summary() -> dict[str, Any]:
        """Cash, investments and total value of the account, in the account currency."""
        return await client.account_summary()

    @server.tool()
    async def get_positions(ticker: str | None = None) -> list[dict[str, Any]]:
        """Open positions. currentPrice is in the instrument's own currency (London shares are often in pence, GBX); priceInAccountCurrency is the price per share in the account currency."""
        positions = await client.positions(ticker)
        for position in positions:
            if position.get("quantity"):
                position["priceInAccountCurrency"] = position_price_gbp(position)
        return positions

    @server.tool()
    async def get_pending_orders() -> list[dict[str, Any]]:
        """Orders placed but not yet filled or cancelled."""
        return await client.pending_orders()

    @server.tool()
    async def get_order(order_id: int) -> dict[str, Any]:
        """Status of one pending order."""
        return await client.order(order_id)

    @server.tool()
    async def get_order_history(ticker: str | None = None, limit: int = 20, cursor: int | None = None) -> dict[str, Any]:
        """Filled, cancelled and rejected orders, newest first. limit is at most 50. Pass nextCursor back as cursor for the next page."""
        page = await client.order_history(cursor, ticker, min(limit, 50))
        return {"items": page["items"], "nextCursor": next_cursor(page.get("nextPagePath"))}

    @server.tool()
    async def search_instruments(query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Find tradable instruments by ticker, name, short name or ISIN (case-insensitive)."""
        needle = query.casefold()
        fields = ("ticker", "name", "shortName", "isin")
        return [i for i in await instruments() if any(needle in str(i.get(f, "")).casefold() for f in fields)][:limit]

    @server.tool()
    async def preview_market_order(ticker: str, quantity: float, extended_hours: bool = False) -> dict[str, Any]:
        """Preview a market order. Buys are only allowed for instruments already held, since there is no price quote. Returns a token for confirm_order."""
        return await desk.preview("market", ticker, quantity, {"extendedHours": extended_hours})

    @server.tool()
    async def preview_limit_order(ticker: str, quantity: float, limit_price: float, time_validity: TimeValidity = "DAY") -> dict[str, Any]:
        """Preview a limit order. limit_price is in the instrument's own currency (pence for GBX). Returns a token for confirm_order."""
        return await desk.preview("limit", ticker, quantity, {"limitPrice": limit_price, "timeValidity": time_validity})

    @server.tool()
    async def preview_stop_order(ticker: str, quantity: float, stop_price: float, time_validity: TimeValidity = "DAY") -> dict[str, Any]:
        """Preview a stop order (a market order once the last traded price reaches stop_price). Sells only. Returns a token for confirm_order."""
        return await desk.preview("stop", ticker, quantity, {"stopPrice": stop_price, "timeValidity": time_validity})

    @server.tool()
    async def preview_stop_limit_order(ticker: str, quantity: float, stop_price: float, limit_price: float, time_validity: TimeValidity = "DAY") -> dict[str, Any]:
        """Preview a stop-limit order (a limit order at limit_price once the last traded price reaches stop_price). Returns a token for confirm_order."""
        return await desk.preview("stop_limit", ticker, quantity, {"stopPrice": stop_price, "limitPrice": limit_price, "timeValidity": time_validity})

    @server.tool()
    async def confirm_order(token: str, ctx: Context) -> dict[str, Any]:
        """Place a previewed order. The server asks the user to approve it first; if they decline, nothing is sent. Each token works once."""
        return await desk.confirm(token, user_approval(ctx))

    @server.tool()
    async def cancel_order(order_id: int, ctx: Context) -> str:
        """Ask Trading 212 to cancel a pending order. The server asks the user to approve it first."""
        return await desk.cancel(order_id, user_approval(ctx))

    return server


async def serve(settings: Settings) -> None:
    client = T212Client(settings.base_url, settings.api_key, settings.api_secret)
    try:
        await create_server(client, settings.cache_dir / f"instruments-{settings.env}.json", settings.log_path, settings.rules).run_stdio_async()
    finally:
        await client.aclose()


def main() -> None:
    asyncio.run(serve(load_settings()))
