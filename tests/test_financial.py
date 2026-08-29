"""Tests for financial-analysis MCP tools."""

import copy
import json

from monarch_mcp_server.tools.financial import (
    MAX_CASHFLOW_RESPONSE_CHARS,
    _CASHFLOW_LIMIT_LADDER,
    get_cashflow,
)


def _merchant_row(index: int, income: float, expense: float):
    """Build a raw byMerchant aggregate row, as upstream returns them."""
    return {
        "groupBy": {
            "merchant": {
                "id": f"mer-{index}",
                "name": f"Merchant {index}",
                "logoUrl": f"https://res.cloudinary.com/monarch-money/x/{index}",
                "__typename": "Merchant",
            },
            "__typename": "AggregateGroupBy",
        },
        "summary": {
            "sumIncome": income,
            "sumExpense": expense,
            "__typename": "TransactionsSummary",
        },
        "__typename": "AggregateData",
    }


class TestGetCashflow:
    async def test_returns_totals(self):
        result = json.loads(await get_cashflow())
        assert result["total_income"] == 5000.00
        assert result["total_expenses"] == -3200.00
        assert result["savings"] == 1800.00
        assert result["savings_rate"] == 0.36

    async def test_passes_date_params(self, mock_monarch_client):
        await get_cashflow(start_date="2026-01-01", end_date="2026-01-31")
        mock_monarch_client.get_cashflow.assert_called_once_with(
            start_date="2026-01-01", end_date="2026-01-31"
        )

    async def test_echoes_period(self):
        result = json.loads(
            await get_cashflow(start_date="2026-01-01", end_date="2026-01-31")
        )
        assert result["period"] == {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        }

    async def test_flattens_breakdown_rows(self):
        result = json.loads(await get_cashflow())

        groceries = next(
            row
            for row in result["by_category"]["rows"]
            if row["category"] == "Groceries"
        )
        assert groceries == {
            "category": "Groceries",
            "category_id": "cat-1",
            "icon": "🛒",
            "group_id": "grp-1",
            "group_type": "expense",
            "sum": -3200.00,
        }

        income_group = next(
            row
            for row in result["by_category_group"]["rows"]
            if row["group"] == "Income"
        )
        assert income_group == {
            "group": "Income",
            "group_id": "grp-2",
            "group_type": "income",
            "sum": 5000.00,
        }

        employer = next(
            row
            for row in result["by_merchant"]["rows"]
            if row["merchant"] == "Employer"
        )
        assert employer == {
            "merchant": "Employer",
            "merchant_id": "mer-2",
            "income": 5000.00,
            "expense": 0.00,
        }

    async def test_drops_graphql_noise(self):
        """__typename and merchant logo URLs are the bulk of the raw payload."""
        raw = await get_cashflow()
        assert "__typename" not in raw
        assert "cloudinary" not in raw
        assert "logoUrl" not in raw

    async def test_reports_counts_when_nothing_is_dropped(self):
        result = json.loads(await get_cashflow())
        assert result["limit"] is None
        assert result["by_merchant"]["total"] == 2
        assert result["by_merchant"]["returned"] == 2
        assert result["by_merchant"]["truncated"] is False

    async def test_returns_every_row_that_fits(self, mock_monarch_client):
        """A response under the ceiling is never trimmed."""
        payload = copy.deepcopy(mock_monarch_client.get_cashflow.return_value)
        payload["byMerchant"] = [
            _merchant_row(i, income=0.0, expense=-float(i)) for i in range(1, 127)
        ]
        mock_monarch_client.get_cashflow.return_value = payload

        result = json.loads(await get_cashflow())

        assert result["limit"] is None
        assert result["by_merchant"]["returned"] == 126
        assert result["by_merchant"]["truncated"] is False

    async def test_trims_only_when_the_response_would_overflow(
        self, mock_monarch_client
    ):
        payload = copy.deepcopy(mock_monarch_client.get_cashflow.return_value)
        payload["byMerchant"] = [
            _merchant_row(i, income=0.0, expense=-float(i)) for i in range(1, 4001)
        ]
        mock_monarch_client.get_cashflow.return_value = payload

        raw = await get_cashflow()
        result = json.loads(raw)

        assert len(raw) <= MAX_CASHFLOW_RESPONSE_CHARS
        assert result["limit"] in _CASHFLOW_LIMIT_LADDER
        assert result["by_merchant"]["total"] == 4000
        assert result["by_merchant"]["truncated"] is True
        # Trimmed to fit, not slashed to the floor.
        assert result["by_merchant"]["returned"] > 5

    async def test_caps_long_breakdowns_and_says_so(self, mock_monarch_client):
        payload = copy.deepcopy(mock_monarch_client.get_cashflow.return_value)
        payload["byMerchant"] = [
            _merchant_row(i, income=0.0, expense=-float(i)) for i in range(1, 101)
        ]
        mock_monarch_client.get_cashflow.return_value = payload

        result = json.loads(await get_cashflow(limit=5))

        assert result["limit"] == 5
        assert result["by_merchant"]["total"] == 100
        assert result["by_merchant"]["returned"] == 5
        assert result["by_merchant"]["truncated"] is True
        assert len(result["by_merchant"]["rows"]) == 5

    async def test_keeps_the_largest_rows_by_absolute_flow(self, mock_monarch_client):
        payload = copy.deepcopy(mock_monarch_client.get_cashflow.return_value)
        payload["byMerchant"] = [
            _merchant_row(i, income=0.0, expense=-float(i)) for i in range(1, 101)
        ]
        mock_monarch_client.get_cashflow.return_value = payload

        result = json.loads(await get_cashflow(limit=3))

        assert [row["merchant"] for row in result["by_merchant"]["rows"]] == [
            "Merchant 100",
            "Merchant 99",
            "Merchant 98",
        ]

    async def test_ranks_merchants_by_income_as_well_as_expense(
        self, mock_monarch_client
    ):
        """A big income merchant must not be dropped by expense-only ranking."""
        payload = copy.deepcopy(mock_monarch_client.get_cashflow.return_value)
        payload["byMerchant"] = [
            _merchant_row(i, income=0.0, expense=-float(i)) for i in range(1, 101)
        ] + [_merchant_row(999, income=50_000.0, expense=0.0)]
        mock_monarch_client.get_cashflow.return_value = payload

        result = json.loads(await get_cashflow(limit=3))

        assert result["by_merchant"]["rows"][0]["merchant"] == "Merchant 999"

    async def test_limit_zero_returns_everything(self, mock_monarch_client):
        payload = copy.deepcopy(mock_monarch_client.get_cashflow.return_value)
        payload["byMerchant"] = [
            _merchant_row(i, income=0.0, expense=-float(i)) for i in range(1, 101)
        ]
        mock_monarch_client.get_cashflow.return_value = payload

        result = json.loads(await get_cashflow(limit=0))

        assert result["by_merchant"]["returned"] == 100
        assert result["by_merchant"]["truncated"] is False

    async def test_stays_under_the_ceiling_for_a_realistic_payload(
        self, mock_monarch_client
    ):
        """The original bug: one real month blew past the MCP response ceiling."""
        payload = copy.deepcopy(mock_monarch_client.get_cashflow.return_value)
        payload["byMerchant"] = [
            _merchant_row(i, income=0.0, expense=-float(i)) for i in range(1, 127)
        ]
        mock_monarch_client.get_cashflow.return_value = payload

        assert len(await get_cashflow()) <= MAX_CASHFLOW_RESPONSE_CHARS

    async def test_handles_unrecognized_payload_shape(self, mock_monarch_client):
        mock_monarch_client.get_cashflow.return_value = {
            "somethingNew": [{"value": 1, "__typename": "Whatever"}]
        }

        result = json.loads(await get_cashflow())

        assert result["somethingNew"] == [{"value": 1}]

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_cashflow.side_effect = Exception("Cashflow error")
        result = await get_cashflow()
        assert "get_cashflow" in result
