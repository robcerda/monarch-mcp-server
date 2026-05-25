"""Account management tools."""

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import RootModel, ValidationError

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

logger = logging.getLogger(__name__)


class BalanceCorrections(RootModel[Dict[date, Decimal]]):
    """Validates the corrections payload for upload_account_balance_history.

    Keys must be ISO dates (YYYY-MM-DD) and values must parse as decimals.
    Pydantic raises on bad input rather than letting typos silently no-op.
    """


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
                "is_hidden": account.get("isHidden", False),
            }
            account_list.append(account_info)

        return json_success(account_list)
    except Exception as e:
        return json_error("get_accounts", e)


@mcp.tool()
async def refresh_accounts(account_ids: Optional[List[str]] = None) -> str:
    """Request account data refresh from financial institutions.

    Args:
        account_ids: Specific account IDs to refresh. If omitted or empty,
            refreshes all active, non-hidden accounts.
    """
    try:
        client = await get_monarch_client()
        if not account_ids:
            accounts = await client.get_accounts()
            account_ids = [
                a["id"]
                for a in accounts.get("accounts", [])
                if (
                    a.get("isActive", not a.get("deactivatedAt"))
                    and not a.get("isHidden")
                )
            ]
        if not account_ids:
            return json_success(
                {"refreshed": [], "message": "No active, visible accounts to refresh"}
            )
        result = await client.request_accounts_refresh(account_ids)
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
        snapshots = await client.get_account_history(account_id=int(account_id))

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


@mcp.tool()
async def upload_account_balance_history(
    account_id: str,
    corrections: str,
    dry_run: bool = False,
) -> str:
    """
    Upload corrected balance snapshots for an account.

    Fetches the full existing balance history, applies the corrections,
    and re-uploads the complete history.

    Args:
        account_id: The ID of the account to correct
        corrections: JSON object mapping ISO dates (YYYY-MM-DD) to corrected
                     balances, e.g. '{"2026-04-23": 24846.45, "2026-04-24": 24846.45}'
        dry_run: If True, return the planned changes without uploading

    Mismatched dates (corrections that do not match any existing snapshot) are
    surfaced explicitly in the response rather than silently dropped.
    """
    try:
        try:
            raw = json.loads(corrections)
        except json.JSONDecodeError as exc:
            return json_error(
                "upload_account_balance_history",
                ValueError(f"corrections is not valid JSON: {exc.msg}"),
            )

        if not isinstance(raw, dict):
            return json_error(
                "upload_account_balance_history",
                ValueError("corrections must be a JSON object mapping dates to numbers"),
            )

        try:
            validated = BalanceCorrections.model_validate(raw)
        except ValidationError as exc:
            return json_error("upload_account_balance_history", exc)

        date_to_balance: Dict[str, Decimal] = {
            d.isoformat(): amount for d, amount in validated.root.items()
        }

        if not date_to_balance:
            return json_success({
                "updated": False,
                "message": "No corrections provided",
            })

        from monarchmoney.monarchmoney import BalanceHistoryRow

        client = await get_monarch_client()
        snapshots = await client.get_account_history(account_id=int(account_id))

        existing_dates = {s.get("date") for s in snapshots}
        unmatched = sorted(d for d in date_to_balance if d not in existing_dates)

        applied: list[str] = []
        rows: list[BalanceHistoryRow] = []
        for snapshot in snapshots:
            date_str = snapshot.get("date")
            balance = snapshot.get("signedBalance", 0)
            account_name = snapshot.get("accountName", "")

            if date_str in date_to_balance:
                balance = float(date_to_balance[date_str])
                applied.append(date_str)

            rows.append(BalanceHistoryRow(
                date=datetime.strptime(date_str, "%Y-%m-%d"),
                amount=balance,
                account_name=account_name,
            ))

        if not applied:
            return json_success({
                "updated": False,
                "message": "No matching dates found in history",
                "unmatched_dates": unmatched,
            })

        if dry_run:
            return json_success({
                "dry_run": True,
                "account_id": account_id,
                "dates_to_correct": applied,
                "unmatched_dates": unmatched,
                "total_snapshots": len(rows),
            })

        result = await client.upload_account_balance_history(
            account_id=account_id,
            csv_content=rows,
        )

        return json_success({
            "updated": result,
            "dates_corrected": applied,
            "unmatched_dates": unmatched,
            "total_snapshots": len(rows),
        })
    except Exception as e:
        return json_error("upload_account_balance_history", e)
