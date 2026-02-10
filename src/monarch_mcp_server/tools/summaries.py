"""Transaction summary tools."""

import logging
from typing import Any, Dict, Optional

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

logger = logging.getLogger(__name__)


@mcp.tool()
async def get_transactions_summary() -> str:
    """
    Get a high-level summary of transactions.

    Returns quick statistics about your transactions without fetching all details.
    Useful for getting a quick overview of transaction activity.

    Returns:
        Summary statistics including counts and totals.
    """
    try:
        client = await get_monarch_client()
        result = await client.get_transactions_summary()
        return json_success(result)
    except Exception as e:
        return json_error("get_transactions_summary", e)


@mcp.tool()
async def get_spending_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
) -> str:
    """
    Get a spending summary broken down by category.

    Shows how much you've spent in each category over a time period.
    Great for understanding where your money is going.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        limit: Maximum number of categories to return (default: 100)

    Returns:
        Spending breakdown by category with totals.

    Examples:
        Get spending summary for current month:
            get_spending_summary(start_date="2024-02-01", end_date="2024-02-29")

        Get spending summary for the year:
            get_spending_summary(start_date="2024-01-01")
    """
    try:
        client = await get_monarch_client()

        params: Dict[str, Any] = {"limit": limit}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        result = await client.get_cashflow_summary(**params)

        summary = result.get("summary", [])

        formatted: Dict[str, Any] = {
            "period": {
                "start_date": start_date,
                "end_date": end_date,
            },
            "total_income": 0,
            "total_expenses": 0,
            "net": 0,
            "by_category": []
        }

        for item in summary:
            category_info = {
                "category": item.get("category", {}).get("name") if item.get("category") else "Uncategorized",
                "category_id": item.get("category", {}).get("id") if item.get("category") else None,
                "group": item.get("categoryGroup", {}).get("name") if item.get("categoryGroup") else None,
                "sum": item.get("sum", 0),
                "avg": item.get("avg", 0),
            }
            formatted["by_category"].append(category_info)

            amount = item.get("sum", 0)
            if amount > 0:
                formatted["total_income"] += amount
            else:
                formatted["total_expenses"] += abs(amount)

        formatted["net"] = formatted["total_income"] - formatted["total_expenses"]

        formatted["by_category"].sort(key=lambda x: abs(x.get("sum", 0)), reverse=True)

        return json_success(formatted)
    except Exception as e:
        return json_error("get_spending_summary", e)
