"""Tests for budget-related MCP tools."""

import json

from monarch_mcp_server.tools.budgets import get_budgets


class TestGetBudgets:
    async def test_returns_raw_budget_data(self):
        result = json.loads(await get_budgets())
        assert "budgetData" in result
        categories = result["budgetData"]["monthlyAmountsByCategory"]
        assert len(categories) == 2
        assert categories[0]["category"]["name"] == "Groceries"

    async def test_passes_date_params(self, mock_monarch_client):
        await get_budgets(start_date="2026-03-01", end_date="2026-03-31")
        mock_monarch_client.get_budgets.assert_called_once_with(
            start_date="2026-03-01", end_date="2026-03-31"
        )

    async def test_passes_none_dates_by_default(self, mock_monarch_client):
        await get_budgets()
        mock_monarch_client.get_budgets.assert_called_once_with(
            start_date=None, end_date=None
        )

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_budgets.side_effect = Exception("Budget error")
        result = await get_budgets()
        assert "get_budgets" in result
