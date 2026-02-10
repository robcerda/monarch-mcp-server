[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/robcerda-monarch-mcp-server-badge.png)](https://mseep.ai/app/robcerda-monarch-mcp-server)

# Monarch Money MCP Server

A Model Context Protocol (MCP) server for integrating with the Monarch Money personal finance platform. This server provides seamless access to your financial accounts, transactions, budgets, and analytics through Claude Desktop.

My MonarchMoney referral: https://www.monarchmoney.com/referral/ufmn0r83yf?r_source=share

**Built with the [MonarchMoney Python library](https://github.com/hammem/monarchmoney) by [@hammem](https://github.com/hammem)** - A fantastic unofficial API for Monarch Money with full MFA support.

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
   ```bash
   pip install -r requirements.txt
   pip install -e .
   ```

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
   
   **Important**: Replace `/path/to/your/monarch-mcp-server` with your actual path!

4. **Restart Claude Desktop**

### 2. One-Time Authentication Setup

**Important**: For security and MFA support, authentication is done outside of Claude Desktop.

#### Option A: Email/Password Login
```bash
cd /path/to/your/monarch-mcp-server
python login_setup.py
```

Follow the prompts:
- Enter your Monarch Money email and password
- Provide 2FA code if you have MFA enabled
- Session will be saved automatically

#### Option B: Google OAuth Login
If you sign in to Monarch with Google:
```bash
cd /path/to/your/monarch-mcp-server
python google_login.py
```

This opens a browser window where you can sign in with Google. The token is captured automatically.

You can also trigger authentication from within Claude using the `authenticate_with_google` tool.

### 3. Start Using in Claude Desktop

Once authenticated, use these tools directly in Claude Desktop:
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
- **MFA Support**: Full support for two-factor authentication
- **Google OAuth**: Sign in with Google account (no password needed)
- **Session Persistence**: No need to re-authenticate frequently
- **Secure**: Credentials never pass through Claude Desktop

## 🛠️ Available Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `setup_authentication` | Get setup instructions | None |
| `authenticate_with_google` | Open browser for Google OAuth login | None |
| `check_auth_status` | Check authentication status | None |
| `get_accounts` | Get all financial accounts | None |
| `get_transactions` | Get transactions with filtering | `limit`, `offset`, `start_date`, `end_date`, `account_id` |
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
If you see "Authentication needed" errors:
1. Run the setup command: `python login_setup.py` (or `python google_login.py` for Google OAuth)
2. Restart Claude Desktop
3. Try using a tool like `get_accounts`

### Session Expired
Sessions last for weeks, but if expired:
1. Run the same setup command again
2. Enter your credentials and 2FA code
3. Session will be refreshed automatically

### Common Error Messages
- **"No valid session found"**: Run `login_setup.py` 
- **"Invalid account ID"**: Use `get_accounts` to see valid account IDs
- **"Date format error"**: Use YYYY-MM-DD format for dates

## 🏗️ Technical Details

### Project Structure
```
monarch-mcp-server/
├── src/monarch_mcp_server/
│   ├── __init__.py
│   └── server.py          # Main server implementation
├── login_setup.py         # Email/password authentication script
├── google_login.py        # Google OAuth authentication script
├── pyproject.toml         # Project configuration
├── requirements.txt       # Dependencies
└── README.md             # This documentation
```

### Session Management
- Sessions are stored securely in `.mm/mm_session.pickle`
- Automatic session discovery and loading
- Sessions persist across Claude Desktop restarts
- No need for frequent re-authentication

### Security Features
- Credentials never transmitted through Claude Desktop
- MFA/2FA fully supported
- Session files are encrypted
- Authentication handled in secure terminal environment

## 🙏 Acknowledgments

This MCP server is built on top of the excellent [MonarchMoney Python library](https://github.com/hammem/monarchmoney) created by [@hammem](https://github.com/hammem). Their library provides the robust foundation that makes this integration possible, including:

- Secure authentication with MFA support
- Comprehensive API coverage for Monarch Money
- Session management and persistence
- Well-documented and maintained codebase

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
2. Restart Claude Desktop
3. Re-run authentication if needed: `python login_setup.py`