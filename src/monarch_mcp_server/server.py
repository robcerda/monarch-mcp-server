"""Monarch Money MCP Server."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context, FastMCP
from monarchmoney import MonarchMoney

from monarch_mcp_server import auth
from monarch_mcp_server.secure_session import secure_session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("Monarch Money MCP Server")


class NotAuthenticated(RuntimeError):
    """Raised when no usable session is available for a data-tool call."""


def _get_client() -> MonarchMoney:
    client = secure_session.get_authenticated_client()
    if client is None:
        raise NotAuthenticated(
            "Not signed in to Monarch Money. Call `monarch_login` to authenticate."
        )
    return client


# ---------------------------------------------------------------- auth tools


@mcp.tool()
async def monarch_login(ctx: Context) -> str:
    """Sign in to Monarch Money.

    The client opens a secure form to collect email, password, and (if
    required) an MFA code. Credentials never pass through the model.
    """
    return await auth.login_interactive(ctx)


@mcp.tool()
async def monarch_login_with_token(ctx: Context) -> str:
    """Sign in using a browser-copied session token.

    Useful for SSO users who can't use password login. Grab the token from
    browser DevTools → Application → Local Storage → app.monarchmoney.com.
    """
    return await auth.login_with_token_interactive(ctx)


@mcp.tool()
async def monarch_logout() -> str:
    """Clear the stored Monarch Money session from the system keyring."""
    return await auth.logout()


@mcp.tool()
async def check_auth_status() -> str:
    """Report whether a live Monarch Money session is available."""
    token = secure_session.load_token()
    if not token:
        return "Not authenticated. Call `monarch_login`."
    mm = MonarchMoney(token=token)
    try:
        await mm.get_subscription_details()
        return "Authenticated — session is live."
    except Exception as e:
        return (
            f"Stored token appears invalid ({e}). "
            "Call `monarch_login` to re-authenticate."
        )


# ---------------------------------------------------------------- data tools


@mcp.tool()
async def get_accounts() -> str:
    """Get all financial accounts from Monarch Money."""
    client = _get_client()
    accounts = await client.get_accounts()

    account_list = []
    for account in accounts.get("accounts", []):
        type_info = account.get("type", {})
        type_name = type_info.get("name") if isinstance(type_info, dict) else None

        institution_info = account.get("institution", {})
        institution_name = (
            institution_info.get("name") if isinstance(institution_info, dict) else None
        )

        account_list.append(
            {
                "id": account.get("id"),
                "name": account.get("displayName") or account.get("name"),
                "type": type_name,
                "balance": account.get("currentBalance"),
                "institution": institution_name,
                "is_active": not account.get("deactivatedAt"),
                "is_hidden": account.get("isHidden", False),
            }
        )

    return json.dumps(account_list, indent=2, default=str)


@mcp.tool()
async def get_transactions(
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_id: Optional[str] = None,
) -> str:
    """Get transactions from Monarch Money.

    Args:
        limit: Number of transactions to retrieve (default: 100)
        offset: Number of transactions to skip (default: 0)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        account_id: Specific account ID to filter by
    """
    client = _get_client()
    filters: Dict[str, Any] = {}
    if start_date:
        filters["start_date"] = start_date
    if end_date:
        filters["end_date"] = end_date
    if account_id:
        filters["account_id"] = account_id

    transactions = await client.get_transactions(limit=limit, offset=offset, **filters)

    transaction_list = []
    for txn in transactions.get("allTransactions", {}).get("results", []):
        transaction_list.append(
            {
                "id": txn.get("id"),
                "date": txn.get("date"),
                "amount": txn.get("amount"),
                "description": txn.get("description"),
                "category": (
                    txn.get("category", {}).get("name") if txn.get("category") else None
                ),
                "account": txn.get("account", {}).get("displayName"),
                "merchant": (
                    txn.get("merchant", {}).get("name") if txn.get("merchant") else None
                ),
                "is_pending": txn.get("isPending", False),
            }
        )

    return json.dumps(transaction_list, indent=2, default=str)


@mcp.tool()
async def get_budgets(
    start_date: Optional[str] = None, end_date: Optional[str] = None
) -> str:
    """Get budget information from Monarch Money.

    Args:
        start_date: Optional start date in YYYY-MM-DD format.
        end_date: Optional end date in YYYY-MM-DD format.
    """
    client = _get_client()
    budgets = await client.get_budgets(start_date=start_date, end_date=end_date)
    return json.dumps(budgets, indent=2, default=str)


@mcp.tool()
async def get_cashflow(
    start_date: Optional[str] = None, end_date: Optional[str] = None
) -> str:
    """Get cashflow analysis from Monarch Money.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    client = _get_client()
    filters: Dict[str, Any] = {}
    if start_date:
        filters["start_date"] = start_date
    if end_date:
        filters["end_date"] = end_date

    cashflow = await client.get_cashflow(**filters)
    return json.dumps(cashflow, indent=2, default=str)


@mcp.tool()
async def get_account_holdings(account_id: str) -> str:
    """Get investment holdings for a specific account.

    Args:
        account_id: The ID of the investment account
    """
    client = _get_client()
    holdings = await client.get_account_holdings(account_id)
    return json.dumps(holdings, indent=2, default=str)


@mcp.tool()
async def create_transaction(
    date: str,
    account_id: str,
    amount: float,
    merchant_name: str,
    category_id: str,
    notes: Optional[str] = None,
    update_balance: Optional[bool] = False,
) -> str:
    """Create a new transaction in Monarch Money.

    Args:
        date: Transaction date in YYYY-MM-DD format
        account_id: The account ID to add the transaction to
        amount: Transaction amount (positive for income, negative for expenses)
        merchant_name: Merchant or payee name
        category_id: Category ID for the transaction
        notes: Optional notes for the transaction
        update_balance: Whether to update the account balance (default: false)
    """
    client = _get_client()
    kwargs: Dict[str, Any] = {
        "date": date,
        "account_id": account_id,
        "amount": amount,
        "merchant_name": merchant_name,
        "category_id": category_id,
    }
    if notes:
        kwargs["notes"] = notes
    if update_balance:
        kwargs["update_balance"] = update_balance

    result = await client.create_transaction(**kwargs)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def update_transaction(
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
    """Update an existing transaction in Monarch Money.

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
    client = _get_client()
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

    result = await client.update_transaction(**update_data)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_transaction_categories() -> str:
    """Get all available transaction categories from Monarch Money."""
    client = _get_client()
    data = await client.get_transaction_categories()

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


@mcp.tool()
async def get_transaction_category_groups() -> str:
    """Get all transaction category groups (parent groupings for categories)."""
    client = _get_client()
    data = await client.get_transaction_category_groups()
    groups = [
        {"id": g.get("id"), "name": g.get("name"), "type": g.get("type")}
        for g in data.get("categoryGroups", [])
    ]
    return json.dumps(groups, indent=2, default=str)


@mcp.tool()
async def create_transaction_category(
    group_id: str,
    transaction_category_name: str,
    icon: Optional[str] = None,
    rollover_enabled: Optional[bool] = None,
    rollover_type: Optional[str] = None,
) -> str:
    """Create a new transaction category.

    Args:
        group_id: The category group ID this category belongs to
        transaction_category_name: Name of the new category
        icon: Optional emoji icon for the category
        rollover_enabled: Optional, whether budget rollover is enabled
        rollover_type: Optional rollover type (e.g. "monthly")
    """
    client = _get_client()
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

    result = await client.create_transaction_category(**kwargs)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_transaction_tags() -> str:
    """Get all available transaction tags from Monarch Money."""
    client = _get_client()
    data = await client.get_transaction_tags()
    raw_tags = data.get("householdTransactionTags") or data.get("tags") or []
    tags = [
        {"id": t.get("id"), "name": t.get("name"), "color": t.get("color")}
        for t in raw_tags
    ]
    return json.dumps(tags, indent=2, default=str)


@mcp.tool()
async def set_transaction_tags(transaction_id: str, tag_ids: List[str]) -> str:
    """Set the tags on a transaction (replaces existing tags).

    Args:
        transaction_id: The ID of the transaction to tag
        tag_ids: List of tag IDs to assign. Pass [] to clear all tags.
    """
    client = _get_client()
    result = await client.set_transaction_tags(
        transaction_id=transaction_id, tag_ids=tag_ids
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def add_transaction_tag(transaction_id: str, tag_id: str) -> str:
    """Add a tag to a transaction, preserving any tags already on it.

    Args:
        transaction_id: The ID of the transaction
        tag_id: The tag ID to add
    """
    client = _get_client()
    details = await client.get_transaction_details(transaction_id)
    txn = details.get("getTransaction") or {}
    existing = [t.get("id") for t in (txn.get("tags") or []) if t.get("id")]
    if tag_id not in existing:
        existing.append(tag_id)
    result = await client.set_transaction_tags(
        transaction_id=transaction_id, tag_ids=existing
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def create_transaction_tag(name: str, color: str) -> str:
    """Create a new transaction tag.

    Args:
        name: Name of the new tag
        color: Hex color code for the tag (e.g. "#ff0000")
    """
    client = _get_client()
    result = await client.create_transaction_tag(name=name, color=color)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def categorize_transaction(transaction_id: str, category_id: str) -> str:
    """Assign a category to a transaction.

    Args:
        transaction_id: The ID of the transaction to categorize
        category_id: The category ID to assign
    """
    client = _get_client()
    result = await client.update_transaction(
        transaction_id=transaction_id, category_id=category_id
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def refresh_accounts() -> str:
    """Request account data refresh from financial institutions."""
    client = _get_client()
    result = await client.request_accounts_refresh()
    return json.dumps(result, indent=2, default=str)


def main() -> None:
    logger.info("Starting Monarch Money MCP Server")
    mcp.run()


app = mcp


if __name__ == "__main__":
    main()
