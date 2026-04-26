"""Tests for account-related MCP tools."""

import json

from monarch_mcp_server.tools.accounts import (
    get_accounts,
    get_account_holdings,
    refresh_accounts,
)


class TestGetAccounts:
    async def test_returns_formatted_account_list(self):
        result = json.loads(await get_accounts())
        assert len(result) == 2
        assert result[0]["id"] == "acc-1"
        assert result[0]["name"] == "Checking Account"
        assert result[0]["type"] == "checking"
        assert result[0]["balance"] == 1500.00
        assert result[0]["institution"] == "Test Bank"
        assert result[0]["is_active"] is True
        assert result[0]["is_hidden"] is False

    async def test_hidden_account_flagged(self):
        result = json.loads(await get_accounts())
        assert result[1]["is_hidden"] is True

    async def test_handles_null_type(self, mock_monarch_client):
        mock_monarch_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "acc-3",
                    "displayName": "Unknown",
                    "type": None,
                    "currentBalance": 0,
                    "institution": None,
                    "deactivatedAt": None,
                    "isHidden": False,
                }
            ]
        }
        result = json.loads(await get_accounts())
        assert result[0]["type"] is None
        assert result[0]["institution"] is None

    async def test_handles_empty_accounts(self, mock_monarch_client):
        mock_monarch_client.get_accounts.return_value = {"accounts": []}
        result = json.loads(await get_accounts())
        assert result == []

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_accounts.side_effect = Exception("API timeout")
        result = await get_accounts()
        assert "get_accounts" in result
        assert "API timeout" in result


class TestGetAccountHoldings:
    async def test_returns_holdings(self):
        result = json.loads(await get_account_holdings("acc-1"))
        assert result["holdings"][0]["name"] == "VTI"
        assert result["holdings"][0]["value"] == 25000.00

    async def test_passes_account_id(self, mock_monarch_client):
        await get_account_holdings("acc-99")
        mock_monarch_client.get_account_holdings.assert_called_once_with("acc-99")

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_account_holdings.side_effect = Exception("Not found")
        result = await get_account_holdings("bad-id")
        assert "get_account_holdings" in result


class TestRefreshAccounts:
    async def test_refreshes_accounts(self):
        result = json.loads(await refresh_accounts())
        assert result["requestAccountsRefresh"]["success"] is True

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.request_accounts_refresh.side_effect = Exception("Timeout")
        result = await refresh_accounts()
        assert "refresh_accounts" in result
