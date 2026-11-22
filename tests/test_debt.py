"""Tests for debt paydown tools."""

import json
from unittest.mock import AsyncMock, patch

from monarch_mcp_server.tools.debt import get_debt_paydown


def _acct(**o):
    a = {"id": "a1", "displayName": "Card", "displayBalance": 1000.0, "apr": 20.0,
         "interestRate": None, "minimumPayment": 25.0, "plannedPayment": 0.0,
         "excludeFromDebtPaydown": False}
    a.update(o)
    return a


def _client(accounts, plan=None):
    c = AsyncMock()
    c.gql_call.return_value = {
        "debtAccounts": accounts,
        "debtPaydownPlan": plan or {
            "currentDebtPrincipal": 1000.0, "projectedInterest": 100.0,
            "projectedTotal": 1100.0, "debtFreeDate": "2028-01-01",
            "adjustedDebtFreeDate": None, "debtAccountProjections": [],
        },
    }
    return c


class TestGetDebtPaydown:
    """Tests for get_debt_paydown tool."""

    @patch('monarch_mcp_server.tools.debt.get_monarch_client')
    async def test_reports_plan(self, mock_get_client):
        mock_get_client.return_value = _client([_acct()])

        data = json.loads(await get_debt_paydown())

        assert data["debt_free_date"] == "2028-01-01"
        assert data["excluded_accounts"] == []
        assert data["included_accounts"][0]["apr"] == 20.0

    @patch('monarch_mcp_server.tools.debt.get_monarch_client')
    async def test_excluded_accounts_are_separated_and_totalled(self, mock_get_client):
        """An excluded high-APR balance must be visible, not folded into the plan.

        The plan's principal covers only included accounts, so without this the
        projection silently understates both cost and payoff time.
        """
        mock_get_client.return_value = _client([
            _acct(),
            _acct(id="a2", displayName="High APR", displayBalance=500.0,
                  apr=29.5, excludeFromDebtPaydown=True),
        ])

        data = json.loads(await get_debt_paydown())

        assert data["total_debt_across_accounts"] == 1500.0
        assert data["debt_in_plan"] == 1000.0
        assert data["debt_excluded_from_plan"] == 500.0
        assert data["excluded_accounts"][0]["name"] == "High APR"

    @patch('monarch_mcp_server.tools.debt.get_monarch_client')
    async def test_method_is_passed_through(self, mock_get_client):
        client = _client([_acct()])
        mock_get_client.return_value = client

        await get_debt_paydown(method="avalanche")

        sent = client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent["debtPaydownMethod"] == "avalanche"

    @patch('monarch_mcp_server.tools.debt.get_monarch_client')
    async def test_error_handling(self, mock_get_client):
        c = AsyncMock()
        c.gql_call.side_effect = Exception("boom")
        mock_get_client.return_value = c

        data = json.loads(await get_debt_paydown())

        assert data["error"] is True
        assert data["tool"] == "get_debt_paydown"
