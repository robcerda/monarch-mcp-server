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
# accounts, so it can fail outright. This narrower query asks only for fields
# the current API still returns.
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


# Kept separate so get_budgets retains its category-only request and response
# contract. The summary exposes both overlapping views plus Monarch's totals.
BUDGET_SUMMARY_QUERY = gql(
    """
    query MCPBudgetSummary($startDate: Date!, $endDate: Date!) {
      budgetData(startMonth: $startDate, endMonth: $endDate) {
        monthlyAmountsByCategory {
          category { id }
          monthlyAmounts {
            month
            plannedCashFlowAmount
            plannedSetAsideAmount
            actualAmount
            remainingAmount
          }
        }
        monthlyAmountsByCategoryGroup {
          categoryGroup { id }
          monthlyAmounts {
            month
            plannedCashFlowAmount
            actualAmount
            remainingAmount
          }
        }
        totalsByMonth {
          month
          totalIncome { plannedAmount actualAmount }
          totalExpenses { plannedAmount actualAmount }
        }
      }
      categoryGroups {
        id
        name
        type
        groupLevelBudgetingEnabled
        categories { id name }
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
    """Format Monarch budget data into one row per category/month."""
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
        A JSON list with one row per budgeted category per month. Each row has:
        ``id`` (category id), ``name`` (category name), ``planned`` (planned
        cash-flow amount), ``actual`` (actual amount), ``remaining``,
        ``category_group`` (group name), and ``month`` (YYYY-MM-DD).
    """
    try:
        client = await get_monarch_client()
        budget_data = await get_budget_data(client, start_date, end_date)
        return json_success(format_budget_data(budget_data))
    except Exception as e:
        return json_error("get_budgets", e)


@mcp.tool()
async def get_budget_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """Read category budgets, group budgets, and authoritative monthly totals.

    Args:
        start_date: Start month in YYYY-MM-DD format (defaults to current month).
        end_date: End month in YYYY-MM-DD format (defaults to current month).

    Returns:
        category_budgets and group_budgets contain one row per category/group
        per month. Each has planned, actual, remaining, and current group
        metadata, including groupLevelBudgetingEnabled. totals_by_month is
        Monarch's authoritative totalsByMonth response (null if unavailable).

        Category and group rows overlap: never add the two sets together.
        With group budgeting enabled, zero category plans do not mean there
        is no group allowance. Use totals_by_month for overall totals, and
        retain remaining amounts as returned because carryover can affect
        them. Group metadata describes current settings, not their history.
    """
    try:
        default_start, default_end = current_month_range()
        client = await get_monarch_client()
        result = await client.gql_call(
            operation="MCPBudgetSummary",
            graphql_query=BUDGET_SUMMARY_QUERY,
            variables={
                "startDate": start_date or default_start,
                "endDate": end_date or default_end,
            },
        )
        groups = {
            group["id"]: group
            for group in result.get("categoryGroups", [])
            if group.get("id")
        }
        category_groups = {
            category["id"]: group
            for group in groups.values()
            for category in group.get("categories", [])
            if category.get("id")
        }
        category_rows = format_budget_data(result)
        for row in category_rows:
            group = category_groups.get(row["id"], {})
            row.update(
                {
                    "category_group_id": group.get("id"),
                    "category_group_type": group.get("type"),
                    "groupLevelBudgetingEnabled": group.get(
                        "groupLevelBudgetingEnabled"
                    ),
                }
            )

        budget_data = result.get("budgetData", {})
        group_rows = []
        for group_budget in budget_data.get("monthlyAmountsByCategoryGroup", []):
            group_id = (group_budget.get("categoryGroup") or {}).get("id")
            group = groups.get(group_id, {})
            for amount in group_budget.get("monthlyAmounts", []):
                group_rows.append(
                    {
                        "id": group_id,
                        "name": group.get("name"),
                        "type": group.get("type"),
                        "groupLevelBudgetingEnabled": group.get(
                            "groupLevelBudgetingEnabled"
                        ),
                        "month": amount.get("month"),
                        "planned": amount.get("plannedCashFlowAmount"),
                        "actual": amount.get("actualAmount"),
                        "remaining": amount.get("remainingAmount"),
                    }
                )

        return json_success(
            {
                "category_budgets": category_rows,
                "group_budgets": group_rows,
                "totals_by_month": budget_data.get("totalsByMonth"),
                "aggregation_guidance": (
                    "Category and group rows overlap; do not add them together. "
                    "Use totals_by_month for authoritative overall totals. "
                    "When groupLevelBudgetingEnabled is true, zero category "
                    "plans do not mean the group has no budget. Group metadata "
                    "reflects current settings, not historical configuration."
                ),
            }
        )
    except Exception as e:
        return json_error("get_budget_summary", e)


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

        # No literal "success": True here. The upstream mutation selects no
        # errors field, so there is nothing to check and nothing that justifies
        # asserting the write landed. Report what was requested and hand back
        # the raw result rather than a claim the response cannot support.
        return json_success({
            "requested": {
                "amount": amount,
                "apply_to_future": apply_to_future,
                "category_id": category_id,
                "category_group_id": category_group_id,
                "start_date": start_date,
            },
            "result": result,
        })
    except Exception as e:
        return json_error("set_budget_amount", e)
