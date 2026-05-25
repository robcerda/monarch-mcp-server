"""Category tools."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from gql import gql

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

logger = logging.getLogger(__name__)


@mcp.tool()
async def get_transaction_categories() -> str:
    """Get all available transaction categories from Monarch Money."""
    try:
        client = await get_monarch_client()
        data = await client.get_transaction_categories()
        categories = []
        for cat in data.get("categories", []):
            group = cat.get("group") or {}
            categories.append(
                {
                    "id": cat.get("id"),
                    "name": cat.get("name"),
                    "icon": cat.get("icon"),
                    "group": group.get("name") if isinstance(group, dict) else None,
                    "group_id": group.get("id") if isinstance(group, dict) else None,
                }
            )
        return json_success(categories)
    except Exception as e:
        return json_error("get_transaction_categories", e)


@mcp.tool()
async def get_transaction_category_groups() -> str:
    """Get all transaction category groups (parent groupings for categories)."""
    try:
        client = await get_monarch_client()
        data = await client.get_transaction_category_groups()
        groups = [
            {"id": g.get("id"), "name": g.get("name"), "type": g.get("type")}
            for g in data.get("categoryGroups", [])
        ]
        return json_success(groups)
    except Exception as e:
        return json_error("get_transaction_category_groups", e)


@mcp.tool()
async def create_transaction_category(
    group_id: str,
    transaction_category_name: str,
    icon: Optional[str] = None,
    rollover_enabled: Optional[bool] = None,
    rollover_type: Optional[str] = None,
) -> str:
    """
    Create a new transaction category.

    Args:
        group_id: The category group ID this category belongs to
        transaction_category_name: Name of the new category
        icon: Optional emoji icon for the category
        rollover_enabled: Optional, whether budget rollover is enabled
        rollover_type: Optional rollover type (e.g. "monthly")
    """
    try:
        client = await get_monarch_client()
        kwargs: Dict[str, Any] = {
            "group_id": group_id,
            "transaction_category_name": transaction_category_name,
        }
        if icon is not None:
            kwargs["icon"] = icon
        if rollover_enabled is not None:
            kwargs["rollover_enabled"] = rollover_enabled
        if rollover_type is not None:
            kwargs["rollover_type"] = rollover_type
        result = await client.create_transaction_category(**kwargs)
        return json_success(result)
    except Exception as e:
        return json_error("create_transaction_category", e)


# ---------------------------------------------------------------------------
# GraphQL constants (custom queries not in monarchmoney library)
# ---------------------------------------------------------------------------

UPDATE_CATEGORY_MUTATION = gql(
    """
mutation Web_UpdateCategory($input: UpdateCategoryInput!) {
  updateCategory(input: $input) {
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    category {
      id
      name
      icon
      systemCategory
      systemCategoryDisplayName
      budgetVariability
      excludeFromBudget
      isSystemCategory
      isDisabled
      isProtected
      group {
        id
        type
        groupLevelBudgetingEnabled
        __typename
      }
      rolloverPeriod {
        id
        startMonth
        startingBalance
        type
        frequency
        targetAmount
        __typename
      }
      __typename
    }
    __typename
  }
}
"""
)

GET_CATEGORY_DETAILS_QUERY = gql(
    """
query GetCategoryDetails($id: UUID, $month: Date!, $includeBudgetAmounts: Boolean!) {
  category(id: $id) {
    id
    order
    name
    icon
    isSystemCategory
    systemCategory
    excludeFromBudget
    isDisabled
    group {
      id
      name
      type
      __typename
    }
    rolloverPeriod {
      id
      startingBalance
      __typename
    }
    budgetAmountsForMonth(month: $month) @include(if: $includeBudgetAmounts) {
      month
      plannedAmount
      actualAmount
      remainingAmount
      previousMonthRolloverAmount
      rolloverType
      __typename
    }
    __typename
  }
}
"""
)

GET_AGGREGATES_BY_MONTH_QUERY = gql(
    """
query GetAggregatesGraph($startDate: Date, $endDate: Date) {
  aggregates(
    filters: {startDate: $startDate, endDate: $endDate}
    groupBy: ["category", "month"]
    fillEmptyValues: true
  ) {
    groupBy {
      category {
        id
        __typename
      }
      month
      __typename
    }
    summary {
      sum
      __typename
    }
    __typename
  }
}
"""
)


# ---------------------------------------------------------------------------
# GraphQL-backed tools
# ---------------------------------------------------------------------------


_VALID_BUDGET_VARIABILITY = {"fixed", "flexible", "non_monthly"}
_VALID_ROLLOVER_FREQUENCY = {"monthly", "variable"}


@mcp.tool()
async def update_category(
    category_id: str,
    name: Optional[str] = None,
    icon: Optional[str] = None,
    group_id: Optional[str] = None,
    category_type: Optional[str] = None,
    exclude_from_budget: Optional[bool] = None,
    budget_variability: Optional[str] = None,
    rollover_enabled: Optional[bool] = None,
    rollover_start_month: Optional[str] = None,
    rollover_starting_balance: Optional[float] = None,
    rollover_frequency: Optional[str] = None,
    rollover_target_amount: Optional[float] = None,
    rollover_type: Optional[str] = None,
    dry_run: bool = False,
) -> str:
    """
    Update an existing category's settings.

    Modify a category's name, icon, group, budget variability, and rollover
    configuration. Use get_transaction_categories to find category IDs, and
    get_category_details to see current settings before updating.

    Args:
        category_id: The category ID to update.
        name: New display name.
        icon: New emoji icon.
        group_id: Move to a different category group (use
            get_transaction_category_groups to find group IDs).
        category_type: Category type, typically "expense" or "income".
        exclude_from_budget: Whether to exclude this category from budgets.
        budget_variability: Budget variability mode. Values: "fixed" (same
            every month), "flexible" (pooled into flex bucket), "non_monthly"
            (annual/irregular with rollover).
        rollover_enabled: Whether budget rollover is enabled.
        rollover_start_month: When rollover tracking begins (YYYY-MM-DD,
            first of month).
        rollover_starting_balance: Starting rollover balance in dollars.
        rollover_frequency: Rollover frequency. Values: "monthly",
            "variable".
        rollover_target_amount: Target amount for rollover savings goal.
        rollover_type: Rollover type. Values: "monthly".
        dry_run: If True, return the planned changes without executing the
            mutation. Shows current vs proposed values.

    Returns:
        Updated category details including budget variability and rollover
        configuration. In dry_run mode, returns current state and proposed
        changes without applying them.

    Example:
        Change a category to non-monthly with rollover:
            update_category(
                category_id="243338338825232741",
                budget_variability="non_monthly",
                rollover_enabled=True,
                rollover_start_month="2026-05-01",
                rollover_starting_balance=0,
                rollover_frequency="variable",
            )

        Preview changes without applying:
            update_category(
                category_id="243338338825232741",
                budget_variability="flexible",
                dry_run=True,
            )
    """
    try:
        if (
            budget_variability is not None
            and budget_variability not in _VALID_BUDGET_VARIABILITY
        ):
            return json_success(
                {
                    "success": False,
                    "message": (
                        f"Invalid budget_variability: {budget_variability!r}. "
                        f"Must be one of: {sorted(_VALID_BUDGET_VARIABILITY)}"
                    ),
                }
            )

        if (
            rollover_frequency is not None
            and rollover_frequency not in _VALID_ROLLOVER_FREQUENCY
        ):
            return json_success(
                {
                    "success": False,
                    "message": (
                        f"Invalid rollover_frequency: {rollover_frequency!r}. "
                        f"Must be one of: {sorted(_VALID_ROLLOVER_FREQUENCY)}"
                    ),
                }
            )

        provided: Dict[str, Any] = {}
        if name is not None:
            provided["name"] = name
        if icon is not None:
            provided["icon"] = icon
        if group_id is not None:
            provided["group"] = group_id
        if category_type is not None:
            provided["type"] = category_type
        if exclude_from_budget is not None:
            provided["excludeFromBudget"] = exclude_from_budget
        if budget_variability is not None:
            provided["budgetVariability"] = budget_variability
        if rollover_enabled is not None:
            provided["rolloverEnabled"] = rollover_enabled
        if rollover_start_month is not None:
            provided["rolloverStartMonth"] = rollover_start_month
        if rollover_starting_balance is not None:
            provided["rolloverStartingBalance"] = rollover_starting_balance
        if rollover_frequency is not None:
            provided["rolloverFrequency"] = rollover_frequency
        if rollover_target_amount is not None:
            provided["rolloverTargetAmount"] = rollover_target_amount
        if rollover_type is not None:
            provided["rolloverType"] = rollover_type

        if not provided:
            return json_success(
                {
                    "success": False,
                    "message": "At least one field to update must be provided.",
                }
            )

        if dry_run:
            client = await get_monarch_client()
            current = await client.gql_call(
                operation="GetCategoryDetails",
                graphql_query=GET_CATEGORY_DETAILS_QUERY,
                variables={
                    "id": category_id,
                    "month": datetime.now().strftime("%Y-%m-01"),
                    "includeBudgetAmounts": False,
                },
            )
            cat = current.get("category")
            if not cat:
                return json_success(
                    {
                        "success": False,
                        "message": "No category found with the given ID.",
                    }
                )
            return json_success(
                {
                    "dry_run": True,
                    "category_id": category_id,
                    "current": {
                        "name": cat.get("name"),
                        "icon": cat.get("icon"),
                        "exclude_from_budget": cat.get("excludeFromBudget"),
                        "is_disabled": cat.get("isDisabled"),
                    },
                    "proposed_changes": provided,
                }
            )

        category_input: Dict[str, Any] = {"id": category_id, **provided}

        client = await get_monarch_client()
        result = await client.gql_call(
            operation="Web_UpdateCategory",
            graphql_query=UPDATE_CATEGORY_MUTATION,
            variables={"input": category_input},
        )

        errors = result.get("updateCategory", {}).get("errors")
        if errors:
            return json_success({"success": False, "errors": errors})

        cat = result.get("updateCategory", {}).get("category", {})
        group = cat.get("group") or {}
        rollover = cat.get("rolloverPeriod")

        return json_success(
            {
                "success": True,
                "category": {
                    "id": cat.get("id"),
                    "name": cat.get("name"),
                    "icon": cat.get("icon"),
                    "budget_variability": cat.get("budgetVariability"),
                    "exclude_from_budget": cat.get("excludeFromBudget"),
                    "is_system_category": cat.get("isSystemCategory"),
                    "is_disabled": cat.get("isDisabled"),
                    "group": {
                        "id": group.get("id"),
                        "type": group.get("type"),
                        "group_level_budgeting_enabled": group.get(
                            "groupLevelBudgetingEnabled"
                        ),
                    },
                    "rollover_period": (
                        {
                            "id": rollover.get("id"),
                            "start_month": rollover.get("startMonth"),
                            "starting_balance": rollover.get("startingBalance"),
                            "type": rollover.get("type"),
                            "frequency": rollover.get("frequency"),
                            "target_amount": rollover.get("targetAmount"),
                        }
                        if rollover
                        else None
                    ),
                },
            }
        )
    except Exception as e:
        return json_error("update_category", e)


@mcp.tool()
async def get_category_details(
    category_id: str,
    month: Optional[str] = None,
) -> str:
    """
    Get a single category's details including budget amounts for a month.

    Returns the category's configuration (group, rollover settings) plus
    budget performance for the specified month: planned amount, actual
    spending, remaining budget, and any rollover from the previous month.

    Args:
        category_id: The category ID to look up.
        month: Month to get budget amounts for, in YYYY-MM-DD format (first
            of month). Defaults to the current month.

    Returns:
        Category details with budget amounts (planned, actual, remaining,
        rollover).

    Example:
        Check how Groceries is tracking this month:
            get_category_details(category_id="46433339325375401")
    """
    try:
        if not month:
            month = datetime.now().strftime("%Y-%m-01")

        client = await get_monarch_client()
        result = await client.gql_call(
            operation="GetCategoryDetails",
            graphql_query=GET_CATEGORY_DETAILS_QUERY,
            variables={
                "id": category_id,
                "month": month,
                "includeBudgetAmounts": True,
            },
        )

        cat = result.get("category")
        if not cat:
            return json_success(
                {
                    "category": None,
                    "message": "No category found with the given ID.",
                }
            )

        group = cat.get("group") or {}
        rollover = cat.get("rolloverPeriod")
        budget = cat.get("budgetAmountsForMonth")

        return json_success(
            {
                "id": cat.get("id"),
                "name": cat.get("name"),
                "icon": cat.get("icon"),
                "order": cat.get("order"),
                "is_system_category": cat.get("isSystemCategory"),
                "exclude_from_budget": cat.get("excludeFromBudget"),
                "is_disabled": cat.get("isDisabled"),
                "group": {
                    "id": group.get("id"),
                    "name": group.get("name"),
                    "type": group.get("type"),
                },
                "rollover_period": (
                    {
                        "id": rollover.get("id"),
                        "starting_balance": rollover.get("startingBalance"),
                    }
                    if rollover
                    else None
                ),
                "budget_amounts": (
                    {
                        "month": budget.get("month"),
                        "planned_amount": budget.get("plannedAmount"),
                        "actual_amount": budget.get("actualAmount"),
                        "remaining_amount": budget.get("remainingAmount"),
                        "previous_month_rollover_amount": budget.get(
                            "previousMonthRolloverAmount"
                        ),
                        "rollover_type": budget.get("rolloverType"),
                    }
                    if budget
                    else None
                ),
            }
        )
    except Exception as e:
        return json_error("get_category_details", e)


@mcp.tool()
async def get_cashflow_by_month(
    start_date: str,
    end_date: str,
) -> str:
    """
    Get spending trends over time, broken down by category and month.

    Use this for month-over-month comparisons and trend analysis. Returns
    each category's spending for every month in the date range, sorted by
    total magnitude.

    For single-period totals by category, use get_spending_summary instead.

    Args:
        start_date: Start date in YYYY-MM-DD format (first of month).
        end_date: End date in YYYY-MM-DD format (last day or first of next
            month).

    Returns:
        List of categories with monthly spending totals, sorted by total
        absolute spending (largest first).

    Example:
        See how spending changed over the last 6 months:
            get_cashflow_by_month(
                start_date="2025-12-01",
                end_date="2026-05-31",
            )
    """
    try:
        client = await get_monarch_client()
        result = await client.gql_call(
            operation="GetAggregatesGraph",
            graphql_query=GET_AGGREGATES_BY_MONTH_QUERY,
            variables={"startDate": start_date, "endDate": end_date},
        )

        aggregates = result.get("aggregates", [])

        categories_map: Dict[str, List[Dict[str, Any]]] = {}
        for item in aggregates:
            group_by = item.get("groupBy", {})
            cat = group_by.get("category") or {}
            cat_id = cat.get("id") or "uncategorized"
            month_val = group_by.get("month")
            total = item.get("summary", {}).get("sum", 0)

            if cat_id not in categories_map:
                categories_map[cat_id] = []
            categories_map[cat_id].append({"month": month_val, "sum": total})

        categories_list: List[Dict[str, Any]] = []
        for cat_id, monthly_totals in categories_map.items():
            abs_total = sum(abs(m.get("sum", 0) or 0) for m in monthly_totals)
            categories_list.append(
                {
                    "category_id": cat_id,
                    "_sort_key": abs_total,
                    "monthly_totals": sorted(
                        monthly_totals, key=lambda m: m.get("month") or ""
                    ),
                }
            )

        categories_list.sort(key=lambda c: c["_sort_key"], reverse=True)

        for cat in categories_list:
            del cat["_sort_key"]

        return json_success(
            {
                "period": {"start_date": start_date, "end_date": end_date},
                "categories": categories_list,
            }
        )
    except Exception as e:
        return json_error("get_cashflow_by_month", e)


