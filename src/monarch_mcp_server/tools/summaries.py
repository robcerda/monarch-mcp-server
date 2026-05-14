"""Transaction summary tools."""

import logging
from typing import Any, Dict, List, Optional

from gql import gql

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_error, json_success

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GraphQL constants
# ---------------------------------------------------------------------------

GET_CASHFLOW_ENTITY_AGGREGATES_QUERY = gql(
    """
query Common_GetCashFlowEntityAggregates($filters: TransactionFilterInput) {
  byCategory: aggregates(filters: $filters, groupBy: ["category"]) {
    groupBy {
      category {
        id
        name
        icon
        group {
          id
          type
          __typename
        }
        __typename
      }
      __typename
    }
    summary {
      sum
      __typename
    }
    __typename
  }
  byCategoryGroup: aggregates(filters: $filters, groupBy: ["categoryGroup"]) {
    groupBy {
      categoryGroup {
        id
        name
        type
        __typename
      }
      __typename
    }
    summary {
      sum
      __typename
    }
    __typename
  }
  byMerchant: aggregates(filters: $filters, groupBy: ["merchant"]) {
    groupBy {
      merchant {
        id
        name
        logoUrl
        __typename
      }
      __typename
    }
    summary {
      sumIncome
      sumExpense
      __typename
    }
    __typename
  }
  summary: aggregates(filters: $filters, fillEmptyValues: true) {
    summary {
      sumIncome
      sumExpense
      savings
      savingsRate
      __typename
    }
    __typename
  }
}
"""
)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


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
) -> str:
    """
    Get a spending summary broken down by category, category group, and merchant.

    Shows how much you've spent in each category over a time period, plus
    overall income, expenses, and savings rate.

    Args:
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.

    Returns:
        Spending breakdown with by_category, by_category_group, by_merchant,
        and overall totals (income, expenses, savings, savings_rate).

    Examples:
        Get spending summary for current month:
            get_spending_summary(start_date="2026-05-01", end_date="2026-05-31")

        Get spending summary for the year:
            get_spending_summary(start_date="2026-01-01", end_date="2026-12-31")
    """
    try:
        client = await get_monarch_client()

        filters: Dict[str, Any] = {}
        if start_date:
            filters["startDate"] = start_date
        if end_date:
            filters["endDate"] = end_date

        result = await client.gql_call(
            operation="Common_GetCashFlowEntityAggregates",
            graphql_query=GET_CASHFLOW_ENTITY_AGGREGATES_QUERY,
            variables={"filters": filters},
        )

        by_category: List[Dict[str, Any]] = []
        for item in result.get("byCategory", []):
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
        by_category.sort(key=lambda x: abs(x.get("sum", 0)), reverse=True)

        by_category_group: List[Dict[str, Any]] = []
        for item in result.get("byCategoryGroup", []):
            grp = item.get("groupBy", {}).get("categoryGroup") or {}
            by_category_group.append(
                {
                    "group": grp.get("name"),
                    "group_id": grp.get("id"),
                    "group_type": grp.get("type"),
                    "sum": item.get("summary", {}).get("sum", 0),
                }
            )
        by_category_group.sort(key=lambda x: abs(x.get("sum", 0)), reverse=True)

        by_merchant: List[Dict[str, Any]] = []
        for item in result.get("byMerchant", []):
            merch = item.get("groupBy", {}).get("merchant") or {}
            by_merchant.append(
                {
                    "merchant": merch.get("name"),
                    "merchant_id": merch.get("id"),
                    "income": item.get("summary", {}).get("sumIncome", 0),
                    "expense": item.get("summary", {}).get("sumExpense", 0),
                }
            )
        by_merchant.sort(key=lambda x: abs(x.get("expense", 0)), reverse=True)

        overall = {}
        summary_items = result.get("summary", [])
        if summary_items:
            s = summary_items[0].get("summary", {})
            overall = {
                "total_income": s.get("sumIncome", 0),
                "total_expenses": s.get("sumExpense", 0),
                "savings": s.get("savings", 0),
                "savings_rate": s.get("savingsRate", 0),
            }

        formatted: Dict[str, Any] = {
            "period": {
                "start_date": start_date,
                "end_date": end_date,
            },
            **overall,
            "by_category": by_category,
            "by_category_group": by_category_group,
            "by_merchant": by_merchant,
        }

        return json_success(formatted)
    except Exception as e:
        return json_error("get_spending_summary", e)
