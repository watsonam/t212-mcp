import json
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

from mcp.server.mcpserver import MCPServer

from t212_mcp.client import T212Client
from t212_mcp.config import load_settings
from t212_mcp.orders import OrderDesk

INSTRUMENT_CACHE_SECONDS = 86400


def next_cursor(next_page_path: str | None) -> int | None:
    if not next_page_path or not (cursor := parse_qs(urlparse(next_page_path).query).get("cursor")):
        return None
    return int(cursor[0])


TimeValidity = Literal["DAY", "GOOD_TILL_CANCEL"]
INSTRUCTIONS = (
    "Trading 212 Stocks ISA. Tickers look like AAPL_US_EQ; find them with search_instruments, never guess. "
    "Orders are by share quantity: positive buys, negative sells. Every preview_* tool returns a preview and a token. "
    "Show the preview to the user and call confirm_order only after they approve it. Never confirm an order twice or resend one after an error."
)


def create_server(client: T212Client, instrument_cache: Path, order_log: Path, trading_enabled: bool = False, max_order_gbp: float = 1000, max_daily_gbp: float = 2000, token_seconds: float = 300) -> MCPServer:
    server = MCPServer("trading212", instructions=INSTRUCTIONS)

    async def instruments() -> list[dict]:
        if instrument_cache.exists() and time.time() - instrument_cache.stat().st_mtime < INSTRUMENT_CACHE_SECONDS:
            return json.loads(instrument_cache.read_text())
        items = await client.instruments()
        instrument_cache.parent.mkdir(parents=True, exist_ok=True)
        instrument_cache.write_text(json.dumps(items))
        return items

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
                position["priceInAccountCurrency"] = position["walletImpact"]["currentValue"] / position["quantity"]
        return positions

    @server.tool()
    async def get_pending_orders() -> list[dict[str, Any]]:
        """Orders placed but not yet filled or cancelled."""
        return await client.pending_orders()

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

    desk = OrderDesk(client, instruments, order_log, trading_enabled, max_order_gbp, max_daily_gbp, token_seconds)

    @server.tool()
    async def get_order(order_id: int) -> dict[str, Any]:
        """Status of one pending order."""
        return await client.order(order_id)

    @server.tool()
    async def preview_market_order(ticker: str, quantity: float, extended_hours: bool = False) -> dict[str, Any]:
        """Preview a market order. Buys are only allowed for instruments already held, since there is no price quote. Returns a token for confirm_order."""
        return await desk.preview("market", ticker, quantity, extended_hours=extended_hours)

    @server.tool()
    async def preview_limit_order(ticker: str, quantity: float, limit_price: float, time_validity: TimeValidity = "DAY") -> dict[str, Any]:
        """Preview a limit order. limit_price is in the instrument's own currency (pence for GBX). Returns a token for confirm_order."""
        return await desk.preview("limit", ticker, quantity, limit_price=limit_price, time_validity=time_validity)

    @server.tool()
    async def preview_stop_order(ticker: str, quantity: float, stop_price: float, time_validity: TimeValidity = "DAY") -> dict[str, Any]:
        """Preview a stop order (a market order once the last traded price reaches stop_price). Sells only. Returns a token for confirm_order."""
        return await desk.preview("stop", ticker, quantity, stop_price=stop_price, time_validity=time_validity)

    @server.tool()
    async def preview_stop_limit_order(ticker: str, quantity: float, stop_price: float, limit_price: float, time_validity: TimeValidity = "DAY") -> dict[str, Any]:
        """Preview a stop-limit order (a limit order at limit_price once the last traded price reaches stop_price). Returns a token for confirm_order."""
        return await desk.preview("stop_limit", ticker, quantity, limit_price=limit_price, stop_price=stop_price, time_validity=time_validity)

    @server.tool()
    async def confirm_order(token: str) -> dict[str, Any]:
        """Place a previewed order. Only call this after the user approves the preview. Each token works once."""
        return await desk.confirm(token)

    @server.tool()
    async def cancel_order(order_id: int) -> str:
        """Ask Trading 212 to cancel a pending order."""
        return await desk.cancel(order_id)

    return server


def main() -> None:
    settings = load_settings()
    client = T212Client(settings.base_url, settings.api_key, settings.api_secret)
    instrument_cache = settings.cache_dir / f"instruments-{settings.env}.json"
    create_server(client, instrument_cache, settings.log_path, settings.trading_enabled, settings.max_order_gbp, settings.max_daily_gbp).run()
