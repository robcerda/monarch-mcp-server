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
from monarchmoney.monarchmoney import MonarchMoneyEndpoints  # type: ignore
from pydantic import BaseModel, Field
from monarch_mcp_server import auth
from monarch_mcp_server.secure_session import secure_session

# Patch MonarchMoney to use new API domain (monarch.com instead of monarchmoney.com)
MonarchMoneyEndpoints.BASE_URL = "https://api.monarch.com"

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
    return """🔐 Monarch Money - Authentication Options

Option 1: Google OAuth (Recommended)
   Call the 'authenticate_with_google' tool to open a browser
   and sign in with your Google account.

Option 2: Email/Password (Terminal)
   Run in terminal: python login_setup.py

✅ Session persists across restarts
✅ Token stored securely in system keyring"""


@mcp.tool()
def authenticate_with_google() -> str:
    """
    Open a browser window to authenticate with Monarch Money using Google OAuth.

    This will:
    1. Open a browser window
    2. Navigate to Monarch login page
    3. You sign in with Google (or email/password)
    4. Token is automatically captured and saved

    Use this when you get authentication errors or need to refresh your session.

    Returns:
        Success or failure message.
    """
    try:
        import asyncio
        from playwright.async_api import async_playwright

        async def _authenticate():
            captured_token = None

            async with async_playwright() as p:
                # Launch browser in non-headless mode
                browser = await p.chromium.launch(
                    headless=False,
                    args=['--disable-blink-features=AutomationControlled']
                )

                context = await browser.new_context(
                    viewport={'width': 1280, 'height': 800},
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                )

                page = await context.new_page()

                # Capture auth token from requests
                async def handle_request(request):
                    nonlocal captured_token
                    auth_header = request.headers.get('authorization', '')
                    if auth_header.startswith('Token ') and not captured_token:
                        captured_token = auth_header.replace('Token ', '')

                page.on('request', handle_request)

                # Navigate to login
                await page.goto("https://app.monarch.com/login")

                # Wait for token capture (max 5 minutes)
                max_wait = 300
                waited = 0
                while not captured_token and waited < max_wait:
                    await asyncio.sleep(1)
                    waited += 1

                await browser.close()

                if captured_token:
                    # Save to keyring
                    secure_session.save_token(captured_token)
                    return {"success": True, "message": "Authentication successful! Token saved."}
                else:
                    return {"success": False, "message": "Timeout - no token captured. Please try again."}

        result = run_async(_authenticate())
        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        return json.dumps({
            "success": False,
            "message": f"Authentication failed: {str(e)}"
        }, indent=2)


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
def set_transaction_category(
    transaction_id: str,
    category_id: str,
    mark_reviewed: bool = True,
) -> str:
    """
    Set the category for a transaction and optionally mark it as reviewed.

    This is the primary tool for categorizing transactions during review.
    Use get_categories() first to see available categories.

    Args:
        transaction_id: The ID of the transaction to categorize
        category_id: The ID of the category to assign (use get_categories to find IDs)
        mark_reviewed: Whether to also mark the transaction as reviewed (default: True)

    Returns:
        Updated transaction details.
    """
    try:

        async def _set_category():
            client = await get_monarch_client()

            update_params = {
                "transaction_id": transaction_id,
                "category_id": category_id,
            }

            if mark_reviewed:
                update_params["needs_review"] = False

            return await client.update_transaction(**update_params)

        result = run_async(_set_category())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to set transaction category: {e}")
        return f"Error setting category: {str(e)}"


@mcp.tool()
def update_transaction_notes(
    transaction_id: str,
    notes: str,
    receipt_url: Optional[str] = None,
) -> str:
    """
    Update the notes/memo for a transaction.

    Suggested format: [Receipt: URL] Description
    If receipt_url is provided, it will be prepended to the notes.

    Args:
        transaction_id: The ID of the transaction to update
        notes: The note/memo text to add
        receipt_url: Optional URL to a receipt (will be formatted as [Receipt: URL])

    Returns:
        Updated transaction details.
    """
    try:

        async def _update_notes():
            client = await get_monarch_client()

            # Format notes with receipt URL if provided
            if receipt_url:
                formatted_notes = f"[Receipt: {receipt_url}] {notes}"
            else:
                formatted_notes = notes

            return await client.update_transaction(
                transaction_id=transaction_id,
                notes=formatted_notes,
            )

        result = run_async(_update_notes())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to update transaction notes: {e}")
        return f"Error updating notes: {str(e)}"


@mcp.tool()
def mark_transaction_reviewed(
    transaction_id: str,
) -> str:
    """
    Mark a transaction as reviewed (clears the needs_review flag).

    Use this after reviewing a transaction that doesn't need category changes.

    Args:
        transaction_id: The ID of the transaction to mark as reviewed

    Returns:
        Updated transaction details.
    """
    try:

        async def _mark_reviewed():
            client = await get_monarch_client()

            return await client.update_transaction(
                transaction_id=transaction_id,
                needs_review=False,
            )

        result = run_async(_mark_reviewed())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to mark transaction as reviewed: {e}")
        return f"Error marking reviewed: {str(e)}"


@mcp.tool()
def bulk_categorize_transactions(
    transaction_ids: List[str],
    category_id: str,
    mark_reviewed: bool = True,
) -> str:
    """
    Apply the same category to multiple transactions at once.

    This is useful for categorizing similar transactions in bulk,
    such as all purchases from the same merchant.

    Args:
        transaction_ids: List of transaction IDs to categorize
        category_id: The category ID to apply to all transactions
        mark_reviewed: Whether to also mark transactions as reviewed (default: True)

    Returns:
        Summary of results including success/failure counts.
    """
    try:

        async def _bulk_categorize():
            client = await get_monarch_client()

            results = {
                "total": len(transaction_ids),
                "successful": 0,
                "failed": 0,
                "errors": [],
            }

            for txn_id in transaction_ids:
                try:
                    update_params = {
                        "transaction_id": txn_id,
                        "category_id": category_id,
                    }
                    if mark_reviewed:
                        update_params["needs_review"] = False

                    await client.update_transaction(**update_params)
                    results["successful"] += 1
                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append({
                        "transaction_id": txn_id,
                        "error": str(e),
                    })

            return results

        result = run_async(_bulk_categorize())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to bulk categorize transactions: {e}")
        return f"Error in bulk categorization: {str(e)}"


@mcp.tool()
def get_tags() -> str:
    """
    Get all transaction tags from Monarch Money.

    Returns a list of tags with their colors and transaction counts.
    Use this to see available tags before applying them to transactions.
    """
    try:

        async def _get_tags():
            client = await get_monarch_client()
            return await client.get_transaction_tags()

        tags_data = run_async(_get_tags())

        # Format tags for display
        tag_list = []
        for tag in tags_data.get("householdTransactionTags", []):
            tag_info = {
                "id": tag.get("id"),
                "name": tag.get("name"),
                "color": tag.get("color"),
                "order": tag.get("order"),
                "transaction_count": tag.get("transactionCount", 0),
            }
            tag_list.append(tag_info)

        return json.dumps(tag_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get tags: {e}")
        return f"Error getting tags: {str(e)}"


@mcp.tool()
def set_transaction_tags(
    transaction_id: str,
    tag_ids: List[str],
) -> str:
    """
    Set tags on a transaction.

    Note: This REPLACES all existing tags on the transaction.
    To add a tag, include both existing and new tag IDs.
    To remove all tags, pass an empty list.

    Args:
        transaction_id: The ID of the transaction to tag
        tag_ids: List of tag IDs to apply (use get_tags to find IDs)

    Returns:
        Updated transaction details.
    """
    try:

        async def _set_tags():
            client = await get_monarch_client()
            return await client.set_transaction_tags(
                transaction_id=transaction_id,
                tag_ids=tag_ids,
            )

        result = run_async(_set_tags())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to set transaction tags: {e}")
        return f"Error setting tags: {str(e)}"


@mcp.tool()
def create_tag(
    name: str,
    color: str = "#19D2A5",
) -> str:
    """
    Create a new transaction tag.

    Args:
        name: Name for the new tag
        color: Hex color code for the tag (default: "#19D2A5" - teal)
               Examples: "#FF5733" (red-orange), "#3498DB" (blue), "#9B59B6" (purple)

    Returns:
        The created tag details including its ID.
    """
    try:

        async def _create_tag():
            client = await get_monarch_client()
            return await client.create_transaction_tag(
                name=name,
                color=color,
            )

        result = run_async(_create_tag())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create tag: {e}")
        return f"Error creating tag: {str(e)}"


@mcp.tool()
def search_transactions(
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category_ids: Optional[List[str]] = None,
    account_ids: Optional[List[str]] = None,
    tag_ids: Optional[List[str]] = None,
    has_attachments: Optional[bool] = None,
    has_notes: Optional[bool] = None,
    hidden_from_reports: Optional[bool] = None,
    is_split: Optional[bool] = None,
    is_recurring: Optional[bool] = None,
) -> str:
    """
    Search and filter transactions with comprehensive filtering options.

    This is the most flexible transaction query tool, supporting all available filters.

    Args:
        search: Text to search for in transaction descriptions/merchants
        limit: Maximum number of transactions to return (default: 100)
        offset: Number of transactions to skip for pagination (default: 0)
        start_date: Filter start date in YYYY-MM-DD format
        end_date: Filter end date in YYYY-MM-DD format
        category_ids: List of category IDs to filter by
        account_ids: List of account IDs to filter by
        tag_ids: List of tag IDs to filter by
        has_attachments: Filter for transactions with/without attachments
        has_notes: Filter for transactions with/without notes
        hidden_from_reports: Filter for transactions hidden/shown in reports
        is_split: Filter for split/non-split transactions
        is_recurring: Filter for recurring/non-recurring transactions

    Returns:
        List of matching transactions with full details.
    """
    try:

        async def _search_transactions():
            client = await get_monarch_client()

            # Build filters dict with only non-None values
            filters = {"limit": limit, "offset": offset}

            if search:
                filters["search"] = search
            if start_date:
                filters["start_date"] = start_date
            if end_date:
                filters["end_date"] = end_date
            if category_ids:
                filters["category_ids"] = category_ids
            if account_ids:
                filters["account_ids"] = account_ids
            if tag_ids:
                filters["tag_ids"] = tag_ids
            if has_attachments is not None:
                filters["has_attachments"] = has_attachments
            if has_notes is not None:
                filters["has_notes"] = has_notes
            if hidden_from_reports is not None:
                filters["hidden_from_reports"] = hidden_from_reports
            if is_split is not None:
                filters["is_split"] = is_split
            if is_recurring is not None:
                filters["is_recurring"] = is_recurring

            return await client.get_transactions(**filters)

        transactions_data = run_async(_search_transactions())

        # Format transactions with full details
        transaction_list = []
        for txn in transactions_data.get("allTransactions", {}).get("results", []):
            transaction_info = {
                "id": txn.get("id"),
                "date": txn.get("date"),
                "amount": txn.get("amount"),
                "merchant": txn.get("merchant", {}).get("name") if txn.get("merchant") else None,
                "original_name": txn.get("plaidName") or txn.get("originalName"),
                "category": txn.get("category", {}).get("name") if txn.get("category") else None,
                "category_id": txn.get("category", {}).get("id") if txn.get("category") else None,
                "account": txn.get("account", {}).get("displayName") if txn.get("account") else None,
                "account_id": txn.get("account", {}).get("id") if txn.get("account") else None,
                "notes": txn.get("notes"),
                "needs_review": txn.get("needsReview", False),
                "is_pending": txn.get("pending", False),
                "hide_from_reports": txn.get("hideFromReports", False),
                "is_split": txn.get("isSplitTransaction", False),
                "is_recurring": txn.get("isRecurring", False),
                "has_attachments": bool(txn.get("attachments")),
                "tags": [
                    {"id": tag.get("id"), "name": tag.get("name")}
                    for tag in txn.get("tags", [])
                ] if txn.get("tags") else [],
            }
            transaction_list.append(transaction_info)

        return json.dumps(transaction_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to search transactions: {e}")
        return f"Error searching transactions: {str(e)}"


@mcp.tool()
def get_transaction_details(
    transaction_id: str,
) -> str:
    """
    Get full details for a specific transaction.

    Returns comprehensive information including attachments, splits, tags, and more.

    Args:
        transaction_id: The ID of the transaction to get details for

    Returns:
        Complete transaction details.
    """
    try:

        async def _get_details():
            client = await get_monarch_client()
            return await client.get_transaction_details(transaction_id=transaction_id)

        result = run_async(_get_details())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction details: {e}")
        return f"Error getting transaction details: {str(e)}"


@mcp.tool()
def delete_transaction(
    transaction_id: str,
) -> str:
    """
    Delete a transaction from Monarch Money.

    Warning: This action cannot be undone.

    Args:
        transaction_id: The ID of the transaction to delete

    Returns:
        Confirmation of deletion.
    """
    try:

        async def _delete():
            client = await get_monarch_client()
            return await client.delete_transaction(transaction_id=transaction_id)

        result = run_async(_delete())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to delete transaction: {e}")
        return f"Error deleting transaction: {str(e)}"


@mcp.tool()
def get_recurring_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get upcoming recurring transactions.

    Returns scheduled recurring transactions with their merchants, amounts, and accounts.

    Args:
        start_date: Start date in YYYY-MM-DD format (defaults to start of current month)
        end_date: End date in YYYY-MM-DD format (defaults to end of current month)

    Returns:
        List of upcoming recurring transactions.
    """
    try:

        async def _get_recurring():
            client = await get_monarch_client()

            filters = {}
            if start_date:
                filters["start_date"] = start_date
            if end_date:
                filters["end_date"] = end_date

            return await client.get_recurring_transactions(**filters)

        result = run_async(_get_recurring())

        # Format recurring transactions
        recurring_list = []
        for item in result.get("recurringTransactionItems", []):
            recurring_info = {
                "date": item.get("date"),
                "amount": item.get("amount"),
                "is_past": item.get("isPast", False),
                "transaction_id": item.get("transactionId"),
                "stream": {
                    "id": item.get("stream", {}).get("id"),
                    "frequency": item.get("stream", {}).get("frequency"),
                    "amount": item.get("stream", {}).get("amount"),
                    "is_approximate": item.get("stream", {}).get("isApproximate", False),
                    "merchant": item.get("stream", {}).get("merchant", {}).get("name")
                    if item.get("stream", {}).get("merchant") else None,
                } if item.get("stream") else None,
                "category": item.get("category", {}).get("name") if item.get("category") else None,
                "account": item.get("account", {}).get("displayName") if item.get("account") else None,
            }
            recurring_list.append(recurring_info)

        return json.dumps(recurring_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get recurring transactions: {e}")
        return f"Error getting recurring transactions: {str(e)}"


# =============================================================================
# Transaction Splits
# =============================================================================


@mcp.tool()
def get_transaction_splits(
    transaction_id: str,
) -> str:
    """
    Get the splits for a transaction.

    Returns the split details if the transaction has been split into multiple parts.

    Args:
        transaction_id: The ID of the transaction to get splits for

    Returns:
        Split information for the transaction, or empty if not split.
    """
    try:

        async def _get_splits():
            client = await get_monarch_client()
            return await client.get_transaction_splits(transaction_id=transaction_id)

        result = run_async(_get_splits())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction splits: {e}")
        return f"Error getting transaction splits: {str(e)}"


@mcp.tool()
def split_transaction(
    transaction_id: str,
    splits: str,
) -> str:
    """
    Split a transaction into multiple parts with different categories/merchants.

    The sum of all split amounts must equal the original transaction amount.
    Pass an empty list to remove all splits and restore the original transaction.

    Args:
        transaction_id: The ID of the transaction to split
        splits: JSON array of split objects. Each split should have:
            - amount: The amount for this split (negative for expenses, positive for income)
            - categoryId: (optional) The category ID for this split
            - merchantName: (optional) The merchant name for this split
            Example: '[{"amount": -50.00, "categoryId": "123", "merchantName": "Groceries"}, {"amount": -25.00, "categoryId": "456", "merchantName": "Household"}]'

    Returns:
        The updated split information for the transaction.
    """
    try:
        # Parse the splits JSON
        try:
            split_data = json.loads(splits)
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON in splits parameter: {str(e)}"

        if not isinstance(split_data, list):
            return "Error: splits must be a JSON array"

        async def _split_transaction():
            client = await get_monarch_client()
            return await client.update_transaction_splits(
                transaction_id=transaction_id,
                split_data=split_data
            )

        result = run_async(_split_transaction())

        return json.dumps({
            "success": True,
            "message": f"Transaction split into {len(split_data)} parts" if split_data else "Splits removed from transaction",
            "splits": result
        }, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to split transaction: {e}")
        return f"Error splitting transaction: {str(e)}"


# =============================================================================
# Transaction Rules API (reverse-engineered from Monarch web app)
# =============================================================================

# GraphQL query for getting transaction rules
GET_TRANSACTION_RULES_QUERY = """
query GetTransactionRules {
  transactionRules {
    id
    order
    merchantCriteriaUseOriginalStatement
    merchantCriteria {
      operator
      value
      __typename
    }
    originalStatementCriteria {
      operator
      value
      __typename
    }
    merchantNameCriteria {
      operator
      value
      __typename
    }
    amountCriteria {
      operator
      isExpense
      value
      valueRange {
        lower
        upper
        __typename
      }
      __typename
    }
    categoryIds
    accountIds
    categories {
      id
      name
      icon
      __typename
    }
    accounts {
      id
      displayName
      __typename
    }
    setMerchantAction {
      id
      name
      __typename
    }
    setCategoryAction {
      id
      name
      icon
      __typename
    }
    addTagsAction {
      id
      name
      color
      __typename
    }
    linkGoalAction {
      id
      name
      __typename
    }
    setHideFromReportsAction
    reviewStatusAction
    recentApplicationCount
    lastAppliedAt
    __typename
  }
}
"""

CREATE_TRANSACTION_RULE_MUTATION = """
mutation Common_CreateTransactionRuleMutationV2($input: CreateTransactionRuleInput!) {
  createTransactionRuleV2(input: $input) {
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    __typename
  }
}
"""

UPDATE_TRANSACTION_RULE_MUTATION = """
mutation Common_UpdateTransactionRuleMutationV2($input: UpdateTransactionRuleInput!) {
  updateTransactionRuleV2(input: $input) {
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    __typename
  }
}
"""

DELETE_TRANSACTION_RULE_MUTATION = """
mutation Common_DeleteTransactionRule($id: ID!) {
  deleteTransactionRule(id: $id) {
    deleted
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    __typename
  }
}
"""


@mcp.tool()
def get_transaction_rules() -> str:
    """
    Get all transaction auto-categorization rules from Monarch Money.

    Returns a list of rules with their conditions and actions.
    Rules automatically categorize transactions based on merchant, amount, etc.
    """
    try:
        from gql import gql

        async def _get_rules():
            client = await get_monarch_client()
            query = gql(GET_TRANSACTION_RULES_QUERY)
            return await client.gql_call(
                operation="GetTransactionRules",
                graphql_query=query,
                variables={},
            )

        result = run_async(_get_rules())

        # Format rules for display
        rules_list = []
        for rule in result.get("transactionRules", []):
            rule_info = {
                "id": rule.get("id"),
                "order": rule.get("order"),
                # Criteria (conditions)
                "merchant_criteria": rule.get("merchantCriteria"),
                "merchant_name_criteria": rule.get("merchantNameCriteria"),
                "original_statement_criteria": rule.get("originalStatementCriteria"),
                "amount_criteria": rule.get("amountCriteria"),
                "category_ids": rule.get("categoryIds"),
                "account_ids": rule.get("accountIds"),
                "use_original_statement": rule.get("merchantCriteriaUseOriginalStatement"),
                # Actions
                "set_category_action": {
                    "id": rule.get("setCategoryAction", {}).get("id"),
                    "name": rule.get("setCategoryAction", {}).get("name"),
                } if rule.get("setCategoryAction") else None,
                "set_merchant_action": {
                    "id": rule.get("setMerchantAction", {}).get("id"),
                    "name": rule.get("setMerchantAction", {}).get("name"),
                } if rule.get("setMerchantAction") else None,
                "add_tags_action": [
                    {"id": tag.get("id"), "name": tag.get("name")}
                    for tag in rule.get("addTagsAction", [])
                ] if rule.get("addTagsAction") else None,
                "link_goal_action": rule.get("linkGoalAction"),
                "hide_from_reports_action": rule.get("setHideFromReportsAction"),
                "review_status_action": rule.get("reviewStatusAction"),
                # Stats
                "recent_application_count": rule.get("recentApplicationCount"),
                "last_applied_at": rule.get("lastAppliedAt"),
            }
            rules_list.append(rule_info)

        return json.dumps(rules_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction rules: {e}")
        return f"Error getting transaction rules: {str(e)}"


@mcp.tool()
def create_transaction_rule(
    merchant_criteria_operator: Optional[str] = None,
    merchant_criteria_value: Optional[str] = None,
    amount_operator: Optional[str] = None,
    amount_value: Optional[float] = None,
    amount_is_expense: bool = True,
    set_category_id: Optional[str] = None,
    set_merchant_name: Optional[str] = None,
    add_tag_ids: Optional[List[str]] = None,
    hide_from_reports: Optional[bool] = None,
    review_status: Optional[str] = None,
    account_ids: Optional[List[str]] = None,
    apply_to_existing: bool = False,
) -> str:
    """
    Create a new transaction auto-categorization rule.

    Rules automatically categorize future transactions based on conditions.

    Args:
        merchant_criteria_operator: How to match merchant ("eq", "contains")
        merchant_criteria_value: Merchant name/pattern to match
        amount_operator: Amount comparison ("gt", "lt", "eq", "between")
        amount_value: Amount threshold value
        amount_is_expense: Whether amount is expense (negative) or income
        set_category_id: Category ID to assign (use get_categories for IDs)
        set_merchant_name: Merchant name to set on matching transactions
        add_tag_ids: List of tag IDs to add (use get_tags for IDs)
        hide_from_reports: Whether to hide matching transactions from reports
        review_status: Review status to set ("needs_review" or null)
        account_ids: Limit rule to specific account IDs
        apply_to_existing: Whether to apply rule to existing transactions

    Returns:
        Result of rule creation.

    Example:
        Create rule: "Amazon purchases → Shopping category"
        create_transaction_rule(
            merchant_criteria_operator="contains",
            merchant_criteria_value="amazon",
            set_category_id="cat_123"
        )
    """
    try:
        from gql import gql

        async def _create_rule():
            client = await get_monarch_client()

            # Build input
            rule_input: Dict[str, Any] = {
                "applyToExistingTransactions": apply_to_existing,
            }

            # Merchant criteria
            if merchant_criteria_operator and merchant_criteria_value:
                rule_input["merchantNameCriteria"] = [{
                    "operator": merchant_criteria_operator,
                    "value": merchant_criteria_value,
                }]

            # Amount criteria
            if amount_operator and amount_value is not None:
                rule_input["amountCriteria"] = {
                    "operator": amount_operator,
                    "isExpense": amount_is_expense,
                    "value": amount_value,
                    "valueRange": None,
                }

            # Account filter
            if account_ids:
                rule_input["accountIds"] = account_ids

            # Actions
            if set_category_id:
                rule_input["setCategoryAction"] = set_category_id
            if set_merchant_name:
                rule_input["setMerchantAction"] = set_merchant_name
            if add_tag_ids:
                rule_input["addTagsAction"] = add_tag_ids
            if hide_from_reports is not None:
                rule_input["setHideFromReportsAction"] = hide_from_reports
            if review_status:
                rule_input["reviewStatusAction"] = review_status

            query = gql(CREATE_TRANSACTION_RULE_MUTATION)
            return await client.gql_call(
                operation="Common_CreateTransactionRuleMutationV2",
                graphql_query=query,
                variables={"input": rule_input},
            )

        result = run_async(_create_rule())

        # Check for errors
        errors = result.get("createTransactionRuleV2", {}).get("errors")
        if errors:
            return json.dumps({"success": False, "errors": errors}, indent=2)

        return json.dumps({"success": True, "message": "Rule created successfully"}, indent=2)
    except Exception as e:
        logger.error(f"Failed to create transaction rule: {e}")
        return f"Error creating transaction rule: {str(e)}"


@mcp.tool()
def update_transaction_rule(
    rule_id: str,
    merchant_criteria_operator: Optional[str] = None,
    merchant_criteria_value: Optional[str] = None,
    amount_operator: Optional[str] = None,
    amount_value: Optional[float] = None,
    amount_is_expense: bool = True,
    set_category_id: Optional[str] = None,
    set_merchant_name: Optional[str] = None,
    add_tag_ids: Optional[List[str]] = None,
    hide_from_reports: Optional[bool] = None,
    review_status: Optional[str] = None,
    account_ids: Optional[List[str]] = None,
    apply_to_existing: bool = False,
) -> str:
    """
    Update an existing transaction rule.

    Args:
        rule_id: The ID of the rule to update (use get_transaction_rules to find IDs)
        merchant_criteria_operator: How to match merchant ("eq", "contains")
        merchant_criteria_value: Merchant name/pattern to match
        amount_operator: Amount comparison ("gt", "lt", "eq", "between")
        amount_value: Amount threshold value
        amount_is_expense: Whether amount is expense (negative) or income
        set_category_id: Category ID to assign
        set_merchant_name: Merchant name to set
        add_tag_ids: List of tag IDs to add
        hide_from_reports: Whether to hide from reports
        review_status: Review status to set
        account_ids: Limit rule to specific accounts
        apply_to_existing: Apply changes to existing transactions

    Returns:
        Result of rule update.
    """
    try:
        from gql import gql

        async def _update_rule():
            client = await get_monarch_client()

            # Build input
            rule_input: Dict[str, Any] = {
                "id": rule_id,
                "applyToExistingTransactions": apply_to_existing,
            }

            # Merchant criteria
            if merchant_criteria_operator and merchant_criteria_value:
                rule_input["merchantNameCriteria"] = [{
                    "operator": merchant_criteria_operator,
                    "value": merchant_criteria_value,
                }]

            # Amount criteria
            if amount_operator and amount_value is not None:
                rule_input["amountCriteria"] = {
                    "operator": amount_operator,
                    "isExpense": amount_is_expense,
                    "value": amount_value,
                    "valueRange": None,
                }

            # Account filter
            if account_ids:
                rule_input["accountIds"] = account_ids

            # Actions
            if set_category_id:
                rule_input["setCategoryAction"] = set_category_id
            if set_merchant_name:
                rule_input["setMerchantAction"] = set_merchant_name
            if add_tag_ids:
                rule_input["addTagsAction"] = add_tag_ids
            if hide_from_reports is not None:
                rule_input["setHideFromReportsAction"] = hide_from_reports
            if review_status:
                rule_input["reviewStatusAction"] = review_status

            query = gql(UPDATE_TRANSACTION_RULE_MUTATION)
            return await client.gql_call(
                operation="Common_UpdateTransactionRuleMutationV2",
                graphql_query=query,
                variables={"input": rule_input},
            )

        result = run_async(_update_rule())

        # Check for errors
        errors = result.get("updateTransactionRuleV2", {}).get("errors")
        if errors:
            return json.dumps({"success": False, "errors": errors}, indent=2)

        return json.dumps({"success": True, "message": "Rule updated successfully"}, indent=2)
    except Exception as e:
        logger.error(f"Failed to update transaction rule: {e}")
        return f"Error updating transaction rule: {str(e)}"


@mcp.tool()
def delete_transaction_rule(
    rule_id: str,
) -> str:
    """
    Delete a transaction rule.

    Args:
        rule_id: The ID of the rule to delete (use get_transaction_rules to find IDs)

    Returns:
        Confirmation of deletion.
    """
    try:
        from gql import gql

        async def _delete_rule():
            client = await get_monarch_client()

            query = gql(DELETE_TRANSACTION_RULE_MUTATION)
            return await client.gql_call(
                operation="Common_DeleteTransactionRule",
                graphql_query=query,
                variables={"id": rule_id},
            )

        result = run_async(_delete_rule())

        # Check result
        delete_result = result.get("deleteTransactionRule", {})
        if delete_result.get("deleted"):
            return json.dumps({"success": True, "message": "Rule deleted successfully"}, indent=2)

        errors = delete_result.get("errors")
        if errors:
            return json.dumps({"success": False, "errors": errors}, indent=2)

        return json.dumps({"success": False, "message": "Unknown error"}, indent=2)
    except Exception as e:
        logger.error(f"Failed to delete transaction rule: {e}")
        return f"Error deleting transaction rule: {str(e)}"


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


@mcp.tool()
def get_categories() -> str:
    """
    Get all transaction categories from Monarch Money.

    Returns a list of categories with their groups, icons, and metadata.
    Useful for selecting a category when categorizing transactions.
    """
    try:

        async def _get_categories():
            client = await get_monarch_client()
            return await client.get_transaction_categories()

        categories_data = run_async(_get_categories())

        # Format categories for display
        category_list = []
        for cat in categories_data.get("categories", []):
            category_info = {
                "id": cat.get("id"),
                "name": cat.get("name"),
                "icon": cat.get("icon"),
                "group": cat.get("group", {}).get("name") if cat.get("group") else None,
                "group_id": cat.get("group", {}).get("id") if cat.get("group") else None,
                "is_system_category": cat.get("isSystemCategory", False),
                "is_disabled": cat.get("isDisabled", False),
            }
            category_list.append(category_info)

        return json.dumps(category_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get categories: {e}")
        return f"Error getting categories: {str(e)}"


@mcp.tool()
def get_category_groups() -> str:
    """
    Get all transaction category groups from Monarch Money.

    Returns groups like Income, Expenses, etc. with their associated categories.
    """
    try:

        async def _get_category_groups():
            client = await get_monarch_client()
            return await client.get_transaction_category_groups()

        groups_data = run_async(_get_category_groups())

        # Format category groups for display
        group_list = []
        for group in groups_data.get("categoryGroups", []):
            group_info = {
                "id": group.get("id"),
                "name": group.get("name"),
                "type": group.get("type"),
                "budget_variability": group.get("budgetVariability"),
                "group_level_budgeting_enabled": group.get("groupLevelBudgetingEnabled", False),
                "categories": [
                    {
                        "id": cat.get("id"),
                        "name": cat.get("name"),
                        "icon": cat.get("icon"),
                    }
                    for cat in group.get("categories", [])
                ],
            }
            group_list.append(group_info)

        return json.dumps(group_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get category groups: {e}")
        return f"Error getting category groups: {str(e)}"


@mcp.tool()
def get_transactions_needing_review(
    needs_review: bool = True,
    days: Optional[int] = None,
    uncategorized_only: bool = False,
    without_notes_only: bool = False,
    limit: int = 100,
    account_id: Optional[str] = None,
) -> str:
    """
    Get transactions that need review based on various criteria.

    This is the primary tool for finding transactions to categorize and review.

    Args:
        needs_review: Filter for transactions flagged as needing review (default: True)
        days: Only include transactions from the last N days (e.g., 7 for last week)
        uncategorized_only: Only include transactions without a category assigned
        without_notes_only: Only include transactions without notes/memos
        limit: Maximum number of transactions to return (default: 100)
        account_id: Filter by specific account ID

    Returns:
        List of transactions matching the criteria with full details.
    """
    try:
        from datetime import datetime, timedelta

        async def _get_transactions():
            client = await get_monarch_client()

            # Build filters
            filters = {"limit": limit}

            # Date range filter
            if days:
                end_date = datetime.now().strftime("%Y-%m-%d")
                start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                filters["start_date"] = start_date
                filters["end_date"] = end_date

            if account_id:
                filters["account_ids"] = [account_id]

            # Note: has_notes filter (if supported by API)
            if without_notes_only:
                filters["has_notes"] = False

            return await client.get_transactions(**filters)

        transactions_data = run_async(_get_transactions())

        # Post-filter transactions based on criteria
        transaction_list = []
        for txn in transactions_data.get("allTransactions", {}).get("results", []):
            # Filter by needs_review
            if needs_review and not txn.get("needsReview", False):
                continue

            # Filter by uncategorized (no category or null category)
            if uncategorized_only:
                category = txn.get("category")
                if category and category.get("id"):
                    continue

            # Format transaction with full details
            transaction_info = {
                "id": txn.get("id"),
                "date": txn.get("date"),
                "amount": txn.get("amount"),
                "merchant": txn.get("merchant", {}).get("name") if txn.get("merchant") else None,
                "original_name": txn.get("plaidName") or txn.get("originalName"),
                "category": txn.get("category", {}).get("name") if txn.get("category") else None,
                "category_id": txn.get("category", {}).get("id") if txn.get("category") else None,
                "account": txn.get("account", {}).get("displayName") if txn.get("account") else None,
                "account_id": txn.get("account", {}).get("id") if txn.get("account") else None,
                "notes": txn.get("notes"),
                "needs_review": txn.get("needsReview", False),
                "is_pending": txn.get("pending", False),
                "hide_from_reports": txn.get("hideFromReports", False),
                "tags": [
                    {"id": tag.get("id"), "name": tag.get("name")}
                    for tag in txn.get("tags", [])
                ] if txn.get("tags") else [],
            }
            transaction_list.append(transaction_info)

        return json.dumps(transaction_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transactions needing review: {e}")
        return f"Error getting transactions: {str(e)}"


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
