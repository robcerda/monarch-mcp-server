"""Monarch Money MCP Server - Main server implementation."""

import os
import logging
import asyncio
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, date
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from monarchmoney import MonarchMoney, RequireMFAException
from pydantic import BaseModel, Field
from monarch_mcp_server.secure_session import secure_session

# PATCH: Monarch Money changed their API endpoint (see https://github.com/hammem/monarchmoney/issues/179)
# Old: api.monarchmoney.com -> New: api.monarch.com
# Note: BASE_URL is on MonarchMoneyEndpoints class, not MonarchMoney
from monarchmoney.monarchmoney import MonarchMoneyEndpoints
MonarchMoneyEndpoints.BASE_URL = "https://api.monarch.com"
logger_temp = logging.getLogger(__name__)
logger_temp.info("🔧 Patched MonarchMoneyEndpoints.BASE_URL to https://api.monarch.com")

# Configure logging - stdout for containers, file for local dev
IS_CONTAINER = os.environ.get("MCP_TRANSPORT", "stdio") != "stdio"
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

if not IS_CONTAINER:
    # Local dev: also log to file for debugging Claude Desktop issues
    try:
        _debug_file_handler = logging.FileHandler("/tmp/monarch-mcp-debug.log")
        _debug_file_handler.setLevel(logging.DEBUG)
        _debug_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(_debug_file_handler)
    except OSError:
        pass  # Can't write to /tmp in some environments

# Load environment variables
load_dotenv()

# Initialize FastMCP server
_mcp_host = os.environ.get("MCP_HOST", "0.0.0.0") if IS_CONTAINER else "127.0.0.1"
_mcp_port = int(os.environ.get("MCP_PORT", "9000"))
mcp = FastMCP("Monarch Money MCP Server", host=_mcp_host, port=_mcp_port)


# ============================================================================
# MCP RESOURCE: Financial Assistant System Prompt
# ============================================================================

ASSISTANT_SYSTEM_PROMPT = """# Monarch Financial Assistant

You are a personal financial assistant with full access to the user's Monarch Money data.

## Capabilities

### Read Operations
- View all accounts, transactions, budgets, and cashflow data
- Track account history and net worth over time
- Monitor recurring transactions (subscriptions, bills, income)
- Analyze spending patterns by category and tag
- View connected institutions and sync status

### Write Operations
- Create and update transactions
- Manage transaction categories and tags
- Set and adjust budget amounts
- Create manual accounts
- Update account settings
- Split transactions across categories

## Guidelines

### Data Handling
- Always provide specific numbers when discussing finances
- Use date ranges to contextualize data (e.g., "this month", "vs last month")
- Round currency to 2 decimal places
- Format large numbers with commas (e.g., $1,234.56)

### Analysis Approach
- Compare current spending to historical averages
- Identify anomalies and unusual transactions
- Track progress toward budget goals
- Highlight recurring charges and subscription costs
- Proactively surface insights when reviewing financial data

### Safety & Confirmation
- Confirm before any write operation that modifies data
- Show what will be changed before making changes
- Cannot delete accounts or categories (by design)
- Can delete individual transactions when explicitly requested
- Never expose sensitive account numbers or credentials

### Communication Style
- Be concise but thorough
- Use tables for comparing data when helpful
- Provide actionable insights, not just raw data
- Ask clarifying questions when requests are ambiguous
- Proactively suggest related information the user might find useful

### Common Workflows
1. **Budget Check**: get_budgets → summarize vs planned amounts → highlight overages
2. **Spending Analysis**: get_transactions with date range → categorize → identify patterns
3. **Net Worth**: get_accounts → summarize by type → get_account_history for trends
4. **Subscription Audit**: get_recurring_transactions → identify all subscriptions → suggest cancellations
5. **Transaction Categorization**: get_transactions → identify uncategorized → suggest categories"""


@mcp.resource("monarch://assistant/prompt")
def get_assistant_prompt() -> str:
    """System prompt defining the Monarch Financial Assistant personality and guidelines."""
    return ASSISTANT_SYSTEM_PROMPT


def run_async(coro):
    """Run async function in a new thread with its own event loop."""

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    with ThreadPoolExecutor() as executor:
        future = executor.submit(_run)
        return future.result()


class MonarchConfig(BaseModel):
    """Configuration for Monarch Money connection."""

    email: Optional[str] = Field(default=None, description="Monarch Money email")
    password: Optional[str] = Field(default=None, description="Monarch Money password")
    session_file: str = Field(
        default="monarch_session.json", description="Session file path"
    )


async def get_monarch_client(allow_reauth: bool = True) -> MonarchMoney:
    """Get or create MonarchMoney client instance using secure session storage.

    If the token is invalid and credentials are stored, will auto-re-authenticate.
    """
    logger.debug("🔍 get_monarch_client called, allow_reauth=%s", allow_reauth)

    # Try to get authenticated client from secure session
    client = secure_session.get_authenticated_client()
    logger.debug("🔍 get_authenticated_client returned: %s", "client" if client else "None")

    if client is not None:
        logger.info("✅ Using authenticated client from secure keyring storage")
        return client

    # If no token but we have stored credentials, try to re-authenticate
    logger.debug("🔍 No client, checking if reauth allowed...")
    if allow_reauth:
        logger.debug("🔍 Attempting reauthenticate...")
        client = await secure_session.reauthenticate()
        logger.debug("🔍 reauthenticate returned: %s", "client" if client else "None")
        if client is not None:
            return client

    # If no secure session, try environment credentials
    email = os.getenv("MONARCH_EMAIL")
    password = os.getenv("MONARCH_PASSWORD")

    if email and password:
        try:
            client = MonarchMoney()
            # save_session=False prevents monarchmoney from creating .mm/ directory
            # which fails when running from Claude Desktop (runs from root /)
            await client.login(email, password, save_session=False)
            logger.info(
                "Successfully logged into Monarch Money with environment credentials"
            )

            # Save the session securely
            secure_session.save_authenticated_session(client)

            return client
        except Exception as e:
            logger.error(f"Failed to login to Monarch Money: {e}")
            raise

    raise RuntimeError("🔐 Authentication needed! Run: python login_setup.py")


async def get_monarch_client_with_retry() -> MonarchMoney:
    """Get client with automatic retry on auth failure."""
    client = await get_monarch_client()

    # Test if the client works by making a simple call
    try:
        await client.get_subscription_details()
        return client
    except Exception as e:
        # Be aggressive about re-auth - any API failure could be auth-related
        logger.warning(f"⚠️  API call failed ({type(e).__name__}: {e}), attempting re-authentication...")
        # Clear the bad token and try to re-authenticate
        secure_session.delete_token()
        client = await secure_session.reauthenticate()
        if client is not None:
            logger.info("✅ Re-authentication successful")
            return client
        raise RuntimeError("🔐 Re-authentication failed! Run: python login_setup.py")


@mcp.tool()
def setup_authentication() -> str:
    """Get instructions for setting up secure authentication with Monarch Money."""
    return """🔐 Monarch Money - One-Time Setup

1️⃣ Open Terminal and run:
   python login_setup.py

2️⃣ Enter your Monarch Money credentials when prompted
   • Email and password
   • 2FA code if you have MFA enabled

3️⃣ Session will be saved automatically and last for weeks

4️⃣ Start using Monarch tools in Claude Desktop:
   • get_accounts - View all accounts
   • get_transactions - Recent transactions
   • get_budgets - Budget information

✅ Session persists across Claude restarts
✅ No need to re-authenticate frequently
✅ All credentials stay secure in terminal"""


@mcp.tool()
def check_auth_status() -> str:
    """Check if already authenticated with Monarch Money. Auto-refreshes token if expired."""
    try:
        # Check if we have a token in the keyring
        token = secure_session.load_token()
        if not token:
            # No token - check if we have credentials to authenticate
            email, password, mfa_secret = secure_session.load_credentials()
            if email and password:
                # Try to authenticate
                async def _reauth():
                    return await secure_session.reauthenticate()

                client = run_async(_reauth())
                if client:
                    return "✅ No token found, but successfully re-authenticated using stored credentials!"
                else:
                    return "❌ No token found and re-authentication failed. Run: python login_setup.py"
            else:
                return "❌ No authentication token or credentials found. Run: python login_setup.py"

        # Token exists - validate it by making a test API call
        async def _validate_token():
            try:
                client = await get_monarch_client_with_retry()
                # If we get here, token is valid (or was refreshed)
                await client.get_subscription_details()
                return True, "valid"
            except Exception as e:
                return False, str(e)

        is_valid, message = run_async(_validate_token())

        if is_valid:
            status = "✅ Authentication valid - token verified with Monarch API\n"
            email, _, mfa_secret = secure_session.load_credentials()
            if email:
                status += f"📧 Account: {email}\n"
            if mfa_secret:
                status += "🔐 MFA secret stored for auto-refresh\n"
            else:
                status += "⚠️  No MFA secret stored - manual login needed when token expires\n"
            return status
        else:
            return f"❌ Token validation failed: {message}\nRun: python login_setup.py"

    except Exception as e:
        return f"Error checking auth status: {str(e)}"


@mcp.tool()
def debug_session_loading() -> str:
    """Debug keyring session loading issues."""
    try:
        # Check keyring access
        token = secure_session.load_token()
        if token:
            return f"✅ Token found in keyring (length: {len(token)})"
        else:
            return "❌ No token found in keyring. Run login_setup.py to authenticate."
    except Exception as e:
        import traceback

        error_details = traceback.format_exc()
        return f"❌ Keyring access failed:\nError: {str(e)}\nType: {type(e)}\nTraceback:\n{error_details}"


@mcp.tool()
def get_accounts() -> str:
    """Get all financial accounts from Monarch Money."""
    try:

        async def _get_accounts():
            client = await get_monarch_client_with_retry()
            return await client.get_accounts()

        accounts = run_async(_get_accounts())

        # Format accounts for display
        account_list = []
        for account in accounts.get("accounts", []):
            account_info = {
                "id": account.get("id"),
                "name": account.get("displayName") or account.get("name"),
                "type": (account.get("type") or {}).get("name"),
                "balance": account.get("currentBalance"),
                "institution": (account.get("institution") or {}).get("name"),
                "is_active": account.get("isActive")
                if "isActive" in account
                else not account.get("deactivatedAt"),
            }
            account_list.append(account_info)

        return json.dumps(account_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get accounts: {e}")
        return f"Error getting accounts: {str(e)}"


@mcp.tool()
def get_transactions(
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    account_ids: Optional[str] = None,
    category_ids: Optional[str] = None,
    tag_ids: Optional[str] = None,
    has_attachments: Optional[bool] = None,
    has_notes: Optional[bool] = None,
    hidden_from_reports: Optional[bool] = None,
    is_split: Optional[bool] = None,
    is_recurring: Optional[bool] = None,
    synced_from_institution: Optional[bool] = None,
) -> str:
    """
    Get and search transactions from Monarch Money.

    Args:
        limit: Number of transactions to retrieve (default: 100)
        offset: Number of transactions to skip for pagination (default: 0)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        search: Text search across transaction descriptions and merchants
        account_ids: Comma-separated account IDs to filter by (e.g., "123,456")
        category_ids: Comma-separated category IDs to filter by
        tag_ids: Comma-separated tag IDs to filter by
        has_attachments: Filter for transactions with/without attachments
        has_notes: Filter for transactions with/without notes
        hidden_from_reports: Filter for transactions hidden/shown in reports
        is_split: Filter for split/non-split transactions
        is_recurring: Filter for recurring/non-recurring transactions
        synced_from_institution: Filter for synced vs manual transactions
    """
    try:
        # Parse comma-separated IDs into lists
        account_id_list = [a.strip() for a in account_ids.split(",") if a.strip()] if account_ids else None
        category_id_list = [c.strip() for c in category_ids.split(",") if c.strip()] if category_ids else None
        tag_id_list = [t.strip() for t in tag_ids.split(",") if t.strip()] if tag_ids else None

        async def _get_transactions():
            client = await get_monarch_client_with_retry()

            # Build filters - only include non-None values
            kwargs = {"limit": limit, "offset": offset}

            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            if search is not None:
                kwargs["search"] = search
            if account_id_list:
                kwargs["account_ids"] = account_id_list
            if category_id_list:
                kwargs["category_ids"] = category_id_list
            if tag_id_list:
                kwargs["tag_ids"] = tag_id_list
            if has_attachments is not None:
                kwargs["has_attachments"] = has_attachments
            if has_notes is not None:
                kwargs["has_notes"] = has_notes
            if hidden_from_reports is not None:
                kwargs["hidden_from_reports"] = hidden_from_reports
            if is_split is not None:
                kwargs["is_split"] = is_split
            if is_recurring is not None:
                kwargs["is_recurring"] = is_recurring
            if synced_from_institution is not None:
                kwargs["synced_from_institution"] = synced_from_institution

            return await client.get_transactions(**kwargs)

        transactions = run_async(_get_transactions())

        # Format transactions for display
        transaction_list = []
        for txn in transactions.get("allTransactions", {}).get("results", []):
            transaction_info = {
                "id": txn.get("id"),
                "date": txn.get("date"),
                "amount": txn.get("amount"),
                "description": txn.get("description"),
                "category": txn.get("category", {}).get("name")
                if txn.get("category")
                else None,
                "category_id": txn.get("category", {}).get("id")
                if txn.get("category")
                else None,
                "account": txn.get("account", {}).get("displayName"),
                "account_id": txn.get("account", {}).get("id"),
                "merchant": txn.get("merchant", {}).get("name")
                if txn.get("merchant")
                else None,
                "tags": [tag.get("name") for tag in txn.get("tags", [])],
                "notes": txn.get("notes"),
                "is_pending": txn.get("isPending", False),
                "is_recurring": txn.get("isRecurring", False),
                "has_attachments": txn.get("hasAttachments", False),
                "hidden_from_reports": txn.get("hideFromReports", False),
            }
            transaction_list.append(transaction_info)

        result = {
            "total_count": transactions.get("allTransactions", {}).get("totalCount", len(transaction_list)),
            "transactions": transaction_list,
        }
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transactions: {e}")
        return f"Error getting transactions: {str(e)}"


@mcp.tool()
def get_budgets(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get budget information from Monarch Money.

    Args:
        start_date: Start date in YYYY-MM-DD format (defaults to last month)
        end_date: End date in YYYY-MM-DD format (defaults to next month)
    """
    try:

        async def _get_budgets():
            client = await get_monarch_client_with_retry()
            kwargs = {}
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            return await client.get_budgets(**kwargs)

        budgets = run_async(_get_budgets())

        # Build category lookup from categoryGroups
        category_lookup = {}
        for group in budgets.get("categoryGroups", []):
            for cat in group.get("categories", []):
                category_lookup[cat.get("id")] = {
                    "name": cat.get("name"),
                    "group": group.get("name"),
                    "icon": cat.get("icon"),
                }

        # Format budgets for display (new flexible budget format)
        budget_list = []
        budget_data = budgets.get("budgetData", {})

        for cat_budget in budget_data.get("monthlyAmountsByCategory", []):
            cat_id = cat_budget.get("category", {}).get("id")
            cat_info = category_lookup.get(cat_id, {})

            for monthly in cat_budget.get("monthlyAmounts", []):
                planned = monthly.get("plannedCashFlowAmount", 0) or 0
                actual = monthly.get("actualAmount", 0) or 0
                remaining = monthly.get("remainingAmount", 0) or 0

                # Skip categories with no budget set
                if planned == 0 and actual == 0:
                    continue

                budget_info = {
                    "category": cat_info.get("name", "Unknown"),
                    "group": cat_info.get("group", "Unknown"),
                    "month": monthly.get("month"),
                    "budgeted": planned,
                    "spent": abs(actual),
                    "remaining": remaining,
                    "rollover_type": monthly.get("rolloverType"),
                }
                budget_list.append(budget_info)

        # Also include summary by category group
        for group_budget in budget_data.get("monthlyAmountsByCategoryGroup", []):
            group_id = group_budget.get("categoryGroup", {}).get("id")
            group_name = None
            for g in budgets.get("categoryGroups", []):
                if g.get("id") == group_id:
                    group_name = g.get("name")
                    break

        result = {
            "budget_system": budgets.get("budgetSystem"),
            "budgets": budget_list,
        }

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get budgets: {e}")
        return f"Error getting budgets: {str(e)}"


@mcp.tool()
def get_cashflow(
    start_date: Optional[str] = None, end_date: Optional[str] = None
) -> str:
    """
    Get cashflow analysis from Monarch Money.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    try:

        async def _get_cashflow():
            client = await get_monarch_client_with_retry()

            filters = {}
            if start_date:
                filters["start_date"] = start_date
            if end_date:
                filters["end_date"] = end_date

            return await client.get_cashflow(**filters)

        cashflow = run_async(_get_cashflow())

        return json.dumps(cashflow, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get cashflow: {e}")
        return f"Error getting cashflow: {str(e)}"


@mcp.tool()
def get_account_holdings(account_id: str) -> str:
    """
    Get investment holdings for a specific account.

    Args:
        account_id: The ID of the investment account
    """
    try:

        async def _get_holdings():
            client = await get_monarch_client_with_retry()
            return await client.get_account_holdings(account_id)

        holdings = run_async(_get_holdings())

        return json.dumps(holdings, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get account holdings: {e}")
        return f"Error getting account holdings: {str(e)}"


@mcp.tool()
def create_transaction(
    account_id: str,
    amount: float,
    description: str,
    date: str,
    category_id: Optional[str] = None,
    merchant_name: Optional[str] = None,
) -> str:
    """
    Create a new transaction in Monarch Money.

    Args:
        account_id: The account ID to add the transaction to
        amount: Transaction amount (positive for income, negative for expenses)
        description: Transaction description
        date: Transaction date in YYYY-MM-DD format
        category_id: Optional category ID
        merchant_name: Optional merchant name
    """
    try:

        async def _create_transaction():
            client = await get_monarch_client_with_retry()

            transaction_data = {
                "account_id": account_id,
                "amount": amount,
                "description": description,
                "date": date,
            }

            if category_id:
                transaction_data["category_id"] = category_id
            if merchant_name:
                transaction_data["merchant_name"] = merchant_name

            return await client.create_transaction(**transaction_data)

        result = run_async(_create_transaction())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create transaction: {e}")
        return f"Error creating transaction: {str(e)}"


@mcp.tool()
def update_transaction(
    transaction_id: str,
    amount: Optional[float] = None,
    category_id: Optional[str] = None,
    merchant_name: Optional[str] = None,
    date: Optional[str] = None,
    notes: Optional[str] = None,
    hide_from_reports: Optional[bool] = None,
    needs_review: Optional[bool] = None,
    goal_id: Optional[str] = None,
) -> str:
    """
    Update an existing transaction in Monarch Money.

    Args:
        transaction_id: The ID of the transaction to update
        amount: New transaction amount
        category_id: New category ID (use get_transaction_categories to find IDs)
        merchant_name: New merchant name
        date: New transaction date in YYYY-MM-DD format
        notes: Notes/memo to add to the transaction
        hide_from_reports: Set True to exclude from reports/budgets, False to include
        needs_review: Set True to flag for review, False to clear flag
        goal_id: Associate transaction with a savings goal
    """
    try:

        async def _update_transaction():
            client = await get_monarch_client_with_retry()

            update_data = {"transaction_id": transaction_id}

            if amount is not None:
                update_data["amount"] = amount
            if category_id is not None:
                update_data["category_id"] = category_id
            if merchant_name is not None:
                update_data["merchant_name"] = merchant_name
            if date is not None:
                update_data["date"] = date
            if notes is not None:
                update_data["notes"] = notes
            if hide_from_reports is not None:
                update_data["hide_from_reports"] = hide_from_reports
            if needs_review is not None:
                update_data["needs_review"] = needs_review
            if goal_id is not None:
                update_data["goal_id"] = goal_id

            return await client.update_transaction(**update_data)

        result = run_async(_update_transaction())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to update transaction: {e}")
        return f"Error updating transaction: {str(e)}"


@mcp.tool()
def get_transaction_categories() -> str:
    """
    Get all transaction categories from Monarch Money.
    Use this to find category IDs for update_transaction.
    """
    try:

        async def _get_categories():
            client = await get_monarch_client_with_retry()
            return await client.get_transaction_categories()

        categories = run_async(_get_categories())

        # Format categories for easy lookup
        category_list = []
        for cat in categories.get("categories", []):
            category_info = {
                "id": cat.get("id"),
                "name": cat.get("name"),
                "icon": cat.get("icon"),
                "group": cat.get("group", {}).get("name") if cat.get("group") else None,
            }
            category_list.append(category_info)

        return json.dumps(category_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction categories: {e}")
        return f"Error getting transaction categories: {str(e)}"


@mcp.tool()
def refresh_accounts() -> str:
    """Request account data refresh from financial institutions."""
    try:

        async def _refresh_accounts():
            client = await get_monarch_client_with_retry()
            return await client.request_accounts_refresh()

        result = run_async(_refresh_accounts())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to refresh accounts: {e}")
        return f"Error refreshing accounts: {str(e)}"


# ============================================================================
# NEW READ TOOLS - Phase 1 Implementation
# ============================================================================


@mcp.tool()
def get_account_history(
    account_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get historical daily balance snapshots for an account.
    Useful for net worth tracking and balance trends over time.

    Args:
        account_id: The ID of the account
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns: JSON array of {date, balance} entries
    """
    try:

        async def _get_history():
            client = await get_monarch_client_with_retry()
            kwargs = {"account_id": account_id}
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            return await client.get_account_history(**kwargs)

        history = run_async(_get_history())
        return json.dumps(history, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get account history: {e}")
        return f"Error getting account history: {str(e)}"


@mcp.tool()
def get_recurring_transactions() -> str:
    """
    Get predicted recurring transactions (subscriptions, bills, income).
    Monarch automatically detects recurring patterns.

    Returns: JSON array of recurring transaction predictions
    """
    try:

        async def _get_recurring():
            client = await get_monarch_client_with_retry()
            return await client.get_recurring_transactions()

        recurring = run_async(_get_recurring())
        return json.dumps(recurring, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get recurring transactions: {e}")
        return f"Error getting recurring transactions: {str(e)}"


@mcp.tool()
def get_transaction_tags() -> str:
    """
    Get all configured transaction tags.

    Returns: JSON array of tags with id and name
    """
    try:

        async def _get_tags():
            client = await get_monarch_client_with_retry()
            return await client.get_transaction_tags()

        tags = run_async(_get_tags())

        # Format for easy lookup
        tag_list = []
        for tag in tags.get("householdTransactionTags", []):
            tag_list.append({
                "id": tag.get("id"),
                "name": tag.get("name"),
            })

        return json.dumps(tag_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction tags: {e}")
        return f"Error getting transaction tags: {str(e)}"


@mcp.tool()
def get_transaction_category_groups() -> str:
    """
    Get all transaction category groups (the high-level groupings for categories).

    Returns: JSON array of category groups with their categories
    """
    try:

        async def _get_groups():
            client = await get_monarch_client_with_retry()
            return await client.get_transaction_category_groups()

        groups = run_async(_get_groups())
        return json.dumps(groups, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get category groups: {e}")
        return f"Error getting category groups: {str(e)}"


@mcp.tool()
def get_transaction_details(transaction_id: str) -> str:
    """
    Get detailed information about a single transaction.

    Args:
        transaction_id: The ID of the transaction

    Returns: JSON with full transaction details including splits, tags, notes
    """
    try:

        async def _get_details():
            client = await get_monarch_client_with_retry()
            return await client.get_transaction_details(transaction_id)

        details = run_async(_get_details())
        return json.dumps(details, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction details: {e}")
        return f"Error getting transaction details: {str(e)}"


@mcp.tool()
def get_transaction_splits(transaction_id: str) -> str:
    """
    Get split information for a transaction.

    Args:
        transaction_id: The ID of the transaction

    Returns: JSON with split transaction details
    """
    try:

        async def _get_splits():
            client = await get_monarch_client_with_retry()
            return await client.get_transaction_splits(transaction_id)

        splits = run_async(_get_splits())
        return json.dumps(splits, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction splits: {e}")
        return f"Error getting transaction splits: {str(e)}"


@mcp.tool()
def get_transactions_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get transaction page summary data with aggregated metrics.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns: JSON with summary metrics
    """
    try:

        async def _get_summary():
            client = await get_monarch_client_with_retry()
            kwargs = {}
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            return await client.get_transactions_summary(**kwargs)

        summary = run_async(_get_summary())
        return json.dumps(summary, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transactions summary: {e}")
        return f"Error getting transactions summary: {str(e)}"


@mcp.tool()
def get_institutions() -> str:
    """
    Get list of connected financial institutions.

    Returns: JSON array of institutions with connection status
    """
    try:

        async def _get_institutions():
            client = await get_monarch_client_with_retry()
            return await client.get_institutions()

        institutions = run_async(_get_institutions())
        return json.dumps(institutions, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get institutions: {e}")
        return f"Error getting institutions: {str(e)}"


@mcp.tool()
def get_account_type_options() -> str:
    """
    Get available account type options for manual account creation.

    Returns: JSON array of account types
    """
    try:

        async def _get_types():
            client = await get_monarch_client_with_retry()
            return await client.get_account_type_options()

        types = run_async(_get_types())
        return json.dumps(types, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get account type options: {e}")
        return f"Error getting account type options: {str(e)}"


@mcp.tool()
def get_subscription_details() -> str:
    """
    Get Monarch Money subscription status and details.

    Returns: JSON with subscription information
    """
    try:

        async def _get_subscription():
            client = await get_monarch_client_with_retry()
            return await client.get_subscription_details()

        subscription = run_async(_get_subscription())
        return json.dumps(subscription, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get subscription details: {e}")
        return f"Error getting subscription details: {str(e)}"


@mcp.tool()
def get_cashflow_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get high-level cashflow metrics: total income, expenses, savings rate.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns: JSON with income, expenses, savings, savingsRate
    """
    try:

        async def _get_summary():
            client = await get_monarch_client_with_retry()
            kwargs = {}
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            return await client.get_cashflow_summary(**kwargs)

        summary = run_async(_get_summary())
        return json.dumps(summary, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get cashflow summary: {e}")
        return f"Error getting cashflow summary: {str(e)}"


@mcp.tool()
def is_accounts_refresh_complete() -> str:
    """
    Check if accounts refresh is complete.

    Returns: JSON with refresh status
    """
    try:

        async def _check_refresh():
            client = await get_monarch_client_with_retry()
            return await client.is_accounts_refresh_complete()

        status = run_async(_check_refresh())
        return json.dumps({"refresh_complete": status}, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to check refresh status: {e}")
        return f"Error checking refresh status: {str(e)}"


# ============================================================================
# NEW WRITE TOOLS - Phase 2 Implementation
# ============================================================================


@mcp.tool()
def create_transaction_category(
    name: str,
    group_id: Optional[str] = None,
    icon: Optional[str] = None,
) -> str:
    """
    Create a new transaction category.

    Args:
        name: Category display name
        group_id: Optional parent category group ID (use get_transaction_category_groups to find IDs)
        icon: Optional icon identifier

    Returns: JSON with created category details
    """
    try:

        async def _create_category():
            client = await get_monarch_client_with_retry()
            kwargs = {"name": name}
            if group_id:
                kwargs["group_id"] = group_id
            if icon:
                kwargs["icon"] = icon
            return await client.create_transaction_category(**kwargs)

        result = run_async(_create_category())
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create transaction category: {e}")
        return f"Error creating transaction category: {str(e)}"


@mcp.tool()
def create_transaction_tag(name: str) -> str:
    """
    Create a new transaction tag.

    Args:
        name: Tag display name

    Returns: JSON with created tag details
    """
    try:

        async def _create_tag():
            client = await get_monarch_client_with_retry()
            return await client.create_transaction_tag(name)

        result = run_async(_create_tag())
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create transaction tag: {e}")
        return f"Error creating transaction tag: {str(e)}"


@mcp.tool()
def set_transaction_tags(transaction_id: str, tag_ids: str) -> str:
    """
    Apply tags to a transaction. Replaces existing tags.

    Args:
        transaction_id: Target transaction ID
        tag_ids: Comma-separated list of tag IDs to apply (e.g., "123,456,789")
                 Pass empty string to remove all tags.

    Returns: JSON confirmation with updated transaction
    """
    try:
        # Parse comma-separated tag IDs
        tag_id_list = [t.strip() for t in tag_ids.split(",") if t.strip()] if tag_ids else []

        async def _set_tags():
            client = await get_monarch_client_with_retry()
            return await client.set_transaction_tags(transaction_id, tag_id_list)

        result = run_async(_set_tags())
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to set transaction tags: {e}")
        return f"Error setting transaction tags: {str(e)}"


@mcp.tool()
def set_budget_amount(
    category_id: str,
    amount: float,
    month: Optional[str] = None,
    apply_to_future: bool = False,
) -> str:
    """
    Set budget amount for a category. Pass 0 to clear budget.

    Args:
        category_id: Target category ID (use get_transaction_categories to find IDs)
        amount: Budget amount (0 to clear)
        month: Target month in YYYY-MM format (defaults to current month)
        apply_to_future: Apply to all future months

    Returns: JSON confirmation
    """
    try:

        async def _set_budget():
            client = await get_monarch_client_with_retry()
            kwargs = {
                "category_id": category_id,
                "amount": amount,
            }
            if month:
                kwargs["start_date"] = f"{month}-01"
            if apply_to_future:
                kwargs["apply_to_future"] = apply_to_future
            return await client.set_budget_amount(**kwargs)

        result = run_async(_set_budget())
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to set budget amount: {e}")
        return f"Error setting budget amount: {str(e)}"


@mcp.tool()
def create_manual_account(
    name: str,
    account_type: str,
    account_subtype: Optional[str] = None,
    include_in_net_worth: bool = True,
) -> str:
    """
    Create a manually-tracked account (not linked to institution).

    Args:
        name: Account display name
        account_type: Type from get_account_type_options() (e.g., "checking", "savings", "credit_card")
        account_subtype: Optional subtype
        include_in_net_worth: Whether to include in net worth calculations (default: True)

    Returns: JSON with created account details
    """
    try:

        async def _create_account():
            client = await get_monarch_client_with_retry()
            return await client.create_manual_account(
                account_type=account_type,
                account_sub_type=account_subtype,
                account_name=name,
                is_in_net_worth=include_in_net_worth,
            )

        result = run_async(_create_account())
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create manual account: {e}")
        return f"Error creating manual account: {str(e)}"


@mcp.tool()
def update_account(
    account_id: str,
    name: Optional[str] = None,
    include_in_net_worth: Optional[bool] = None,
    hide_from_list: Optional[bool] = None,
    hide_transactions_from_reports: Optional[bool] = None,
) -> str:
    """
    Update account settings.

    Args:
        account_id: The ID of the account to update
        name: New display name
        include_in_net_worth: Whether to include in net worth calculations
        hide_from_list: Whether to hide from account list
        hide_transactions_from_reports: Whether to exclude transactions from reports

    Returns: JSON with updated account details
    """
    try:

        async def _update_account():
            client = await get_monarch_client_with_retry()
            kwargs = {"account_id": account_id}
            if name is not None:
                kwargs["account_name"] = name
            if include_in_net_worth is not None:
                kwargs["is_in_net_worth"] = include_in_net_worth
            if hide_from_list is not None:
                kwargs["hide_from_list"] = hide_from_list
            if hide_transactions_from_reports is not None:
                kwargs["hide_transactions_from_reports"] = hide_transactions_from_reports
            return await client.update_account(**kwargs)

        result = run_async(_update_account())
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to update account: {e}")
        return f"Error updating account: {str(e)}"


class TransactionSplit(BaseModel):
    """A single allocation within a transaction split."""

    amount: float = Field(
        description=(
            "SIGNED dollar amount for this split, using the SAME SIGN as the parent "
            "transaction. Expenses are NEGATIVE (e.g. -145.54), income is POSITIVE. "
            "The sum of all splits' amounts MUST equal the parent transaction's amount "
            "exactly, or Monarch rejects the request."
        )
    )
    category_id: str = Field(
        description=(
            "Category ID for this split (from get_transaction_categories). Required - "
            "a split with no/invalid category is silently dropped by Monarch."
        )
    )
    merchant_name: Optional[str] = Field(
        default=None,
        description=(
            "Merchant name for this split. Optional - defaults to the parent "
            "transaction's merchant when omitted."
        ),
    )
    hide_from_reports: bool = Field(
        default=False,
        description="Whether to exclude this split from reports and budgets.",
    )


@mcp.tool()
def update_transaction_splits(
    transaction_id: str,
    splits: List[TransactionSplit],
) -> str:
    """
    Replace the split allocations for a transaction.

    This REPLACES all existing splits on the transaction with the ones provided.
    Pass an empty list to remove all splits and restore the transaction to a single
    unsplit line.

    CRITICAL RULES (the two things that most often cause silent failures):
      1. SIGNED AMOUNTS: each split's `amount` uses the same sign as the parent
         transaction. Expenses are negative (e.g. -145.54), income positive.
      2. AMOUNTS MUST SUM TO THE PARENT: the sum of all split amounts must equal the
         parent transaction's amount exactly. This tool validates this before sending
         and returns a clear error (with the numbers) if it doesn't match.

    Args:
        transaction_id: The ID of the transaction to split.
        splits: List of split allocations. Each split has amount (signed),
                category_id (required), merchant_name (optional), and
                hide_from_reports (optional, default false).

    Example - split a -$153.54 Target expense into clothing (-$145.54) and household (-$8.00):
        splits=[
          {"amount": -145.54, "category_id": "231909059602791072", "merchant_name": "Target"},
          {"amount": -8.00,   "category_id": "231909059602791068", "merchant_name": "Target"}
        ]

    Returns: JSON with the updated transaction splits, or a clear error message.
    """
    try:
        # Empty list => delete all splits (handled directly by the API).
        if splits:
            async def _get_parent():
                client = await get_monarch_client_with_retry()
                return await client.get_transaction_details(transaction_id)

            parent = run_async(_get_parent())
            parent_txn = (parent or {}).get("getTransaction", {}) or {}
            parent_amount = parent_txn.get("amount")
            parent_merchant = (parent_txn.get("merchant") or {}).get("name")

            split_sum = round(sum(s.amount for s in splits), 2)

            if parent_amount is not None:
                parent_amount = round(float(parent_amount), 2)

                # Wrong-sign detection: sum matches the parent's magnitude but not its sign.
                if abs(split_sum + parent_amount) < 0.01 and abs(split_sum - parent_amount) >= 0.01:
                    return (
                        f"Error: split amounts have the WRONG SIGN. Parent transaction "
                        f"amount is {parent_amount} but your splits sum to {split_sum}. "
                        f"Expenses must be NEGATIVE - flip the signs so the splits sum to "
                        f"{parent_amount}."
                    )

                if abs(split_sum - parent_amount) >= 0.01:
                    return (
                        f"Error: split amounts must sum to the parent transaction amount. "
                        f"Parent is {parent_amount}, but your splits sum to {split_sum} "
                        f"(off by {round(split_sum - parent_amount, 2)}). Adjust the splits "
                        f"so they total exactly {parent_amount}."
                    )

        # Map to the camelCase shape the Monarch GraphQL API expects. The library passes
        # these keys straight through with no conversion, so snake_case keys are ignored.
        split_data = []
        for s in splits:
            split_data.append(
                {
                    "amount": s.amount,
                    "categoryId": s.category_id,
                    "merchantName": s.merchant_name
                    if s.merchant_name is not None
                    else parent_merchant,
                    "hideFromReports": s.hide_from_reports,
                }
            )

        async def _update_splits():
            client = await get_monarch_client_with_retry()
            return await client.update_transaction_splits(transaction_id, split_data)

        result = run_async(_update_splits())
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to update transaction splits: {e}")
        return f"Error updating transaction splits: {str(e)}"


@mcp.tool()
def request_accounts_refresh_and_wait(timeout_seconds: int = 120) -> str:
    """
    Request account refresh and wait for completion.
    Blocks until refresh is complete or timeout is reached.

    Args:
        timeout_seconds: Maximum time to wait for refresh (default: 120)

    Returns: JSON with refresh status and completion time
    """
    try:

        async def _refresh_and_wait():
            client = await get_monarch_client_with_retry()
            return await client.request_accounts_refresh_and_wait(timeout=timeout_seconds)

        result = run_async(_refresh_and_wait())
        return json.dumps({"success": result, "message": "Accounts refresh completed"}, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to refresh accounts: {e}")
        return f"Error refreshing accounts: {str(e)}"


@mcp.tool()
def delete_transaction(transaction_id: str) -> str:
    """
    Delete a single transaction. Use with caution - this action cannot be undone.

    Args:
        transaction_id: The ID of the transaction to delete

    Returns: JSON confirmation of deletion
    """
    try:

        async def _delete_transaction():
            client = await get_monarch_client_with_retry()
            return await client.delete_transaction(transaction_id)

        result = run_async(_delete_transaction())
        return json.dumps({"success": True, "deleted_transaction_id": transaction_id, "result": result}, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to delete transaction: {e}")
        return f"Error deleting transaction: {str(e)}"


# ============================================================================
# WEB ROUTES (for deployed/container mode)
# ============================================================================

import secrets
import time

# Login tokens: {token: expiry_timestamp}
_login_tokens: dict[str, float] = {}
LOGIN_TOKEN_TTL = 600  # 10 minutes


def _generate_login_token() -> str:
    """Generate a single-use login token with expiry."""
    # Clean expired tokens
    now = time.time()
    expired = [t for t, exp in _login_tokens.items() if exp < now]
    for t in expired:
        del _login_tokens[t]

    token = secrets.token_urlsafe(32)
    _login_tokens[token] = now + LOGIN_TOKEN_TTL
    return token


def _validate_login_token(token: str) -> bool:
    """Validate and consume a login token (single-use)."""
    if not token or token not in _login_tokens:
        return False
    if time.time() > _login_tokens[token]:
        del _login_tokens[token]
        return False
    del _login_tokens[token]  # Single-use: consume on validation
    return True


@mcp.tool()
def get_login_url() -> str:
    """
    Generate a secure one-time login URL for the web authentication page.
    The URL contains a cryptographic token that expires after 10 minutes.
    Use this when you need to authenticate with Monarch Money via the web login.

    Returns: A one-time login URL
    """
    token = _generate_login_token()
    base_url = os.environ.get("MCP_PUBLIC_URL", f"http://localhost:{_mcp_port}")
    login_url = f"{base_url}/login?token={token}"
    logger.info(f"🔗 Generated login URL (token expires in {LOGIN_TOKEN_TTL}s)")
    return json.dumps({
        "login_url": login_url,
        "expires_in_seconds": LOGIN_TOKEN_TTL,
        "note": "This URL is single-use and expires in 10 minutes."
    }, indent=2)


if IS_CONTAINER:
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse

    LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Monarch Money - MCP Server Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #0f172a; color: #e2e8f0; min-height: 100vh;
               display: flex; align-items: center; justify-content: center; }
        .container { background: #1e293b; border-radius: 12px; padding: 2rem;
                     max-width: 420px; width: 100%; box-shadow: 0 4px 24px rgba(0,0,0,0.3); }
        h1 { font-size: 1.5rem; margin-bottom: 0.5rem; text-align: center; }
        p.subtitle { color: #94a3b8; text-align: center; margin-bottom: 1.5rem; font-size: 0.9rem; }
        label { display: block; font-size: 0.85rem; color: #94a3b8; margin-bottom: 0.3rem; }
        input { width: 100%; padding: 0.7rem; border-radius: 8px; border: 1px solid #334155;
                background: #0f172a; color: #e2e8f0; font-size: 1rem; margin-bottom: 1rem; }
        input:focus { outline: none; border-color: #6366f1; }
        button { width: 100%; padding: 0.8rem; border-radius: 8px; border: none;
                 background: #6366f1; color: white; font-size: 1rem; cursor: pointer;
                 font-weight: 600; }
        button:hover { background: #4f46e5; }
        button:active { transform: scale(0.98); }
        button:disabled { background: #475569; cursor: not-allowed; transform: none; }
        button .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.3);
                          border-top-color: white; border-radius: 50%; animation: spin 0.6s linear infinite;
                          vertical-align: middle; margin-right: 0.5rem; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .status { margin-top: 1rem; padding: 0.8rem; border-radius: 8px; font-size: 0.9rem; display: none; }
        .status.success { display: block; background: #064e3b; color: #6ee7b7; }
        .status.error { display: block; background: #450a0a; color: #fca5a5; }
        .mfa-section { display: none; }
        .mfa-section.show { display: block; }
        @media (max-width: 480px) {
            .container { margin: 1rem; padding: 1.5rem; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Monarch Money</h1>
        <p class="subtitle">MCP Server Authentication</p>
        <form id="loginForm">
            <label for="email">Email</label>
            <input type="email" id="email" name="email" required placeholder="your@email.com">

            <label for="password">Password</label>
            <input type="password" id="password" name="password" required placeholder="Password">

            <div id="mfaSection" class="mfa-section">
                <label for="mfa_secret">MFA Secret Key (TOTP base32, for auto-renewal)</label>
                <input type="text" id="mfa_secret" name="mfa_secret" placeholder="Optional - enables auto token renewal">
            </div>

            <label style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem;cursor:pointer;">
                <input type="checkbox" id="showMfa" style="width:auto;margin:0;">
                <span>I have MFA enabled</span>
            </label>

            <button type="submit" id="submitBtn">Sign In</button>
        </form>
        <div id="status" class="status"></div>
    </div>
    <script>
        document.getElementById('showMfa').addEventListener('change', function() {
            document.getElementById('mfaSection').classList.toggle('show', this.checked);
        });
        document.getElementById('loginForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const btn = document.getElementById('submitBtn');
            const status = document.getElementById('status');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span>Authenticating...';
            status.className = 'status';
            status.style.display = 'none';
            try {
                const formToken = document.getElementById('loginForm').dataset.token;
                const resp = await fetch('/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        token: formToken,
                        email: document.getElementById('email').value,
                        password: document.getElementById('password').value,
                        mfa_secret: document.getElementById('mfa_secret').value || null
                    })
                });
                const data = await resp.json();
                if (resp.ok) {
                    status.className = 'status success';
                    status.textContent = data.message;
                } else {
                    status.className = 'status error';
                    status.textContent = data.error || 'Authentication failed';
                }
            } catch (err) {
                status.className = 'status error';
                status.textContent = 'Network error: ' + err.message;
            }
            btn.disabled = false;
            btn.textContent = 'Sign In';
        });
    </script>
</body>
</html>"""

    @mcp.custom_route("/login", methods=["GET"])
    async def login_page(request: Request) -> HTMLResponse:
        token = request.query_params.get("token", "")
        if not _validate_login_token(token):
            return HTMLResponse(
                "<h1>Access Denied</h1><p>Invalid or expired login link. "
                "Use the <code>get_login_url</code> MCP tool to generate a new one.</p>",
                status_code=403,
            )
        # Generate a new single-use token for the POST submission
        post_token = _generate_login_token()
        html = LOGIN_HTML.replace('id="loginForm"', f'id="loginForm" data-token="{post_token}"')
        return HTMLResponse(html)

    @mcp.custom_route("/login", methods=["POST"])
    async def handle_login(request: Request) -> JSONResponse:
        try:
            body = await request.json()

            # Validate the post token
            post_token = body.get("token", "")
            if not _validate_login_token(post_token):
                return JSONResponse({"error": "Session expired. Generate a new login URL."}, status_code=403)

            email = body.get("email")
            password = body.get("password")
            mfa_secret = body.get("mfa_secret")

            if not email or not password:
                return JSONResponse({"error": "Email and password required"}, status_code=400)

            # Attempt login
            client = MonarchMoney()
            try:
                await client.login(email, password, save_session=False)
            except RequireMFAException:
                if not mfa_secret:
                    return JSONResponse({"error": "MFA required. Provide your TOTP secret key."}, status_code=401)
                import pyotp
                totp = pyotp.TOTP(mfa_secret)
                mfa_code = totp.now()
                await client.multi_factor_authenticate(email, password, mfa_code)

            if not client.token:
                return JSONResponse({"error": "Login succeeded but no token received"}, status_code=500)

            # Save credentials and token
            secure_session.save_credentials(email, password, mfa_secret)
            secure_session.save_token(client.token)

            logger.info(f"✅ Web login successful for {email[:3]}***")
            return JSONResponse({"message": "Authenticated successfully! MCP server is ready."})
        except Exception as e:
            logger.error(f"❌ Web login failed: {e}")
            return JSONResponse({"error": f"Authentication failed: {str(e)}"}, status_code=401)

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> JSONResponse:
        """Deep health check: server up + auth valid + API reachable."""
        health = {"server": "ok", "authenticated": False, "api_reachable": False}
        status_code = 200

        # Check token exists
        token = secure_session.load_token()
        if not token:
            health["error"] = "No token stored. Login required at /login"
            return JSONResponse(health, status_code=503)

        health["authenticated"] = True

        # Validate token against Monarch API
        try:
            async def _check():
                client = MonarchMoney(token=token)
                return await client.get_subscription_details()

            run_async(_check())
            health["api_reachable"] = True
        except Exception as e:
            error_str = str(e)
            health["api_reachable"] = False

            # Attempt auto-recovery
            try:
                async def _reauth():
                    return await secure_session.reauthenticate()

                client = run_async(_reauth())
                if client:
                    health["api_reachable"] = True
                    health["recovered"] = True
                    logger.info("✅ Health check triggered successful re-authentication")
                else:
                    health["error"] = "Token expired, auto-recovery failed"
                    status_code = 503
            except Exception as reauth_err:
                health["error"] = f"Token expired, recovery failed: {str(reauth_err)}"
                status_code = 503

        return JSONResponse(health, status_code=status_code)

    @mcp.custom_route("/status", methods=["GET"])
    async def auth_status(request: Request) -> JSONResponse:
        token = secure_session.load_token()
        if token:
            return JSONResponse({"authenticated": True, "token_length": len(token)})
        return JSONResponse({"authenticated": False})


def main():
    """Main entry point for the server."""
    transport = os.environ.get("MCP_TRANSPORT", "stdio")

    logger.info(f"Starting Monarch Money MCP Server (transport={transport}, host={_mcp_host}, port={_mcp_port})")

    try:
        mcp.run(transport=transport)
    except Exception as e:
        logger.error(f"Failed to run server: {str(e)}")
        raise


# Export for mcp run
app = mcp

if __name__ == "__main__":
    main()
