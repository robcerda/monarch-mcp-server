"""Tests for MCP tool functions with mocked API calls."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from monarch_mcp_server.server import (
    create_transaction,
    get_account_holdings,
    get_accounts,
    get_budgets,
    get_cashflow,
    get_transactions,
    refresh_accounts,
    update_transaction,
)


@pytest.fixture
def mock_monarch_client() -> MagicMock:
    """Create a mock MonarchMoney client."""
    client = MagicMock()
    client.get_accounts = AsyncMock()
    client.get_transactions = AsyncMock()
    client.get_budgets = AsyncMock()
    client.get_cashflow = AsyncMock()
    client.get_account_holdings = AsyncMock()
    client.create_transaction = AsyncMock()
    client.update_transaction = AsyncMock()
    client.request_accounts_refresh = AsyncMock()
    return client


class TestGetAccounts:
    """Tests for get_accounts tool."""

    def test_get_accounts_success(self, mock_monarch_client: MagicMock) -> None:
        """Test successful account retrieval."""
        mock_monarch_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "acc123",
                    "displayName": "Checking",
                    "type": {"name": "checking"},
                    "currentBalance": 1000.00,
                    "institution": {"name": "Test Bank"},
                    "isActive": True,
                }
            ]
        }

        with patch(
            "monarch_mcp_server.server.get_monarch_client",
            return_value=mock_monarch_client,
        ):
            result = get_accounts()

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["id"] == "acc123"
        assert data[0]["name"] == "Checking"
        assert data[0]["balance"] == 1000.00

    def test_get_accounts_auth_error(self) -> None:
        """Test that authentication errors are handled correctly."""
        with patch(
            "monarch_mcp_server.server.get_monarch_client",
            side_effect=RuntimeError(
                "Authentication needed! Run: python login_setup.py"
            ),
        ):
            result = get_accounts()

        assert "Authentication needed" in result


class TestGetTransactions:
    """Tests for get_transactions tool."""

    def test_get_transactions_with_defaults(
        self, mock_monarch_client: MagicMock
    ) -> None:
        """Test transaction retrieval with default parameters."""
        mock_monarch_client.get_transactions.return_value = {
            "allTransactions": {
                "results": [
                    {
                        "id": "txn123",
                        "date": "2024-01-15",
                        "amount": -50.00,
                        "description": "Coffee Shop",
                        "category": {"name": "Food"},
                        "account": {"displayName": "Checking"},
                        "merchant": {"name": "Starbucks"},
                        "isPending": False,
                    }
                ]
            }
        }

        with patch(
            "monarch_mcp_server.server.get_monarch_client",
            return_value=mock_monarch_client,
        ):
            result = get_transactions()

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["id"] == "txn123"
        assert data[0]["amount"] == -50.00

    def test_get_transactions_validation_error_limit(self) -> None:
        """Test that invalid limit returns validation error."""
        result = get_transactions(limit=0)
        assert "Validation error" in result
        assert "limit" in result

    def test_get_transactions_validation_error_offset(self) -> None:
        """Test that invalid offset returns validation error."""
        result = get_transactions(offset=-1)
        assert "Validation error" in result
        assert "offset" in result

    def test_get_transactions_validation_error_date(self) -> None:
        """Test that invalid date format returns validation error."""
        result = get_transactions(start_date="01-15-2024")
        assert "Validation error" in result
        assert "YYYY-MM-DD" in result


class TestGetCashflow:
    """Tests for get_cashflow tool."""

    def test_get_cashflow_validation_error_date(self) -> None:
        """Test that invalid date format returns validation error."""
        result = get_cashflow(start_date="invalid")
        assert "Validation error" in result


class TestCreateTransaction:
    """Tests for create_transaction tool."""

    def test_create_transaction_success(self, mock_monarch_client: MagicMock) -> None:
        """Test successful transaction creation."""
        mock_monarch_client.create_transaction.return_value = {
            "createTransaction": {"id": "new_txn_123"}
        }

        with patch(
            "monarch_mcp_server.server.get_monarch_client",
            return_value=mock_monarch_client,
        ):
            result = create_transaction(
                account_id="acc123",
                amount=-25.00,
                description="Test Transaction",
                date="2024-01-15",
            )

        data = json.loads(result)
        assert "createTransaction" in data

    def test_create_transaction_validation_error_date(self) -> None:
        """Test that invalid date returns validation error."""
        result = create_transaction(
            account_id="acc123",
            amount=-25.00,
            description="Test",
            date="invalid",
        )
        assert "Validation error" in result

    def test_create_transaction_validation_error_description_too_long(self) -> None:
        """Test that overly long description returns validation error."""
        result = create_transaction(
            account_id="acc123",
            amount=-25.00,
            description="x" * 600,
            date="2024-01-15",
        )
        assert "Validation error" in result
        assert "description" in result


class TestUpdateTransaction:
    """Tests for update_transaction tool."""

    def test_update_transaction_success(self, mock_monarch_client: MagicMock) -> None:
        """Test successful transaction update."""
        mock_monarch_client.update_transaction.return_value = {
            "updateTransaction": {"id": "txn123", "amount": -30.00}
        }

        with patch(
            "monarch_mcp_server.server.get_monarch_client",
            return_value=mock_monarch_client,
        ):
            result = update_transaction(
                transaction_id="txn123",
                amount=-30.00,
            )

        data = json.loads(result)
        assert "updateTransaction" in data

    def test_update_transaction_validation_error_date(self) -> None:
        """Test that invalid date returns validation error."""
        result = update_transaction(
            transaction_id="txn123",
            date="invalid",
        )
        assert "Validation error" in result

    def test_update_transaction_validation_error_description_too_long(self) -> None:
        """Test that overly long description returns validation error."""
        result = update_transaction(
            transaction_id="txn123",
            description="x" * 600,
        )
        assert "Validation error" in result


class TestRefreshAccounts:
    """Tests for refresh_accounts tool."""

    def test_refresh_accounts_success(self, mock_monarch_client: MagicMock) -> None:
        """Test successful account refresh."""
        mock_monarch_client.request_accounts_refresh.return_value = {
            "requestAccountsRefresh": {"success": True}
        }

        with patch(
            "monarch_mcp_server.server.get_monarch_client",
            return_value=mock_monarch_client,
        ):
            result = refresh_accounts()

        data = json.loads(result)
        assert data["requestAccountsRefresh"]["success"] is True
