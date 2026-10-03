import asyncio
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


@pytest.fixture
async def spaced_client(api):
    client = T212Client("https://demo.trading212.com", "key", "secret", min_intervals={"positions": 0.2})
    yield client
    await client.aclose()


async def test_spaces_calls_to_same_endpoint(api, spaced_client):
    api.get("positions").respond(json=[])
    start = time.monotonic()
    await spaced_client.positions()
    await spaced_client.positions()
    assert time.monotonic() - start >= 0.2


async def test_spaces_concurrent_calls(api, spaced_client):
    api.get("positions").respond(json=[])
    start = time.monotonic()
    await asyncio.gather(spaced_client.positions(), spaced_client.positions(), spaced_client.positions())
    assert time.monotonic() - start >= 0.4


async def test_ignores_unreadable_rate_limit_reset(api, client):
    api.get("orders").respond(json=[], headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "soon"})
    assert await client.pending_orders() == []


async def test_waits_when_rate_limit_is_used_up(api, client):
    api.get("orders").respond(json=[], headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(time.time() + 0.3)})
    start = time.monotonic()
    await client.pending_orders()
    await client.pending_orders()
    assert time.monotonic() - start >= 0.25
