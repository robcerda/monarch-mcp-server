"""Account management tools."""

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import RootModel, ValidationError

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import (
    json_error,
    json_rejected,
    json_success,
    payload_errors,
)

logger = logging.getLogger(__name__)


class BalanceCorrections(RootModel[Dict[date, Decimal]]):
    """Validates the corrections payload for upload_account_balance_history.

    Keys must be ISO dates (YYYY-MM-DD) and values must parse as decimals.
    Pydantic raises on bad input rather than letting typos silently no-op.
    """


def _sync_status(account: dict) -> dict:
    """Summarise an account's institution-connection state.

    When a bank link breaks, the account keeps its last balance and stops
    importing; the API does not raise an error for it. The GetAccounts query
    already returns the credential metadata that reveals this, so surface it
    in the listing rather than requiring a second call. For a per-connection
    view with staleness thresholds, see ``get_account_sync_health``.

    ``connection_status`` is the raw institution status the provider reports
    (e.g. ``RELINK``/``DEGRADED``/``HEALTHY``); the other keys are derived flags.
    """
    credential = account.get("credential") or {}
    needs_reauth = bool(credential.get("updateRequired"))
    disconnected_at = credential.get("disconnectedFromDataProviderAt")
    # Raw institution connection status (e.g. "RELINK", "DEGRADED", "HEALTHY").
    # The GetAccounts query already returns credential.institution.status; it is
    # the provider-reported reason behind a broken link, so surface it alongside
    # the derived flags rather than only inferring state from updateRequired.
    connection_status = (credential.get("institution") or {}).get("status")
    sync_disabled = bool(account.get("syncDisabled"))
    if account.get("isManual"):
        state = "manual"
    elif needs_reauth:
        state = "needs_reauth"
    elif disconnected_at:
        state = "disconnected"
    elif sync_disabled:
        state = "sync_disabled"
    else:
        state = "ok"
    return {
        "state": state,
        "needs_reauth": needs_reauth,
        "connection_status": connection_status,
        "disconnected_at": disconnected_at,
        "sync_disabled": sync_disabled,
        "data_provider": credential.get("dataProvider") or account.get("dataProvider"),
    }


@mcp.tool()
async def get_accounts() -> str:
    """Get all financial accounts from Monarch Money.

    Each account includes ``last_updated_at`` (Monarch's last successful sync
    for the account) and a ``sync`` block whose ``state`` is one of ``ok``,
    ``needs_reauth``, ``disconnected``, ``sync_disabled`` or ``manual``. A
    broken link does not error: balances freeze and transactions stop
    arriving, so check ``sync.state`` before trusting a stale-looking account.
    ``get_account_sync_health`` gives the same information per institution
    connection, with staleness thresholds.
    """
    try:
        client = await get_monarch_client()
        accounts = await client.get_accounts()

        account_list = []
        for account in accounts.get("accounts", []):
            account_info = {
                "id": account.get("id"),
                "name": account.get("displayName") or account.get("name"),
                "owned_by_user": (account.get("ownedByUser") or {}).get("displayName"), # Institution owner, not the Monarch Account Owner.
                "type": (account.get("type") or {}).get("name"),
                "balance": account.get("currentBalance"),
                "current_balance": account.get("currentBalance"),
                "display_balance": account.get("displayBalance"),
                "institution": (account.get("institution") or {}).get("name"),
                "is_active": account.get("isActive")
                if "isActive" in account
                else not account.get("deactivatedAt"),
                "is_hidden": account.get("isHidden", False),
                "is_manual": account.get("isManual", False),
                "last_updated_at": account.get("displayLastUpdatedAt"),
                "sync": _sync_status(account),
            }
            account_list.append(account_info)

        return json_success(account_list)
    except Exception as e:
        return json_error("get_accounts", e)



@mcp.tool()
async def update_account(
    account_id: str,
    name: Optional[str] = None,
    balance: Optional[float] = None,
    account_type: Optional[str] = None,
    account_sub_type: Optional[str] = None,
    include_in_net_worth: Optional[bool] = None,
    hide_from_summary_list: Optional[bool] = None,
    hide_transactions_from_reports: Optional[bool] = None,
    dry_run: bool = False,
) -> str:
    """Update an account's name, balance, type or visibility settings.

    Fills a gap that otherwise forces a trip to the Monarch UI: renaming a
    generically named account, excluding a custodial account from net worth,
    or correcting the balance of an account whose institution reports nothing.

    Only the fields you pass are changed; omitted fields are left alone.

    Args:
        account_id: The account to update (see get_accounts).
        name: New display name. Aggregators often supply useless names like
            "CREDIT CARD (...1234)"; a name carrying issuer, product and last
            four survives re-syncs and is legible in a report months later.
        balance: Set the current balance. Intended for manual accounts and for
            synced accounts whose institution does not report a balance --
            a loan showing 0.00 while a real balance is owed, for example.
            A synced account that later starts reporting will overwrite this.
        account_type: Account group type, e.g. "loan", "other_asset",
            "other_liability".
        account_sub_type: Sub type, e.g. "mortgage", "line_of_credit", "auto".
        include_in_net_worth: Whether the balance counts toward net worth. Set
            False for accounts you hold but do not own -- custodial UTMA/UGMA
            accounts are the child's property, so counting them overstates the
            custodian's position.
        hide_from_summary_list: Hide the account from the Accounts view. Note
            this hides the balance from you as well; prefer
            include_in_net_worth=False when the goal is only to stop it
            counting.
        hide_transactions_from_reports: Exclude the account's transactions from
            budgets and reports, without touching net worth.
        dry_run: If True, report the current and proposed values without
            writing anything.

    Returns:
        The updated account, or the planned change when dry_run is True.
    """
    fields = {
        "account_name": name,
        "account_balance": balance,
        "account_type": account_type,
        "account_sub_type": account_sub_type,
        "include_in_net_worth": include_in_net_worth,
        "hide_from_summary_list": hide_from_summary_list,
        "hide_transactions_from_reports": hide_transactions_from_reports,
    }
    changes = {k: v for k, v in fields.items() if v is not None}
    if not changes:
        return json_error(
            "update_account",
            ValueError(
                "No fields to update. Pass at least one of: name, balance, "
                "account_type, account_sub_type, include_in_net_worth, "
                "hide_from_summary_list, hide_transactions_from_reports."
            ),
        )

    try:
        client = await get_monarch_client()

        if dry_run:
            accounts = await client.get_accounts()
            current = next(
                (
                    a
                    for a in accounts.get("accounts", [])
                    if str(a.get("id")) == str(account_id)
                ),
                None,
            )
            if current is None:
                return json_error(
                    "update_account", ValueError(f"Account {account_id} not found")
                )
            return json_success(
                {
                    "dry_run": True,
                    "account_id": account_id,
                    "current": {
                        "name": current.get("displayName"),
                        "balance": current.get("currentBalance"),
                        "include_in_net_worth": current.get("includeInNetWorth"),
                        "hide_from_summary_list": current.get("hideFromList"),
                        "hide_transactions_from_reports": current.get(
                            "hideTransactionsFromReports"
                        ),
                    },
                    "proposed": changes,
                }
            )

        result = await client.update_account(account_id=account_id, **changes)
        errors = payload_errors(result, "updateAccount")
        if errors:
            return json_rejected("update_account", errors)

        payload = (result or {}).get("updateAccount") or {}
        account = payload.get("account") or {}
        return json_success(
            {
                "updated": True,
                "account_id": account_id,
                "applied": changes,
                "account": {
                    "name": account.get("displayName"),
                    "balance": account.get("currentBalance"),
                    "include_in_net_worth": account.get("includeInNetWorth"),
                    "hide_from_summary_list": account.get("hideFromList"),
                    "hide_transactions_from_reports": account.get(
                        "hideTransactionsFromReports"
                    ),
                },
            }
        )
    except Exception as e:
        return json_error("update_account", e)


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
