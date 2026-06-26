"""Tests for budget-related MCP tools."""

import json

from monarch_mcp_server.tools.budgets import get_budgets


class TestGetBudgets:
    async def test_returns_formatted_category_rows(self):
        result = json.loads(await get_budgets())
        assert isinstance(result, list)
        assert len(result) == 2
        groceries = next(row for row in result if row["id"] == "cat-1")
        assert groceries == {
            "id": "cat-1",
            "name": "Groceries",
            "planned": 500.00,
            "actual": 320.00,
            "remaining": 180.00,
            "category_group": "Food",
            "month": "2026-03-01",
        }

    async def test_passes_explicit_date_params(self, mock_monarch_client):
        await get_budgets(start_date="2026-03-01", end_date="2026-03-31")
        _, kwargs = mock_monarch_client.gql_call.call_args
        assert kwargs["variables"] == {
            "startDate": "2026-03-01",
            "endDate": "2026-03-31",
        }

    async def test_defaults_to_current_month(self, mock_monarch_client):
        from monarch_mcp_server.tools.budgets import current_month_range

        start, end = current_month_range()
        await get_budgets()
        _, kwargs = mock_monarch_client.gql_call.call_args
        assert kwargs["variables"] == {"startDate": start, "endDate": end}

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.gql_call.side_effect = Exception("Budget error")
        result = await get_budgets()
        assert "get_budgets" in result
