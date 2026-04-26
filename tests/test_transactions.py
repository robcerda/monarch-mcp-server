"""Tests for transaction-related MCP tools."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from monarch_mcp_server.tools.transactions import (
    get_transactions,
    create_transaction,
    update_transaction,
    categorize_transaction,
    get_transactions_needing_review,
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

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_get_transactions_needs_review_filter(self, mock_get_client):
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

        result = await get_transactions_needing_review(needs_review=True)

        transactions = json.loads(result)
        assert len(transactions) == 1
        assert transactions[0]["id"] == "txn_1"
        assert transactions[0]["needs_review"] is True

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_get_transactions_uncategorized_filter(self, mock_get_client):
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

        result = await get_transactions_needing_review(
            needs_review=True,
            uncategorized_only=True
        )

        transactions = json.loads(result)
        assert len(transactions) == 1
        assert transactions[0]["id"] == "txn_1"
        assert transactions[0]["category"] is None

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_get_transactions_with_days_filter(self, mock_get_client):
        """Test filtering by days parameter."""
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {"results": []}
        }
        mock_get_client.return_value = mock_client

        result = await get_transactions_needing_review(days=7, needs_review=False)

        # Verify the API was called with date filters
        call_kwargs = mock_client.get_transactions.call_args.kwargs
        assert "start_date" in call_kwargs
        assert "end_date" in call_kwargs

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_get_transactions_full_details(self, mock_get_client):
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

        result = await get_transactions_needing_review(needs_review=True)

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

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_get_transactions_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("Auth needed")

        result = await get_transactions_needing_review()

        data = json.loads(result)
        assert data["error"] is True
        assert "Auth needed" in data["message"]

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_get_transactions_empty(self, mock_get_client):
        """Test when no transactions match criteria."""
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {"results": []}
        }
        mock_get_client.return_value = mock_client

        result = await get_transactions_needing_review()

        transactions = json.loads(result)
        assert len(transactions) == 0


class TestUpdateTransactionNotes:
    """Tests for update_transaction_notes tool."""

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_update_notes_simple(self, mock_get_client):
        """Test updating notes without receipt URL."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {"updateTransaction": {}}
        mock_get_client.return_value = mock_client

        await update_transaction_notes(
            transaction_id="txn_123",
            notes="Business lunch with client"
        )

        call_kwargs = mock_client.update_transaction.call_args.kwargs
        assert call_kwargs["notes"] == "Business lunch with client"

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_update_notes_with_receipt(self, mock_get_client):
        """Test updating notes with receipt URL."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {"updateTransaction": {}}
        mock_get_client.return_value = mock_client

        await update_transaction_notes(
            transaction_id="txn_123",
            notes="Office supplies",
            receipt_url="https://drive.google.com/file/abc123"
        )

        call_kwargs = mock_client.update_transaction.call_args.kwargs
        assert call_kwargs["notes"] == "[Receipt: https://drive.google.com/file/abc123] Office supplies"

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_update_notes_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = await update_transaction_notes("txn_123", "test")

        data = json.loads(result)
        assert data["error"] is True
        assert "API error" in data["message"]


class TestMarkTransactionReviewed:
    """Tests for mark_transaction_reviewed tool."""

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_mark_reviewed_success(self, mock_get_client):
        """Test marking transaction as reviewed."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {
            "updateTransaction": {
                "transaction": {"id": "txn_123", "needsReview": False}
            }
        }
        mock_get_client.return_value = mock_client

        result = await mark_transaction_reviewed(transaction_id="txn_123")

        call_kwargs = mock_client.update_transaction.call_args.kwargs
        assert call_kwargs["transaction_id"] == "txn_123"
        assert call_kwargs["needs_review"] is False

        data = json.loads(result)
        assert "updateTransaction" in data

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_mark_reviewed_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = await mark_transaction_reviewed("txn_123")

        data = json.loads(result)
        assert data["error"] is True
        assert "API error" in data["message"]


class TestBulkCategorizeTransactions:
    """Tests for bulk_categorize_transactions tool."""

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_bulk_categorize_all_success(self, mock_get_client):
        """Test successful bulk categorization of all transactions."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {"updateTransaction": {}}
        mock_get_client.return_value = mock_client

        result = await bulk_categorize_transactions(
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

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_bulk_categorize_partial_failure(self, mock_get_client):
        """Test bulk categorization with some failures."""
        mock_client = AsyncMock()
        # First call succeeds, second fails, third succeeds
        mock_client.update_transaction.side_effect = [
            {"updateTransaction": {}},
            RuntimeError("Transaction not found"),
            {"updateTransaction": {}},
        ]
        mock_get_client.return_value = mock_client

        result = await bulk_categorize_transactions(
            transaction_ids=["txn_1", "txn_2", "txn_3"],
            category_id="cat_123"
        )

        data = json.loads(result)
        assert data["total"] == 3
        assert data["successful"] == 2
        assert data["failed"] == 1
        assert len(data["errors"]) == 1
        assert data["errors"][0]["transaction_id"] == "txn_2"

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_bulk_categorize_without_mark_reviewed(self, mock_get_client):
        """Test bulk categorization without marking as reviewed."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {"updateTransaction": {}}
        mock_get_client.return_value = mock_client

        await bulk_categorize_transactions(
            transaction_ids=["txn_1"],
            category_id="cat_123",
            mark_reviewed=False
        )

        call_kwargs = mock_client.update_transaction.call_args.kwargs
        assert "needs_review" not in call_kwargs

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_bulk_categorize_empty_list(self, mock_get_client):
        """Test bulk categorization with empty transaction list."""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await bulk_categorize_transactions(
            transaction_ids=[],
            category_id="cat_123"
        )

        data = json.loads(result)
        assert data["total"] == 0
        assert data["successful"] == 0
        assert data["failed"] == 0

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_bulk_categorize_client_error(self, mock_get_client):
        """Test error when client cannot be obtained."""
        mock_get_client.side_effect = RuntimeError("Auth needed")

        result = await bulk_categorize_transactions(
            transaction_ids=["txn_1"],
            category_id="cat_123"
        )

        data = json.loads(result)
        assert data["error"] is True
        assert "Auth needed" in data["message"]


class TestSearchTransactions:
    """Tests for search_transactions tool."""

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_search_with_text(self, mock_get_client):
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

        result = await search_transactions(search="Amazon")

        call_kwargs = mock_client.get_transactions.call_args.kwargs
        assert call_kwargs["search"] == "Amazon"

        transactions = json.loads(result)
        assert len(transactions) == 1

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_search_with_multiple_filters(self, mock_get_client):
        """Test search with multiple filters."""
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {"results": []}
        }
        mock_get_client.return_value = mock_client

        await search_transactions(
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

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_search_returns_full_details(self, mock_get_client):
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

        result = await search_transactions()

        transactions = json.loads(result)
        txn = transactions[0]
        assert txn["has_attachments"] is True
        assert txn["is_split"] is False
        assert txn["is_recurring"] is False
        assert len(txn["tags"]) == 1

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_search_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = await search_transactions(search="test")

        data = json.loads(result)
        assert data["error"] is True
        assert "API error" in data["message"]


class TestGetTransactionDetails:
    """Tests for get_transaction_details tool."""

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_get_details_success(self, mock_get_client):
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

        result = await get_transaction_details(transaction_id="txn_123")

        mock_client.get_transaction_details.assert_called_once_with(
            transaction_id="txn_123"
        )

        data = json.loads(result)
        assert "getTransaction" in data

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_get_details_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("Transaction not found")

        result = await get_transaction_details("txn_invalid")

        data = json.loads(result)
        assert data["error"] is True
        assert "Transaction not found" in data["message"]


class TestDeleteTransaction:
    """Tests for delete_transaction tool."""

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_delete_success(self, mock_get_client):
        """Test successful transaction deletion."""
        mock_client = AsyncMock()
        mock_client.delete_transaction.return_value = {
            "deleteTransaction": {"deleted": True}
        }
        mock_get_client.return_value = mock_client

        result = await delete_transaction(transaction_id="txn_123")

        mock_client.delete_transaction.assert_called_once_with(
            transaction_id="txn_123"
        )

        data = json.loads(result)
        assert data["deleteTransaction"]["deleted"] is True

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_delete_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("Cannot delete")

        result = await delete_transaction("txn_123")

        data = json.loads(result)
        assert data["error"] is True
        assert "Cannot delete" in data["message"]


class TestGetRecurringTransactions:
    """Tests for get_recurring_transactions tool."""

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_get_recurring_success(self, mock_get_client):
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

        result = await get_recurring_transactions()

        recurring = json.loads(result)
        assert len(recurring) == 1
        assert recurring[0]["amount"] == -15.99
        assert recurring[0]["stream"]["merchant"] == "Netflix"
        assert recurring[0]["stream"]["frequency"] == "monthly"

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_get_recurring_with_dates(self, mock_get_client):
        """Test with custom date range."""
        mock_client = AsyncMock()
        mock_client.get_recurring_transactions.return_value = {
            "recurringTransactionItems": []
        }
        mock_get_client.return_value = mock_client

        await get_recurring_transactions(
            start_date="2024-02-01",
            end_date="2024-02-29"
        )

        call_kwargs = mock_client.get_recurring_transactions.call_args.kwargs
        assert call_kwargs["start_date"] == "2024-02-01"
        assert call_kwargs["end_date"] == "2024-02-29"

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_get_recurring_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = await get_recurring_transactions()

        data = json.loads(result)
        assert data["error"] is True
        assert "API error" in data["message"]


class TestGetTransactions:
    async def test_returns_formatted_transactions(self):
        result = json.loads(await get_transactions())
        assert len(result) == 2
        assert result[0]["id"] == "txn-1"
        assert result[0]["amount"] == -42.50
        assert result[0]["category"] == "Groceries"
        assert result[0]["category_id"] == "cat-1"
        assert result[0]["account_id"] == "acc-1"
        assert result[0]["merchant"] == "Whole Foods"
        assert result[0]["needs_review"] is True
        assert result[0]["notes"] == "weekly groceries"
        assert result[0]["is_recurring"] is False
        assert result[0]["review_status"] == "needs_review"
        assert result[0]["is_split_transaction"] is False
        assert result[0]["hide_from_reports"] is False
        assert result[0]["tags"] == [{"id": "tag-1", "name": "business"}]

    async def test_handles_null_merchant(self):
        result = json.loads(await get_transactions())
        assert result[1]["merchant"] is None
        assert result[1]["notes"] is None
        assert result[1]["needs_review"] is False
        assert result[1]["tags"] == []

    async def test_handles_null_category(self, mock_monarch_client):
        mock_monarch_client.get_transactions.return_value = {
            "allTransactions": {
                "results": [
                    {
                        "id": "txn-3",
                        "date": "2026-03-03",
                        "amount": -10.00,
                        "description": "ATM",
                        "category": None,
                        "account": {"id": "acc-1", "displayName": "Checking"},
                        "merchant": None,
                        "isPending": True,
                        "needsReview": False,
                        "notes": None,
                        "isRecurring": False,
                        "reviewStatus": None,
                        "isSplitTransaction": False,
                        "hideFromReports": False,
                        "tags": [],
                    }
                ]
            }
        }
        result = json.loads(await get_transactions())
        assert result[0]["category"] is None
        assert result[0]["category_id"] is None
        assert result[0]["is_pending"] is True

    async def test_passes_filters_to_client(self, mock_monarch_client):
        await get_transactions(
            limit=10, offset=5, start_date="2026-03-01", account_id="acc-1"
        )
        mock_monarch_client.get_transactions.assert_called_once_with(
            limit=10,
            offset=5,
            start_date="2026-03-01",
            account_ids=["acc-1"],
        )

    async def test_account_id_backward_compat(self, mock_monarch_client):
        await get_transactions(account_id="acc-1")
        mock_monarch_client.get_transactions.assert_called_once_with(
            limit=100, offset=0, account_ids=["acc-1"]
        )

    async def test_account_id_merged_with_account_ids(self, mock_monarch_client):
        await get_transactions(account_id="acc-1", account_ids=["acc-2"])
        mock_monarch_client.get_transactions.assert_called_once_with(
            limit=100, offset=0, account_ids=["acc-2", "acc-1"]
        )

    async def test_account_id_not_duplicated(self, mock_monarch_client):
        await get_transactions(account_id="acc-1", account_ids=["acc-1"])
        mock_monarch_client.get_transactions.assert_called_once_with(
            limit=100, offset=0, account_ids=["acc-1"]
        )

    async def test_search_filter(self, mock_monarch_client):
        await get_transactions(search="order-123")
        mock_monarch_client.get_transactions.assert_called_once_with(
            limit=100, offset=0, search="order-123"
        )

    async def test_boolean_filters(self, mock_monarch_client):
        await get_transactions(has_notes=True, is_split=False, is_recurring=True)
        mock_monarch_client.get_transactions.assert_called_once_with(
            limit=100, offset=0, has_notes=True, is_split=False, is_recurring=True
        )

    async def test_list_filters(self, mock_monarch_client):
        await get_transactions(category_ids=["cat-1"], tag_ids=["tag-1", "tag-2"])
        mock_monarch_client.get_transactions.assert_called_once_with(
            limit=100, offset=0, category_ids=["cat-1"], tag_ids=["tag-1", "tag-2"]
        )

    async def test_handles_empty_transactions(self, mock_monarch_client):
        mock_monarch_client.get_transactions.return_value = {
            "allTransactions": {"results": []}
        }
        result = json.loads(await get_transactions())
        assert result == []

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transactions.side_effect = Exception("Auth expired")
        result = await get_transactions()
        assert "get_transactions" in result


class TestCreateTransaction:
    async def test_creates_transaction(self):
        result = json.loads(
            await create_transaction(
                date="2026-03-15",
                account_id="acc-1",
                amount=-25.00,
                merchant_name="Coffee Shop",
                category_id="cat-1",
            )
        )
        assert "createTransaction" in result

    async def test_passes_all_params(self, mock_monarch_client):
        await create_transaction(
            date="2026-03-15",
            account_id="acc-1",
            amount=-25.00,
            merchant_name="Coffee Shop",
            category_id="cat-1",
            notes="Morning coffee",
            update_balance=True,
        )
        mock_monarch_client.create_transaction.assert_called_once_with(
            date="2026-03-15",
            account_id="acc-1",
            amount=-25.00,
            merchant_name="Coffee Shop",
            category_id="cat-1",
            notes="Morning coffee",
            update_balance=True,
        )

    async def test_omits_optional_params_when_not_set(self, mock_monarch_client):
        await create_transaction(
            date="2026-03-15",
            account_id="acc-1",
            amount=-25.00,
            merchant_name="Store",
            category_id="cat-1",
        )
        mock_monarch_client.create_transaction.assert_called_once_with(
            date="2026-03-15",
            account_id="acc-1",
            amount=-25.00,
            merchant_name="Store",
            category_id="cat-1",
        )

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.create_transaction.side_effect = Exception("Bad request")
        result = await create_transaction(
            date="2026-03-15",
            account_id="acc-1",
            amount=-25.00,
            merchant_name="Store",
            category_id="cat-1",
        )
        assert "create_transaction" in result


class TestUpdateTransaction:
    async def test_updates_transaction(self):
        result = json.loads(await update_transaction("txn-1", category_id="cat-2"))
        assert "updateTransaction" in result

    async def test_passes_only_provided_fields(self, mock_monarch_client):
        await update_transaction("txn-1", amount=99.99, notes="Updated")
        mock_monarch_client.update_transaction.assert_called_once_with(
            transaction_id="txn-1", amount=99.99, notes="Updated"
        )

    async def test_passes_all_fields(self, mock_monarch_client):
        await update_transaction(
            "txn-1",
            category_id="cat-2",
            merchant_name="New Merchant",
            goal_id="goal-1",
            amount=50.00,
            date="2026-04-01",
            hide_from_reports=True,
            needs_review=False,
            notes="All fields",
        )
        mock_monarch_client.update_transaction.assert_called_once_with(
            transaction_id="txn-1",
            category_id="cat-2",
            merchant_name="New Merchant",
            goal_id="goal-1",
            amount=50.00,
            date="2026-04-01",
            hide_from_reports=True,
            needs_review=False,
            notes="All fields",
        )

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.update_transaction.side_effect = Exception("Not found")
        result = await update_transaction("bad-id")
        assert "update_transaction" in result


class TestCategorizeTransaction:
    async def test_categorizes(self, mock_monarch_client):
        result = json.loads(await categorize_transaction("txn-1", "cat-2"))
        assert "updateTransaction" in result
        mock_monarch_client.update_transaction.assert_called_once_with(
            transaction_id="txn-1", category_id="cat-2"
        )

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.update_transaction.side_effect = Exception("boom")
        result = await categorize_transaction("txn-1", "cat-2")
        assert "categorize_transaction" in result

