import json
import os
import time

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from conftest import structured
from t212_mcp.server import create_server

INSTRUMENTS = [
    {"ticker": "VUSAl_EQ", "name": "Vanguard S&P 500 (Dist)", "shortName": "VUSA", "isin": "IE00B3XXRP09", "currencyCode": "GBX", "type": "ETF"},
    {"ticker": "AAPL_US_EQ", "name": "Apple", "shortName": "AAPL", "isin": "US0378331005", "currencyCode": "USD", "type": "STOCK"},
]


@pytest.fixture
def server(client, tmp_path):
    return create_server(client, tmp_path / "instruments.json", tmp_path / "orders.jsonl")


async def test_positions_add_price_in_account_currency(api, server):
    api.get("positions").respond(json=[{"instrument": {"ticker": "VUSAl_EQ"}, "quantity": 4, "currentPrice": 9000, "walletImpact": {"currency": "GBP", "currentValue": 360.0}}])
    [position] = structured(await server.call_tool("get_positions", {}))
    assert position["priceInAccountCurrency"] == 90.0


async def test_order_history_returns_next_cursor(api, server):
    api.get("history/orders").respond(json={"items": [{"order": {"id": 7}}], "nextPagePath": "/api/v0/equity/history/orders?limit=20&cursor=12345"})
    page = structured(await server.call_tool("get_order_history", {}))
    assert page == {"items": [{"order": {"id": 7}}], "nextCursor": 12345}


async def test_order_history_last_page_has_no_cursor(api, server):
    api.get("history/orders").respond(json={"items": [], "nextPagePath": None})
    assert structured(await server.call_tool("get_order_history", {}))["nextCursor"] is None


async def test_search_matches_name_ticker_and_isin(api, server):
    api.get("metadata/instruments").respond(json=INSTRUMENTS)
    assert [i["ticker"] for i in structured(await server.call_tool("search_instruments", {"query": "vanguard"}))] == ["VUSAl_EQ"]
    assert [i["ticker"] for i in structured(await server.call_tool("search_instruments", {"query": "aapl"}))] == ["AAPL_US_EQ"]
    assert [i["ticker"] for i in structured(await server.call_tool("search_instruments", {"query": "US0378331005"}))] == ["AAPL_US_EQ"]


async def test_instruments_are_cached_on_disk(api, client, tmp_path):
    route = api.get("metadata/instruments").respond(json=INSTRUMENTS)
    await create_server(client, tmp_path / "instruments.json", tmp_path / "orders.jsonl").call_tool("search_instruments", {"query": "apple"})
    await create_server(client, tmp_path / "instruments.json", tmp_path / "orders.jsonl").call_tool("search_instruments", {"query": "apple"})
    assert route.call_count == 1


async def test_stale_cache_is_refetched(api, client, tmp_path):
    cache = tmp_path / "instruments.json"
    cache.write_text(json.dumps([]))
    old = time.time() - 2 * 86400
    os.utime(cache, (old, old))
    api.get("metadata/instruments").respond(json=INSTRUMENTS)
    result = structured(await create_server(client, cache, tmp_path / "orders.jsonl").call_tool("search_instruments", {"query": "apple"}))
    assert [i["ticker"] for i in result] == ["AAPL_US_EQ"]


async def test_api_errors_become_tool_errors(api, server):
    api.get("account/summary").respond(403)
    with pytest.raises(ToolError, match="account"):
        await server.call_tool("get_account_summary", {})
