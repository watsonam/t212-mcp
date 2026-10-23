# t212-mcp

An MCP (Model Context Protocol) server for the Trading 212 public API. It lets an MCP client, such as Claude Code, Claude Desktop, GitHub Copilot in VS Code or Cursor, read a Trading 212 Stocks ISA, and preview and place orders that you approve.

This project is not affiliated with or endorsed by Trading 212. It can place real trades with real money. It comes with no warranty (see [LICENSE](LICENSE)); you are responsible for every order it places.

## What works today

- The read tools have been tested against a live Trading 212 account.
- The order tools have only been tested against mocked HTTP responses. They have not yet placed an order on Trading 212 itself.
- In our use, Claude (in Claude Code and Claude Desktop) declined to place trades on the user's behalf. With Claude, expect the order tools to be limited to previews. Other clients and models may call `confirm_order`; every order still needs your approval in the client.
- The server runs on macOS, Linux and Windows, on Python 3.11 or later. The tests run on all three systems for every push to `main` and every pull request.

## Tools

| Tool | Endpoint | Scope |
| --- | --- | --- |
| `get_account_summary` | `GET account/summary` | account |
| `get_positions` | `GET positions` | portfolio |
| `get_pending_orders` | `GET orders` | orders:read |
| `get_order_history` | `GET history/orders` | history:orders |
| `search_instruments` | `GET metadata/instruments` | metadata |
| `get_order` | `GET orders/{id}` | orders:read |
| `preview_market_order` | none | portfolio, metadata |
| `preview_limit_order` | none | portfolio, metadata |
| `preview_stop_order` | none | portfolio, metadata |
| `preview_stop_limit_order` | none | portfolio, metadata |
| `confirm_order` | `POST orders/{type}` | orders:execute |
| `cancel_order` | `DELETE orders/{id}` | orders:execute |

`get_positions` adds `priceInAccountCurrency`, the price per share in GBP (`walletImpact.currentValue / quantity`). `currentPrice` is in the instrument's own currency, often pence for London shares.

The instrument list is cached for 24 hours in `~/.cache/t212-mcp/instruments-<env>.json`, since the endpoint allows one request per 50 seconds. The client spaces calls to each endpoint to stay inside its rate limit.

## Orders

Placing an order takes two calls. A `preview_*` tool checks the order and returns the ticker, name, side, quantity, estimated GBP value and a token. `confirm_order` with that token asks you to approve the order, then places it. A token works once and expires after 5 minutes.

The approval question comes from the server through MCP elicitation, so the model cannot answer it for you. It works with clients on older and newer MCP protocol versions. `cancel_order` asks the same way. If you decline or dismiss the question, nothing is sent. If the MCP client cannot show the question, the order is refused.

Approval is only as strong as your MCP client. A client set to accept server questions automatically, or one that lets the model answer them, defeats it.

The server enforces these rules:

- Live order tools are off unless `T212_LIVE_TRADING=1` is set. With `T212_ENV=demo` they are always on.
- Order tools only work on a GBP account.
- Each order has a GBP cap (default £1,000), and so does each day (default £2,000). Both apply to buys and sells.
- There is no price quote endpoint, so a value is only estimated where it can be bounded. A market order needs a position already held, priced at `walletImpact.currentValue / quantity` plus 5% for price movement. A limit or stop-limit order is valued at quantity times the limit price, converted to GBP.
- A holding worth less than £1 is not used for pricing, since its rounded value gives an unreliable price.
- A stop buy is refused, because its fill price has no bound. Use a stop-limit order.
- A limit price in USD or another foreign currency is converted at the rate implied by the largest held position in that currency. With no such position, the order is refused. A limit price for a London share quoted in pence (GBX) is in pence.
- A sell larger than the quantity available for trading is refused.
- An order request is never retried. On a timeout, a 408 or a 5xx response, or an unreadable response, the tool says the outcome is unknown, and the order counts toward the daily cap. Check `get_pending_orders` and `get_order_history` before trying again. A cancellation with no answer is reported the same way.
- Every preview, request, response and cancellation is appended to `~/.local/state/t212-mcp/orders-<env>.jsonl`, where `~` is your home folder (on Windows, `C:\Users\you`). The daily cap is read from this log, per local calendar day. The log is locked while the daily cap is checked, so two sessions cannot both pass it at once.

To change the caps, create `~/.config/t212-mcp/config.toml`. The server refuses to start if the file is not valid TOML, names an unknown setting, or sets a cap that is not a positive number:

```toml
max_order_gbp = 1000
max_daily_gbp = 2000
```

## Setup

Install [uv](https://docs.astral.sh/uv/), clone this repository, then run:

```bash
uv sync
```

Create an API key in the Trading 212 app (Settings, API). A key for reading only needs account, portfolio, metadata, orders:read and history:orders. Placing orders also needs orders:execute. Restrict the key to your home IP address. Demo and live need separate keys.

The server reads the key and secret from environment variables first, then from the OS keychain.

| Variable | Meaning |
| --- | --- |
| `T212_ENV` | `demo` (default) or `live` |
| `T212_DEMO_API_KEY`, `T212_DEMO_API_SECRET` | demo credentials |
| `T212_LIVE_API_KEY`, `T212_LIVE_API_SECRET` | live credentials |
| `T212_LIVE_TRADING` | `1` enables live order tools |
| `T212_CONFIG` | caps file, default `~/.config/t212-mcp/config.toml` |
| `T212_CACHE_DIR` | instrument cache directory |
| `T212_ORDER_LOG` | order log file |

To keep the secrets in the system keychain instead (the macOS Keychain, Windows Credential Manager, or the Secret Service on Linux):

```bash
uv run keyring set t212-mcp live_api_key
uv run keyring set t212-mcp live_api_secret
```

## Claude Code

```bash
claude mcp add trading212 -s user --env T212_ENV=live -- uv --directory /path/to/t212-mcp run t212-mcp
```

Add `--env T212_LIVE_TRADING=1` to enable live orders.

## Claude Desktop

Add this to `claude_desktop_config.json`. On macOS it is in `~/Library/Application Support/Claude/`; on Windows it is in `%APPDATA%\Claude\`:

```json
{
  "mcpServers": {
    "trading212": {
      "command": "uv",
      "args": ["--directory", "/path/to/t212-mcp", "run", "t212-mcp"],
      "env": {"T212_ENV": "live"}
    }
  }
}
```

Claude Desktop does not inherit your shell environment, so use the keychain or put the variables in `env`. Never commit them.

On Windows, write the path with forward slashes, for example `"C:/Users/you/t212-mcp"`, or escape each backslash.

## Other MCP clients

Any MCP client that can start a local program can run the server. The order tools also need the client to support elicitation, so that it can show you the approval question. Where it does not, orders are refused and the read tools still work. Config file names and locations change between versions, so check your client's documentation if a snippet does not work.

GitHub Copilot in VS Code reads `.vscode/mcp.json` in a workspace:

```json
{
  "servers": {
    "trading212": {
      "type": "stdio",
      "command": "uv",
      "args": ["--directory", "/path/to/t212-mcp", "run", "t212-mcp"],
      "env": {"T212_ENV": "live"}
    }
  }
}
```

Cursor (`~/.cursor/mcp.json`) and Gemini CLI (`~/.gemini/settings.json`) use the same `mcpServers` block as Claude Desktop.

OpenAI Codex CLI reads `~/.codex/config.toml`:

```toml
[mcp_servers.trading212]
command = "uv"
args = ["--directory", "/path/to/t212-mcp", "run", "t212-mcp"]
env = { T212_ENV = "live" }
```

## Tests

```bash
uv run pytest
```

HTTP calls are mocked with respx. The code follows Trading 212's OpenAPI spec, which is not included here. To download it for reference on macOS or Linux:

```bash
mkdir -p spec && curl -sfL https://docs.trading212.com/_spec/api.json -o spec/api.json
```

On Windows, in PowerShell:

```powershell
New-Item -ItemType Directory -Force spec; Invoke-WebRequest https://docs.trading212.com/_spec/api.json -OutFile spec/api.json
```
