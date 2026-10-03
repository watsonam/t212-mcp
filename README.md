# t212-mcp

An MCP (Model Context Protocol) server for the Trading 212 public API. It lets Claude Code or Claude Desktop read a Trading 212 Stocks ISA.

Phase 1 is read-only. Order tools come later, tested on the demo account first.

## Tools

| Tool | Endpoint | Scope |
| --- | --- | --- |
| `get_account_summary` | `GET account/summary` | account |
| `get_positions` | `GET positions` | portfolio |
| `get_pending_orders` | `GET orders` | orders:read |
| `get_order_history` | `GET history/orders` | history:orders |
| `search_instruments` | `GET metadata/instruments` | metadata |

`get_positions` adds `priceInAccountCurrency`, the price per share in GBP (`walletImpact.currentValue / quantity`). `currentPrice` is in the instrument's own currency, often pence for London shares.

The instrument list is cached for 24 hours in `~/.cache/t212-mcp/instruments-<env>.json`, since the endpoint allows one request per 50 seconds. The client spaces calls to each endpoint to stay inside its rate limit.

## Setup

```bash
uv sync
```

Create an API key in the Trading 212 app (Settings, API). The phase 1 live key gets the read scopes only: account, portfolio, metadata, orders:read, history:orders. Restrict it to your home IP address. Use a separate key for demo.

The server reads the key and secret from environment variables first, then from the OS keychain.

| Variable | Meaning |
| --- | --- |
| `T212_ENV` | `demo` (default) or `live` |
| `T212_DEMO_API_KEY`, `T212_DEMO_API_SECRET` | demo credentials |
| `T212_LIVE_API_KEY`, `T212_LIVE_API_SECRET` | live credentials |
| `T212_CACHE_DIR` | instrument cache directory |

To keep the secrets in the macOS keychain instead:

```bash
uv run keyring set t212-mcp live_api_key
uv run keyring set t212-mcp live_api_secret
```

## Claude Code

```bash
claude mcp add trading212 --env T212_ENV=live -- uv --directory /Users/adamwatson/t212-mcp run t212-mcp
```

## Claude Desktop

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "trading212": {
      "command": "uv",
      "args": ["--directory", "/Users/adamwatson/t212-mcp", "run", "t212-mcp"],
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

HTTP calls are mocked with respx. The OpenAPI spec the code follows is in `spec/api.json`.
