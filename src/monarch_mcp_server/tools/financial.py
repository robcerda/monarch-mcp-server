"""Financial analytics tools (cashflow, net worth)."""

import logging
from datetime import datetime as dt
from typing import Any, Dict, Optional

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

logger = logging.getLogger(__name__)


@mcp.tool()
async def get_cashflow(
    start_date: Optional[str] = None, end_date: Optional[str] = None
) -> str:
    """
    Get cashflow analysis from Monarch Money.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    try:
        client = await get_monarch_client()

        filters: Dict[str, Any] = {}
        if start_date:
            filters["start_date"] = start_date
        if end_date:
            filters["end_date"] = end_date

        cashflow = await client.get_cashflow(**filters)
        return json_success(cashflow)
    except Exception as e:
        return json_error("get_cashflow", e)


@mcp.tool()
async def get_net_worth(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_type: Optional[str] = None,
) -> str:
    """
    Get net worth history over time.

    Returns daily snapshots of total net worth, useful for tracking wealth trends.

    Args:
        start_date: Start date in YYYY-MM-DD format (defaults to account history start)
        end_date: End date in YYYY-MM-DD format (defaults to today)
        account_type: Filter by account type (e.g., "brokerage", "depository", "credit")

    Returns:
        Daily net worth snapshots with dates and values.

    Examples:
        Get net worth for the past year:
            get_net_worth(start_date="2024-01-01")

        Get only investment account net worth:
            get_net_worth(account_type="brokerage")
    """
    try:
        client = await get_monarch_client()

        params: Dict[str, Any] = {}
        if start_date:
            params["start_date"] = dt.strptime(start_date, "%Y-%m-%d").date()
        if end_date:
            params["end_date"] = dt.strptime(end_date, "%Y-%m-%d").date()
        if account_type:
            params["account_type"] = account_type

        result = await client.get_aggregate_snapshots(**params)

        snapshots = result.get("aggregateSnapshots", [])

        formatted: Dict[str, Any] = {
            "snapshot_count": len(snapshots),
            "snapshots": []
        }

        if snapshots:
            values = [s.get("balance", 0) for s in snapshots if s.get("balance") is not None]
            if values:
                formatted["current_net_worth"] = values[-1] if values else 0
                formatted["earliest_net_worth"] = values[0] if values else 0
                formatted["change"] = values[-1] - values[0] if len(values) > 1 else 0
                formatted["change_percent"] = (
                    ((values[-1] - values[0]) / values[0] * 100)
                    if values[0] != 0 and len(values) > 1 else 0
                )
                formatted["highest"] = max(values)
                formatted["lowest"] = min(values)

        for snapshot in snapshots[-365:]:
            formatted["snapshots"].append({
                "date": snapshot.get("date"),
                "net_worth": snapshot.get("balance"),
            })

        return json_success(formatted)
    except Exception as e:
        return json_error("get_net_worth", e)


@mcp.tool()
async def get_net_worth_by_account_type(
    start_date: str,
    timeframe: str = "month",
) -> str:
    """
    Get net worth breakdown by account type over time.

    Shows how net worth is distributed across different account types
    (checking, savings, investments, credit cards, etc.) with monthly or yearly granularity.

    Args:
        start_date: Start date in YYYY-MM-DD format
        timeframe: Granularity - "month" or "year" (default: "month")

    Returns:
        Net worth snapshots grouped by account type.

    Examples:
        Get monthly breakdown for the past year:
            get_net_worth_by_account_type(start_date="2024-01-01", timeframe="month")

        Get yearly breakdown:
            get_net_worth_by_account_type(start_date="2020-01-01", timeframe="year")
    """
    try:
        if timeframe not in ("month", "year"):
            return json_success({
                "success": False,
                "error": "timeframe must be 'month' or 'year'"
            })

        client = await get_monarch_client()
        result = await client.get_account_snapshots_by_type(
            start_date=start_date,
            timeframe=timeframe,
        )

        account_types = result.get("accountTypeSnapshots", [])

        formatted: Dict[str, Any] = {
            "timeframe": timeframe,
            "start_date": start_date,
            "account_types": []
        }

        for acct_type in account_types:
            type_info: Dict[str, Any] = {
                "type": acct_type.get("accountType"),
                "snapshots": []
            }

            for snapshot in acct_type.get("snapshots", []):
                type_info["snapshots"].append({
                    "month": snapshot.get("month"),
                    "balance": snapshot.get("balance"),
                })

            if type_info["snapshots"]:
                type_info["current_balance"] = type_info["snapshots"][-1].get("balance", 0)

            formatted["account_types"].append(type_info)

        total = sum(
            t.get("current_balance", 0)
            for t in formatted["account_types"]
            if t.get("current_balance") is not None
        )
        formatted["total_net_worth"] = total

        return json_success(formatted)
    except Exception as e:
        return json_error("get_net_worth_by_account_type", e)
