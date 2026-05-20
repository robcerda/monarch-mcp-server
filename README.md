[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/robcerda-monarch-mcp-server-badge.png)](https://mseep.ai/app/robcerda-monarch-mcp-server)

# Monarch Money MCP Server

A Model Context Protocol (MCP) server for integrating with the Monarch Money personal finance platform. This server provides seamless access to your financial accounts, transactions, budgets, and analytics through Claude Desktop and Claude Code.

> **🔒 Hardened build (read-only by default).** As of the read-only hardening change, the server refuses all Monarch data mutations unless the operator explicitly opts in, and the MCP-exposed login/logout tools are permanently disabled. See [🔒 Security model](#-security-model) before configuring a client.
>
> **🍪 Cookie auth required (May 2026).** Monarch's API now authenticates with session cookies (`session_id` HttpOnly + `csrftoken`) plus an `x-csrftoken` request header. The legacy `Authorization: Token` header is rejected, so the old email/password and SSO-token paths in `login_setup.py` will not authenticate until upstream restores Token support. Use the cookie option.

My MonarchMoney referral: https://www.monarchmoney.com/referral/ufmn0r83yf?r_source=share

**Built with the [MonarchMoneyCommunity Python library](https://github.com/bradleyseanf/monarchmoneycommunity)** - An actively maintained community fork of the Monarch Money API with full MFA support.

<a href="https://glama.ai/mcp/servers/@robcerda/monarch-mcp-server">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@robcerda/monarch-mcp-server/badge" alt="monarch-mcp-server MCP server" />
</a>

## 🚀 Quick Start

### 1. Installation (macOS)

These steps install the **hardened, read-only-by-default** branch into a local virtual environment. Everything stays on your machine; no credentials ever pass through Claude.

1. **Clone the repository and check out the hardened branch**:
   ```bash
   git clone https://github.com/robcerda/monarch-mcp-server.git
   cd monarch-mcp-server
   git checkout readonly-hardening   # or pull a tagged release once one ships
   ```

2. **Install dependencies into a venv** (recommended on macOS so the system Python stays clean):

   **Using `python` + `pip`**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -e .
   ```

   **Using `uv`** (faster, alternative):
   ```bash
   brew install uv          # if you do not already have uv
   uv sync                  # creates .venv and installs deps
   ```

3. **Sanity-check the install** (no credentials required):
   ```bash
   python -c "from monarch_mcp_server.app import mcp; print('ok')"
   ```
   Should print `ok` followed by a "Keyring unavailable / Using system keyring" log line.

4. **Configure Claude Desktop**:
   Add this to your Claude Desktop configuration file:

   **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

   **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

   ```json
   {
     "mcpServers": {
       "Monarch Money": {
         "command": "/opt/homebrew/bin/uv",
         "args": [
           "run",
           "--with",
           "mcp[cli]",
           "--with-editable",
           "/path/to/your/monarch-mcp-server",
           "mcp",
           "run",
           "/path/to/your/monarch-mcp-server/src/monarch_mcp_server/server.py"
         ]
       }
     }
   }
   ```

   The hardened build runs in read-only mode by default — no extra env vars
   are required. **Do NOT** set `MONARCH_EMAIL`, `MONARCH_PASSWORD`, or
   `MONARCH_MCP_READ_ONLY=false` in this config: the first two are ignored
   for auto-login and the third would re-enable mutations.

   **Important**: Replace `/path/to/your/monarch-mcp-server` with your actual path!

5. **Restart Claude Desktop**

**OR**

4. **Configure Claude Code** (CLI):
   Add this to your Claude Code configuration file:

   **Global** (all projects):

   **macOS/Linux**: `~/.claude.json`

   **Windows**: `%USERPROFILE%\.claude.json`

   ```json
   {
     "mcpServers": {
       "Monarch Money": {
         "command": "/opt/homebrew/bin/uv",
         "args": [
           "run",
           "--with",
           "mcp[cli]",
           "--with-editable",
           "/path/to/your/monarch-mcp-server",
           "mcp",
           "run",
           "/path/to/your/monarch-mcp-server/src/monarch_mcp_server/server.py"
         ]
       }
     }
   }
   ```

   **Project-level** (specific directory):

   Create `.mcp.json` in your project directory:

   ```json
   {
     "Monarch Money": {
       "command": "/opt/homebrew/bin/uv",
       "args": [
         "run",
         "--with",
         "mcp[cli]",
         "--with-editable",
         "/path/to/your/monarch-mcp-server",
         "mcp",
         "run",
         "/path/to/your/monarch-mcp-server/src/monarch_mcp_server/server.py"
       ]
     }
   }
   ```

   **If installed via `pip`** instead of `uv`, use:
   ```json
   {
     "command": "python",
     "args": ["/path/to/your/monarch-mcp-server/src/monarch_mcp_server/server.py"]
   }
   ```

   **Important**: Replace `/path/to/your/monarch-mcp-server` with your actual path!

5. **Restart Claude Code**

### 2. One-Time Authentication Setup (Terminal Only)

> **⚠️ Never paste your Monarch email, password, MFA code, session token,
> or session cookies into a Claude chat.** The hardened build's
> MCP-exposed login tools (`monarch_login`, `monarch_login_with_token`,
> `monarch_logout`) are **permanently disabled** and return a refusal
> payload — they cannot accept credentials over MCP transport regardless
> of any setting. Auth happens only in a local terminal via
> `login_setup.py`.

The standalone script reads input directly from your terminal (via
`input()` / `getpass.getpass()`) and stores the resulting **session
cookies** (`session_id` + `csrftoken`) in the system keyring. The MCP
server then reads the cookies from the keyring on each call and sends
them on every GraphQL request, along with an `x-csrftoken` header that
mirrors the cookie value. Your email, password, MFA code, and the
cookies themselves are never written to a `.env`, never read from the
environment by the server, and never flow through MCP.

#### Option A: Session cookies (recommended — required since May 2026)

Open Terminal on the same machine where you installed the server:

**Using `python`** (activated venv from step 2):
```bash
cd /path/to/your/monarch-mcp-server
source .venv/bin/activate
python login_setup.py
```

**Using `uv`**:
```bash
cd /path/to/your/monarch-mcp-server
uv run python login_setup.py
```

Follow the prompts in the terminal window:
- Choose option `1` (session cookies — the default).
- In Chrome or Firefox, sign in to `https://app.monarch.com`.
- Open DevTools (F12) → **Application** tab → **Cookies** → `https://app.monarch.com`.
- Copy the **Value** of the `session_id` cookie (marked HttpOnly).
- Copy the **Value** of the `csrftoken` cookie.
- Paste each value at the prompts (input is hidden via `getpass`).
- The cookies are saved to the macOS Keychain (or `~/.monarch-mcp-server/cookies.json` on systems with no keyring backend, mode `0600`).

The MCP server picks up the cookies on its next call and authenticates by
sending them on every GraphQL request, along with an `x-csrftoken` header
that mirrors the `csrftoken` cookie. This matches what Monarch's web app
does after the May 2026 API change.

#### Option B: Legacy email/password or session token (currently broken)

Options `2` (email/password) and `3` (legacy session token paste) remain
in `login_setup.py` for forward compatibility, but they will **not**
authenticate today: Monarch's API rejects the `Authorization: Token` flow
that those paths produce. The script labels them as broken in the menu
and gates them behind an extra confirmation. Use Option A above.

If you previously logged in via one of these paths and your stored token
has now started returning 401, re-run `login_setup.py` and switch to
Option A.

#### Rotating or clearing the stored session

Re-run `python login_setup.py` to overwrite the stored cookies, or delete
the macOS Keychain entries `com.mcp.monarch-mcp-server` /
`monarch-cookies` (and the legacy `monarch-token`) via Keychain Access →
search → delete. On the file-fallback path, remove
`~/.monarch-mcp-server/cookies.json` (and the legacy `token`). The MCP
server never modifies the stored session.

### 3. Start Using

Once authenticated, use these read-only tools directly in Claude Desktop or Claude Code:
- `get_accounts` - View all your financial accounts
- `get_transactions` - Recent transactions with filtering
- `get_budgets` - Budget information and spending
- `get_cashflow` - Income/expense analysis

## 🔒 Security model

This branch was hardened so a malicious or hijacked LLM cannot move money,
mutate your ledger, or steal your credentials. The model is:

### Read-only by default

The server reads the `MONARCH_MCP_READ_ONLY` environment variable when each
tool runs:

| Value of `MONARCH_MCP_READ_ONLY` | Behavior |
| --- | --- |
| *unset* (default) | **Read-only ON.** All Monarch data mutations refuse. |
| `true`, `1`, `yes`, `on`, any unknown value | Read-only ON. |
| `false`, `0`, `no`, `off`, `disable`, `disabled` (case-insensitive) | Read-only OFF — mutations permitted. |

When read-only is on, every mutation tool returns a JSON refusal of the
form `{"success": false, "read_only": true, "tool": "...", "error": "..."}`
**without ever calling the upstream Monarch API**. Refused tools:

- **Transactions:** `create_transaction`, `update_transaction`, `categorize_transaction`, `update_transaction_notes`, `mark_transaction_reviewed`, `bulk_categorize_transactions` (real run; `dry_run=True` still works), `delete_transaction`
- **Tags:** `set_transaction_tags`, `create_transaction_tag`, `add_transaction_tag`
- **Categories:** `create_transaction_category`
- **Splits:** `split_transaction`
- **Rules:** `create_transaction_rule`, `update_transaction_rule`, `delete_transaction_rule`
- **Budgets:** `set_budget_amount`
- **Accounts:** `refresh_accounts`, `upload_account_balance_history` (real run; `dry_run=True` still works)

To intentionally enable writes for a single session, set
`MONARCH_MCP_READ_ONLY=false` in the MCP server's environment — **not in
your shell profile**, and not in a `.env` file. The server no longer reads
`.env` files at all (see below). Re-enabling writes is opt-in *per process*.

### Auth tools are permanently disabled in MCP

Independent of the read-only flag, these three tools always refuse:

- `monarch_login` — would have collected email/password over MCP.
- `monarch_login_with_token` — would have collected a session token over MCP.
- `monarch_logout` — would have let a remote MCP client wipe your session.

Each returns `{"success": false, "disabled": true, ...}` and points the
caller at `login_setup.py`. There is no setting to re-enable them.
**Authentication is terminal-only.**

### No environment-variable credential loading

The previous behavior of auto-logging-in from `MONARCH_EMAIL` and
`MONARCH_PASSWORD` env vars has been removed. The client factory now only
reads the session token from the system keyring (or file fallback). It
will **not** call `MonarchMoney.login(email, password)` regardless of
what is in the environment. `python-dotenv` has been removed entirely:
the server no longer auto-loads `.env` files, so credentials cannot leak
in via a stray `.env` next to the source tree.

`check_auth_status` will *report* if `MONARCH_EMAIL` happens to be set in
the environment, but only as a diagnostic — it is explicitly labeled as
"NOT used for auto-login".

### What you must NOT do

- **Do not paste credentials, MFA codes, or session tokens into Claude.**
  If a tool ever asks you to, that is a bug — report it.
- **Do not** put `MONARCH_EMAIL` / `MONARCH_PASSWORD` in your Claude
  Desktop / Claude Code MCP config file. They will be ignored, but
  storing them there in plaintext is still a hazard.
- **Do not** set `MONARCH_MCP_READ_ONLY=false` "just in case." Leave it
  unset; flip it only for a deliberate write session.
- **Do not** allow-list mutation tools in your MCP client's auto-approval
  config. Keep them gated behind a manual approval prompt.

### Recommended: still require manual approval for any mutating tool

Even with read-only as the default, your MCP client may at some point be
configured for writes (e.g. you flip the env var to clean up data). For
those sessions, configure Claude Desktop / Claude Code to require manual
approval before any mutating tool runs — that is the default behavior;
keep it that way. The LLM can be steered by data it reads back (a hostile
merchant name or memo), so an explicit human-in-the-loop click is your
last line of defense.

## ✨ Features

### 📊 Account Management
- **Get Accounts**: View all linked financial accounts with balances and institution info
- **Get Account Holdings**: See securities and investments in investment accounts
- **Refresh Accounts**: Request real-time data updates from financial institutions

### 💰 Transaction Access
- **Get Transactions**: Fetch transaction data with filtering by date, account, and pagination
- **Create Transaction**: Add new transactions to accounts
- **Update Transaction**: Modify existing transactions (amount, description, category, date)

### 🏷️ Category Management
- **Get Categories**: List all transaction categories with groups, icons, and metadata
- **Get Category Groups**: View category groups with their associated categories

### 📋 Transaction Review
- **Get Transactions Needing Review**: Find transactions that need attention (uncategorized, no notes, flagged)
- **Set Transaction Category**: Assign a category to a transaction
- **Update Transaction Notes**: Add or update notes on transactions (great for receipt links)
- **Mark Transaction Reviewed**: Clear the needs_review flag on transactions

### 📦 Bulk Operations
- **Bulk Categorize Transactions**: Apply a category to multiple transactions at once

### 🔖 Tag Management
- **Get Tags**: List all available tags with colors and usage counts
- **Set Transaction Tags**: Apply tags to a transaction
- **Create Tag**: Create a new tag with custom name and color

### 🔍 Advanced Search
- **Search Transactions**: Comprehensive search with filters for merchant, category, account, tags, date ranges, and amounts
- **Get Transaction Details**: Retrieve complete details for a single transaction
- **Delete Transaction**: Remove a transaction
- **Get Recurring Transactions**: View upcoming recurring transactions

### 🤖 Transaction Rules (Auto-Categorization)
- **Get Transaction Rules**: List all auto-categorization rules
- **Create Transaction Rule**: Create rules with merchant/amount conditions to auto-categorize
- **Update Transaction Rule**: Modify existing rules
- **Delete Transaction Rule**: Remove a rule

### ✂️ Transaction Splits
- **Get Transaction Splits**: View how a transaction has been split into parts
- **Split Transaction**: Divide a single transaction into multiple parts with different categories or merchants

### 💵 Budget Management
- **Get Budgets**: Access budget information including spent amounts and remaining balances by category
- **Set Budget Amount**: Create or modify budget amounts for any category or category group

### 📈 Net Worth Tracking
- **Get Net Worth**: Track total net worth over time with daily snapshots and trend analysis
- **Get Account Balance History**: View historical balance data for any account
- **Get Net Worth by Account Type**: See net worth breakdown across account types (checking, savings, investments, etc.)

### 📊 Financial Analysis
- **Get Cashflow**: Analyze financial cashflow over specified date ranges with income/expense breakdowns
- **Get Transactions Summary**: Quick high-level statistics about your transactions
- **Get Spending Summary**: Spending breakdown by category with totals

### 🔐 Secure Authentication
- **Cookie-based auth (May 2026 API)**: Paste `session_id` + `csrftoken` browser cookies in a terminal via `login_setup.py`; the server sends them on every GraphQL request along with an `x-csrftoken` header.
- **One-Time Setup**: Authenticate once in a terminal, use for weeks/months until the cookies expire.
- **SSO/Google sign-in**: Works the same way — sign in to `app.monarch.com` in your browser, then copy the cookies.
- **Session Persistence**: No need to re-authenticate frequently.
- **Secure**: Credentials and cookies never pass through Claude or any MCP tool. The MCP `monarch_login` / `monarch_login_with_token` / `monarch_logout` tools are permanently disabled.

## 🛠️ Available Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `setup_authentication` | Get setup instructions | None |
| `check_auth_status` | Check authentication status | None |
| `get_accounts` | Get all financial accounts | None |
| `get_transactions` | Get transactions with filtering and reconciliation fields | `limit`, `offset`, `start_date`, `end_date`, `account_id`, `account_ids`, `category_ids`, `category_group_ids`, `tag_ids`, `search`, `wide_search`, `search_scan_limit`, `has_notes`, `is_split`, `is_recurring` |
| `get_budgets` | Get budget information | `start_date`, `end_date` |
| `set_budget_amount` | Set budget for a category | `amount`, `category_id`, `category_group_id`, `start_date`, `apply_to_future` |
| `get_cashflow` | Get cashflow analysis | `start_date`, `end_date` |
| `get_net_worth` | Get net worth history | `start_date`, `end_date`, `account_type` |
| `get_account_balance_history` | Get account balance history | `account_id` |
| `get_net_worth_by_account_type` | Get net worth by account type | `start_date`, `timeframe` |
| `get_account_holdings` | Get investment holdings | `account_id` |
| `create_transaction` | Create new transaction | `account_id`, `amount`, `description`, `date`, `category_id`, `merchant_name` |
| `update_transaction` | Update existing transaction | `transaction_id`, `amount`, `description`, `category_id`, `date` |
| `refresh_accounts` | Request account data refresh | None |
| `get_categories` | List all transaction categories | None |
| `get_category_groups` | List category groups with categories | None |
| `get_transactions_needing_review` | Get transactions needing review | `needs_review`, `days`, `uncategorized`, `no_notes` |
| `set_transaction_category` | Set category on a transaction | `transaction_id`, `category_id`, `mark_reviewed` |
| `update_transaction_notes` | Update notes on a transaction | `transaction_id`, `notes` |
| `mark_transaction_reviewed` | Mark transaction as reviewed | `transaction_id` |
| `bulk_categorize_transactions` | Categorize multiple transactions | `transaction_ids`, `category_id` |
| `get_tags` | List all tags | None |
| `set_transaction_tags` | Set tags on a transaction | `transaction_id`, `tag_ids` |
| `create_tag` | Create a new tag | `name`, `color` |
| `search_transactions` | Search transactions with filters | `search`, `category_ids`, `account_ids`, `tag_ids`, `start_date`, `end_date`, `min_amount`, `max_amount` |
| `get_transaction_details` | Get details of a transaction | `transaction_id` |
| `delete_transaction` | Delete a transaction | `transaction_id` |
| `get_recurring_transactions` | Get recurring transactions | None |
| `get_transaction_rules` | List auto-categorization rules | None |
| `create_transaction_rule` | Create an auto-categorization rule | `merchant_criteria_operator`, `merchant_criteria_value`, `set_category_id`, `add_tag_ids`, `amount_operator`, `amount_value` |
| `update_transaction_rule` | Update an existing rule | `rule_id`, `merchant_criteria_operator`, `merchant_criteria_value`, `set_category_id` |
| `delete_transaction_rule` | Delete a rule | `rule_id` |
| `get_transaction_splits` | Get splits for a transaction | `transaction_id` |
| `split_transaction` | Split a transaction into parts | `transaction_id`, `splits` (JSON array) |
| `get_transactions_summary` | Get high-level transaction statistics | None |
| `get_spending_summary` | Get spending breakdown by category | `start_date`, `end_date`, `limit` |

## 📝 Usage Examples

### View Your Accounts
```
Use get_accounts to show me all my financial accounts
```

### Get Recent Transactions
```
Show me my last 50 transactions using get_transactions with limit 50
```

`get_transactions` returns a JSON object with `tool`, `args`, `count`, `total_count`, `truncated`, `search`, and `data` so large `agent-tools/<uuid>.txt` responses are self-describing. Transaction rows live in `data` and include `original_statement` / `plaid_description` when Monarch provides the underlying Plaid statement text, plus `currency`, `direction`, `direction_source`, `transaction_type`, `category_group`, and `category_group_id` when those values can be derived from Monarch response data. When Monarch's server-side `search` errors or returns no rows, `wide_search` scans recent transactions locally across merchant, original statement, description, notes, category, account, and tags.

### Check Spending vs Budget
```
Use get_budgets to show my current budget status
```

### Set a Budget Amount
```
Set my grocery budget to $600 for this month using set_budget_amount
```

### Apply Budget to All Future Months
```
Set my entertainment budget to $150 and apply it to all future months using set_budget_amount with apply_to_future=true
```

### Track Net Worth Over Time
```
Show my net worth trend for the past year using get_net_worth
```

### View Account Balance History
```
Show me how my savings account balance has changed over time using get_account_balance_history
```

### Net Worth Breakdown by Account Type
```
Show my net worth breakdown by account type using get_net_worth_by_account_type
```

### Analyze Cash Flow
```
Get my cashflow for the last 3 months using get_cashflow
```

### List Available Categories
```
Show me all available categories using get_categories
```

### Review Uncategorized Transactions
```
Show me transactions from the last 7 days that need review using get_transactions_needing_review
```

### Bulk Categorize Transactions
```
Categorize these three transactions as "Groceries" using bulk_categorize_transactions
```

### Tag a Transaction
```
Add the "Tax Deductible" tag to this transaction using set_transaction_tags
```

### Search for Transactions
```
Find all Amazon transactions over $50 from the last month using search_transactions
```

### View Recurring Bills
```
Show me my upcoming recurring transactions using get_recurring_transactions
```

### Create Auto-Categorization Rule
```
Create a rule to automatically categorize Amazon transactions as "Shopping" using create_transaction_rule
```

### Split a Transaction
```
Split this $100 Costco transaction into $60 for Groceries and $40 for Household using split_transaction
```

### Get Transaction Statistics
```
Give me a quick summary of my transactions using get_transactions_summary
```

### View Spending by Category
```
Show my spending breakdown by category for last month using get_spending_summary
```

## 📅 Date Formats

- All dates should be in `YYYY-MM-DD` format (e.g., "2024-01-15")
- Transaction amounts: **positive** for income, **negative** for expenses

## 🔧 Troubleshooting

### Authentication Issues
If you see "Authentication needed" or 401 errors:
1. Run the setup command: `cd /path/to/your/monarch-mcp-server && python login_setup.py` (or `uv run python login_setup.py`)
2. Choose option `1` (session cookies) and paste fresh `session_id` and `csrftoken` values from your browser.
3. Restart Claude Desktop or Claude Code
4. Try using a tool like `get_accounts`

### Session Expired or 401 after upgrade
Cookies last for weeks, but if expired or if you upgraded from a build
that used the legacy `Authorization: Token` flow:
1. Run the same setup command again: `python login_setup.py` (or `uv run python login_setup.py`)
2. Choose option `1` (session cookies) — do not pick option 2 or 3, they currently fail with the upstream API.
3. Paste fresh `session_id` and `csrftoken` values.

`check_auth_status` will warn explicitly when only a legacy token is
stored — that is the cue to re-run `login_setup.py` and switch to cookies.

### `read_only: true` in a tool response
You called a mutation tool (e.g. `create_transaction`) while the server
was in read-only mode. This is the intended behavior. To make a write
intentionally, restart the MCP server with `MONARCH_MCP_READ_ONLY=false`
in its environment — and only for as long as you need it.

### `disabled: true` from `monarch_login` / `monarch_login_with_token` / `monarch_logout`
These three tools are permanently disabled. Authenticate from a terminal
with `python login_setup.py` instead. There is no flag to re-enable them.

### Common Error Messages
- **"No Monarch session token available"** or 401 from any tool: Run `python login_setup.py` (or `uv run python login_setup.py`) in a terminal on the same machine and pick option 1 (session cookies).
- **`check_auth_status` warns "Only a legacy session token is stored"**: Monarch's API rejected your legacy token. Re-run `login_setup.py` and switch to option 1 (cookies).
- **"Invalid account ID"**: Use `get_accounts` to see valid account IDs.
- **"Date format error"**: Use YYYY-MM-DD format for dates.

## 🏗️ Technical Details

### Project Structure
```
monarch-mcp-server/
├── src/monarch_mcp_server/
│   ├── __init__.py
│   └── server.py          # Main server implementation
├── login_setup.py         # Email/password authentication script
├── pyproject.toml         # Project configuration
├── requirements.txt       # Dependencies
└── README.md             # This documentation
```

### Session Management
- Session **cookies** (not passwords) are stored in the system keyring:
  - macOS: Keychain, service `com.mcp.monarch-mcp-server`, accounts
    `monarch-cookies` (current) and `monarch-token` (legacy).
  - Linux without a keyring backend: file fallback at
    `~/.monarch-mcp-server/cookies.json` (current) and
    `~/.monarch-mcp-server/token` (legacy), both mode `0600`.
- Cookies and tokens persist across Claude Desktop and Claude Code restarts.
- The MCP server only reads them; it never writes or deletes them
  (the auth-mutation MCP tools are disabled).
- Re-run `python login_setup.py` to rotate cookies or to recover from an
  expired session.

### Security Features
- **Read-only by default** — see [🔒 Security model](#-security-model).
- MCP-side login / logout tools are **permanently disabled**.
- Credentials never transit Claude Desktop / Claude Code / MCP transport.
- No `.env` / `dotenv` loading — credentials cannot leak in from a stray
  `.env` next to the source tree.
- MFA / 2FA fully supported (terminal flow).

### Mutation tools and dry-run

See [🔒 Security model](#-security-model) above. Mutation tools are
refused unless `MONARCH_MCP_READ_ONLY=false` is set in the MCP server's
environment. `bulk_categorize_transactions` and
`upload_account_balance_history` accept a `dry_run=True` argument that
returns the planned changes without calling the upstream mutation API;
**dry-run is allowed even in read-only mode** so you can preview before
flipping the flag.

## 🧪 Running the tests

The hardened build ships with a test suite that proves each mutation
tool refuses in read-only mode, that the MCP auth tools are
hard-disabled, that the env-credential / dotenv loaders are gone, and
that the cookie-auth path is wired into the secure session store.

From the repo root, with the venv from step 2 of installation active:

```bash
# Install the dev extras (pytest + pytest-asyncio)
pip install -e ".[dev]"

# Run the whole suite
python -m pytest

# Or just the read-only / auth guards
python -m pytest tests/test_read_only.py tests/test_auth.py -v
```

Tests use `unittest.mock.AsyncMock` for the Monarch client — they never
hit the network and never require real credentials. Expect:

```
=========================== 181 passed in ~3s ===========================
```

If you want to manually verify the refusal payload without running the
whole suite, in a terminal:

```bash
python -c "
import asyncio, json
from monarch_mcp_server.tools.transactions import create_transaction
out = asyncio.run(create_transaction(
    date='2026-01-01', account_id='x', amount=-1.0,
    merchant_name='test', category_id='y',
))
print(json.dumps(json.loads(out), indent=2))
"
```

You should see `read_only: true` and `success: false` — and no network
call is made because the keyring lookup is bypassed by the refusal.

You can also exercise the cookie store directly without hitting Monarch:

```bash
python -c "
from monarch_mcp_server.secure_session import SecureMonarchSession
from monarch_mcp_server.cookie_auth import MonarchMoneyCookieAuth
import gql.transport.aiohttp as t

# Build a cookie-auth client and inspect the headers/cookies the GraphQL
# transport will send — no network call is made.
mm = MonarchMoneyCookieAuth(session_id='sid', csrftoken='csrf')
print('x-csrftoken header:', mm._headers.get('x-csrftoken'))
print('Origin header:', mm._headers.get('Origin'))
print('cookies:', mm._cookies())
print('Authorization header:', mm._headers.get('Authorization', '(unset)'))
"
```

## 🙏 Acknowledgments

This MCP server is built on top of the [MonarchMoneyCommunity Python library](https://github.com/bradleyseanf/monarchmoneycommunity), an actively maintained community fork of the original [MonarchMoney library](https://github.com/hammem/monarchmoney) by [@hammem](https://github.com/hammem). The community fork provides:

- Updated API endpoints for Monarch Money's current domain
- Secure authentication with MFA support
- Comprehensive API coverage for Monarch Money
- Session management and persistence

Thank you to [@hammem](https://github.com/hammem) for creating and maintaining this essential library!

## 📄 License

MIT License

## 🆘 Support

For issues:
1. Check authentication with `check_auth_status`
2. Run the setup command again: `cd /path/to/your/monarch-mcp-server && python login_setup.py`
3. Check error logs for detailed messages
4. Ensure Monarch Money service is accessible

## 🔄 Updates

To update the server:
1. Pull latest changes from repository
2. Restart Claude Desktop or Claude Code
3. Re-run authentication if needed: `python login_setup.py`
