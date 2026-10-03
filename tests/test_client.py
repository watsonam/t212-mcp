import base64
import time

import pytest

from t212_mcp.client import T212Client, T212Error


async def test_sends_basic_auth(api, client):
    route = api.get("account/summary").respond(json={"id": 1, "currency": "GBP"})
    assert await client.account_summary() == {"id": 1, "currency": "GBP"}
    assert route.calls.last.request.headers["authorization"] == "Basic " + base64.b64encode(b"key:secret").decode()


async def test_positions_filters_by_ticker(api, client):
    route = api.get("positions").respond(json=[])
    await client.positions("AAPL_US_EQ")
    assert route.calls.last.request.url.params["ticker"] == "AAPL_US_EQ"


async def test_order_history_drops_unset_params(api, client):
    route = api.get("history/orders").respond(json={"items": [], "nextPagePath": None})
    await client.order_history(limit=50)
    assert dict(route.calls.last.request.url.params) == {"limit": "50"}


async def test_403_names_missing_scope(api, client):
    api.get("history/orders").respond(403)
    with pytest.raises(T212Error, match="history:orders"):
        await client.order_history()


async def test_401_says_bad_key(api, client):
    api.get("positions").respond(401)
    with pytest.raises(T212Error, match="API key"):
        await client.positions()


async def test_429_reports_reset(api, client):
    api.get("orders").respond(429, headers={"x-ratelimit-reset": "1759480000"})
    with pytest.raises(T212Error, match="1759480000"):
        await client.pending_orders()


async def test_spaces_calls_to_same_endpoint(api):
    api.get("positions").respond(json=[])
    client = T212Client("https://demo.trading212.com", "key", "secret", min_intervals={"positions": 0.2})
    start = time.monotonic()
    await client.positions()
    await client.positions()
    assert time.monotonic() - start >= 0.2
    await client.aclose()
