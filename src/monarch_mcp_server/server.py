"""Monarch Money MCP Server - Main server implementation."""

import os
import logging
import asyncio
from typing import Any, Dict, Optional
import json
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from mcp.server.fastmcp import Context, FastMCP
import mcp.types as types
from monarchmoney import MonarchMoney, RequireMFAException  # type: ignore
from pydantic import BaseModel, Field
from monarch_mcp_server import auth
from monarch_mcp_server.secure_session import secure_session

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize FastMCP server
mcp = FastMCP("Monarch Money MCP Server")


def run_async(coro: Any) -> Any:
    """Run async function in a new thread with its own event loop."""

    def _run() -> Any:
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


async def get_monarch_client() -> MonarchMoney:
    """Get or create MonarchMoney client instance using secure session storage."""
    # Try to get authenticated client from secure session
    client = secure_session.get_authenticated_client()

    if client is not None:
        logger.info("✅ Using authenticated client from secure keyring storage")
        return client

    # If no secure session, try environment credentials
    email = os.getenv("MONARCH_EMAIL")
    password = os.getenv("MONARCH_PASSWORD")

    if email and password:
        try:
            client = MonarchMoney()
            await client.login(email, password)
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
    """Check if already authenticated with Monarch Money."""
    try:
        # Check if we have a token in the keyring
        token = secure_session.load_token()
        if token:
            status = "✅ Authentication token found in secure keyring storage\n"
        else:
            status = "❌ No authentication token found in keyring\n"

        email = os.getenv("MONARCH_EMAIL")
        if email:
            status += f"📧 Environment email: {email}\n"

        status += (
            "\n💡 Try get_accounts to test connection or run login_setup.py if needed."
        )

        return status
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
async def monarch_login(ctx: Context) -> str:
    """Sign in to Monarch Money.

    Opens a secure form in the client UI to collect email, password, and
    (if required) an MFA code. Credentials never pass through the model —
    they flow client-UI → server directly via the MCP protocol.
    """
    return await auth.login_interactive(ctx)


@mcp.tool()
async def monarch_login_with_token(ctx: Context) -> str:
    """Sign in to Monarch Money using a browser-copied session token.

    Useful for SSO users who can't use password login. Grab the token from
    browser DevTools → Application → Local Storage → app.monarchmoney.com.
    """
    return await auth.login_with_token_interactive(ctx)


@mcp.tool()
async def monarch_logout() -> str:
    """Clear the stored Monarch Money session from the system keyring."""
    return await auth.logout()


@mcp.tool()
def get_accounts() -> str:
    """Get all financial accounts from Monarch Money."""
    try:

        async def _get_accounts() -> Any:
            client = await get_monarch_client()
            return await client.get_accounts()

        accounts = run_async(_get_accounts())

        # Format accounts for display
        account_list = []
        for account in accounts.get("accounts", []):
            type_info = account.get("type", {})
            type_name = type_info.get("name") if isinstance(type_info, dict) else None

            institution_info = account.get("institution", {})
            institution_name = institution_info.get("name") if isinstance(institution_info, dict) else None

            account_info = {
                "id": account.get("id"),
                "name": account.get("displayName") or account.get("name"),
                "type": type_name,
                "balance": account.get("currentBalance"),
                "institution": institution_name,
                "is_active": not account.get("deactivatedAt"),
                "is_hidden": account.get("isHidden", False)
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
    account_id: Optional[str] = None,
    search: Optional[str] = None,
    category_ids: Optional[list[str]] = None,
    account_ids: Optional[list[str]] = None,
    tag_ids: Optional[list[str]] = None,
    has_notes: Optional[bool] = None,
    is_split: Optional[bool] = None,
    is_recurring: Optional[bool] = None,
) -> str:
    """
    Get transactions from Monarch Money.

    Args:
        limit: Number of transactions to retrieve (default: 100)
        offset: Number of transactions to skip (default: 0)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        account_id: Specific account ID to filter by (deprecated, use account_ids)
        search: Search query to filter transactions
        category_ids: List of category IDs to filter by
        account_ids: List of account IDs to filter by
        tag_ids: List of tag IDs to filter by
        has_notes: Filter for transactions with/without notes
        is_split: Filter for split transactions
        is_recurring: Filter for recurring transactions
    """
    try:

        async def _get_transactions() -> Any:
            client = await get_monarch_client()

            # Build filters
            filters: Dict[str, Any] = {}
            if start_date:
                filters["start_date"] = start_date
            if end_date:
                filters["end_date"] = end_date
            if search:
                filters["search"] = search
            if has_notes is not None:
                filters["has_notes"] = has_notes
            if is_split is not None:
                filters["is_split"] = is_split
            if is_recurring is not None:
                filters["is_recurring"] = is_recurring

            # Merge account_id (singular, backward compat) into account_ids list
            merged_account_ids = list(account_ids or [])
            if account_id and account_id not in merged_account_ids:
                merged_account_ids.append(account_id)
            if merged_account_ids:
                filters["account_ids"] = merged_account_ids

            if category_ids:
                filters["category_ids"] = category_ids
            if tag_ids:
                filters["tag_ids"] = tag_ids

            return await client.get_transactions(limit=limit, offset=offset, **filters)

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
                "account_id": txn.get("account", {}).get("id")
                if txn.get("account")
                else None,
                "merchant": txn.get("merchant", {}).get("name")
                if txn.get("merchant")
                else None,
                "is_pending": txn.get("isPending", False),
                "needs_review": txn.get("needsReview"),
                "notes": txn.get("notes"),
                "is_recurring": txn.get("isRecurring"),
                "review_status": txn.get("reviewStatus"),
                "is_split_transaction": txn.get("isSplitTransaction"),
                "tags": [
                    {"id": t.get("id"), "name": t.get("name")}
                    for t in txn.get("tags", [])
                ],
                "hide_from_reports": txn.get("hideFromReports"),
            }
            transaction_list.append(transaction_info)

        return json.dumps(transaction_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transactions: {e}")
        return f"Error getting transactions: {str(e)}"


@mcp.tool()
def get_budgets(
    start_date: Optional[str] = None, end_date: Optional[str] = None
) -> str:
    """Get budget information from Monarch Money.

    Args:
        start_date: Optional start date in YYYY-MM-DD format.
        end_date: Optional end date in YYYY-MM-DD format.
    """
    try:

        async def _get_budgets() -> Any:
            client = await get_monarch_client()
            return await client.get_budgets(
                start_date=start_date, end_date=end_date
            )

        budgets = run_async(_get_budgets())
        return json.dumps(budgets, indent=2, default=str)
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

        async def _get_cashflow() -> Any:
            client = await get_monarch_client()

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

        async def _get_holdings() -> Any:
            client = await get_monarch_client()
            return await client.get_account_holdings(account_id)

        holdings = run_async(_get_holdings())

        return json.dumps(holdings, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get account holdings: {e}")
        return f"Error getting account holdings: {str(e)}"


@mcp.tool()
def create_transaction(
    date: str,
    account_id: str,
    amount: float,
    merchant_name: str,
    category_id: str,
    notes: Optional[str] = None,
    update_balance: Optional[bool] = False,
) -> str:
    """
    Create a new transaction in Monarch Money.

    Args:
        date: Transaction date in YYYY-MM-DD format
        account_id: The account ID to add the transaction to
        amount: Transaction amount (positive for income, negative for expenses)
        merchant_name: Merchant or payee name
        category_id: Category ID for the transaction
        notes: Optional notes for the transaction
        update_balance: Whether to update the account balance (default: false)
    """
    try:

        async def _create_transaction() -> Any:
            client = await get_monarch_client()

            transaction_data = {
                "date": date,
                "account_id": account_id,
                "amount": amount,
                "merchant_name": merchant_name,
                "category_id": category_id,
            }

            if notes:
                transaction_data["notes"] = notes
            if update_balance:
                transaction_data["update_balance"] = update_balance

            return await client.create_transaction(**transaction_data)

        result = run_async(_create_transaction())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create transaction: {e}")
        return f"Error creating transaction: {str(e)}"


@mcp.tool()
def update_transaction(
    transaction_id: str,
    category_id: Optional[str] = None,
    merchant_name: Optional[str] = None,
    goal_id: Optional[str] = None,
    amount: Optional[float] = None,
    date: Optional[str] = None,
    hide_from_reports: Optional[bool] = None,
    needs_review: Optional[bool] = None,
    notes: Optional[str] = None,
) -> str:
    """
    Update an existing transaction in Monarch Money.

    Args:
        transaction_id: The ID of the transaction to update
        category_id: New category ID
        merchant_name: New merchant or payee name
        goal_id: Goal ID to associate with the transaction
        amount: New transaction amount
        date: New transaction date in YYYY-MM-DD format
        hide_from_reports: Whether to hide this transaction from reports
        needs_review: Whether this transaction needs review
        notes: Notes for the transaction
    """
    try:

        async def _update_transaction() -> Any:
            client = await get_monarch_client()

            update_data: Dict[str, Any] = {"transaction_id": transaction_id}

            if category_id is not None:
                update_data["category_id"] = category_id
            if merchant_name is not None:
                update_data["merchant_name"] = merchant_name
            if goal_id is not None:
                update_data["goal_id"] = goal_id
            if amount is not None:
                update_data["amount"] = amount
            if date is not None:
                update_data["date"] = date
            if hide_from_reports is not None:
                update_data["hide_from_reports"] = hide_from_reports
            if needs_review is not None:
                update_data["needs_review"] = needs_review
            if notes is not None:
                update_data["notes"] = notes

            return await client.update_transaction(**update_data)

        result = run_async(_update_transaction())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to update transaction: {e}")
        return f"Error updating transaction: {str(e)}"


@mcp.tool()
def get_transaction_categories() -> str:
    """Get all available transaction categories from Monarch Money."""
    try:

        async def _get() -> Any:
            client = await get_monarch_client()
            return await client.get_transaction_categories()

        data = run_async(_get())

        categories = []
        for cat in data.get("categories", []):
            group = cat.get("group") or {}
            categories.append(
                {
                    "id": cat.get("id"),
                    "name": cat.get("name"),
                    "icon": cat.get("icon"),
                    "group": group.get("name") if isinstance(group, dict) else None,
                    "group_id": group.get("id") if isinstance(group, dict) else None,
                }
            )
        return json.dumps(categories, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction categories: {e}")
        return f"Error getting transaction categories: {str(e)}"


@mcp.tool()
def get_transaction_category_groups() -> str:
    """Get all transaction category groups (parent groupings for categories)."""
    try:

        async def _get() -> Any:
            client = await get_monarch_client()
            return await client.get_transaction_category_groups()

        data = run_async(_get())
        groups = [
            {"id": g.get("id"), "name": g.get("name"), "type": g.get("type")}
            for g in data.get("categoryGroups", [])
        ]
        return json.dumps(groups, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction category groups: {e}")
        return f"Error getting transaction category groups: {str(e)}"


@mcp.tool()
def create_transaction_category(
    group_id: str,
    transaction_category_name: str,
    icon: Optional[str] = None,
    rollover_enabled: Optional[bool] = None,
    rollover_type: Optional[str] = None,
) -> str:
    """
    Create a new transaction category.

    Args:
        group_id: The category group ID this category belongs to
        transaction_category_name: Name of the new category
        icon: Optional emoji icon for the category
        rollover_enabled: Optional, whether budget rollover is enabled
        rollover_type: Optional rollover type (e.g. "monthly")
    """
    try:

        async def _create() -> Any:
            client = await get_monarch_client()
            kwargs: Dict[str, Any] = {
                "group_id": group_id,
                "transaction_category_name": transaction_category_name,
            }
            if icon is not None:
                kwargs["icon"] = icon
            if rollover_enabled is not None:
                kwargs["rollover_enabled"] = rollover_enabled
            if rollover_type is not None:
                kwargs["rollover_type"] = rollover_type
            return await client.create_transaction_category(**kwargs)

        result = run_async(_create())
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create transaction category: {e}")
        return f"Error creating transaction category: {str(e)}"


@mcp.tool()
def get_transaction_tags() -> str:
    """Get all available transaction tags from Monarch Money."""
    try:

        async def _get() -> Any:
            client = await get_monarch_client()
            return await client.get_transaction_tags()

        data = run_async(_get())

        # The library returns tags under "householdTransactionTags"
        raw_tags = data.get("householdTransactionTags") or data.get("tags") or []
        tags = [
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "color": t.get("color"),
            }
            for t in raw_tags
        ]
        return json.dumps(tags, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction tags: {e}")
        return f"Error getting transaction tags: {str(e)}"


@mcp.tool()
def set_transaction_tags(transaction_id: str, tag_ids: list[str]) -> str:
    """
    Set the tags on a transaction (replaces existing tags).

    Args:
        transaction_id: The ID of the transaction to tag
        tag_ids: List of tag IDs to assign. Pass [] to clear all tags.
    """
    try:

        async def _set() -> Any:
            client = await get_monarch_client()
            return await client.set_transaction_tags(
                transaction_id=transaction_id, tag_ids=tag_ids
            )

        result = run_async(_set())
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to set transaction tags: {e}")
        return f"Error setting transaction tags: {str(e)}"


@mcp.tool()
def add_transaction_tag(transaction_id: str, tag_id: str) -> str:
    """
    Add a tag to a transaction, preserving any tags already on it.

    Args:
        transaction_id: The ID of the transaction
        tag_id: The tag ID to add
    """
    try:

        async def _add() -> Any:
            client = await get_monarch_client()
            details = await client.get_transaction_details(transaction_id)
            txn = details.get("getTransaction") or {}
            existing = [t.get("id") for t in (txn.get("tags") or []) if t.get("id")]
            if tag_id not in existing:
                existing.append(tag_id)
            return await client.set_transaction_tags(
                transaction_id=transaction_id, tag_ids=existing
            )

        result = run_async(_add())
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to add transaction tag: {e}")
        return f"Error adding transaction tag: {str(e)}"


@mcp.tool()
def create_transaction_tag(name: str, color: str) -> str:
    """
    Create a new transaction tag.

    Args:
        name: Name of the new tag
        color: Hex color code for the tag (e.g. "#ff0000")
    """
    try:

        async def _create() -> Any:
            client = await get_monarch_client()
            return await client.create_transaction_tag(name=name, color=color)

        result = run_async(_create())
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create transaction tag: {e}")
        return f"Error creating transaction tag: {str(e)}"


@mcp.tool()
def categorize_transaction(transaction_id: str, category_id: str) -> str:
    """
    Assign a category to a transaction.

    Args:
        transaction_id: The ID of the transaction to categorize
        category_id: The category ID to assign
    """
    try:

        async def _categorize() -> Any:
            client = await get_monarch_client()
            return await client.update_transaction(
                transaction_id=transaction_id, category_id=category_id
            )

        result = run_async(_categorize())
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to categorize transaction: {e}")
        return f"Error categorizing transaction: {str(e)}"


@mcp.tool()
def refresh_accounts() -> str:
    """Request account data refresh from financial institutions."""
    try:

        async def _refresh_accounts() -> Any:
            client = await get_monarch_client()
            return await client.request_accounts_refresh()

        result = run_async(_refresh_accounts())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to refresh accounts: {e}")
        return f"Error refreshing accounts: {str(e)}"


def main() -> None:
    """Main entry point for the server."""
    logger.info("Starting Monarch Money MCP Server...")
    try:
        mcp.run()
    except Exception as e:
        logger.error(f"Failed to run server: {str(e)}")
        raise


# Export for mcp run
app = mcp

if __name__ == "__main__":
    main()
