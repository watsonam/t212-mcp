# t212-mcp

An MCP (Model Context Protocol) server for the Trading 212 public API. It lets Claude Code or Claude Desktop read a Trading 212 Stocks ISA and place orders with your approval.

This project is not affiliated with or endorsed by Trading 212. It can place real trades with real money. It comes with no warranty (see [LICENSE](LICENSE)); you are responsible for every order it places.

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

The approval question comes from the server through MCP elicitation, so Claude cannot answer it for you. `cancel_order` asks the same way. If you decline, nothing is sent. If the MCP client cannot show the question, the order is refused.

The server enforces these rules:

- Live order tools are off unless `T212_LIVE_TRADING=1` is set. With `T212_ENV=demo` they are always on.
- Each order has a GBP cap (default £1,000), and so does each day (default £2,000). Both apply to buys and sells.
- There is no price quote endpoint, so a value is only estimated where it can be bounded. A market buy needs a position already held, priced at `walletImpact.currentValue / quantity`. A limit or stop-limit buy is valued at quantity times the limit price, converted to GBP.
- A stop buy is refused, because its fill price has no bound. Use a stop-limit order.
- A limit price in USD or another foreign currency is converted at the rate implied by a held position in that currency. With no such position, the order is refused.
- A sell larger than the quantity available for trading is refused.
- An order request is never retried. On a timeout, a 408 or a 5xx response, the tool says the outcome is unknown, and the order counts toward the daily cap. Check `get_pending_orders` and `get_order_history` before trying again.
- Every preview, request, response and cancellation is appended to `~/.local/state/t212-mcp/orders-<env>.jsonl`. The daily cap is read from this log.

To change the caps, create `~/.config/t212-mcp/config.toml`. The server refuses to start if the file is not valid TOML, names an unknown setting, or sets a cap that is not a positive number:

```toml
max_order_gbp = 1000
max_daily_gbp = 2000
```

## Setup

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

To keep the secrets in the macOS keychain instead:

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

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

## Tests

```bash
uv run pytest
```

HTTP calls are mocked with respx. The code follows Trading 212's OpenAPI spec, which is not included here. To download it for reference:

```bash
mkdir -p spec && curl -sfL https://docs.trading212.com/_spec/api.json -o spec/api.json
```
