"""Monarch Money MCP Server - Main server implementation."""

import asyncio
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Coroutine, Optional, TypeVar

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from monarchmoney import MonarchMoney, RequireMFAException
from monarchmoney.monarchmoney import MonarchMoneyEndpoints
from pydantic import BaseModel, Field

from monarch_mcp_server.secure_session import secure_session

# Fix for Monarch Money API domain change (api.monarchmoney.com -> api.monarch.com)
# See: https://github.com/hammem/monarchmoney/issues/184
MonarchMoneyEndpoints.BASE_URL = "https://api.monarch.com"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize FastMCP server
mcp = FastMCP("Monarch Money MCP Server")

# Constants
API_TIMEOUT_SECONDS = 30
MAX_LIMIT = 1000
MIN_LIMIT = 1
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_DESCRIPTION_LENGTH = 500

T = TypeVar("T")


class ValidationError(ValueError):
    """Raised when input validation fails."""

    pass


def _sanitize_error(operation: str, error: Exception) -> str:
    """Return a user-safe error message without exposing internal details."""
    if isinstance(error, RuntimeError) and "Authentication needed" in str(error):
        return str(error)
    if isinstance(error, ValidationError):
        return f"Validation error: {error}"
    if isinstance(error, FuturesTimeoutError):
        return f"Error {operation}: Request timed out. Please try again."
    return f"Error {operation}: An unexpected error occurred. Check logs for details."


def _validate_limit(limit: int) -> int:
    """Validate and constrain the limit parameter."""
    if limit < MIN_LIMIT:
        raise ValidationError(f"limit must be at least {MIN_LIMIT}")
    if limit > MAX_LIMIT:
        raise ValidationError(f"limit cannot exceed {MAX_LIMIT}")
    return limit


def _validate_offset(offset: int) -> int:
    """Validate the offset parameter."""
    if offset < 0:
        raise ValidationError("offset must be non-negative")
    return offset


def _validate_date(date_str: Optional[str], field_name: str) -> Optional[str]:
    """Validate date format (YYYY-MM-DD)."""
    if date_str is None:
        return None
    if not DATE_PATTERN.match(date_str):
        raise ValidationError(f"{field_name} must be in YYYY-MM-DD format")
    return date_str


def _validate_description(description: str) -> str:
    """Validate description length."""
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValidationError(
            f"description cannot exceed {MAX_DESCRIPTION_LENGTH} characters"
        )
    return description


def run_async(coro: Coroutine[Any, Any, T], timeout: int = API_TIMEOUT_SECONDS) -> T:
    """Run async function in a new thread with its own event loop.

    Args:
        coro: The coroutine to execute.
        timeout: Maximum seconds to wait for completion (default: API_TIMEOUT_SECONDS).

    Returns:
        The result of the coroutine.

    Raises:
        FuturesTimeoutError: If the operation exceeds the timeout.
    """

    def _run() -> T:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    with ThreadPoolExecutor() as executor:
        future = executor.submit(_run)
        return future.result(timeout=timeout)


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
    # WARNING: Environment variables can leak through process listings (ps aux)
    # Prefer using login_setup.py for secure keyring-based authentication
    email = os.getenv("MONARCH_EMAIL")
    password = os.getenv("MONARCH_PASSWORD")

    if email and password:
        logger.warning(
            "⚠️  Using environment variable credentials. This is less secure than "
            "keyring storage as credentials may be visible in process listings. "
            "Consider running login_setup.py instead."
        )
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
        logger.error(f"Failed to check auth status: {e}", exc_info=True)
        return _sanitize_error("checking auth status", e)


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
        # Log full details for debugging, but don't expose to user
        logger.error(f"Keyring access failed: {e}", exc_info=True)
        return "❌ Keyring access failed. Check logs for details or run login_setup.py to re-authenticate."


@mcp.tool()
def get_accounts() -> str:
    """Get all financial accounts from Monarch Money."""
    try:

        async def _get_accounts() -> dict[str, Any]:
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
                "is_active": (
                    account.get("isActive")
                    if "isActive" in account
                    else not account.get("deactivatedAt")
                ),
            }
            account_list.append(account_info)

        return json.dumps(account_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get accounts: {e}", exc_info=True)
        return _sanitize_error("getting accounts", e)


@mcp.tool()
def get_transactions(
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_id: Optional[str] = None,
) -> str:
    """
    Get transactions from Monarch Money.

    Args:
        limit: Number of transactions to retrieve (1-1000, default: 100)
        offset: Number of transactions to skip (default: 0)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        account_id: Specific account ID to filter by
    """
    try:
        # Validate inputs
        validated_limit = _validate_limit(limit)
        validated_offset = _validate_offset(offset)
        validated_start = _validate_date(start_date, "start_date")
        validated_end = _validate_date(end_date, "end_date")

        async def _get_transactions() -> dict[str, Any]:
            client = await get_monarch_client()

            # Build filters
            filters: dict[str, Any] = {}
            if validated_start:
                filters["start_date"] = validated_start
            if validated_end:
                filters["end_date"] = validated_end
            if account_id:
                filters["account_id"] = account_id

            return await client.get_transactions(
                limit=validated_limit, offset=validated_offset, **filters
            )

        transactions = run_async(_get_transactions())

        # Format transactions for display
        transaction_list = []
        for txn in transactions.get("allTransactions", {}).get("results", []):
            transaction_info = {
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
            transaction_list.append(transaction_info)

        return json.dumps(transaction_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transactions: {e}", exc_info=True)
        return _sanitize_error("getting transactions", e)


@mcp.tool()
def get_budgets() -> str:
    """Get budget information from Monarch Money."""
    try:

        async def _get_budgets() -> dict[str, Any]:
            client = await get_monarch_client()
            return await client.get_budgets()

        budgets = run_async(_get_budgets())

        # Format budgets for display
        budget_list = []
        for budget in budgets.get("budgets", []):
            budget_info = {
                "id": budget.get("id"),
                "name": budget.get("name"),
                "amount": budget.get("amount"),
                "spent": budget.get("spent"),
                "remaining": budget.get("remaining"),
                "category": budget.get("category", {}).get("name"),
                "period": budget.get("period"),
            }
            budget_list.append(budget_info)

        return json.dumps(budget_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get budgets: {e}", exc_info=True)
        return _sanitize_error("getting budgets", e)


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
        # Validate inputs
        validated_start = _validate_date(start_date, "start_date")
        validated_end = _validate_date(end_date, "end_date")

        async def _get_cashflow() -> dict[str, Any]:
            client = await get_monarch_client()

            filters: dict[str, Any] = {}
            if validated_start:
                filters["start_date"] = validated_start
            if validated_end:
                filters["end_date"] = validated_end

            return await client.get_cashflow(**filters)

        cashflow = run_async(_get_cashflow())

        return json.dumps(cashflow, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get cashflow: {e}", exc_info=True)
        return _sanitize_error("getting cashflow", e)


@mcp.tool()
def get_account_holdings(account_id: str) -> str:
    """
    Get investment holdings for a specific account.

    Args:
        account_id: The ID of the investment account
    """
    try:

        async def _get_holdings() -> dict[str, Any]:
            client = await get_monarch_client()
            return await client.get_account_holdings(account_id)

        holdings = run_async(_get_holdings())

        return json.dumps(holdings, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get account holdings: {e}", exc_info=True)
        return _sanitize_error("getting account holdings", e)


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
        description: Transaction description (max 500 characters)
        date: Transaction date in YYYY-MM-DD format
        category_id: Optional category ID
        merchant_name: Optional merchant name
    """
    try:
        # Validate inputs
        validated_date = _validate_date(date, "date")
        if validated_date is None:
            raise ValidationError("date is required")
        validated_description = _validate_description(description)

        async def _create_transaction() -> dict[str, Any]:
            client = await get_monarch_client()

            transaction_data: dict[str, Any] = {
                "account_id": account_id,
                "amount": amount,
                "description": validated_description,
                "date": validated_date,
            }

            if category_id:
                transaction_data["category_id"] = category_id
            if merchant_name:
                transaction_data["merchant_name"] = merchant_name

            return await client.create_transaction(**transaction_data)

        result = run_async(_create_transaction())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create transaction: {e}", exc_info=True)
        return _sanitize_error("creating transaction", e)


@mcp.tool()
def update_transaction(
    transaction_id: str,
    amount: Optional[float] = None,
    description: Optional[str] = None,
    category_id: Optional[str] = None,
    date: Optional[str] = None,
) -> str:
    """
    Update an existing transaction in Monarch Money.

    Args:
        transaction_id: The ID of the transaction to update
        amount: New transaction amount
        description: New transaction description (max 500 characters)
        category_id: New category ID
        date: New transaction date in YYYY-MM-DD format
    """
    try:
        # Validate inputs
        validated_date = _validate_date(date, "date")
        validated_description = (
            _validate_description(description) if description is not None else None
        )

        async def _update_transaction() -> dict[str, Any]:
            client = await get_monarch_client()

            update_data: dict[str, Any] = {"transaction_id": transaction_id}

            if amount is not None:
                update_data["amount"] = amount
            if validated_description is not None:
                update_data["description"] = validated_description
            if category_id is not None:
                update_data["category_id"] = category_id
            if validated_date is not None:
                update_data["date"] = validated_date

            return await client.update_transaction(**update_data)

        result = run_async(_update_transaction())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to update transaction: {e}", exc_info=True)
        return _sanitize_error("updating transaction", e)


@mcp.tool()
def refresh_accounts() -> str:
    """Request account data refresh from financial institutions."""
    try:

        async def _refresh_accounts() -> dict[str, Any]:
            client = await get_monarch_client()
            return await client.request_accounts_refresh()

        result = run_async(_refresh_accounts())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to refresh accounts: {e}", exc_info=True)
        return _sanitize_error("refreshing accounts", e)


def main():
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
