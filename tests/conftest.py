import pytest
import respx

from t212_mcp.client import T212Client

BASE = "https://demo.trading212.com/api/v0/equity/"


@pytest.fixture
def api():
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        yield mock


@pytest.fixture
async def client(api):
    client = T212Client("https://demo.trading212.com", "key", "secret", min_intervals={})
    yield client
    await client.aclose()


def structured(result):
    content = result.structured_content
    return content["result"] if set(content) == {"result"} else content
