"""Tests for financial-analysis MCP tools."""

import json

from monarch_mcp_server.tools.financial import get_cashflow


class TestGetCashflow:
    async def test_returns_cashflow_data(self):
        result = json.loads(await get_cashflow())
        assert result["cashflow"]["income"] == 5000.00
        assert result["cashflow"]["expenses"] == -3200.00

    async def test_passes_date_params(self, mock_monarch_client):
        await get_cashflow(start_date="2026-01-01", end_date="2026-01-31")
        mock_monarch_client.get_cashflow.assert_called_once_with(
            start_date="2026-01-01", end_date="2026-01-31"
        )

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_cashflow.side_effect = Exception("Cashflow error")
        result = await get_cashflow()
        assert "get_cashflow" in result
