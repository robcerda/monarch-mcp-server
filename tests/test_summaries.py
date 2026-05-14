"""Tests for transaction summary MCP tools."""

import json
from unittest.mock import AsyncMock, patch

from monarch_mcp_server.tools.summaries import (
    get_spending_summary,
    get_transactions_summary,
)


class TestGetTransactionsSummary:
    """Tests for get_transactions_summary tool."""

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_returns_summary(self, mock_get_client):
        """Test successful summary retrieval."""
        mock_client = AsyncMock()
        mock_client.get_transactions_summary.return_value = {
            "transactionCount": 142,
            "totalAmount": -3200.50,
        }
        mock_get_client.return_value = mock_client

        result = await get_transactions_summary()

        data = json.loads(result)
        assert data["transactionCount"] == 142
        assert data["totalAmount"] == -3200.50

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_handles_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("Auth needed")

        result = await get_transactions_summary()

        data = json.loads(result)
        assert data["error"] is True
        assert "Auth needed" in data["message"]


class TestGetSpendingSummary:
    """Tests for get_spending_summary tool."""

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_full_response(self, mock_get_client):
        """Test successful spending summary with all sections."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "byCategory": [
                {
                    "groupBy": {
                        "category": {
                            "id": "cat-1",
                            "name": "Groceries",
                            "icon": "cart",
                            "group": {"id": "grp-1", "type": "expense"},
                        }
                    },
                    "summary": {"sum": -450.0},
                },
                {
                    "groupBy": {
                        "category": {
                            "id": "cat-2",
                            "name": "Salary",
                            "icon": "money",
                            "group": {"id": "grp-2", "type": "income"},
                        }
                    },
                    "summary": {"sum": 5000.0},
                },
            ],
            "byCategoryGroup": [
                {
                    "groupBy": {
                        "categoryGroup": {
                            "id": "grp-1",
                            "name": "Food",
                            "type": "expense",
                        }
                    },
                    "summary": {"sum": -450.0},
                },
            ],
            "byMerchant": [
                {
                    "groupBy": {
                        "merchant": {
                            "id": "merch-1",
                            "name": "Whole Foods",
                            "logoUrl": "https://example.com/logo.png",
                        }
                    },
                    "summary": {"sumIncome": 0, "sumExpense": -320.0},
                },
            ],
            "summary": [
                {
                    "summary": {
                        "sumIncome": 5000.0,
                        "sumExpense": -450.0,
                        "savings": 4550.0,
                        "savingsRate": 0.91,
                    }
                }
            ],
        }
        mock_get_client.return_value = mock_client

        result = await get_spending_summary(
            start_date="2026-01-01", end_date="2026-01-31"
        )

        data = json.loads(result)
        assert data["period"]["start_date"] == "2026-01-01"
        assert data["period"]["end_date"] == "2026-01-31"
        assert data["total_income"] == 5000.0
        assert data["total_expenses"] == -450.0
        assert data["savings"] == 4550.0
        assert data["savings_rate"] == 0.91

        assert len(data["by_category"]) == 2
        assert data["by_category"][0]["category"] == "Salary"
        assert data["by_category"][0]["sum"] == 5000.0
        assert data["by_category"][1]["category"] == "Groceries"
        assert data["by_category"][1]["category_id"] == "cat-1"
        assert data["by_category"][1]["group_type"] == "expense"

        assert len(data["by_category_group"]) == 1
        assert data["by_category_group"][0]["group"] == "Food"

        assert len(data["by_merchant"]) == 1
        assert data["by_merchant"][0]["merchant"] == "Whole Foods"
        assert data["by_merchant"][0]["expense"] == -320.0

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_passes_date_filters(self, mock_get_client):
        """Test that date params are passed as filters to gql_call."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "byCategory": [],
            "byCategoryGroup": [],
            "byMerchant": [],
            "summary": [],
        }
        mock_get_client.return_value = mock_client

        await get_spending_summary(start_date="2026-03-01", end_date="2026-03-31")

        call_args = mock_client.gql_call.call_args
        variables = call_args.kwargs["variables"]
        assert variables["filters"]["startDate"] == "2026-03-01"
        assert variables["filters"]["endDate"] == "2026-03-31"

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_no_dates(self, mock_get_client):
        """Test calling without date filters."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "byCategory": [],
            "byCategoryGroup": [],
            "byMerchant": [],
            "summary": [],
        }
        mock_get_client.return_value = mock_client

        await get_spending_summary()

        call_args = mock_client.gql_call.call_args
        variables = call_args.kwargs["variables"]
        assert "startDate" not in variables["filters"]
        assert "endDate" not in variables["filters"]

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_empty_results(self, mock_get_client):
        """Test handling of empty aggregate results."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "byCategory": [],
            "byCategoryGroup": [],
            "byMerchant": [],
            "summary": [],
        }
        mock_get_client.return_value = mock_client

        result = await get_spending_summary()

        data = json.loads(result)
        assert data["by_category"] == []
        assert data["by_category_group"] == []
        assert data["by_merchant"] == []
        assert "total_income" not in data

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_sorts_by_absolute_value(self, mock_get_client):
        """Test that categories are sorted by absolute sum descending."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "byCategory": [
                {
                    "groupBy": {
                        "category": {
                            "id": "c1",
                            "name": "Small",
                            "icon": None,
                            "group": None,
                        }
                    },
                    "summary": {"sum": -10.0},
                },
                {
                    "groupBy": {
                        "category": {
                            "id": "c2",
                            "name": "Large",
                            "icon": None,
                            "group": None,
                        }
                    },
                    "summary": {"sum": -500.0},
                },
            ],
            "byCategoryGroup": [],
            "byMerchant": [],
            "summary": [],
        }
        mock_get_client.return_value = mock_client

        result = await get_spending_summary()

        data = json.loads(result)
        assert data["by_category"][0]["category"] == "Large"
        assert data["by_category"][1]["category"] == "Small"

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_handles_null_category(self, mock_get_client):
        """Test handling of null category in aggregates."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "byCategory": [
                {
                    "groupBy": {"category": None},
                    "summary": {"sum": -25.0},
                },
            ],
            "byCategoryGroup": [],
            "byMerchant": [],
            "summary": [],
        }
        mock_get_client.return_value = mock_client

        result = await get_spending_summary()

        data = json.loads(result)
        assert data["by_category"][0]["category"] is None
        assert data["by_category"][0]["sum"] == -25.0

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_handles_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("Auth needed")

        result = await get_spending_summary()

        data = json.loads(result)
        assert data["error"] is True
        assert "Auth needed" in data["message"]
