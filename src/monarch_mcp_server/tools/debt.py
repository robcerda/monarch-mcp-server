"""Debt paydown tools."""

import logging
from typing import Any, Dict, List

from gql import gql

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

logger = logging.getLogger(__name__)

# Debt paydown is not a goal. Monarch's legacy goal system had a "debt" goal
# type, but the migration to savingsGoals dropped it -- a legacy debt goal
# comes back from legacyGoalsMigrationData with newGoalId null -- and replaced
# it with a plan computed over the debt accounts themselves.
GET_DEBT_PAYDOWN_QUERY = gql("""
query GetDebtPaydown($input: SavingsCalculatorInput!) {
  debtAccounts {
    id
    displayName
    displayBalance
    apr
    interestRate
    minimumPayment
    plannedPayment
    excludeFromDebtPaydown
    __typename
  }
  debtPaydownPlan(input: $input) {
    currentDebtPrincipal
    projectedInterest
    projectedTotal
    debtFreeDate
    adjustedDebtFreeDate
    adjustedProjectedInterest
    adjustedProjectedTotal
    debtAccountProjections {
      account {
        id
        displayName
        __typename
      }
      principal
      projectedInterest
      projectedTotal
      debtFreeDate
      __typename
    }
    __typename
  }
}
""")


@mcp.tool()
async def get_debt_paydown(method: str = "planned") -> str:
    """
    Get the debt paydown plan and the accounts feeding it.

    Reports every debt account with its APR, minimum and planned payment, and
    whether it is excluded from the plan, alongside the projected interest and
    debt-free date.

    Excluded accounts are called out separately. Excluding a high-APR account
    quietly shrinks the plan's principal, so the projected debt-free date can
    look better than reality while the most expensive balance is untouched.

    Args:
        method: Paydown strategy. "planned" uses the payments configured on
            each account; Monarch also models avalanche/snowball orderings.

    Returns:
        JSON with the plan, per-account projections, and any excluded accounts.
    """
    try:
        client = await get_monarch_client()
        result = await client.gql_call(
            operation="GetDebtPaydown",
            graphql_query=GET_DEBT_PAYDOWN_QUERY,
            variables={"input": {"debtPaydownMethod": method}},
        )

        accounts = result.get("debtAccounts") or []
        plan: Dict[str, Any] = result.get("debtPaydownPlan") or {}

        included: List[Dict[str, Any]] = []
        excluded: List[Dict[str, Any]] = []
        for a in accounts:
            row = {
                "account_id": a.get("id"),
                "name": a.get("displayName"),
                "balance": a.get("displayBalance"),
                "apr": a.get("apr"),
                "minimum_payment": a.get("minimumPayment"),
                "planned_payment": a.get("plannedPayment"),
            }
            (excluded if a.get("excludeFromDebtPaydown") else included).append(row)

        total = sum(a.get("displayBalance") or 0 for a in accounts)
        excluded_total = sum(r["balance"] or 0 for r in excluded)

        return json_success({
            "method": method,
            "total_debt_across_accounts": round(total, 2),
            "debt_in_plan": plan.get("currentDebtPrincipal"),
            "debt_excluded_from_plan": round(excluded_total, 2),
            "projected_interest": plan.get("projectedInterest"),
            "projected_total": plan.get("projectedTotal"),
            "debt_free_date": plan.get("debtFreeDate"),
            "adjusted_debt_free_date": plan.get("adjustedDebtFreeDate"),
            "excluded_accounts": excluded,
            "included_accounts": included,
            "projections": [
                {
                    "name": (p.get("account") or {}).get("displayName"),
                    "principal": p.get("principal"),
                    "projected_interest": p.get("projectedInterest"),
                    "debt_free_date": p.get("debtFreeDate"),
                }
                for p in (plan.get("debtAccountProjections") or [])
            ],
            "note": (
                "Excluded accounts are not in the plan's principal, interest or "
                "debt-free date. If a high-APR card is excluded, the projection "
                "understates both the cost and the payoff time."
            ),
        })
    except Exception as e:
        return json_error("get_debt_paydown", e)
