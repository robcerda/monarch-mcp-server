"""Budget tools."""

import calendar
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from gql import gql
from monarchmoney import MonarchMoney

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

logger = logging.getLogger(__name__)

# The upstream SDK's get_budgets() requests category-group fields (e.g.
# budgetVariability/rolloverPeriod) that Monarch's current API rejects for some
# accounts, so it can fail outright. This query asks only for fields the current
# API still returns.
#
# Alongside the per-category amounts it pulls the Flex-budget context those
# amounts alone can't convey: under "Fixed & Flexible" budgeting the real
# flexible budget is a single "flex bucket" total (``monthlyAmountsForFlexExpense``)
# that the per-category flex sub-budgets do NOT sum to, and ``totalsByMonth`` gives
# the Fixed / Non-Monthly / Flexible / overall rollups the way Monarch computes
# them. Both live on ``budgetData`` and don't touch the guarded category-group
# fields above.
BUDGET_QUERY = gql(
    """
    query MCPBudgetData($startDate: Date!, $endDate: Date!) {
      budgetData(startMonth: $startDate, endMonth: $endDate) {
        monthlyAmountsByCategory {
          category {
            id
            __typename
          }
          monthlyAmounts {
            month
            plannedCashFlowAmount
            plannedSetAsideAmount
            actualAmount
            remainingAmount
            __typename
          }
          __typename
        }
        monthlyAmountsForFlexExpense {
          monthlyAmounts {
            month
            plannedCashFlowAmount
            actualAmount
            remainingAmount
            __typename
          }
          __typename
        }
        totalsByMonth {
          month
          totalIncome {
            plannedAmount
            actualAmount
            remainingAmount
            __typename
          }
          totalExpenses {
            plannedAmount
            actualAmount
            remainingAmount
            __typename
          }
          totalFixedExpenses {
            plannedAmount
            actualAmount
            remainingAmount
            __typename
          }
          totalNonMonthlyExpenses {
            plannedAmount
            actualAmount
            remainingAmount
            __typename
          }
          totalFlexibleExpenses {
            plannedAmount
            actualAmount
            remainingAmount
            __typename
          }
          __typename
        }
        __typename
      }
      categoryGroups {
        id
        name
        type
        categories {
          id
          name
          __typename
        }
        __typename
      }
    }
    """
)


def current_month_range() -> tuple[str, str]:
    """Return the current month bounds as ISO date strings."""
    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=1).isoformat(), today.replace(day=last_day).isoformat()


async def get_budget_data(
    client: MonarchMoney,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch budget data using fields supported by Monarch's current API."""
    default_start, default_end = current_month_range()
    return await client.gql_call(
        operation="MCPBudgetData",
        graphql_query=BUDGET_QUERY,
        variables={
            "startDate": start_date or default_start,
            "endDate": end_date or default_end,
        },
    )


def format_budget_data(budget_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Format Monarch budget data into one row per category/month.

    NOTE: for categories in the Flexible bucket the per-category ``planned`` is
    only a guideline sub-budget — the real flexible budget is the single
    flex-bucket total (see ``format_flex_bucket``), which these sub-budgets do
    not sum to. Analyze flexible spending against the flex bucket / section
    totals, not these per-category planned amounts.
    """
    category_lookup: Dict[str, Dict[str, Optional[str]]] = {}
    for group in budget_data.get("categoryGroups", []):
        for category in group.get("categories", []):
            category_id = category.get("id")
            if category_id:
                category_lookup[category_id] = {
                    "name": category.get("name"),
                    "category_group": group.get("name"),
                }

    budget_rows = []
    monthly_by_category = (
        budget_data.get("budgetData", {}).get("monthlyAmountsByCategory", [])
    )
    for category_budget in monthly_by_category:
        category_id = (category_budget.get("category") or {}).get("id")
        category_info = category_lookup.get(category_id, {})
        for monthly_amount in category_budget.get("monthlyAmounts", []):
            budget_rows.append(
                {
                    "id": category_id,
                    "name": category_info.get("name"),
                    "planned": monthly_amount.get("plannedCashFlowAmount"),
                    "actual": monthly_amount.get("actualAmount"),
                    "remaining": monthly_amount.get("remainingAmount"),
                    "category_group": category_info.get("category_group"),
                    "month": monthly_amount.get("month"),
                }
            )

    return budget_rows


def format_flex_bucket(budget_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Format the Flex-bucket total per month.

    Under Fixed & Flexible budgeting the flexible budget is a single "flex
    bucket" amount set independently of the flex sub-categories. This is the
    number that actually counts toward the budget, so compare total flexible
    *spend* against this — not against the sum of the flex category sub-budgets.
    """
    flex = (budget_data.get("budgetData", {}) or {}).get(
        "monthlyAmountsForFlexExpense"
    ) or {}
    rows = []
    for monthly_amount in flex.get("monthlyAmounts", []):
        rows.append(
            {
                "month": monthly_amount.get("month"),
                "planned": monthly_amount.get("plannedCashFlowAmount"),
                "actual": monthly_amount.get("actualAmount"),
                "remaining": monthly_amount.get("remainingAmount"),
            }
        )
    return rows


def _totals(node: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    node = node or {}
    return {
        "planned": node.get("plannedAmount"),
        "actual": node.get("actualAmount"),
        "remaining": node.get("remainingAmount"),
    }


def format_section_totals(budget_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Format the per-month section rollups the way Monarch computes them.

    Total budget = Fixed + Non-Monthly + Flex bucket (NOT the sum of individual
    flex categories). Fixed and Non-Monthly totals auto-sum from their
    sub-budgets; the Flexible total is the flex bucket.
    """
    totals_by_month = (budget_data.get("budgetData", {}) or {}).get(
        "totalsByMonth", []
    )
    rows = []
    for month_totals in totals_by_month:
        rows.append(
            {
                "month": month_totals.get("month"),
                "income": _totals(month_totals.get("totalIncome")),
                "total_expenses": _totals(month_totals.get("totalExpenses")),
                "fixed": _totals(month_totals.get("totalFixedExpenses")),
                "non_monthly": _totals(month_totals.get("totalNonMonthlyExpenses")),
                "flexible": _totals(month_totals.get("totalFlexibleExpenses")),
            }
        )
    return rows


@mcp.tool()
async def get_budgets(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get budget information from Monarch Money.

    Args:
        start_date: Start month in YYYY-MM-DD format (defaults to the current month)
        end_date: End month in YYYY-MM-DD format (defaults to the current month)

    Returns:
        A JSON object with three keys:

        ``categories``: one row per budgeted category per month, each with
            ``id``, ``name``, ``planned`` (planned cash-flow amount), ``actual``,
            ``remaining``, ``category_group``, and ``month`` (YYYY-MM-DD).
        ``flex_bucket``: the Flex-bucket total per month (``month``, ``planned``,
            ``actual``, ``remaining``). Under Fixed & Flexible budgeting THIS is
            the real flexible budget — the flex categories' ``planned`` values are
            only guidelines and do NOT sum to it. Compare total flexible spend
            against this.
        ``section_totals``: per-month rollups (``fixed``, ``non_monthly``,
            ``flexible``, ``total_expenses``, ``income``), each with
            ``planned`` / ``actual`` / ``remaining``. Total budget = Fixed +
            Non-Monthly + Flex bucket.

        (For category-based budgets not using Flex, ``flex_bucket`` /
        ``section_totals`` may be empty; use ``categories``.)
    """
    try:
        client = await get_monarch_client()
        budget_data = await get_budget_data(client, start_date, end_date)
        return json_success(
            {
                "categories": format_budget_data(budget_data),
                "flex_bucket": format_flex_bucket(budget_data),
                "section_totals": format_section_totals(budget_data),
            }
        )
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
