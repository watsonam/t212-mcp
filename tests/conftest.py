import asyncio
import json

import pytest
import respx
from mcp import types
from mcp.client import Client
from mcp.server.mcpserver.exceptions import ToolError

from t212_mcp.client import T212Client
from t212_mcp.config import TradingRules
from t212_mcp.server import create_server

BASE = "https://demo.trading212.com/api/v0/equity/"
INSTRUMENTS = [
    {"ticker": "VUSAl_EQ", "name": "Vanguard S&P 500", "shortName": "VUSA", "isin": "IE00B3XXRP09", "currencyCode": "GBX", "type": "ETF"},
    {"ticker": "MSFT_US_EQ", "name": "Microsoft", "shortName": "MSFT", "isin": "US5949181045", "currencyCode": "USD", "type": "STOCK"},
    {"ticker": "AAPL_US_EQ", "name": "Apple", "shortName": "AAPL", "isin": "US0378331005", "currencyCode": "USD", "type": "STOCK"},
    {"ticker": "7203_JP_EQ", "name": "Toyota", "shortName": "7203", "isin": "JP3633400001", "currencyCode": "JPY", "type": "STOCK"},
]
POSITIONS = [
    {"instrument": {"ticker": "VUSAl_EQ", "currency": "GBX"}, "quantity": 10, "quantityAvailableForTrading": 10, "currentPrice": 9000, "walletImpact": {"currentValue": 900.0}},
    {"instrument": {"ticker": "MSFT_US_EQ", "currency": "USD"}, "quantity": 2, "quantityAvailableForTrading": 2, "currentPrice": 400, "walletImpact": {"currentValue": 600.0}},
]


@pytest.fixture
def api():
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def account(api):
    api.get("metadata/instruments", name="instruments").respond(json=INSTRUMENTS)
    api.get("positions", name="positions").respond(json=POSITIONS)
    api.get("account/summary", name="summary").respond(json={"currency": "GBP"})
    return api


@pytest.fixture
async def client(api):
    client = T212Client("https://demo.trading212.com", "key", "secret", min_intervals={})
    yield client
    await client.aclose()


@pytest.fixture
def make_server(client, tmp_path):
    def make(token_seconds=300, **rules):
        return create_server(client, tmp_path / "instruments.json", tmp_path / "orders.jsonl", TradingRules(**{"enabled": True, **rules}), token_seconds)
    return make


@pytest.fixture
def log(tmp_path):
    def read():
        return [json.loads(line) for line in (tmp_path / "orders.jsonl").read_text(encoding="utf-8").splitlines()]
    return read


@pytest.fixture(params=["legacy", "auto"])
def call(request):
    async def call_tool(server, tool, args=None, approve=True, questions=None, elicitation=True, action="accept", content=None, delay=0):
        async def answer(context, params):
            if questions is not None:
                questions.append(params.message)
            await asyncio.sleep(delay)
            return types.ElicitResult(action=action, content=(content or {"approve": approve}) if action == "accept" else None)
        try:
            async with Client(server, elicitation_callback=answer if elicitation else None, mode=request.param) as connection:
                result = await connection.call_tool(tool, args or {})
        except Exception as error:
            raise ToolError(repr(error)) from error
        if result.is_error:
            raise ToolError(result.content[0].text)
        content = result.structured_content
        return content["result"] if set(content) == {"result"} else content
    return call_tool
