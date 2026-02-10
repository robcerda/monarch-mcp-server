"""Account management tools."""

import logging
from typing import Optional

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

logger = logging.getLogger(__name__)


@mcp.tool()
async def get_accounts() -> str:
    """Get all financial accounts from Monarch Money."""
    try:
        client = await get_monarch_client()
        accounts = await client.get_accounts()

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

        return json_success(account_list)
    except Exception as e:
        return json_error("get_accounts", e)


@mcp.tool()
async def refresh_accounts() -> str:
    """Request account data refresh from financial institutions."""
    try:
        client = await get_monarch_client()
        result = await client.request_accounts_refresh()
        return json_success(result)
    except Exception as e:
        return json_error("refresh_accounts", e)


@mcp.tool()
async def get_account_holdings(account_id: str) -> str:
    """
    Get investment holdings for a specific account.

    Args:
        account_id: The ID of the investment account
    """
    try:
        client = await get_monarch_client()
        holdings = await client.get_account_holdings(account_id)
        return json_success(holdings)
    except Exception as e:
        return json_error("get_account_holdings", e)


@mcp.tool()
async def get_account_balance_history(account_id: str) -> str:
    """
    Get historical balance data for a specific account.

    Returns all historical balance snapshots for tracking account growth over time.

    Args:
        account_id: The ID of the account (use get_accounts to find IDs)

    Returns:
        Historical balance snapshots for the account.

    Examples:
        Track savings account growth:
            get_account_balance_history(account_id="acc_123")
    """
    try:
        client = await get_monarch_client()
        result = await client.get_account_history(account_id=int(account_id))

        snapshots = result.get("accountSnapshotHistory", {}).get("snapshots", [])

        formatted = {
            "account_id": account_id,
            "snapshot_count": len(snapshots),
            "snapshots": []
        }

        if snapshots:
            balances = [s.get("signedBalance", 0) for s in snapshots if s.get("signedBalance") is not None]
            if balances:
                formatted["current_balance"] = balances[-1] if balances else 0
                formatted["earliest_balance"] = balances[0] if balances else 0
                formatted["change"] = balances[-1] - balances[0] if len(balances) > 1 else 0
                formatted["highest"] = max(balances)
                formatted["lowest"] = min(balances)

        for snapshot in snapshots:
            formatted["snapshots"].append({
                "date": snapshot.get("date"),
                "balance": snapshot.get("signedBalance"),
            })

        return json_success(formatted)
    except Exception as e:
        return json_error("get_account_balance_history", e)
