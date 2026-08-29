"""Tests for transaction summary MCP tools."""

import json
from unittest.mock import AsyncMock, patch

from monarch_mcp_server.helpers import LIMIT_LADDER, MAX_RESPONSE_CHARS
from monarch_mcp_server.tools.summaries import (
    get_spending_summary,
    get_transactions_summary,
)


def _client_with_merchants(count: int) -> AsyncMock:
    """A client whose aggregates hold *count* merchant rows and nothing else."""
    client = AsyncMock()
    client.gql_call.return_value = {
        "byCategory": [],
        "byCategoryGroup": [],
        "byMerchant": [
            {
                "groupBy": {
                    "merchant": {"id": f"mer-{i}", "name": f"Merchant {i}"},
                },
                "summary": {"sumIncome": 0.0, "sumExpense": -float(i)},
            }
            for i in range(1, count + 1)
        ],
        "summary": [],
    }
    return client


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

        assert data["limit"] is None

        categories = data["by_category"]
        assert (categories["total"], categories["returned"]) == (2, 2)
        assert categories["truncated"] is False
        assert categories["rows"][0]["category"] == "Salary"
        assert categories["rows"][0]["sum"] == 5000.0
        assert categories["rows"][1]["category"] == "Groceries"
        assert categories["rows"][1]["category_id"] == "cat-1"
        assert categories["rows"][1]["group_type"] == "expense"

        assert data["by_category_group"]["total"] == 1
        assert data["by_category_group"]["rows"][0]["group"] == "Food"

        assert data["by_merchant"]["total"] == 1
        assert data["by_merchant"]["rows"][0]["merchant"] == "Whole Foods"
        assert data["by_merchant"]["rows"][0]["expense"] == -320.0

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
        for key in ("by_category", "by_category_group", "by_merchant"):
            assert data[key] == {
                "total": 0,
                "returned": 0,
                "truncated": False,
                "rows": [],
            }
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
        assert data["by_category"]["rows"][0]["category"] == "Large"
        assert data["by_category"]["rows"][1]["category"] == "Small"

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
        assert data["by_category"]["rows"][0]["category"] is None
        assert data["by_category"]["rows"][0]["sum"] == -25.0

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_returns_every_merchant_that_fits(self, mock_get_client):
        """A response under the ceiling is never trimmed."""
        mock_get_client.return_value = _client_with_merchants(150)

        data = json.loads(await get_spending_summary())

        assert data["limit"] is None
        assert data["by_merchant"]["returned"] == 150
        assert data["by_merchant"]["truncated"] is False

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_trims_only_when_the_response_would_overflow(self, mock_get_client):
        """A full year runs to thousands of merchants and must still fit."""
        mock_get_client.return_value = _client_with_merchants(4000)

        raw = await get_spending_summary()
        data = json.loads(raw)

        assert len(raw) <= MAX_RESPONSE_CHARS
        assert data["limit"] in LIMIT_LADDER
        assert data["by_merchant"]["total"] == 4000
        assert data["by_merchant"]["truncated"] is True

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_ranks_merchants_by_income_as_well_as_expense(self, mock_get_client):
        """A big income merchant must not be dropped by expense-only ranking."""
        mock_client = _client_with_merchants(200)
        mock_client.gql_call.return_value["byMerchant"].append(
            {
                "groupBy": {"merchant": {"id": "big", "name": "Payroll"}},
                "summary": {"sumIncome": 90_000.0, "sumExpense": 0.0},
            }
        )
        mock_get_client.return_value = mock_client

        data = json.loads(await get_spending_summary(limit=3))

        assert data["by_merchant"]["rows"][0]["merchant"] == "Payroll"

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_explicit_limit_is_honoured(self, mock_get_client):
        mock_get_client.return_value = _client_with_merchants(150)

        data = json.loads(await get_spending_summary(limit=5))

        assert data["limit"] == 5
        assert data["by_merchant"]["returned"] == 5
        assert data["by_merchant"]["total"] == 150
        assert data["by_merchant"]["truncated"] is True

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_limit_zero_disables_trimming(self, mock_get_client):
        mock_get_client.return_value = _client_with_merchants(4000)

        data = json.loads(await get_spending_summary(limit=0))

        assert data["by_merchant"]["returned"] == 4000
        assert data["by_merchant"]["truncated"] is False

    @patch("monarch_mcp_server.tools.summaries.get_monarch_client")
    async def test_handles_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("Auth needed")

        result = await get_spending_summary()

        data = json.loads(result)
        assert data["error"] is True
        assert "Auth needed" in data["message"]
