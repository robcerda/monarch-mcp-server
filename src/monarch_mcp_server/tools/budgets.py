"""Budget tools."""

import logging
from typing import Any, Dict, Optional

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

logger = logging.getLogger(__name__)


@mcp.tool()
async def get_budgets(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get budget information from Monarch Money.

    Args:
        start_date: Start date in YYYY-MM-DD format (defaults to last month)
        end_date: End date in YYYY-MM-DD format (defaults to next month)

    Returns:
        List of budgets with amounts, spent, and remaining for each category.
    """
    try:
        client = await get_monarch_client()
        filters: Dict[str, Any] = {}
        if start_date:
            filters["start_date"] = start_date
        if end_date:
            filters["end_date"] = end_date
        budgets = await client.get_budgets(**filters)

        budget_list = []
        for budget in budgets.get("budgetData", {}).get("budgetMonths", []):
            month_info: Dict[str, Any] = {
                "month": budget.get("month"),
                "total_budgeted": budget.get("totalBudgeted"),
                "total_spent": budget.get("totalSpent"),
                "categories": [],
            }

            for cat_group in budget.get("categoryGroups", []):
                group_name = cat_group.get("categoryGroup", {}).get("name")
                for cat in cat_group.get("categories", []):
                    cat_info = {
                        "category_id": cat.get("category", {}).get("id"),
                        "category_name": cat.get("category", {}).get("name"),
                        "category_icon": cat.get("category", {}).get("icon"),
                        "group": group_name,
                        "budgeted": cat.get("budgetedAmount"),
                        "spent": cat.get("actualAmount"),
                        "remaining": cat.get("remainingAmount"),
                        "rollover": cat.get("rolloverAmount"),
                    }
                    month_info["categories"].append(cat_info)

            budget_list.append(month_info)

        return json_success(budget_list)
    except Exception as e:
        return json_error("get_budgets", e)


@mcp.tool()
async def set_budget_amount(
    amount: float,
    category_id: Optional[str] = None,
    category_group_id: Optional[str] = None,
    start_date: Optional[str] = None,
    apply_to_future: bool = False,
) -> str:
    """
    Set or update a budget amount for a category or category group.

    Use get_budgets() first to see current budgets and category IDs.
    Use get_categories() or get_category_groups() to find category/group IDs.

    Args:
        amount: The budget amount to set. Use 0 to clear/unset the budget.
        category_id: The ID of the category to budget (cannot use with category_group_id)
        category_group_id: The ID of the category group to budget (cannot use with category_id)
        start_date: The month to set budget for in YYYY-MM-DD format (defaults to current month)
        apply_to_future: Whether to apply this amount to all future months (default: False)

    Returns:
        Result of the budget update.

    Examples:
        Set grocery budget to $600 for current month:
            set_budget_amount(amount=600, category_id="cat_groceries_123")

        Set dining budget to $200 and apply to all future months:
            set_budget_amount(amount=200, category_id="cat_dining_456", apply_to_future=True)

        Clear a budget (set to 0):
            set_budget_amount(amount=0, category_id="cat_123")
    """
    try:
        if category_id and category_group_id:
            return json_success({
                "success": False,
                "error": "Cannot specify both category_id and category_group_id. Choose one."
            })

        if not category_id and not category_group_id:
            return json_success({
                "success": False,
                "error": "Must specify either category_id or category_group_id."
            })

        client = await get_monarch_client()

        params: Dict[str, Any] = {
            "amount": amount,
            "apply_to_future": apply_to_future,
        }

        if category_id:
            params["category_id"] = category_id
        if category_group_id:
            params["category_group_id"] = category_group_id
        if start_date:
            params["start_date"] = start_date

        result = await client.set_budget_amount(**params)

        return json_success({
            "success": True,
            "message": f"Budget set to ${amount:.2f}" + (" for all future months" if apply_to_future else ""),
            "result": result
        })
    except Exception as e:
        return json_error("set_budget_amount", e)
