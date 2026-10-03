import pytest
import respx
from mcp import types
from mcp.client import Client
from mcp.server.mcpserver.exceptions import ToolError

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


async def call(server, tool, args, approve=True, questions=None, elicitation=True):
    async def answer(context, params):
        if questions is not None:
            questions.append(params.message)
        return types.ElicitResult(action="accept", content={"approve": approve})
    async with Client(server, elicitation_callback=answer if elicitation else None, mode="legacy") as connection:
        result = await connection.call_tool(tool, args)
    if result.is_error:
        raise ToolError(result.content[0].text)
    return structured(result)
