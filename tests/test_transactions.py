"""Tests for transaction-related MCP tools."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# Mock the monarchmoney module before importing server
import sys
sys.modules['monarchmoney'] = MagicMock()
sys.modules['monarchmoney'].MonarchMoney = MagicMock
sys.modules['monarchmoney'].RequireMFAException = Exception

from monarch_mcp_server.server import get_transactions_needing_review


class TestGetTransactionsNeedingReview:
    """Tests for get_transactions_needing_review tool."""

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_get_transactions_needs_review_filter(self, mock_get_client):
        """Test filtering by needs_review flag."""
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {
                "results": [
                    {
                        "id": "txn_1",
                        "date": "2024-01-15",
                        "amount": -50.00,
                        "merchant": {"name": "Amazon"},
                        "category": {"id": "cat_1", "name": "Shopping"},
                        "account": {"id": "acc_1", "displayName": "Checking"},
                        "needsReview": True,
                        "notes": None,
                        "tags": [],
                    },
                    {
                        "id": "txn_2",
                        "date": "2024-01-14",
                        "amount": -25.00,
                        "merchant": {"name": "Starbucks"},
                        "category": {"id": "cat_2", "name": "Coffee"},
                        "account": {"id": "acc_1", "displayName": "Checking"},
                        "needsReview": False,
                        "notes": "Morning coffee",
                        "tags": [],
                    },
                ]
            }
        }
        mock_get_client.return_value = mock_client

        result = get_transactions_needing_review(needs_review=True)

        transactions = json.loads(result)
        assert len(transactions) == 1
        assert transactions[0]["id"] == "txn_1"
        assert transactions[0]["needs_review"] is True

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_get_transactions_uncategorized_filter(self, mock_get_client):
        """Test filtering for uncategorized transactions."""
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {
                "results": [
                    {
                        "id": "txn_1",
                        "date": "2024-01-15",
                        "amount": -50.00,
                        "merchant": {"name": "Unknown Store"},
                        "category": None,
                        "account": {"id": "acc_1", "displayName": "Checking"},
                        "needsReview": True,
                        "notes": None,
                        "tags": [],
                    },
                    {
                        "id": "txn_2",
                        "date": "2024-01-14",
                        "amount": -25.00,
                        "merchant": {"name": "Grocery Store"},
                        "category": {"id": "cat_1", "name": "Groceries"},
                        "account": {"id": "acc_1", "displayName": "Checking"},
                        "needsReview": True,
                        "notes": None,
                        "tags": [],
                    },
                ]
            }
        }
        mock_get_client.return_value = mock_client

        result = get_transactions_needing_review(
            needs_review=True,
            uncategorized_only=True
        )

        transactions = json.loads(result)
        assert len(transactions) == 1
        assert transactions[0]["id"] == "txn_1"
        assert transactions[0]["category"] is None

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_get_transactions_with_days_filter(self, mock_get_client):
        """Test filtering by days parameter."""
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {"results": []}
        }
        mock_get_client.return_value = mock_client

        result = get_transactions_needing_review(days=7, needs_review=False)

        # Verify the API was called with date filters
        call_kwargs = mock_client.get_transactions.call_args.kwargs
        assert "start_date" in call_kwargs
        assert "end_date" in call_kwargs

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_get_transactions_full_details(self, mock_get_client):
        """Test that full transaction details are returned."""
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {
                "results": [
                    {
                        "id": "txn_1",
                        "date": "2024-01-15",
                        "amount": -50.00,
                        "merchant": {"name": "Amazon"},
                        "plaidName": "AMAZON.COM*1234",
                        "category": {"id": "cat_1", "name": "Shopping"},
                        "account": {"id": "acc_1", "displayName": "Checking"},
                        "needsReview": True,
                        "pending": False,
                        "hideFromReports": False,
                        "notes": "Test note",
                        "tags": [{"id": "tag_1", "name": "Online"}],
                    },
                ]
            }
        }
        mock_get_client.return_value = mock_client

        result = get_transactions_needing_review(needs_review=True)

        transactions = json.loads(result)
        assert len(transactions) == 1
        txn = transactions[0]
        assert txn["id"] == "txn_1"
        assert txn["merchant"] == "Amazon"
        assert txn["original_name"] == "AMAZON.COM*1234"
        assert txn["category"] == "Shopping"
        assert txn["category_id"] == "cat_1"
        assert txn["account"] == "Checking"
        assert txn["account_id"] == "acc_1"
        assert txn["notes"] == "Test note"
        assert txn["is_pending"] is False
        assert txn["hide_from_reports"] is False
        assert len(txn["tags"]) == 1
        assert txn["tags"][0]["name"] == "Online"

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_get_transactions_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("Auth needed")

        result = get_transactions_needing_review()

        assert "Error getting transactions" in result
        assert "Auth needed" in result

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_get_transactions_empty(self, mock_get_client):
        """Test when no transactions match criteria."""
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {"results": []}
        }
        mock_get_client.return_value = mock_client

        result = get_transactions_needing_review()

        transactions = json.loads(result)
        assert len(transactions) == 0
