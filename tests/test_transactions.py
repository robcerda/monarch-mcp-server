"""Tests for transaction-related MCP tools."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# Mock the monarchmoney module before importing server
import sys
sys.modules['monarchmoney'] = MagicMock()
sys.modules['monarchmoney'].MonarchMoney = MagicMock
sys.modules['monarchmoney'].RequireMFAException = Exception

from monarch_mcp_server.server import (
    get_transactions_needing_review,
    set_transaction_category,
    update_transaction_notes,
    mark_transaction_reviewed,
    bulk_categorize_transactions,
    search_transactions,
    get_transaction_details,
    delete_transaction,
    get_recurring_transactions,
)


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


class TestSetTransactionCategory:
    """Tests for set_transaction_category tool."""

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_set_category_with_mark_reviewed(self, mock_get_client):
        """Test setting category and marking as reviewed."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {
            "updateTransaction": {
                "transaction": {
                    "id": "txn_123",
                    "category": {"id": "cat_456", "name": "Groceries"},
                    "needsReview": False,
                }
            }
        }
        mock_get_client.return_value = mock_client

        result = set_transaction_category(
            transaction_id="txn_123",
            category_id="cat_456",
            mark_reviewed=True
        )

        # Verify API called with correct params
        call_kwargs = mock_client.update_transaction.call_args.kwargs
        assert call_kwargs["transaction_id"] == "txn_123"
        assert call_kwargs["category_id"] == "cat_456"
        assert call_kwargs["needs_review"] is False

        # Verify response
        data = json.loads(result)
        assert "updateTransaction" in data

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_set_category_without_mark_reviewed(self, mock_get_client):
        """Test setting category without marking as reviewed."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {"updateTransaction": {}}
        mock_get_client.return_value = mock_client

        set_transaction_category(
            transaction_id="txn_123",
            category_id="cat_456",
            mark_reviewed=False
        )

        # Verify needs_review was not passed
        call_kwargs = mock_client.update_transaction.call_args.kwargs
        assert "needs_review" not in call_kwargs

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_set_category_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = set_transaction_category("txn_123", "cat_456")

        assert "Error setting category" in result


class TestUpdateTransactionNotes:
    """Tests for update_transaction_notes tool."""

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_update_notes_simple(self, mock_get_client):
        """Test updating notes without receipt URL."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {"updateTransaction": {}}
        mock_get_client.return_value = mock_client

        update_transaction_notes(
            transaction_id="txn_123",
            notes="Business lunch with client"
        )

        call_kwargs = mock_client.update_transaction.call_args.kwargs
        assert call_kwargs["notes"] == "Business lunch with client"

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_update_notes_with_receipt(self, mock_get_client):
        """Test updating notes with receipt URL."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {"updateTransaction": {}}
        mock_get_client.return_value = mock_client

        update_transaction_notes(
            transaction_id="txn_123",
            notes="Office supplies",
            receipt_url="https://drive.google.com/file/abc123"
        )

        call_kwargs = mock_client.update_transaction.call_args.kwargs
        assert call_kwargs["notes"] == "[Receipt: https://drive.google.com/file/abc123] Office supplies"

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_update_notes_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = update_transaction_notes("txn_123", "test")

        assert "Error updating notes" in result


class TestMarkTransactionReviewed:
    """Tests for mark_transaction_reviewed tool."""

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_mark_reviewed_success(self, mock_get_client):
        """Test marking transaction as reviewed."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {
            "updateTransaction": {
                "transaction": {"id": "txn_123", "needsReview": False}
            }
        }
        mock_get_client.return_value = mock_client

        result = mark_transaction_reviewed(transaction_id="txn_123")

        call_kwargs = mock_client.update_transaction.call_args.kwargs
        assert call_kwargs["transaction_id"] == "txn_123"
        assert call_kwargs["needs_review"] is False

        data = json.loads(result)
        assert "updateTransaction" in data

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_mark_reviewed_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = mark_transaction_reviewed("txn_123")

        assert "Error marking reviewed" in result


class TestBulkCategorizeTransactions:
    """Tests for bulk_categorize_transactions tool."""

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_bulk_categorize_all_success(self, mock_get_client):
        """Test successful bulk categorization of all transactions."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {"updateTransaction": {}}
        mock_get_client.return_value = mock_client

        result = bulk_categorize_transactions(
            transaction_ids=["txn_1", "txn_2", "txn_3"],
            category_id="cat_123",
            mark_reviewed=True
        )

        data = json.loads(result)
        assert data["total"] == 3
        assert data["successful"] == 3
        assert data["failed"] == 0
        assert len(data["errors"]) == 0

        # Verify update_transaction was called 3 times
        assert mock_client.update_transaction.call_count == 3

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_bulk_categorize_partial_failure(self, mock_get_client):
        """Test bulk categorization with some failures."""
        mock_client = AsyncMock()
        # First call succeeds, second fails, third succeeds
        mock_client.update_transaction.side_effect = [
            {"updateTransaction": {}},
            RuntimeError("Transaction not found"),
            {"updateTransaction": {}},
        ]
        mock_get_client.return_value = mock_client

        result = bulk_categorize_transactions(
            transaction_ids=["txn_1", "txn_2", "txn_3"],
            category_id="cat_123"
        )

        data = json.loads(result)
        assert data["total"] == 3
        assert data["successful"] == 2
        assert data["failed"] == 1
        assert len(data["errors"]) == 1
        assert data["errors"][0]["transaction_id"] == "txn_2"

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_bulk_categorize_without_mark_reviewed(self, mock_get_client):
        """Test bulk categorization without marking as reviewed."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {"updateTransaction": {}}
        mock_get_client.return_value = mock_client

        bulk_categorize_transactions(
            transaction_ids=["txn_1"],
            category_id="cat_123",
            mark_reviewed=False
        )

        call_kwargs = mock_client.update_transaction.call_args.kwargs
        assert "needs_review" not in call_kwargs

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_bulk_categorize_empty_list(self, mock_get_client):
        """Test bulk categorization with empty transaction list."""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = bulk_categorize_transactions(
            transaction_ids=[],
            category_id="cat_123"
        )

        data = json.loads(result)
        assert data["total"] == 0
        assert data["successful"] == 0
        assert data["failed"] == 0

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_bulk_categorize_client_error(self, mock_get_client):
        """Test error when client cannot be obtained."""
        mock_get_client.side_effect = RuntimeError("Auth needed")

        result = bulk_categorize_transactions(
            transaction_ids=["txn_1"],
            category_id="cat_123"
        )

        assert "Error in bulk categorization" in result


class TestSearchTransactions:
    """Tests for search_transactions tool."""

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_search_with_text(self, mock_get_client):
        """Test text search."""
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
                        "needsReview": False,
                        "tags": [],
                    }
                ]
            }
        }
        mock_get_client.return_value = mock_client

        result = search_transactions(search="Amazon")

        call_kwargs = mock_client.get_transactions.call_args.kwargs
        assert call_kwargs["search"] == "Amazon"

        transactions = json.loads(result)
        assert len(transactions) == 1

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_search_with_multiple_filters(self, mock_get_client):
        """Test search with multiple filters."""
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {"results": []}
        }
        mock_get_client.return_value = mock_client

        search_transactions(
            search="coffee",
            start_date="2024-01-01",
            end_date="2024-01-31",
            category_ids=["cat_1"],
            account_ids=["acc_1"],
            has_notes=False,
            is_recurring=True
        )

        call_kwargs = mock_client.get_transactions.call_args.kwargs
        assert call_kwargs["search"] == "coffee"
        assert call_kwargs["start_date"] == "2024-01-01"
        assert call_kwargs["end_date"] == "2024-01-31"
        assert call_kwargs["category_ids"] == ["cat_1"]
        assert call_kwargs["account_ids"] == ["acc_1"]
        assert call_kwargs["has_notes"] is False
        assert call_kwargs["is_recurring"] is True

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_search_returns_full_details(self, mock_get_client):
        """Test that search returns full transaction details."""
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
                        "notes": "Gift",
                        "needsReview": True,
                        "pending": False,
                        "hideFromReports": False,
                        "isSplitTransaction": False,
                        "isRecurring": False,
                        "attachments": [{"id": "att_1"}],
                        "tags": [{"id": "tag_1", "name": "Personal"}],
                    }
                ]
            }
        }
        mock_get_client.return_value = mock_client

        result = search_transactions()

        transactions = json.loads(result)
        txn = transactions[0]
        assert txn["has_attachments"] is True
        assert txn["is_split"] is False
        assert txn["is_recurring"] is False
        assert len(txn["tags"]) == 1

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_search_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = search_transactions(search="test")

        assert "Error searching transactions" in result


class TestGetTransactionDetails:
    """Tests for get_transaction_details tool."""

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_get_details_success(self, mock_get_client):
        """Test successful retrieval of transaction details."""
        mock_client = AsyncMock()
        mock_client.get_transaction_details.return_value = {
            "getTransaction": {
                "id": "txn_123",
                "amount": -100.00,
                "date": "2024-01-15",
                "category": {"id": "cat_1", "name": "Shopping"},
                "attachments": [{"id": "att_1", "filename": "receipt.pdf"}],
                "splits": [],
            }
        }
        mock_get_client.return_value = mock_client

        result = get_transaction_details(transaction_id="txn_123")

        mock_client.get_transaction_details.assert_called_once_with(
            transaction_id="txn_123"
        )

        data = json.loads(result)
        assert "getTransaction" in data

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_get_details_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("Transaction not found")

        result = get_transaction_details("txn_invalid")

        assert "Error getting transaction details" in result


class TestDeleteTransaction:
    """Tests for delete_transaction tool."""

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_delete_success(self, mock_get_client):
        """Test successful transaction deletion."""
        mock_client = AsyncMock()
        mock_client.delete_transaction.return_value = {
            "deleteTransaction": {"deleted": True}
        }
        mock_get_client.return_value = mock_client

        result = delete_transaction(transaction_id="txn_123")

        mock_client.delete_transaction.assert_called_once_with(
            transaction_id="txn_123"
        )

        data = json.loads(result)
        assert data["deleteTransaction"]["deleted"] is True

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_delete_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("Cannot delete")

        result = delete_transaction("txn_123")

        assert "Error deleting transaction" in result


class TestGetRecurringTransactions:
    """Tests for get_recurring_transactions tool."""

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_get_recurring_success(self, mock_get_client):
        """Test successful retrieval of recurring transactions."""
        mock_client = AsyncMock()
        mock_client.get_recurring_transactions.return_value = {
            "recurringTransactionItems": [
                {
                    "date": "2024-02-01",
                    "amount": -15.99,
                    "isPast": False,
                    "transactionId": None,
                    "stream": {
                        "id": "stream_1",
                        "frequency": "monthly",
                        "amount": -15.99,
                        "isApproximate": False,
                        "merchant": {"name": "Netflix"},
                    },
                    "category": {"name": "Entertainment"},
                    "account": {"displayName": "Credit Card"},
                }
            ]
        }
        mock_get_client.return_value = mock_client

        result = get_recurring_transactions()

        recurring = json.loads(result)
        assert len(recurring) == 1
        assert recurring[0]["amount"] == -15.99
        assert recurring[0]["stream"]["merchant"] == "Netflix"
        assert recurring[0]["stream"]["frequency"] == "monthly"

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_get_recurring_with_dates(self, mock_get_client):
        """Test with custom date range."""
        mock_client = AsyncMock()
        mock_client.get_recurring_transactions.return_value = {
            "recurringTransactionItems": []
        }
        mock_get_client.return_value = mock_client

        get_recurring_transactions(
            start_date="2024-02-01",
            end_date="2024-02-29"
        )

        call_kwargs = mock_client.get_recurring_transactions.call_args.kwargs
        assert call_kwargs["start_date"] == "2024-02-01"
        assert call_kwargs["end_date"] == "2024-02-29"

    @patch('monarch_mcp_server.server.get_monarch_client')
    def test_get_recurring_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = get_recurring_transactions()

        assert "Error getting recurring transactions" in result
