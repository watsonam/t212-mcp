import json
import os
import time

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError


@pytest.fixture
def server(make_server):
    return make_server()


async def test_positions_add_price_in_account_currency(api, server, call):
    api.get("positions").respond(json=[{"instrument": {"ticker": "VUSAl_EQ"}, "quantity": 4, "currentPrice": 9000, "walletImpact": {"currency": "GBP", "currentValue": 360.0}}])
    [position] = await call(server, "get_positions")
    assert position["priceInAccountCurrency"] == 90.0


async def test_order_history_returns_next_cursor(api, server, call):
    api.get("history/orders").respond(json={"items": [{"order": {"id": 7}}], "nextPagePath": "/api/v0/equity/history/orders?limit=20&cursor=12345"})
    assert await call(server, "get_order_history") == {"items": [{"order": {"id": 7}}], "nextCursor": 12345}


async def test_order_history_last_page_has_no_cursor(api, server, call):
    api.get("history/orders").respond(json={"items": [], "nextPagePath": None})
    assert (await call(server, "get_order_history"))["nextCursor"] is None


@pytest.mark.parametrize(("query", "ticker"), [("vanguard", "VUSAl_EQ"), ("aapl", "AAPL_US_EQ"), ("US0378331005", "AAPL_US_EQ")])
async def test_search_matches_name_ticker_and_isin(account, server, call, query, ticker):
    assert [i["ticker"] for i in await call(server, "search_instruments", {"query": query})] == [ticker]


async def test_instruments_are_cached_on_disk(account, make_server, call):
    await call(make_server(), "search_instruments", {"query": "apple"})
    await call(make_server(), "search_instruments", {"query": "apple"})
    assert account["instruments"].call_count == 1


async def test_stale_cache_is_refetched(account, make_server, call, tmp_path):
    cache = tmp_path / "instruments.json"
    cache.write_text(json.dumps([]), encoding="utf-8")
    old = time.time() - 2 * 86400
    os.utime(cache, (old, old))
    assert [i["ticker"] for i in await call(make_server(), "search_instruments", {"query": "apple"})] == ["AAPL_US_EQ"]


async def test_corrupt_cache_is_refetched(account, make_server, call, tmp_path):
    (tmp_path / "instruments.json").write_text("[{\"ticker\": ", encoding="utf-8")
    assert [i["ticker"] for i in await call(make_server(), "search_instruments", {"query": "apple"})] == ["AAPL_US_EQ"]
    assert json.loads((tmp_path / "instruments.json").read_text(encoding="utf-8"))[0]["ticker"] == "VUSAl_EQ"


async def test_cache_that_is_not_text_is_refetched(account, make_server, call, tmp_path):
    (tmp_path / "instruments.json").write_bytes(b"\xff\xfe\x00")
    assert [i["ticker"] for i in await call(make_server(), "search_instruments", {"query": "apple"})] == ["AAPL_US_EQ"]


async def test_order_history_passes_cursor_and_limit(api, server, call):
    route = api.get("history/orders").respond(json={"items": [], "nextPagePath": None})
    await call(server, "get_order_history", {"cursor": 99, "limit": 50, "ticker": "AAPL_US_EQ"})
    assert dict(route.calls.last.request.url.params) == {"cursor": "99", "limit": "50", "ticker": "AAPL_US_EQ"}


@pytest.mark.parametrize(("tool", "args"), [("get_order_history", {"limit": 0}), ("get_order_history", {"limit": 51}), ("search_instruments", {"query": "a", "limit": -1})])
async def test_limits_out_of_range_are_refused(account, server, call, tool, args):
    route = account.get("history/orders").respond(json={"items": [], "nextPagePath": None})
    with pytest.raises(ToolError):
        await call(server, tool, args)
    assert route.call_count == 0


async def test_read_tool_network_error_says_no_answer(api, server, call):
    api.get("positions").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ToolError, match="No answer"):
        await call(server, "get_positions")


async def test_api_errors_become_tool_errors(api, server, call):
    api.get("account/summary").respond(403)
    with pytest.raises(ToolError, match="account"):
        await call(server, "get_account_summary")
