[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/robcerda-monarch-mcp-server-badge.png)](https://mseep.ai/app/robcerda-monarch-mcp-server)

# Monarch Money MCP Server

A Model Context Protocol (MCP) server for the [Monarch Money](https://www.monarchmoney.com) personal finance platform. Exposes accounts, transactions, budgets, and cashflow as tools any MCP client (Claude Code, Claude Desktop, etc.) can call.

Built on the [MonarchMoneyCommunity](https://github.com/bradleyseanf/monarchmoneycommunity) Python library, which maintains the underlying GraphQL API client and MFA support.

## Quick Start

### 1. Install

```bash
git clone https://github.com/robcerda/monarch-mcp-server.git
cd monarch-mcp-server
uv sync
```

(`pip install -r requirements.txt && pip install -e .` also works.)

### 2. Register the server

**Claude Code** (`~/.claude.json` for global, `.mcp.json` for project-level):

```json
{
  "mcpServers": {
    "monarch-money": {
      "command": "/opt/homebrew/bin/uv",
      "args": [
        "run",
        "--with", "mcp[cli]",
        "--with-editable", "/path/to/monarch-mcp-server",
        "mcp", "run",
        "/path/to/monarch-mcp-server/src/monarch_mcp_server/server.py"
      ]
    }
  }
}
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS): same structure.

Replace `/path/to/monarch-mcp-server` with your checkout path. Restart the client.

### 3. Sign in

From any chat with the MCP server connected, just say:

> sign me in to monarch

The `monarch_login` tool opens a secure form in the client UI for your email, password, and MFA code (if needed). Credentials travel directly from the client UI to the server via the MCP protocol — they are **never** passed as tool arguments and **never** enter the model's context. The resulting session token is saved to your system keyring so you don't need to sign in again until it expires.

If you sign in with Google/SSO, use `monarch_login_with_token` instead and paste your browser's session token (DevTools → Application → Local Storage → `app.monarchmoney.com` → key `token`).

## Tools

### Auth
| Tool | Purpose |
|------|---------|
| `monarch_login` | Password + MFA sign-in via elicitation |
| `monarch_login_with_token` | Paste a browser session token (SSO users) |
| `monarch_logout` | Clear stored session from keyring |
| `check_auth_status` | Report whether the stored session is live |

### Accounts
| Tool | Purpose |
|------|---------|
| `get_accounts` | List all linked accounts with balances |
| `get_account_holdings` | Securities/investments in a given account |
| `refresh_accounts` | Ask Monarch to re-sync from institutions |

### Transactions
| Tool | Purpose |
|------|---------|
| `get_transactions` | Fetch with filtering by date, account, pagination |
| `create_transaction` | Add a new transaction |
| `update_transaction` | Modify fields on an existing transaction |
| `categorize_transaction` | Shortcut: set category on a transaction |

### Categories & tags
| Tool | Purpose |
|------|---------|
| `get_transaction_categories` | List available categories |
| `get_transaction_category_groups` | List category groups |
| `create_transaction_category` | Create a new category |
| `get_transaction_tags` | List available tags |
| `set_transaction_tags` | Replace the tags on a transaction |
| `add_transaction_tag` | Add a tag without clobbering existing ones |
| `create_transaction_tag` | Create a new tag |

### Budgets & cashflow
| Tool | Purpose |
|------|---------|
| `get_budgets` | Current budget status |
| `get_cashflow` | Income/expense analysis |

## Security

- **Credentials never reach the model.** Sign-in uses MCP [elicitation](https://modelcontextprotocol.io) (form mode): email, password, and MFA code flow client-UI → server directly as a protocol message. They never appear in tool arguments, the transcript, or the model's context window.
- **Sessions stored in the system keyring.** macOS Keychain, GNOME Keyring / KWallet, or Windows Credential Manager, via [`keyring`](https://pypi.org/project/keyring/). A file fallback at `~/.monarch-mcp-server/token` with `0600` permissions is used on systems without a usable backend.
- **MFA supported.** If Monarch requires MFA, the login tool re-elicits just the code and retries.
- **No plaintext password on disk.** Only the short-lived session token is persisted.

## Date formats & sign conventions

- Dates: `YYYY-MM-DD` everywhere.
- Transaction amounts: **positive** = income, **negative** = expense.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Not signed in to Monarch Money` | Call `monarch_login` |
| `Stored token appears invalid` | Call `monarch_login` to refresh |
| Tools don't appear in the client | Restart the client (MCP tool lists are cached at session start) |
| `Python>=3.12,<3.14` from uv | Launch the client from a shell with Python 3.12+ on PATH, or pin with `--python 3.12` in the MCP command args |

## Architecture

### Components

```
  ┌──────────────────────────┐
  │  MCP client              │   Claude Code / Claude Desktop / ...
  │  (Claude Code, etc.)     │
  └──────────┬───────────────┘
             │ stdio (MCP protocol: JSON-RPC + elicitation)
             ▼
  ┌──────────────────────────┐
  │  monarch-mcp-server      │   this package
  │  ├─ server.py            │     tool definitions (20 tools)
  │  ├─ auth.py              │     elicitation-based login flow
  │  └─ secure_session.py    │     keyring / file-fallback storage
  └──────────┬───────────────┘
             │ Python API
             ▼
  ┌──────────────────────────┐
  │  monarchmoneycommunity   │   GraphQL client, auth, endpoints
  └──────────┬───────────────┘
             │ HTTPS (GraphQL)
             ▼
  ┌──────────────────────────┐
  │  Monarch Money API       │
  └──────────────────────────┘
```

### Auth flow (`monarch_login`)

Elicitation keeps credentials out of the model's context: they travel client-UI → server directly over the MCP protocol and the server only persists the short-lived session token.

```
  Claude Code                          monarch-mcp-server             Monarch API
      │                                       │                            │
      │  tool call: monarch_login             │                            │
      ├──────────────────────────────────────▶│                            │
      │                                       │                            │
      │         ctx.elicit(LoginForm)         │                            │
      │◀──────────────────────────────────────┤                            │
      │  [ UI: email + password form ]        │                            │
      │  user submits                         │                            │
      ├──────────────────────────────────────▶│                            │
      │                                       │  mm.login(email, pw)       │
      │                                       ├───────────────────────────▶│
      │                                       │◀── RequireMFAException ────┤
      │                                       │                            │
      │         ctx.elicit(MFAForm)           │                            │
      │◀──────────────────────────────────────┤                            │
      │  [ UI: MFA code form ]                │                            │
      │  user submits                         │                            │
      ├──────────────────────────────────────▶│                            │
      │                                       │  mm.multi_factor_auth(...) │
      │                                       ├───────────────────────────▶│
      │                                       │◀────── session token ──────┤
      │                                       │                            │
      │                                       │ secure_session.save(token)
      │                                       │        ├─▶ system keyring (primary)
      │                                       │        └─▶ ~/.monarch-mcp-server/token (fallback)
      │                                       │                            │
      │   "Logged in. Session saved."         │                            │
      │◀──────────────────────────────────────┤                            │
```

### Data tool flow (e.g. `get_accounts`)

```
  Claude Code ──▶ server.py ──▶ _get_client() ──▶ secure_session.load()
                      │                                  │
                      │                                  ▼
                      │                         system keyring / file
                      │                                  │
                      │         ◀─── token ──────────────┘
                      │
                      │  MonarchMoney(token=...).get_accounts()
                      ▼
                 monarchmoneycommunity ──▶ GraphQL ──▶ Monarch API
```

If `secure_session.load()` returns no token, `_get_client()` raises `NotAuthenticated` and the tool returns `isError=true` with "Call `monarch_login` to authenticate."

### Session storage

Session tokens are persisted via the [`keyring`](https://pypi.org/project/keyring/) library:

- **macOS** → Keychain
- **Linux (GNOME/KDE)** → Secret Service (GNOME Keyring / KWallet)
- **Windows** → Credential Manager
- **Fallback** (headless / WSL / no backend) → `~/.monarch-mcp-server/token` with `0600` permissions in a `0700` directory

No plaintext password is ever written to disk — only the rotating session token.

## Project structure

```
monarch-mcp-server/
├── src/monarch_mcp_server/
│   ├── __init__.py
│   ├── server.py           # Tool definitions (20 tools: auth + data)
│   ├── auth.py             # Elicitation-based login flow
│   └── secure_session.py   # Keyring + file-fallback storage
├── tests/
│   ├── conftest.py         # Shared fixtures (mock MonarchMoney client)
│   ├── test_tools.py       # Data tools + auth wrappers + _get_client
│   ├── test_auth.py        # Elicitation login flow (happy, MFA, cancel)
│   └── test_secure_session.py  # Keyring / file fallback / get-client
├── .github/workflows/
│   └── test.yml            # CI: pytest on Python 3.12 and 3.13
├── pyproject.toml
├── requirements.txt
└── README.md
```

## Development

```bash
# install with dev extras
uv sync --extra dev

# run tests
uv run pytest tests/

# run a single test file
uv run pytest tests/test_auth.py -v
```

CI runs pytest on every push to `main` and every pull request.

## Acknowledgments

Built on [MonarchMoneyCommunity](https://github.com/bradleyseanf/monarchmoneycommunity) by [@bradleyseanf](https://github.com/bradleyseanf), an active fork of the original [MonarchMoney](https://github.com/hammem/monarchmoney) library by [@hammem](https://github.com/hammem).

## License

MIT
