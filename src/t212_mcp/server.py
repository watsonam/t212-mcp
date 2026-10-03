import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from mcp.server.mcpserver import MCPServer

from t212_mcp.client import T212Client
from t212_mcp.config import load_settings

INSTRUMENT_CACHE_SECONDS = 86400


def next_cursor(next_page_path: str | None) -> int | None:
    if not next_page_path or not (cursor := parse_qs(urlparse(next_page_path).query).get("cursor")):
        return None
    return int(cursor[0])


def create_server(client: T212Client, instrument_cache: Path) -> MCPServer:
    server = MCPServer("trading212", instructions="Read a Trading 212 Stocks ISA. Tickers look like AAPL_US_EQ; use search_instruments to find them, never guess.")

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

    return server


def main() -> None:
    settings = load_settings()
    client = T212Client(settings.base_url, settings.api_key, settings.api_secret)
    create_server(client, settings.cache_dir / f"instruments-{settings.env}.json").run()
