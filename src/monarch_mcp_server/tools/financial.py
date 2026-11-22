"""Financial analytics tools (cashflow, net worth)."""

import logging
from datetime import datetime as dt
from typing import Any, Dict, List, Optional

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import (
    breakdown,
    json_error,
    json_success,
    render_within_budget,
    strip_typenames,
)

logger = logging.getLogger(__name__)

_CASHFLOW_AGGREGATE_KEYS = ("byCategory", "byCategoryGroup", "byMerchant", "summary")


@mcp.tool()
async def get_cashflow(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """
    Get cashflow analysis from Monarch Money.

    Returns overall income, expenses, savings and savings rate for the period,
    plus breakdowns by category, category group, and merchant, each ranked by
    absolute cash flow.

    Every row is returned when the response fits. Only if it would overflow the
    MCP response limit are the smallest rows trimmed, and each breakdown reports
    its true total so nothing is dropped silently.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        limit: Optional hard cap on rows per breakdown. Leave unset to return
               everything that fits. Use 0 to disable trimming entirely — a wide
               date range can then exceed the response limit.
    """
    try:
        client = await get_monarch_client()

        filters: Dict[str, Any] = {}
        if start_date:
            filters["start_date"] = start_date
        if end_date:
            filters["end_date"] = end_date

        cashflow = await client.get_cashflow(**filters)

        # Be forgiving if upstream ever changes shape: pass the payload through
        # rather than silently reporting an empty cashflow.
        if not any(key in cashflow for key in _CASHFLOW_AGGREGATE_KEYS):
            return json_success(strip_typenames(cashflow))

        by_category: List[Dict[str, Any]] = []
        for item in cashflow.get("byCategory", []):
            cat = item.get("groupBy", {}).get("category") or {}
            group = cat.get("group") or {}
            by_category.append(
                {
                    "category": cat.get("name"),
                    "category_id": cat.get("id"),
                    "icon": cat.get("icon"),
                    "group_id": group.get("id"),
                    "group_type": group.get("type"),
                    "sum": item.get("summary", {}).get("sum", 0),
                }
            )
        by_category.sort(key=lambda x: abs(x.get("sum") or 0), reverse=True)

        by_category_group: List[Dict[str, Any]] = []
        for item in cashflow.get("byCategoryGroup", []):
            grp = item.get("groupBy", {}).get("categoryGroup") or {}
            by_category_group.append(
                {
                    "group": grp.get("name"),
                    "group_id": grp.get("id"),
                    "group_type": grp.get("type"),
                    "sum": item.get("summary", {}).get("sum", 0),
                }
            )
        by_category_group.sort(key=lambda x: abs(x.get("sum") or 0), reverse=True)

        by_merchant: List[Dict[str, Any]] = []
        for item in cashflow.get("byMerchant", []):
            merch = item.get("groupBy", {}).get("merchant") or {}
            summary = item.get("summary", {})
            by_merchant.append(
                {
                    "merchant": merch.get("name"),
                    "merchant_id": merch.get("id"),
                    "income": summary.get("sumIncome", 0),
                    "expense": summary.get("sumExpense", 0),
                }
            )
        # Rank on total flow, not expense alone: a payroll or transfer merchant
        # can be the largest line in the period and must survive the cap.
        by_merchant.sort(
            key=lambda x: abs(x.get("income") or 0) + abs(x.get("expense") or 0),
            reverse=True,
        )

        overall: Dict[str, Any] = {}
        summary_items = cashflow.get("summary", [])
        if summary_items:
            s = summary_items[0].get("summary", {})
            overall = {
                "total_income": s.get("sumIncome", 0),
                "total_expenses": s.get("sumExpense", 0),
                "savings": s.get("savings", 0),
                "savings_rate": s.get("savingsRate", 0),
            }

        def render(applied: Optional[int]) -> str:
            return json_success(
                {
                    "period": {"start_date": start_date, "end_date": end_date},
                    "limit": applied,
                    **overall,
                    "by_category": breakdown(by_category, applied),
                    "by_category_group": breakdown(by_category_group, applied),
                    "by_merchant": breakdown(by_merchant, applied),
                }
            )

        return render_within_budget(render, limit)
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
        # Pass ISO strings directly; upstream serializes via gql JSON and
        # cannot handle datetime.date objects in GraphQL variables.
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if account_type:
            params["account_type"] = account_type

        result = await client.get_aggregate_snapshots(**params)

        snapshots = result.get("aggregateSnapshots", [])

        formatted: Dict[str, Any] = {"snapshot_count": len(snapshots), "snapshots": []}

        if snapshots:
            values = [
                s.get("balance", 0) for s in snapshots if s.get("balance") is not None
            ]
            if values:
                formatted["current_net_worth"] = values[-1] if values else 0
                formatted["earliest_net_worth"] = values[0] if values else 0
                formatted["change"] = values[-1] - values[0] if len(values) > 1 else 0
                formatted["change_percent"] = (
                    ((values[-1] - values[0]) / values[0] * 100)
                    if values[0] != 0 and len(values) > 1
                    else 0
                )
                formatted["highest"] = max(values)
                formatted["lowest"] = min(values)

        for snapshot in snapshots[-365:]:
            formatted["snapshots"].append(
                {
                    "date": snapshot.get("date"),
                    "net_worth": snapshot.get("balance"),
                }
            )

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
            return json_success(
                {"success": False, "error": "timeframe must be 'month' or 'year'"}
            )

        client = await get_monarch_client()
        result = await client.get_account_snapshots_by_type(
            start_date=start_date,
            timeframe=timeframe,
        )

        # Upstream returns a flat list under key "snapshotsByAccountType"
        # with shape [{"accountType": str, "month": "YYYY-MM" or "YYYY", "balance": float}, ...]
        rows = result.get("snapshotsByAccountType", [])

        formatted: Dict[str, Any] = {
            "timeframe": timeframe,
            "start_date": start_date,
            "account_types": [],
        }

        # Group flat rows by accountType, preserving order of first appearance.
        grouped: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            atype = row.get("accountType")
            if atype is None:
                continue
            entry = grouped.setdefault(atype, {"type": atype, "snapshots": []})
            entry["snapshots"].append(
                {
                    "month": row.get("month"),
                    "balance": row.get("balance"),
                }
            )

        for type_info in grouped.values():
            if type_info["snapshots"]:
                type_info["current_balance"] = type_info["snapshots"][-1].get(
                    "balance", 0
                )
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
