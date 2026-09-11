[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/robcerda-monarch-mcp-server-badge.png)](https://mseep.ai/app/robcerda-monarch-mcp-server)

# Monarch Money MCP Server

A Model Context Protocol (MCP) server for integrating with the Monarch Money personal finance platform. This server provides seamless access to your financial accounts, transactions, budgets, and analytics through Claude Desktop and Claude Code.

My MonarchMoney referral: https://www.monarchmoney.com/referral/ufmn0r83yf?r_source=share

**Built with the [MonarchMoneyCommunity Python library](https://github.com/bradleyseanf/monarchmoneycommunity)** - An actively maintained community fork of the Monarch Money API with full MFA support.

<a href="https://glama.ai/mcp/servers/@robcerda/monarch-mcp-server">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@robcerda/monarch-mcp-server/badge" alt="monarch-mcp-server MCP server" />
</a>

## 🚀 Quick Start

### 1. Installation

1. **Clone this repository**:
   ```bash
   git clone https://github.com/robcerda/monarch-mcp-server.git
   cd monarch-mcp-server
   ```

2. **Install dependencies**:

   **Using `uv`** (recommended):
   ```bash
   uv sync --locked
   ```

   `--locked` installs exactly what `uv.lock` pins, verified against the
   hashes it records, and refuses to re-resolve. Without it, `uv sync` is free
   to pick up whatever versions happen to satisfy the ranges today.

   **Using `pip`**:
   ```bash
   pip install -r requirements-lock.txt --require-hashes
   pip install -e . --no-deps
   ```

   `requirements-lock.txt` is generated from `uv.lock` and pins every transitive
   dependency with hashes, so `--require-hashes` gives the pip path the same
   guarantee as the uv one. `--no-deps` on the second command stops pip
   re-resolving what the first command just pinned.

   `pip install -r requirements.txt` still works and installs exactly the same
   set. That file is now a one line include of `requirements-lock.txt`, kept so
   existing setups and scripts do not break. The pins moved out of it because a
   root `requirements.txt` gets resolved as an independent manifest, which had
   started producing a pinned set that disagreed with `uv.lock`.

3. **Configure Claude Desktop**:
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
           "--locked",
           "--project",
           "/path/to/your/monarch-mcp-server",
           "monarch-mcp-server"
         ]
       }
     }
   }
   ```

   **Important**: Replace `/path/to/your/monarch-mcp-server` with your actual path!

   `uv run --locked --project` resolves dependencies from the repo's
   `uv.lock`, and `monarch-mcp-server` is the console script declared in
   `pyproject.toml`. `--locked` matters: without it, a lockfile that has
   drifted from `pyproject.toml` is silently re-resolved against PyPI and the
   recorded hashes stop being enforced. With it, drift is a startup error.
   Earlier versions of this README used `uv run --with 'mcp[cli]'`, which
   builds a fresh unpinned environment on every launch and silently picks up
   whatever the newest release happens to be. That is what broke every install
   when the MCP SDK published 2.0, and the client only reported it as the
   server disconnecting. Pinning the launch to the lockfile means a new
   upstream release cannot change what your server runs.

4. **Restart Claude Desktop**

**OR**

3. **Configure Claude Code** (CLI):
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
           "--locked",
           "--project",
           "/path/to/your/monarch-mcp-server",
           "monarch-mcp-server"
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
         "--locked",
         "--project",
         "/path/to/your/monarch-mcp-server",
         "monarch-mcp-server"
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

4. **Restart Claude Code**

### 2. One-Time Authentication Setup

**Important**: For security and MFA support, authentication is done outside of Claude.

Open a terminal and run:

```bash
cd /path/to/your/monarch-mcp-server
uv run python login_setup.py        # or: python login_setup.py
```

The script offers three login paths:

#### Option 1 (recommended): Session cookies from your browser

Long-lived sessions, supports SSO accounts, and sidesteps Cloudflare CAPTCHA gates on programmatic login. Steps:

1. Log in to https://app.monarch.com in Chrome or Firefox.
2. Open DevTools (F12) → Network tab.
3. Click any request whose Name starts with `graphql` (or any request to `api.monarch.com`).
4. Scroll to Request Headers, find the `cookie:` header, and copy the full value.
5. Save it to the cookie file for your platform (recommended), then re-run the script — it reads the file automatically:

   **macOS / Linux** — `~/.config/monarch-mcp/cookie.txt` (respects `$XDG_CONFIG_HOME`):

   ```bash
   mkdir -p ~/.config/monarch-mcp
   # paste the cookie value into the file with your editor, then:
   chmod 600 ~/.config/monarch-mcp/cookie.txt
   ```

   **Windows** — `%APPDATA%\monarch-mcp\cookie.txt`:

   ```powershell
   New-Item -ItemType Directory -Force "$env:APPDATA\monarch-mcp" | Out-Null
   notepad "$env:APPDATA\monarch-mcp\cookie.txt"   # paste the cookie value, save, close
   ```

   Files under your user profile are already ACL-restricted to your account on Windows; no `chmod` equivalent is needed for typical single-user machines.

   To use a different location on any platform, set the `MONARCH_MCP_COOKIE_FILE` environment variable to the full path.

   Alternatively, paste the value at the interactive prompt — but note that
   POSIX terminals silently truncate pasted input at the canonical-mode
   buffer limit (`MAX_CANON`, 1024 bytes on macOS/Linux), and real Monarch
   cookie headers are usually longer than that, so the prompt path fails
   with a confusing auth error for most users. The cookie file has no
   length limit and survives repo updates.

The script verifies the cookies against the live API before saving them to your system keyring. The cookie file is only read at setup time; the running MCP server uses the keyring session.

#### Option 2: Email and password

Standard interactive login. The script handles:

- Email verification codes (Monarch may send one for a new device session even when MFA is off).
- TOTP MFA codes if you have MFA enabled.
- Cloudflare CAPTCHA detection: if Monarch blocks programmatic login, the script tells you to switch to option 1.

The resulting long-lived session token is saved to your system keyring.

#### Option 3: Legacy session token paste

Kept for users with an existing token captured before the May 2026 API change. Monarch may no longer accept token-only auth on the GraphQL endpoint; if the verification call returns 401, fall back to option 1.

### 3. Start Using

Once authenticated, use these tools directly in Claude Desktop or Claude Code:
- `get_accounts` - View all your financial accounts
- `get_transactions` - Recent transactions with filtering
- `get_budgets` - Budget information and spending
- `get_cashflow` - Income/expense analysis

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

### 🔄 Merchant & Recurring Stream Management
- **Get Merchant**: View a merchant's details including recurring transaction stream configuration
- **Update Merchant**: Modify a merchant's name and/or recurring stream settings (frequency, amount, base date)
- **Review Recurring Stream**: Accept, ignore, or reset recurring transaction streams detected by Monarch

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
- **One-Time Setup**: Authenticate once, use for weeks/months
- **Email OTP Support**: Handles Monarch's email verification flow for new devices/sessions
- **MFA Support**: Full support for two-factor authentication
- **SSO/Google sign-in**: Use `monarch_login_with_token` to paste a session token from your browser
- **Session Persistence**: No need to re-authenticate frequently
- **Secure**: Credentials never pass through Claude

## 🛠️ Available Tools

All 58 registered tools. Required parameters are listed first, optional ones
are marked with a trailing question mark. This table is generated from the
live tool registry and the functions' signatures, so it does not drift.

| Tool | Description | Parameters |
|------|-------------|------------|
| `add_transaction_tag` | Add a tag to a transaction, preserving any tags already on it | `transaction_id`, `tag_id` |
| `bulk_categorize_transactions` | Apply the same category to multiple transactions at once | `transaction_ids`, `category_id`, `mark_reviewed`?, `dry_run`? |
| `categorize_transaction` | Assign a category to a transaction | `transaction_id`, `category_id` |
| `check_auth_status` | Report the stored session and its auth mode | None |
| `create_transaction` | Create a new transaction in Monarch Money | `date`, `account_id`, `amount`, `merchant_name`, `category_id`, `notes`?, `update_balance`? |
| `create_transaction_category` | Create a new transaction category | `group_id`, `transaction_category_name`, `icon`?, `rollover_enabled`?, `rollover_type`? |
| `create_transaction_rule` | Create a new transaction auto-categorization rule | `merchant_criteria_operator`?, `merchant_criteria_value`?, `merchant_criteria_values`?, `merchant_criteria`?, `original_statement_operator`?, `original_statement_values`?, `original_statement_criteria`?, `use_original_statement`?, `amount_operator`?, `amount_value`?, `amount_lower`?, `amount_upper`?, `amount_is_expense`?, `set_category_id`?, `set_merchant_name`?, `add_tag_ids`?, `link_goal_id`?, `hide_from_reports`?, `review_status`?, `account_ids`?, `category_ids`?, `apply_to_existing`? |
| `create_transaction_tag` | Create a new transaction tag | `name`, `color` |
| `debug_session_loading` | Diagnose session loading problems | None |
| `delete_transaction` | Delete a transaction from Monarch Money | `transaction_id` |
| `delete_transaction_rule` | Delete a transaction rule | `rule_id` |
| `get_account_balance_history` | Get historical balance data for a specific account | `account_id` |
| `get_account_holdings` | Get investment holdings for a specific account | `account_id` |
| `get_account_sync_health` | Report the health of each linked institution connection | `stale_after_days`? |
| `get_accounts` | Get all financial accounts from Monarch Money | None |
| `get_budgets` | Get budget information from Monarch Money | `start_date`?, `end_date`? |
| `get_cashflow` | Get cashflow analysis from Monarch Money | `start_date`?, `end_date`? |
| `get_cashflow_by_month` | Get spending trends over time, broken down by category and month | `start_date`, `end_date` |
| `get_category_details` | Get a single category's details including budget amounts for a month | `category_id`, `month`? |
| `get_debt_paydown` | Get the debt paydown plan and the accounts feeding it | `method`? |
| `get_goal_contributions` | Show a goal's budgeted contributions, broken down by funding account | `goal_id`, `month`? |
| `get_goals` | List Monarch savings and debt-paydown goals | None |
| `get_merchant` | Get a merchant's details including recurring transaction stream configuration | `merchant_id` |
| `get_net_worth` | Get net worth history over time | `start_date`?, `end_date`?, `account_type`? |
| `get_net_worth_by_account_type` | Get net worth breakdown by account type over time | `start_date`, `timeframe`? |
| `get_recurring_transactions` | Get upcoming recurring transactions | `start_date`?, `end_date`? |
| `get_spending_summary` | Get a spending summary broken down by category, category group, and merchant | `start_date`?, `end_date`? |
| `get_transaction_categories` | Get all available transaction categories from Monarch Money | None |
| `get_transaction_category_groups` | Get all transaction category groups (parent groupings for categories) | None |
| `get_transaction_details` | Get full details for a specific transaction | `transaction_id` |
| `get_transaction_rules` | Get all transaction auto-categorization rules from Monarch Money | None |
| `get_transaction_splits` | Get the splits for a transaction | `transaction_id` |
| `get_transaction_tags` | Get all available transaction tags from Monarch Money | None |
| `get_transactions` | Get transactions from Monarch Money | `limit`?, `offset`?, `start_date`?, `end_date`?, `account_id`?, `search`?, `category_ids`?, `category_group_ids`?, `account_ids`?, `tag_ids`?, `has_notes`?, `is_split`?, `is_recurring`?, `wide_search`?, `search_scan_limit`? |
| `get_transactions_needing_review` | Get transactions that need review based on various criteria | `needs_review`?, `days`?, `uncategorized_only`?, `without_notes_only`?, `limit`?, `offset`?, `account_id`? |
| `get_transactions_summary` | Get a high-level summary of transactions | None |
| `mark_transaction_reviewed` | Mark a transaction as reviewed (clears the needs_review flag) | `transaction_id` |
| `monarch_login` | Sign in via a secure form in the client UI | None |
| `monarch_login_with_token` | Sign in with a browser copied session token | None |
| `monarch_logout` | Clear the stored session and drop the cached client | None |
| `monarch_whoami` | Report who is signed in and what the account's plan entitles it to | None |
| `refresh_accounts` | Request account data refresh from financial institutions | `account_ids`? |
| `reorder_transaction_rule` | Move a transaction rule to a new position in the evaluation order | `rule_id`, `new_order` |
| `review_recurring_stream` | Set the review status of a recurring transaction stream | `stream_id`, `review_status` |
| `search_transactions` | Search and filter transactions with comprehensive filtering options | `search`?, `limit`?, `offset`?, `start_date`?, `end_date`?, `category_ids`?, `account_ids`?, `tag_ids`?, `has_attachments`?, `has_notes`?, `hidden_from_reports`?, `is_split`?, `is_recurring`? |
| `set_budget_amount` | Set or update a budget amount for a category or category group | `amount`, `category_id`?, `category_group_id`?, `start_date`?, `apply_to_future`? |
| `set_goal_contribution` | Set the budgeted monthly contribution to a goal from one funding account | `goal_id`, `account_id`, `amount` |
| `set_transaction_tags` | Set tags on a transaction | `transaction_id`, `tag_ids` |
| `setup_authentication` | Get setup instructions | None |
| `split_transaction` | Split a transaction into multiple parts with different categories/merchants | `transaction_id`, `splits` |
| `update_account` | Update an account's name, balance, type or visibility settings | `account_id`, `name`?, `balance`?, `account_type`?, `account_sub_type`?, `include_in_net_worth`?, `hide_from_summary_list`?, `hide_transactions_from_reports`?, `dry_run`? |
| `update_category` | Update an existing category's settings | `category_id`, `name`?, `icon`?, `group_id`?, `category_type`?, `exclude_from_budget`?, `budget_variability`?, `rollover_enabled`?, `rollover_start_month`?, `rollover_starting_balance`?, `rollover_frequency`?, `rollover_target_amount`?, `rollover_type`?, `confirm_rollover_reset`?, `dry_run`? |
| `update_merchant` | Update a merchant's name and/or recurring transaction stream settings | `merchant_id`, `name`?, `is_recurring`?, `frequency`?, `base_date`?, `amount`?, `is_active`? |
| `update_savings_goal` | Update a savings goal's target or monthly contribution | `goal_id`, `target_amount`?, `target_date`?, `name`?, `priority`?, `goal_type`?, `is_sinking_fund`? |
| `update_transaction` | Update an existing transaction in Monarch Money | `transaction_id`, `category_id`?, `merchant_name`?, `goal_id`?, `amount`?, `date`?, `hide_from_reports`?, `needs_review`?, `notes`? |
| `update_transaction_notes` | Update the notes/memo for a transaction | `transaction_id`, `notes`, `receipt_url`? |
| `update_transaction_rule` | Update an existing transaction rule | `rule_id`, `merchant_criteria_operator`?, `merchant_criteria_value`?, `merchant_criteria_values`?, `merchant_criteria`?, `original_statement_operator`?, `original_statement_values`?, `original_statement_criteria`?, `use_original_statement`?, `amount_operator`?, `amount_value`?, `amount_lower`?, `amount_upper`?, `amount_is_expense`?, `set_category_id`?, `set_merchant_name`?, `add_tag_ids`?, `link_goal_id`?, `hide_from_reports`?, `review_status`?, `account_ids`?, `category_ids`?, `clear_category`?, `clear_merchant`?, `clear_tags`?, `clear_goal_link`?, `clear_review_status`?, `apply_to_existing`? |
| `upload_account_balance_history` | Upload corrected balance snapshots for an account | `account_id`, `corrections`, `dry_run`? |

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
Show me all available categories using get_transaction_categories
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
Find all Amazon transactions from the last month using search_transactions
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

### Update a Recurring Bill Amount
```
Update PennyMac's recurring stream to $1,460.93 monthly using update_merchant
```

### Review Recurring Streams
```
Approve the Netflix recurring stream using review_recurring_stream
```

## 📅 Date Formats

- All dates should be in `YYYY-MM-DD` format (e.g., "2024-01-15")
- Transaction amounts: **positive** for income, **negative** for expenses

## 🔧 Troubleshooting

### Authentication Issues
If you see "Authentication needed" errors:
1. Run the setup command: `cd /path/to/your/monarch-mcp-server && python login_setup.py` (or `uv run python login_setup.py`)
2. Restart Claude Desktop or Claude Code
3. Try using a tool like `get_accounts`

### Email Verification Required
Monarch may require an email one-time code for a new device or session, even if MFA is not enabled. If you see an email-code prompt:
1. Check the email address on your Monarch account
2. Enter the one-time code in `login_setup.py`
3. Let the script finish so it can save the reusable token to your system keyring

### Session Expired or 401 within an hour
If your session dies quickly (under a couple of hours), the most common cause is that Monarch returned a short-lived token. The login script now requests `trusted_device=True` and rejects any short-lived token, so a fresh login produces a long-lived session. If you re-run `login_setup.py` and the issue persists, switch to option 1 (browser cookies); cookie sessions track the lifetime of the underlying browser login.

### Cloudflare CAPTCHA on login
If `login_setup.py` reports "Programmatic login is blocked by Cloudflare CAPTCHA", choose option 1 (browser cookies) instead. Email/password POSTs to Monarch's login endpoint are sometimes gated by Cloudflare for unfamiliar IPs or rapid retries; cookie-based auth bypasses that endpoint entirely.

### `'Context' object has no attribute 'elicit'`
The `monarch_login` and `monarch_login_with_token` tools require the MCP Python SDK 1.10.0 or newer (released June 2025). If your environment cached an older `mcp` install, refresh it:

```bash
uv cache clean mcp
```

Then fully quit and reopen Claude Desktop or Claude Code so it relaunches the server with a fresh resolution. As a fallback while you upgrade, run `python login_setup.py` from the repo to authenticate via the terminal.

### Common Error Messages
- **"No valid session found"**: Run `python login_setup.py` (or `uv run python login_setup.py`) 
- **"Monarch sent a one-time code to your email"**: Run `python login_setup.py` and complete email verification
- **"Invalid account ID"**: Use `get_accounts` to see valid account IDs
- **"Date format error"**: Use YYYY-MM-DD format for dates

## 🏗️ Technical Details

### Project Structure
```
monarch-mcp-server/
├── src/monarch_mcp_server/
│   ├── __init__.py
│   ├── app.py             # FastMCP app instance and entry point
│   ├── client.py          # Cached MonarchMoney client factory
│   ├── monarch_auth.py    # Current Monarch auth compatibility (host, email OTP, device-uuid)
│   ├── secure_session.py  # Keyring-backed token storage (file fallback)
│   ├── server.py          # Backward-compatibility shim re-exporting the tools
│   └── tools/             # MCP tools grouped by domain (accounts, transactions, budgets, …)
├── login_setup.py         # Terminal authentication script
├── pyproject.toml         # Project configuration
├── requirements-lock.txt  # Generated from uv.lock, hash pinned
└── README.md             # This documentation
```

### Session Management
- Session tokens are stored securely in the system keyring (with an automatic file fallback for environments without a keyring backend)
- The `device-uuid` captured at login is stored alongside the token so it reloads cleanly
- Sessions persist across Claude Desktop and Claude Code restarts
- No need for frequent re-authentication

### Security Features
- Credentials never transmitted through Claude Desktop or Claude Code
- MFA/2FA fully supported
- Email verification codes are handled only in the terminal setup script
- Session tokens are stored in the system keyring
- Authentication handled in secure terminal environment

### Strongest option: read only mode

Set `MONARCH_MCP_READ_ONLY=1` in the server's environment and the mutating
tools are never registered. They do not appear in the tool list and cannot be
called at all, which is stronger than an approval prompt: a model that was
talked into a write by a merchant name or memo it read back cannot invoke a
tool that is not there.

```json
{
  "mcpServers": {
    "Monarch Money": {
      "command": "/opt/homebrew/bin/uv",
      "args": ["run", "--project", "/path/to/your/monarch-mcp-server", "monarch-mcp-server"],
      "env": { "MONARCH_MCP_READ_ONLY": "1" }
    }
  }
}
```

This leaves 30 of the 58 tools available, covering everything that reads.
Read only is off by default, so existing setups are unaffected. Note that it
also removes the login and logout tools, since those change durable state, so
authenticate with `login_setup.py` before enabling it.

### Recommended: require approval for mutating tools

These tools mutate your Monarch data. The list is every registered tool that writes, checked against the source rather than maintained by hand:

**Accounts**: `update_account`

**Transactions**: `create_transaction`, `update_transaction`, `delete_transaction`, `categorize_transaction`, `update_transaction_notes`, `mark_transaction_reviewed`, `bulk_categorize_transactions`, `split_transaction`, `upload_account_balance_history`

**Tags**: `set_transaction_tags`, `add_transaction_tag`, `create_transaction_tag`

**Rules**: `create_transaction_rule`, `update_transaction_rule`, `delete_transaction_rule`, `reorder_transaction_rule`

**Categories and budgets**: `create_transaction_category`, `update_category`, `set_budget_amount`

**Goals**: `update_savings_goal`, `set_goal_contribution`

**Merchants**: `update_merchant`, `review_recurring_stream`

**Session**: `monarch_login`, `monarch_login_with_token`, `monarch_logout`

`refresh_accounts` is side effecting too, since it posts a refresh request to your institutions, though it does not change your ledger.

Because the LLM can be influenced by data it reads back (a malicious-looking memo or merchant name in a transaction), the safest setup is to configure your MCP client to require manual approval before any mutating tool runs. In Claude Desktop and Claude Code this is the default behavior for unknown tools; keep it that way for the tools listed above rather than allow-listing them.

`bulk_categorize_transactions`, `upload_account_balance_history`, `update_account` and `update_category` accept a `dry_run=True` argument that returns the planned changes without executing them, useful for previewing before approving.

`update_category` additionally requires `confirm_rollover_reset=True` before `rollover_start_month` or `rollover_starting_balance` will be applied. Those two restart a category's rollover period and discard the balance accumulated in it, which cannot be undone, so they cannot ride along unnoticed in a call that otherwise reads like a rename.

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
