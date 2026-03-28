[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/robcerda-monarch-mcp-server-badge.png)](https://mseep.ai/app/robcerda-monarch-mcp-server)

# Monarch Money MCP Server

A Model Context Protocol (MCP) server for integrating with the Monarch Money personal finance platform. This server provides seamless access to your financial accounts, transactions, budgets, and analytics through Claude Desktop.

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

Open Terminal and run:
```bash
cd /path/to/your/monarch-mcp-server
python login_setup.py
```

Follow the prompts:
- Enter your Monarch Money email and password
- Provide 2FA code if you have MFA enabled
- Session will be saved automatically

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

### 📈 Financial Analysis
- **Get Budgets**: Access budget information including spent amounts and remaining balances
- **Get Cashflow**: Analyze financial cashflow over specified date ranges with income/expense breakdowns

### 🔐 Secure Authentication
- **One-Time Setup**: Authenticate once, use for weeks/months
- **MFA Support**: Full support for two-factor authentication
- **Session Persistence**: No need to re-authenticate frequently
- **Secure**: Credentials never pass through Claude Desktop

## 🛠️ Available Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `setup_authentication` | Get setup instructions | None |
| `check_auth_status` | Check authentication status | None |
| `get_accounts` | Get all financial accounts | None |
| `get_transactions` | Get transactions with filtering | `limit`, `offset`, `start_date`, `end_date`, `account_id` |
| `get_budgets` | Get budget information | None |
| `get_cashflow` | Get cashflow analysis | `start_date`, `end_date` |
| `get_account_holdings` | Get investment holdings | `account_id` |
| `create_transaction` | Create new transaction | `account_id`, `amount`, `description`, `date`, `category_id`, `merchant_name` |
| `update_transaction` | Update existing transaction | `transaction_id`, `amount`, `description`, `category_id`, `date` |
| `refresh_accounts` | Request account data refresh | None |

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

### Analyze Cash Flow
```
Get my cashflow for the last 3 months using get_cashflow
```

## 📅 Date Formats

- All dates should be in `YYYY-MM-DD` format (e.g., "2024-01-15")
- Transaction amounts: **positive** for income, **negative** for expenses

## 🔧 Troubleshooting

### Authentication Issues
If you see "Authentication needed" errors:
1. Run the setup command: `cd /path/to/your/monarch-mcp-server && python login_setup.py`
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
├── login_setup.py         # Authentication setup script
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
2. Restart Claude Desktop
3. Re-run authentication if needed: `python login_setup.py`