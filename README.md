# t212-mcp

I built this so I could ask an AI assistant about my Trading 212 Stocks ISA: what I hold, what it's worth, what orders I have open and what I've traded before. It also lets the assistant set up an order for me, but nothing is ever placed until I say yes to it myself.

It's an MCP server. MCP (Model Context Protocol) is the standard way to give an AI app new tools, so this works with Claude Code, Claude Desktop, GitHub Copilot in VS Code, Cursor and other apps that support MCP.

## Please read this first

- This is a personal project. It isn't made by, affiliated with or endorsed by Trading 212.
- It can place real trades with real money. It comes with no warranty (see [LICENSE](https://github.com/watsonam/t212-mcp/blob/main/LICENSE)), and you're responsible for every order it places.
- Start with a read-only API key. Only add trading permission once you're comfortable with how it works.
- The only official copies are this repository, [github.com/watsonam/t212-mcp](https://github.com/watsonam/t212-mcp), and the [`t212-mcp` package on PyPI](https://pypi.org/project/t212-mcp/), which is built and published from this repository by GitHub Actions. Anything else with a similar name isn't mine, and could be built to steal your key.
- Found a security problem? Please report it privately, as described in [SECURITY.md](https://github.com/watsonam/t212-mcp/blob/main/SECURITY.md).

## Where things stand

- I've connected it to my own live account and fetched my account summary. The other read tools are tested against fake responses, not my real account.
- The order tools are tested against fake responses only. They haven't placed a real order yet.
- When I asked Claude to place a trade, it declined. Claude may simply refuse to trade on your behalf, so with Claude you might only get as far as a preview. Other apps and models may go further, but every order still needs your yes.
- It runs on macOS, Linux and Windows, with Python 3.11 or newer. The tests run on all three every time something is pushed to `main` or a pull request is opened.

## How ordering works

Placing an order always takes two steps.

1. The assistant asks for a preview. You get back what the order is: the share, buy or sell, how many, and roughly what it'll cost in pounds.
2. The assistant asks to confirm. The server then asks you directly, in a pop-up from your AI app, whether to place it. The question spells out the order exactly as it will be sent. If you say no, or close the question, nothing is sent.

The question comes from the server itself, so the assistant can't answer it for you. That only holds if your app shows you the question. An app set to accept these questions automatically, or one that lets the model answer them, removes that protection. If your app can't show the question at all, the order is refused. Cancelling an order asks you the same way, and tells you which order it is, for example "Cancel order 42: SELL 3 x Vanguard S&P 500 (VUSAl_EQ), stop order, stop 8500?".

A preview lasts 5 minutes and can only be used once.

The server checks these rules on every order, whatever the assistant asks for:

- Live trading is off unless you turn it on with `T212_LIVE_TRADING=1`. On the demo account (pretend money) it's always on.
- It only trades on accounts held in pounds (GBP).
- Each order is capped at £1,000 and each day at £2,000. Both caps count sells as well as buys. You can change them (see below).
- Trading 212 doesn't offer a live price feed, so the server only allows orders whose cost it can work out:
  - A market order is only allowed for something you already own. It's priced from your holding, plus 5% in case the price moves.
  - A limit or stop-limit order is priced at the limit you set.
  - A stop buy is refused, because there's no way to know what it'll cost. Use a stop-limit order instead.
  - For shares priced in another currency, such as US dollars, it works out the exchange rate from your largest holding in that currency. If you hold nothing in that currency, the order is refused.
  - Holdings worth under £1 aren't used for pricing, because their rounded values aren't accurate enough.
- London shares are often priced in pence, so a limit price for them is in pence too.
- You can't sell more shares than you have available.
- An order is never sent twice. If Trading 212 doesn't give a clear answer, the server says the outcome is unknown, counts it towards your daily cap, and tells the assistant to check your open orders and history before trying again. Cancellations work the same way.
- Every preview, order and cancellation is written to a log on your computer, at `~/.local/state/t212-mcp/orders-<env>.jsonl`. Only your user account can read it. Here `~` means your home folder (on Windows, `C:\Users\you`). The daily cap is worked out from this log, per calendar day, and the log is locked while it's checked, so two chats can't both slip under the cap at the same time.

## Setting it up

You'll need [uv](https://docs.astral.sh/uv/), a tool for running Python projects. There are two ways to get the server.

The quickest is from PyPI. uv downloads it the first time your AI app starts it, so there's nothing to install now. In the app snippets below, use `uvx` as the command and `["t212-mcp@0.1.0"]` as the arguments. Naming the version means you only move to a new one when you choose to.

The other way is to clone this repository and, from inside it, run:

```bash
uv sync
```

A clone uses exactly the dependency versions the tests ran with, and you can read every change before you `git pull` it.

Next, create an API key in the Trading 212 app, under Settings, then API. You'll get a key and a secret.

- To only read your account, tick account, portfolio, metadata, orders:read and history:orders.
- To place orders too, also tick orders:execute.
- If the app lets you, restrict the key to your home IP address.
- The demo account and your real account need separate keys.

The safest place for the key and secret is your computer's keychain (the macOS Keychain, Windows Credential Manager, or the Secret Service on Linux). Run these and paste each value when asked. Nothing shows on screen while you paste, which is normal.

```bash
uv run keyring set t212-mcp live_api_key
uv run keyring set t212-mcp live_api_secret
```

For a demo key, use `demo_api_key` and `demo_api_secret` instead. You can also set them as environment variables (see the settings table below), but never put them in a file you commit.

## Connecting it to your AI app

The examples below use a clone. In each one, replace `/path/to/t212-mcp` with wherever you cloned this repository. The `--locked` flag makes uv use exactly the versions this repository was tested with, and `--no-dev` leaves out the test tools. On Windows, write the path with forward slashes, like `C:/Users/you/t212-mcp`, or double each backslash.

`T212_ENV=live` points it at your real account. Leave it out to use the demo account.

### Claude Code

```bash
claude mcp add trading212 -s user --env T212_ENV=live -- uv --directory /path/to/t212-mcp run --locked --no-dev t212-mcp
```

Or, from PyPI:

```bash
claude mcp add trading212 -s user --env T212_ENV=live -- uvx t212-mcp@0.1.0
```

To allow live orders, add `--env T212_LIVE_TRADING=1`.

### Claude Desktop

Add this to `claude_desktop_config.json`. On a Mac it's in `~/Library/Application Support/Claude/`, and on Windows it's in `%APPDATA%\Claude\`.

```json
{
  "mcpServers": {
    "trading212": {
      "command": "uv",
      "args": ["--directory", "/path/to/t212-mcp", "run", "--locked", "--no-dev", "t212-mcp"],
      "env": {"T212_ENV": "live"}
    }
  }
}
```

Claude Desktop doesn't see your terminal's environment variables, so keep your key in the keychain, or put the variables in `env`.

### GitHub Copilot in VS Code

Add this to `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "trading212": {
      "type": "stdio",
      "command": "uv",
      "args": ["--directory", "/path/to/t212-mcp", "run", "--locked", "--no-dev", "t212-mcp"],
      "env": {"T212_ENV": "live"}
    }
  }
}
```

### Cursor and Gemini CLI

Cursor (`~/.cursor/mcp.json`) and Gemini CLI (`~/.gemini/settings.json`) use the same `mcpServers` block as Claude Desktop.

### OpenAI Codex CLI

Add this to `~/.codex/config.toml`:

```toml
[mcp_servers.trading212]
command = "uv"
args = ["--directory", "/path/to/t212-mcp", "run", "--locked", "--no-dev", "t212-mcp"]
env = { T212_ENV = "live" }
```

### Other apps

Any app that can run a local MCP server should work. For orders, the app also has to support "elicitation", which is how the server asks you to approve. If it doesn't, orders are refused but reading your account still works. These apps change where they keep their settings from time to time, so if a snippet doesn't work, check the app's own documentation.

## Changing the limits

Create `~/.config/t212-mcp/config.toml` with your own caps, in pounds:

```toml
max_order_gbp = 1000
max_daily_gbp = 2000
```

The server won't start if the file has a typo, a setting it doesn't recognise, or a cap that isn't a positive number. That way a mistake can't quietly switch a cap off.

## Settings

| Variable | What it does |
| --- | --- |
| `T212_ENV` | `demo` (the default) or `live` |
| `T212_LIVE_TRADING` | Set to `1` to allow orders on your live account |
| `T212_DEMO_API_KEY`, `T212_DEMO_API_SECRET` | Demo key, if you're not using the keychain |
| `T212_LIVE_API_KEY`, `T212_LIVE_API_SECRET` | Live key, if you're not using the keychain |
| `T212_CONFIG` | Where the caps file is (default `~/.config/t212-mcp/config.toml`) |
| `T212_CACHE_DIR` | Where the instrument list is cached |
| `T212_ORDER_LOG` | Where the order log is written |

## Tools

These are the tools your AI app can use, with the Trading 212 permission each one needs.

| Tool | What it does | Permission |
| --- | --- | --- |
| `get_account_summary` | Cash, investments and total value | account |
| `get_positions` | What you hold and what it's worth | portfolio |
| `get_pending_orders` | Orders that haven't filled yet | orders:read |
| `get_order` | One open order | orders:read |
| `get_order_history` | Past orders, newest first | history:orders |
| `search_instruments` | Find a share's ticker by name, ticker or ISIN | metadata |
| `preview_market_order` | Preview a market order | portfolio, metadata |
| `preview_limit_order` | Preview a limit order | portfolio, metadata |
| `preview_stop_order` | Preview a stop order (sells only) | portfolio, metadata |
| `preview_stop_limit_order` | Preview a stop-limit order | portfolio, metadata |
| `confirm_order` | Ask you to approve a preview, then place it | orders:execute |
| `cancel_order` | Ask you to approve, then cancel an open order | orders:execute |

A few details:

- `get_positions` adds `priceInAccountCurrency`, the price of one share in pounds. Trading 212's own `currentPrice` is in the share's currency, which is often pence for London shares.
- The full list of shares is saved for 24 hours in `~/.cache/t212-mcp/`, because Trading 212 only allows it to be fetched about once a minute.
- The server spaces out its requests to stay inside Trading 212's rate limits.

## Running the tests

```bash
uv run pytest
```

The tests use fake responses, so they never touch a real account. The code follows Trading 212's API specification, which isn't included here. To download it for reference on a Mac or Linux:

```bash
mkdir -p spec && curl -sfL https://docs.trading212.com/_spec/api.json -o spec/api.json
```

On Windows, in PowerShell:

```powershell
New-Item -ItemType Directory -Force spec; Invoke-WebRequest https://docs.trading212.com/_spec/api.json -OutFile spec/api.json
```
