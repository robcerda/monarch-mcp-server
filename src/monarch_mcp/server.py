"""Monarch Money MCP Server - Main server implementation."""
# pylint: disable=too-many-lines

import argparse
import functools
import json
import logging
import os
import re
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from fastmcp import FastMCP
from gql import gql
from gql.transport.exceptions import TransportServerError, TransportQueryError, TransportError
from monarchmoney import MonarchMoney, LoginFailedException

from monarch_mcp.secure_session import secure_session, is_auth_error
from monarch_mcp.auth_server import trigger_auth_flow, _run_sync

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# ── Read-only mode (write tools disabled by default) ─────────────────
_arg_parser = argparse.ArgumentParser(
    description="Monarch Money MCP Server — read-only by default; "
                "pass --enable-write to expose write tools.",
)
_arg_parser.add_argument(
    "--enable-write",
    nargs="?",
    const="true",
    default="false",
    type=str,
    help="Enable write tools (create, update, delete). "
         "Accepts: --enable-write, --enable-write=true, --enable-write=false. "
         "Default: false (read-only mode).",
)
_PARSED_ARGS, _ = _arg_parser.parse_known_args()
_WRITE_ENABLED = _PARSED_ARGS.enable_write.lower() in ("true", "1")

# Initialize FastMCP server
mcp = FastMCP("Monarch Money MCP Server")


def run_async(coro):
    """Run async function in a new thread with its own event loop.

    If the coroutine raises an authentication error (expired token,
    invalid credentials), the stale token is cleared from the keyring,
    the browser-based auth flow is re-triggered, and a RuntimeError is
    raised so the calling tool can inform the user.

    Only catches the two exception types that ``is_auth_error`` can
    recognise; everything else propagates unchanged to the caller.
    """
    with ThreadPoolExecutor() as executor:
        future = executor.submit(_run_sync, coro)
        try:
            return future.result()
        except (TransportServerError, LoginFailedException) as exc:
            if is_auth_error(exc):
                logger.warning("Token appears expired — clearing and triggering re-auth")
                secure_session.delete_token()
                trigger_auth_flow()
                raise RuntimeError(
                    "Your session has expired. A login page has been opened in "
                    "your browser — please sign in and try again."
                ) from exc
            raise


# ── MCP tool error handling ────────────────────────────────────────────

def _handle_mcp_errors(operation: str):
    """Decorator providing granular exception handling for MCP tool functions.

    Catches specific known exception types with appropriate log messages,
    with a catch-all for anything unexpected.  Every path returns a
    user-readable error string so the MCP tool never crashes.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except RuntimeError as exc:
                logger.error("Runtime error %s: %s", operation, exc)
                return f"Error {operation}: {exc}"
            except TransportServerError as exc:
                code = getattr(exc, "code", "unknown")
                logger.error(
                    "Monarch API HTTP %s error %s: %s", code, operation, exc,
                )
                return f"Error {operation}: Monarch API returned HTTP {code}: {exc}"
            except TransportQueryError as exc:
                logger.error("Monarch API query error %s: %s", operation, exc)
                return f"Error {operation}: API query failed: {exc}"
            except TransportError as exc:
                logger.error(
                    "Monarch API connection error %s: %s", operation, exc,
                )
                return f"Error {operation}: connection error: {exc}"
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error(
                    "Unexpected error %s: %s (%s)",
                    operation, exc, type(exc).__name__,
                )
                return f"Error {operation}: {exc}"
        return wrapper
    return decorator


# ── Client helpers ─────────────────────────────────────────────────────

async def get_monarch_client() -> MonarchMoney:
    """Get or create MonarchMoney client instance using secure session storage."""
    # Try to get authenticated client from secure session
    client = secure_session.get_authenticated_client()

    if client is not None:
        logger.info("Using authenticated client from secure keyring storage")
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
            logger.error("Failed to login to Monarch Money: %s", e)
            raise

    # No credentials anywhere — open browser login and tell the user
    trigger_auth_flow()
    raise RuntimeError(
        "Authentication needed! A login page has been opened in your "
        "browser — please sign in and try again."
    )


# ── Tools ──────────────────────────────────────────────────────────────

@mcp.tool()
def setup_authentication() -> str:
    """Get instructions for setting up secure authentication with Monarch Money."""
    return """Monarch Money - Authentication

Authentication happens automatically in your browser:

1. When the MCP server starts without a saved session, a login page
   opens in your browser automatically

2. Enter your Monarch Money email and password

3. Provide your 2FA code if you have MFA enabled

4. Once authenticated, the token is saved to your system keyring

Then start using Monarch tools in Claude Desktop:
   - get_accounts - View all accounts
   - get_transactions - Recent transactions
   - get_budgets - Budget information

Session persists across Claude restarts (weeks/months).
Expired sessions are re-authenticated automatically.
Credentials are entered in your browser, never through Claude.

Alternative: run `python login_setup.py` in a terminal for
headless environments where a browser is not available."""


@mcp.tool()
def check_auth_status() -> str:
    """Check if already authenticated with Monarch Money."""
    try:
        # Check if we have a token in the keyring
        token = secure_session.load_token()
        if token:
            status = "Authentication token found in secure keyring storage\n"
        else:
            status = "No authentication token found in keyring\n"

        email = os.getenv("MONARCH_EMAIL")
        if email:
            status += f"Environment email: {email}\n"

        status += (
            "\nTry get_accounts to test connection or run login_setup.py if needed."
        )

        return status
    except Exception as e:  # pylint: disable=broad-exception-caught
        return f"Error checking auth status: {e}"


@mcp.tool()
def debug_session_loading() -> str:
    """Debug keyring session loading issues."""
    try:
        # Check keyring access
        token = secure_session.load_token()
        if token:
            return f"Token found in keyring (length: {len(token)})"
        return "No token found in keyring. Run login_setup.py to authenticate."
    except Exception as e:  # pylint: disable=broad-exception-caught
        error_details = traceback.format_exc()
        return (
            f"Keyring access failed:\nError: {e}\n"
            f"Type: {type(e)}\nTraceback:\n{error_details}"
        )


@mcp.tool()
@_handle_mcp_errors("getting accounts")
def get_accounts() -> str:
    """Get all financial accounts from Monarch Money."""

    async def _get_accounts():
        client = await get_monarch_client()
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


@mcp.tool()
@_handle_mcp_errors("getting transactions")
def get_transactions(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-branches
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_id: Optional[str] = None,
    search: Optional[str] = None,
    category_ids: Optional[List[str]] = None,
    account_ids: Optional[List[str]] = None,
    tag_ids: Optional[List[str]] = None,
    has_attachments: Optional[bool] = None,
    has_notes: Optional[bool] = None,
    hidden_from_reports: Optional[bool] = None,
    is_split: Optional[bool] = None,
    is_recurring: Optional[bool] = None,
    synced_from_institution: Optional[bool] = None,
    needs_review: Optional[bool] = None,
) -> str:
    """
    Get transactions from Monarch Money.

    Args:
        limit: Number of transactions to retrieve (default: 100)
        offset: Number of transactions to skip (default: 0)
        start_date: Start date in YYYY-MM-DD format (requires end_date)
        end_date: End date in YYYY-MM-DD format (requires start_date)
        account_id: Specific account ID to filter by (shorthand for account_ids with one ID)
        search: Free text search query
        category_ids: List of category IDs to filter by
        account_ids: List of account IDs to filter by (cannot use with account_id)
        tag_ids: List of tag IDs to filter by
        has_attachments: Filter transactions with/without attachments
        has_notes: Filter transactions with/without notes
        hidden_from_reports: Filter transactions hidden/visible in reports
        is_split: Filter split/unsplit transactions
        is_recurring: Filter recurring/non-recurring transactions
        synced_from_institution: Filter synced/manual transactions
        needs_review: Filter transactions that need review
    """
    if bool(start_date) != bool(end_date):
        return json.dumps(
            {"error": "Both start_date and end_date are required when filtering by date."},
            indent=2,
        )

    if account_id and account_ids:
        return json.dumps(
            {"error": "Cannot use both account_id and account_ids. Use one or the other."},
            indent=2,
        )

    async def _get_transactions():
        client = await get_monarch_client()

        filters = {}
        if start_date:
            filters["start_date"] = start_date
        if end_date:
            filters["end_date"] = end_date
        if account_id:
            filters["account_ids"] = [account_id]
        if account_ids:
            filters["account_ids"] = account_ids
        if search:
            filters["search"] = search
        if category_ids:
            filters["category_ids"] = category_ids
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
        if synced_from_institution is not None:
            filters["synced_from_institution"] = synced_from_institution

        if needs_review is not None:
            filters["needs_review"] = needs_review

        return await client.get_transactions(limit=limit, offset=offset, **filters)

    transactions = run_async(_get_transactions())

    # Format transactions for display
    transaction_list = []
    for txn in transactions.get("allTransactions", {}).get("results", []):
        transaction_info = {
            "id": txn.get("id"),
            "date": txn.get("date"),
            "amount": txn.get("amount"),
            "original_name": txn.get("plaidName"),
            "category": txn.get("category", {}).get("name")
            if txn.get("category")
            else None,
            "account": txn.get("account", {}).get("displayName"),
            "merchant": txn.get("merchant", {}).get("name")
            if txn.get("merchant")
            else None,
            "notes": txn.get("notes"),
            "is_pending": txn.get("pending", False),
            "is_recurring": txn.get("isRecurring", False),
            "tags": [
                {
                    "id": tag.get("id"),
                    "name": tag.get("name"),
                    "color": tag.get("color"),
                }
                for tag in txn.get("tags", [])
            ],
        }
        transaction_list.append(transaction_info)

    return json.dumps(transaction_list, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting budgets")
def get_budgets(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    use_v2_goals: bool = True,
) -> str:
    """
    Get budget information from Monarch Money.

    Args:
        start_date: Start date in YYYY-MM-DD format (default: last month)
        end_date: End date in YYYY-MM-DD format (default: next month)
        use_v2_goals: Whether to use v2 goals format (default: True)
    """
    if bool(start_date) != bool(end_date):
        return json.dumps(
            {"error": "Both start_date and end_date are required when filtering by date."},
            indent=2,
        )

    async def _get_budgets():
        client = await get_monarch_client()
        filters = {}
        if start_date is not None:
            filters["start_date"] = start_date
        if end_date is not None:
            filters["end_date"] = end_date
        return await client.get_budgets(use_v2_goals=use_v2_goals, **filters)

    budgets = run_async(_get_budgets())

    return json.dumps(budgets, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting cashflow")
def get_cashflow(
    start_date: Optional[str] = None, end_date: Optional[str] = None
) -> str:
    """
    Get cashflow analysis from Monarch Money.

    Args:
        start_date: Start date in YYYY-MM-DD format (requires end_date; defaults to current month)
        end_date: End date in YYYY-MM-DD format (requires start_date; defaults to current month)
    """
    if bool(start_date) != bool(end_date):
        return json.dumps(
            {"error": "Both start_date and end_date are required when filtering by date."},
            indent=2,
        )

    async def _get_cashflow():
        client = await get_monarch_client()

        filters = {}
        if start_date:
            filters["start_date"] = start_date
        if end_date:
            filters["end_date"] = end_date

        return await client.get_cashflow(**filters)

    cashflow = run_async(_get_cashflow())

    return json.dumps(cashflow, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting account holdings")
def get_account_holdings(account_id: str) -> str:
    """
    Get investment holdings for a specific account.

    Args:
        account_id: The ID of the investment account
    """

    async def _get_holdings():
        client = await get_monarch_client()
        return await client.get_account_holdings(account_id)

    holdings = run_async(_get_holdings())

    return json.dumps(holdings, indent=2, default=str)


@mcp.tool(enabled=_WRITE_ENABLED)
@_handle_mcp_errors("creating transaction")
def create_transaction(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    account_id: str,
    amount: float,
    merchant_name: str,
    category_id: str,
    date: str,
    notes: Optional[str] = None,
    update_balance: bool = False,
) -> str:
    """
    Create a new transaction in Monarch Money.

    Args:
        account_id: The account ID to add the transaction to
        amount: Transaction amount (positive for income, negative for expenses)
        merchant_name: Merchant name for the transaction
        category_id: Category ID for the transaction
        date: Transaction date in YYYY-MM-DD format
        notes: Optional transaction notes
        update_balance: Whether to update the account balance (default: False)
    """

    async def _create_transaction():
        client = await get_monarch_client()
        return await client.create_transaction(
            date=date,
            account_id=account_id,
            amount=amount,
            merchant_name=merchant_name,
            category_id=category_id,
            notes=notes or "",
            update_balance=update_balance,
        )

    result = run_async(_create_transaction())

    return json.dumps(result, indent=2, default=str)


@mcp.tool(enabled=_WRITE_ENABLED)
@_handle_mcp_errors("updating transaction")
def update_transaction(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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
        merchant_name: New merchant name
        goal_id: Goal ID to associate with the transaction
        amount: New transaction amount
        date: New transaction date in YYYY-MM-DD format
        hide_from_reports: Whether to hide the transaction from reports
        needs_review: Whether the transaction needs review
        notes: Transaction notes
    """

    async def _update_transaction():
        client = await get_monarch_client()

        update_data = {"transaction_id": transaction_id}

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


@mcp.tool(enabled=_WRITE_ENABLED)
@_handle_mcp_errors("deleting transaction")
def delete_transaction(transaction_id: str) -> str:
    """
    Delete a transaction from Monarch Money.

    Args:
        transaction_id: The ID of the transaction to delete
    """

    async def _delete_transaction():
        client = await get_monarch_client()
        return await client.delete_transaction(transaction_id)

    run_async(_delete_transaction())

    return json.dumps({"deleted": True, "transaction_id": transaction_id}, indent=2)


@mcp.tool()
@_handle_mcp_errors("refreshing accounts")
def refresh_accounts() -> str:
    """Request account data refresh from financial institutions."""

    async def _refresh_accounts():
        client = await get_monarch_client()
        accounts = await client.get_accounts()
        account_ids = [
            account["id"]
            for account in accounts.get("accounts", [])
            if account.get("id")
        ]
        if not account_ids:
            return {"error": "No accounts found to refresh."}
        return await client.request_accounts_refresh(account_ids)

    result = run_async(_refresh_accounts())

    return json.dumps(result, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting transaction tags")
def get_transaction_tags() -> str:
    """Get all transaction tags from Monarch Money."""

    async def _get_transaction_tags():
        client = await get_monarch_client()
        return await client.get_transaction_tags()

    tags = run_async(_get_transaction_tags())

    # Format tags for display
    tag_list = []
    for tag in tags.get("householdTransactionTags", []):
        tag_info = {
            "id": tag.get("id"),
            "name": tag.get("name"),
            "color": tag.get("color"),
            "order": tag.get("order"),
            "transactionCount": tag.get("transactionCount"),
        }
        tag_list.append(tag_info)

    return json.dumps(tag_list, indent=2, default=str)


@mcp.tool(enabled=_WRITE_ENABLED)
@_handle_mcp_errors("creating transaction tag")
def create_transaction_tag(name: str, color: str) -> str:
    """
    Create a new transaction tag in Monarch Money.

    Args:
        name: Tag name (required)
        color: Hex RGB color including # (required, e.g., "#19D2A5")
    """
    # Validate color format
    if not re.match(r"^#[0-9A-Fa-f]{6}$", color):
        return json.dumps(
            {
                "error": "Invalid color format. Use hex RGB with # (e.g., '#19D2A5')"
            },
            indent=2,
        )

    # Validate name
    if not name or not name.strip():
        return json.dumps({"error": "Tag name cannot be empty"}, indent=2)

    async def _create_transaction_tag():
        client = await get_monarch_client()
        return await client.create_transaction_tag(name, color)

    result = run_async(_create_transaction_tag())

    return json.dumps(result, indent=2, default=str)


@mcp.tool(enabled=_WRITE_ENABLED)
@_handle_mcp_errors("deleting transaction tag")
def delete_transaction_tag(tag_id: str) -> str:
    """
    Delete a transaction tag from Monarch Money.

    Args:
        tag_id: The ID of the tag to delete
    """

    async def _delete_transaction_tag():
        client = await get_monarch_client()
        mutation = gql(
            """
            mutation Common_DeleteTransactionTag($tagId: ID!) {
                deleteTransactionTag(tagId: $tagId) {
                    __typename
                }
            }
            """
        )
        variables = {"tagId": tag_id}
        return await client.gql_call(
            operation="Common_DeleteTransactionTag",
            graphql_query=mutation,
            variables=variables,
        )

    run_async(_delete_transaction_tag())

    return json.dumps({"deleted": True, "tag_id": tag_id}, indent=2)


@mcp.tool(enabled=_WRITE_ENABLED)
@_handle_mcp_errors("creating transaction rule")
def create_transaction_rule(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    set_category_id: str,
    merchant_name_value: Optional[str] = None,
    merchant_name_operator: str = "contains",
    original_statement_value: Optional[str] = None,
    original_statement_operator: str = "contains",
    account_ids: Optional[List[str]] = None,
    apply_to_existing_transactions: bool = False,
) -> str:
    """
    Create a Monarch Money transaction rule that automatically categorizes transactions.

    At least one of merchant_name_value or original_statement_value must be provided.

    Args:
        set_category_id: Category ID to assign when the rule matches (required)
        merchant_name_value: Merchant name to match (e.g. "Amazon", "Whole Foods")
        merchant_name_operator: How to match the merchant name — "contains" (default) or "eq"
        original_statement_value: Raw statement description to match
        original_statement_operator: How to match the statement text — "contains" (default) or "eq"
        account_ids: Restrict rule to specific account IDs (null = all accounts)
        apply_to_existing_transactions: Also re-categorize past transactions that match
    """
    if not merchant_name_value and not original_statement_value:
        return json.dumps(
            {"error": "At least one of merchant_name_value or "
                      "original_statement_value is required"},
            indent=2,
        )

    valid_operators = {"contains", "eq"}
    if merchant_name_operator not in valid_operators:
        return json.dumps(
            {"error": f"merchant_name_operator must be one of: {sorted(valid_operators)}"},
            indent=2,
        )
    if original_statement_operator not in valid_operators:
        return json.dumps(
            {"error": f"original_statement_operator must be one of: {sorted(valid_operators)}"},
            indent=2,
        )

    input_data: Dict[str, Any] = {
        "setCategoryAction": set_category_id,
        "applyToExistingTransactions": apply_to_existing_transactions,
    }

    if merchant_name_value:
        input_data["merchantNameCriteria"] = [
            {"operator": merchant_name_operator, "value": merchant_name_value}
        ]

    if original_statement_value:
        input_data["originalStatementCriteria"] = [
            {"operator": original_statement_operator, "value": original_statement_value}
        ]

    if account_ids:
        input_data["accountIds"] = account_ids

    async def _create_transaction_rule():
        client = await get_monarch_client()
        mutation = gql(
            """
            mutation Common_CreateTransactionRuleMutationV2($input: CreateTransactionRuleInput!) {
                createTransactionRuleV2(input: $input) {
                    errors {
                        message
                    }
                }
            }
            """
        )
        variables = {"input": input_data}
        return await client.gql_call(
            operation="Common_CreateTransactionRuleMutationV2",
            graphql_query=mutation,
            variables=variables,
        )

    result = run_async(_create_transaction_rule())

    # Surface any API-level errors from the mutation payload
    rule_result = result.get("createTransactionRuleV2", {}) if isinstance(result, dict) else {}
    errors = rule_result.get("errors") or []
    if errors:
        return json.dumps(
            {"error": errors[0].get("message", "Unknown error"), "errors": errors},
            indent=2,
        )

    return json.dumps({"created": True, "input": input_data}, indent=2)


@mcp.tool(enabled=_WRITE_ENABLED)
@_handle_mcp_errors("setting transaction tags")
def set_transaction_tags(transaction_id: str, tag_ids: List[str]) -> str:
    """
    Set tags on a transaction (replaces existing tags).

    Args:
        transaction_id: Transaction UUID (required)
        tag_ids: List of tag IDs to apply (required, empty list removes all tags)

    Note: This overwrites existing tags. To remove all tags, pass an empty list.
    """

    async def _set_transaction_tags():
        client = await get_monarch_client()
        return await client.set_transaction_tags(transaction_id, tag_ids)

    result = run_async(_set_transaction_tags())

    return json.dumps(result, indent=2, default=str)


# ── Phase 2: Read-only tools ──────────────────────────────────────────


@mcp.tool()
@_handle_mcp_errors("getting transaction categories")
def get_transaction_categories() -> str:
    """Get all transaction categories from Monarch Money."""

    async def _get_transaction_categories():
        client = await get_monarch_client()
        return await client.get_transaction_categories()

    categories = run_async(_get_transaction_categories())

    return json.dumps(categories, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting transaction category groups")
def get_transaction_category_groups() -> str:
    """Get all transaction category groups from Monarch Money."""

    async def _get_transaction_category_groups():
        client = await get_monarch_client()
        return await client.get_transaction_category_groups()

    groups = run_async(_get_transaction_category_groups())

    return json.dumps(groups, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting transaction details")
def get_transaction_details(
    transaction_id: str,
    redirect_posted: bool = True,
) -> str:
    """
    Get detailed information about a specific transaction.

    Args:
        transaction_id: The ID of the transaction
        redirect_posted: Whether to redirect to posted transaction (default: True)
    """

    async def _get_transaction_details():
        client = await get_monarch_client()
        return await client.get_transaction_details(
            transaction_id, redirect_posted=redirect_posted,
        )

    details = run_async(_get_transaction_details())

    return json.dumps(details, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting recurring transactions")
def get_recurring_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get recurring transactions from Monarch Money.

    Args:
        start_date: Start date in YYYY-MM-DD format (requires end_date)
        end_date: End date in YYYY-MM-DD format (requires start_date)
    """
    if bool(start_date) != bool(end_date):
        return json.dumps(
            {"error": "Both start_date and end_date are required when filtering by date."},
            indent=2,
        )

    async def _get_recurring_transactions():
        client = await get_monarch_client()
        filters = {}
        if start_date:
            filters["start_date"] = start_date
        if end_date:
            filters["end_date"] = end_date
        return await client.get_recurring_transactions(**filters)

    result = run_async(_get_recurring_transactions())

    return json.dumps(result, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting transactions summary")
def get_transactions_summary() -> str:
    """Get aggregate transaction summary (count, sum, avg, max, income, expenses)."""

    async def _get_transactions_summary():
        client = await get_monarch_client()
        return await client.get_transactions_summary()

    summary = run_async(_get_transactions_summary())

    return json.dumps(summary, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting subscription details")
def get_subscription_details() -> str:
    """Get Monarch Money subscription status and details."""

    async def _get_subscription_details():
        client = await get_monarch_client()
        return await client.get_subscription_details()

    details = run_async(_get_subscription_details())

    return json.dumps(details, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting institutions")
def get_institutions() -> str:
    """Get all connected financial institutions and their connection status."""

    async def _get_institutions():
        client = await get_monarch_client()
        return await client.get_institutions()

    institutions = run_async(_get_institutions())

    return json.dumps(institutions, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting cashflow summary")
def get_cashflow_summary(
    limit: int = 100,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get cashflow summary (income, expenses, savings, savings rate).

    Args:
        limit: Number of records to retrieve (default: 100)
        start_date: Start date in YYYY-MM-DD format (requires end_date)
        end_date: End date in YYYY-MM-DD format (requires start_date)
    """
    if bool(start_date) != bool(end_date):
        return json.dumps(
            {"error": "Both start_date and end_date are required when filtering by date."},
            indent=2,
        )

    async def _get_cashflow_summary():
        client = await get_monarch_client()
        filters = {}
        if start_date:
            filters["start_date"] = start_date
        if end_date:
            filters["end_date"] = end_date
        return await client.get_cashflow_summary(limit=limit, **filters)

    summary = run_async(_get_cashflow_summary())

    return json.dumps(summary, indent=2, default=str)


# ── Phase 3: Mutation tools ──────────────────────────────────────────


@mcp.tool(enabled=_WRITE_ENABLED)
@_handle_mcp_errors("setting budget amount")
def set_budget_amount(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    amount: float,
    category_id: Optional[str] = None,
    category_group_id: Optional[str] = None,
    timeframe: str = "month",
    start_date: Optional[str] = None,
    apply_to_future: bool = False,
) -> str:
    """
    Set or update a budget amount for a category or category group.

    Args:
        amount: The budget amount to set
        category_id: Category ID (mutually exclusive with category_group_id)
        category_group_id: Category group ID (mutually exclusive with category_id)
        timeframe: Budget timeframe - "month" or "week" (default: "month")
        start_date: Budget start date in YYYY-MM-DD format
        apply_to_future: Whether to apply this amount to future periods (default: False)
    """
    if (category_id is None) == (category_group_id is None):
        return json.dumps(
            {"error": "Provide exactly one of category_id or category_group_id."},
            indent=2,
        )

    async def _set_budget_amount():
        client = await get_monarch_client()
        kwargs = {
            "amount": amount,
            "timeframe": timeframe,
            "apply_to_future": apply_to_future,
        }
        if category_id is not None:
            kwargs["category_id"] = category_id
        if category_group_id is not None:
            kwargs["category_group_id"] = category_group_id
        if start_date is not None:
            kwargs["start_date"] = start_date
        return await client.set_budget_amount(**kwargs)

    result = run_async(_set_budget_amount())

    return json.dumps(result, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting transaction splits")
def get_transaction_splits(transaction_id: str) -> str:
    """
    Get split information for a transaction.

    Args:
        transaction_id: The ID of the transaction
    """

    async def _get_transaction_splits():
        client = await get_monarch_client()
        return await client.get_transaction_splits(transaction_id)

    splits = run_async(_get_transaction_splits())

    return json.dumps(splits, indent=2, default=str)


@mcp.tool(enabled=_WRITE_ENABLED)
@_handle_mcp_errors("updating transaction splits")
def update_transaction_splits(
    transaction_id: str,
    split_data: List[Dict[str, Any]],
) -> str:
    """
    Create, modify, or delete splits for a transaction.

    Args:
        transaction_id: The ID of the transaction to split
        split_data: List of split objects, each with keys: merchantName, amount, categoryId.
            Sum of split amounts must equal the original transaction amount.
            Pass an empty list to remove all splits.
    """

    async def _update_transaction_splits():
        client = await get_monarch_client()
        return await client.update_transaction_splits(transaction_id, split_data)

    result = run_async(_update_transaction_splits())

    return json.dumps(result, indent=2, default=str)


@mcp.tool(enabled=_WRITE_ENABLED)
@_handle_mcp_errors("creating transaction category")
def create_transaction_category(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    group_id: str,
    name: str,
    icon: str = "\u2753",
    rollover_enabled: bool = False,
    rollover_type: str = "monthly",
    rollover_start_month: Optional[str] = None,
) -> str:
    """
    Create a new transaction category in Monarch Money.

    Args:
        group_id: The category group ID this category belongs to
        name: The category name
        icon: Category icon (default: question mark emoji)
        rollover_enabled: Whether budget rollover is enabled (default: False)
        rollover_type: Rollover type - "monthly" (default: "monthly")
        rollover_start_month: Rollover start in YYYY-MM-DD (default: 1st of month)
    """

    async def _create_transaction_category():
        client = await get_monarch_client()
        kwargs = {
            "group_id": group_id,
            "transaction_category_name": name,
            "icon": icon,
            "rollover_enabled": rollover_enabled,
            "rollover_type": rollover_type,
        }
        if rollover_start_month is not None:
            kwargs["rollover_start_month"] = datetime.strptime(
                rollover_start_month, "%Y-%m-%d",
            )
        return await client.create_transaction_category(**kwargs)

    result = run_async(_create_transaction_category())

    return json.dumps(result, indent=2, default=str)


@mcp.tool(enabled=_WRITE_ENABLED)
@_handle_mcp_errors("deleting transaction category")
def delete_transaction_category(category_id: str) -> str:
    """
    Delete a transaction category from Monarch Money.

    Args:
        category_id: The ID of the category to delete
    """

    async def _delete_transaction_category():
        client = await get_monarch_client()
        return await client.delete_transaction_category(category_id)

    result = run_async(_delete_transaction_category())

    return json.dumps(
        {"deleted": True, "category_id": category_id, "result": result},
        indent=2,
        default=str,
    )


@mcp.tool(enabled=_WRITE_ENABLED)
@_handle_mcp_errors("creating manual account")
def create_manual_account(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    account_name: str,
    account_type: str,
    account_sub_type: str,
    is_in_net_worth: bool,
    account_balance: float = 0,
) -> str:
    """
    Create a new manual account in Monarch Money.

    Args:
        account_name: Name for the account
        account_type: Account type (use get_account_type_options to see valid types)
        account_sub_type: Account sub-type
        is_in_net_worth: Whether to include in net worth calculation
        account_balance: Starting balance (default: 0)
    """

    async def _create_manual_account():
        client = await get_monarch_client()
        return await client.create_manual_account(
            account_type=account_type,
            account_sub_type=account_sub_type,
            is_in_net_worth=is_in_net_worth,
            account_name=account_name,
            account_balance=account_balance,
        )

    result = run_async(_create_manual_account())

    return json.dumps(result, indent=2, default=str)


@mcp.tool(enabled=_WRITE_ENABLED)
@_handle_mcp_errors("updating account")
def update_account(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    account_id: str,
    account_name: Optional[str] = None,
    account_balance: Optional[float] = None,
    account_type: Optional[str] = None,
    account_sub_type: Optional[str] = None,
    include_in_net_worth: Optional[bool] = None,
    hide_from_summary_list: Optional[bool] = None,
    hide_transactions_from_reports: Optional[bool] = None,
) -> str:
    """
    Update an existing account in Monarch Money.

    Args:
        account_id: The ID of the account to update
        account_name: New account name
        account_balance: New account balance
        account_type: New account type
        account_sub_type: New account sub-type
        include_in_net_worth: Whether to include in net worth
        hide_from_summary_list: Whether to hide from summary list
        hide_transactions_from_reports: Whether to hide transactions from reports
    """

    async def _update_account():
        client = await get_monarch_client()
        update_data = {"account_id": account_id}
        if account_name is not None:
            update_data["account_name"] = account_name
        if account_balance is not None:
            update_data["account_balance"] = account_balance
        if account_type is not None:
            update_data["account_type"] = account_type
        if account_sub_type is not None:
            update_data["account_sub_type"] = account_sub_type
        if include_in_net_worth is not None:
            update_data["include_in_net_worth"] = include_in_net_worth
        if hide_from_summary_list is not None:
            update_data["hide_from_summary_list"] = hide_from_summary_list
        if hide_transactions_from_reports is not None:
            update_data["hide_transactions_from_reports"] = hide_transactions_from_reports
        return await client.update_account(**update_data)

    result = run_async(_update_account())

    return json.dumps(result, indent=2, default=str)


# ── Phase 4: Analytics & history tools ────────────────────────────────


@mcp.tool()
@_handle_mcp_errors("getting account history")
def get_account_history(account_id: str) -> str:
    """
    Get historical balance snapshots for an account.

    Args:
        account_id: The ID of the account
    """

    async def _get_account_history():
        client = await get_monarch_client()
        return await client.get_account_history(account_id)

    history = run_async(_get_account_history())

    return json.dumps(history, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting recent account balances")
def get_recent_account_balances(start_date: Optional[str] = None) -> str:
    """
    Get daily balance for all accounts from a start date.

    Args:
        start_date: Start date in YYYY-MM-DD format (optional)
    """

    async def _get_recent_account_balances():
        client = await get_monarch_client()
        kwargs = {}
        if start_date is not None:
            kwargs["start_date"] = start_date
        return await client.get_recent_account_balances(**kwargs)

    balances = run_async(_get_recent_account_balances())

    return json.dumps(balances, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting account snapshots by type")
def get_account_snapshots_by_type(start_date: str, timeframe: str) -> str:
    """
    Get net value snapshots grouped by account type.

    Args:
        start_date: Start date in YYYY-MM-DD format
        timeframe: Aggregation period - "month" or "year"
    """
    if timeframe not in ("month", "year"):
        return json.dumps(
            {"error": "timeframe must be 'month' or 'year'."},
            indent=2,
        )

    async def _get_account_snapshots_by_type():
        client = await get_monarch_client()
        return await client.get_account_snapshots_by_type(start_date, timeframe)

    snapshots = run_async(_get_account_snapshots_by_type())

    return json.dumps(snapshots, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting aggregate snapshots")
def get_aggregate_snapshots(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_type: Optional[str] = None,
) -> str:
    """
    Get daily aggregate net value of all accounts.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        account_type: Filter by account type (optional)
    """

    async def _get_aggregate_snapshots():
        client = await get_monarch_client()
        kwargs = {}
        if start_date is not None:
            kwargs["start_date"] = start_date
        if end_date is not None:
            kwargs["end_date"] = end_date
        if account_type is not None:
            kwargs["account_type"] = account_type
        return await client.get_aggregate_snapshots(**kwargs)

    snapshots = run_async(_get_aggregate_snapshots())

    return json.dumps(snapshots, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting account type options")
def get_account_type_options() -> str:
    """Get available account types and sub-types for creating manual accounts."""

    async def _get_account_type_options():
        client = await get_monarch_client()
        return await client.get_account_type_options()

    options = run_async(_get_account_type_options())

    return json.dumps(options, indent=2, default=str)


@mcp.tool()
@_handle_mcp_errors("getting credit history")
def get_credit_history() -> str:
    """Get credit score history and related details."""

    async def _get_credit_history():
        client = await get_monarch_client()
        return await client.get_credit_history()

    history = run_async(_get_credit_history())

    return json.dumps(history, indent=2, default=str)


@mcp.tool(enabled=_WRITE_ENABLED)
@_handle_mcp_errors("deleting account")
def delete_account(account_id: str) -> str:
    """
    Delete an account from Monarch Money. This action is irreversible.

    Args:
        account_id: The ID of the account to delete
    """

    async def _delete_account():
        client = await get_monarch_client()
        return await client.delete_account(account_id)

    result = run_async(_delete_account())

    return json.dumps(
        {"deleted": True, "account_id": account_id, "result": result},
        indent=2,
        default=str,
    )


def main():
    """Main entry point for the server."""
    mode = "read-write" if _WRITE_ENABLED else "read-only"
    logger.info("Starting Monarch Money MCP Server (%s mode)...", mode)

    # Auto-trigger browser authentication if no credentials are available
    trigger_auth_flow()

    try:
        mcp.run()
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to run server: %s", e)
        raise


# Export for mcp run
app = mcp

if __name__ == "__main__":
    main()
