"""Tests for transaction-related MCP tools."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

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

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_needs_review_flag_is_delegated_to_monarch(self, mock_get_client):
        """The flag is sent upstream rather than applied to the page here."""
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

        # The filter is Monarch's job now, so the mocked page is returned as
        # given. What matters is that the flag was actually sent upstream.
        assert mock_client.get_transactions.call_args.kwargs["needs_review"] is True
        envelope = json.loads(result)
        assert envelope["count"] == 2

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
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
            needs_review=True, uncategorized_only=True
        )

        envelope = json.loads(result)
        transactions = envelope["data"]
        assert len(transactions) == 1
        assert transactions[0]["id"] == "txn_1"
        assert transactions[0]["category"] is None

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_get_transactions_with_days_filter(self, mock_get_client):
        """Test filtering by days parameter."""
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {"allTransactions": {"results": []}}
        mock_get_client.return_value = mock_client

        result = await get_transactions_needing_review(days=7, needs_review=False)

        # Verify the API was called with date filters
        call_kwargs = mock_client.get_transactions.call_args.kwargs
        assert "start_date" in call_kwargs
        assert "end_date" in call_kwargs

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
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

        transactions = json.loads(result)["data"]
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

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_get_transactions_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("Auth needed")

        result = await get_transactions_needing_review()

        data = json.loads(result)
        assert data["error"] is True
        assert "Auth needed" in data["message"]

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_get_transactions_empty(self, mock_get_client):
        """Test when no transactions match criteria."""
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {"allTransactions": {"results": []}}
        mock_get_client.return_value = mock_client

        result = await get_transactions_needing_review()

        envelope = json.loads(result)
        assert envelope["count"] == 0
        assert envelope["data"] == []


class TestUpdateTransactionNotes:
    """Tests for update_transaction_notes tool."""

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_update_notes_simple(self, mock_get_client):
        """Test updating notes without receipt URL."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {"updateTransaction": {}}
        mock_get_client.return_value = mock_client

        await update_transaction_notes(
            transaction_id="txn_123", notes="Business lunch with client"
        )

        call_kwargs = mock_client.update_transaction.call_args.kwargs
        assert call_kwargs["notes"] == "Business lunch with client"

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_update_notes_with_receipt(self, mock_get_client):
        """Test updating notes with receipt URL."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {"updateTransaction": {}}
        mock_get_client.return_value = mock_client

        await update_transaction_notes(
            transaction_id="txn_123",
            notes="Office supplies",
            receipt_url="https://drive.google.com/file/abc123",
        )

        call_kwargs = mock_client.update_transaction.call_args.kwargs
        assert (
            call_kwargs["notes"]
            == "[Receipt: https://drive.google.com/file/abc123] Office supplies"
        )

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_update_notes_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = await update_transaction_notes("txn_123", "test")

        data = json.loads(result)
        assert data["error"] is True
        assert "API error" in data["message"]


class TestMarkTransactionReviewed:
    """Tests for mark_transaction_reviewed tool."""

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_mark_reviewed_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = await mark_transaction_reviewed("txn_123")

        data = json.loads(result)
        assert data["error"] is True
        assert "API error" in data["message"]


class TestBulkCategorizeTransactions:
    """Tests for bulk_categorize_transactions tool."""

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_bulk_categorize_all_success(self, mock_get_client):
        """Test successful bulk categorization of all transactions."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {"updateTransaction": {}}
        mock_get_client.return_value = mock_client

        result = await bulk_categorize_transactions(
            transaction_ids=["txn_1", "txn_2", "txn_3"],
            category_id="cat_123",
            mark_reviewed=True,
        )

        data = json.loads(result)
        assert data["total"] == 3
        assert data["successful"] == 3
        assert data["failed"] == 0
        assert len(data["errors"]) == 0

        # Verify update_transaction was called 3 times
        assert mock_client.update_transaction.call_count == 3

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
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
            transaction_ids=["txn_1", "txn_2", "txn_3"], category_id="cat_123"
        )

        data = json.loads(result)
        assert data["total"] == 3
        assert data["successful"] == 2
        assert data["failed"] == 1
        assert len(data["errors"]) == 1
        assert data["errors"][0]["transaction_id"] == "txn_2"

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_bulk_categorize_without_mark_reviewed(self, mock_get_client):
        """Test bulk categorization without marking as reviewed."""
        mock_client = AsyncMock()
        mock_client.update_transaction.return_value = {"updateTransaction": {}}
        mock_get_client.return_value = mock_client

        await bulk_categorize_transactions(
            transaction_ids=["txn_1"], category_id="cat_123", mark_reviewed=False
        )

        call_kwargs = mock_client.update_transaction.call_args.kwargs
        assert "needs_review" not in call_kwargs

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_bulk_categorize_empty_list(self, mock_get_client):
        """Test bulk categorization with empty transaction list."""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await bulk_categorize_transactions(
            transaction_ids=[], category_id="cat_123"
        )

        data = json.loads(result)
        assert data["total"] == 0
        assert data["successful"] == 0
        assert data["failed"] == 0

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_bulk_categorize_client_error(self, mock_get_client):
        """Test error when client cannot be obtained."""
        mock_get_client.side_effect = RuntimeError("Auth needed")

        result = await bulk_categorize_transactions(
            transaction_ids=["txn_1"], category_id="cat_123"
        )

        data = json.loads(result)
        assert data["error"] is True
        assert "Auth needed" in data["message"]

    @patch('monarch_mcp_server.tools.transactions.get_monarch_client')
    async def test_bulk_categorize_dry_run_skips_client(self, mock_get_client):
        """dry_run returns the planned update without calling the SDK."""
        result = await bulk_categorize_transactions(
            transaction_ids=["txn_1", "txn_2"],
            category_id="cat_123",
            dry_run=True,
        )

        data = json.loads(result)
        assert data["dry_run"] is True
        assert data["total"] == 2
        assert data["transaction_ids"] == ["txn_1", "txn_2"]
        assert data["category_id"] == "cat_123"
        assert data["mark_reviewed"] is True
        mock_get_client.assert_not_called()


class TestSearchTransactions:
    """Tests for search_transactions tool."""

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_search_with_multiple_filters(self, mock_get_client):
        """Test search with multiple filters."""
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {"allTransactions": {"results": []}}
        mock_get_client.return_value = mock_client

        await search_transactions(
            search="coffee",
            start_date="2024-01-01",
            end_date="2024-01-31",
            category_ids=["cat_1"],
            account_ids=["acc_1"],
            has_notes=False,
            is_recurring=True,
        )

        call_kwargs = mock_client.get_transactions.call_args.kwargs
        assert call_kwargs["search"] == "coffee"
        assert call_kwargs["start_date"] == "2024-01-01"
        assert call_kwargs["end_date"] == "2024-01-31"
        assert call_kwargs["category_ids"] == ["cat_1"]
        assert call_kwargs["account_ids"] == ["acc_1"]
        assert call_kwargs["has_notes"] is False
        assert call_kwargs["is_recurring"] is True

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_search_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = await search_transactions(search="test")

        data = json.loads(result)
        assert data["error"] is True
        assert "API error" in data["message"]


class TestGetTransactionDetails:
    """Tests for get_transaction_details tool."""

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_get_details_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("Transaction not found")

        result = await get_transaction_details("txn_invalid")

        data = json.loads(result)
        assert data["error"] is True
        assert "Transaction not found" in data["message"]


class TestDeleteTransaction:
    """Tests for delete_transaction tool."""

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_delete_success(self, mock_get_client):
        """Test successful transaction deletion."""
        mock_client = AsyncMock()
        mock_client.delete_transaction.return_value = {
            "deleteTransaction": {"deleted": True}
        }
        mock_get_client.return_value = mock_client

        result = await delete_transaction(transaction_id="txn_123")

        mock_client.delete_transaction.assert_called_once_with(transaction_id="txn_123")

        data = json.loads(result)
        assert data["deleteTransaction"]["deleted"] is True

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_delete_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("Cannot delete")

        result = await delete_transaction("txn_123")

        data = json.loads(result)
        assert data["error"] is True
        assert "Cannot delete" in data["message"]


class TestGetRecurringTransactions:
    """Tests for get_recurring_transactions tool."""

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_get_recurring_with_dates(self, mock_get_client):
        """Test with custom date range."""
        mock_client = AsyncMock()
        mock_client.get_recurring_transactions.return_value = {
            "recurringTransactionItems": []
        }
        mock_get_client.return_value = mock_client

        await get_recurring_transactions(start_date="2024-02-01", end_date="2024-02-29")

        call_kwargs = mock_client.get_recurring_transactions.call_args.kwargs
        assert call_kwargs["start_date"] == "2024-02-01"
        assert call_kwargs["end_date"] == "2024-02-29"

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_get_recurring_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = await get_recurring_transactions()

        data = json.loads(result)
        assert data["error"] is True
        assert "API error" in data["message"]


class TestGetTransactions:
    async def _transaction_response(self, **kwargs):
        return json.loads(await get_transactions(**kwargs))

    async def _transaction_rows(self, **kwargs):
        return (await self._transaction_response(**kwargs))["data"]

    async def test_returns_response_envelope(self):
        result = await self._transaction_response()
        assert result["tool"] == "get_transactions"
        assert result["args"]["limit"] == 100
        assert result["args"]["offset"] == 0
        assert result["count"] == 2
        assert result["total_count"] is None
        assert result["truncated"] is False
        assert result["search"]["strategy"] == "server"
        assert isinstance(result["data"], list)

    async def test_returns_formatted_transactions(self):
        result = await self._transaction_rows()
        assert len(result) == 2
        assert result[0]["id"] == "txn-1"
        assert result[0]["amount"] == -42.50
        assert result[0]["currency"] == "CAD"
        assert result[0]["currency_source"] == "api"
        assert result[0]["direction"] == "outflow"
        assert result[0]["direction_source"] == "amount_sign"
        assert result[0]["transaction_type"] == "expense"
        assert result[0]["original_statement"] == "WHOLE FOODS MARKET 10234"
        assert result[0]["plaid_description"] == "WHOLE FOODS MARKET 10234"
        assert result[0]["category"] == "Groceries"
        assert result[0]["category_id"] == "cat-1"
        assert result[0]["category_group"] == "Food"
        assert result[0]["category_group_id"] == "grp-1"
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
        result = await self._transaction_rows()
        assert result[1]["merchant"] is None
        assert result[1]["currency"] == "USD"
        assert result[1]["currency_source"] == "account_name_guess"
        assert result[1]["direction"] == "inflow"
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
        result = await self._transaction_rows()
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

    async def test_category_group_filter_expands_to_categories(
        self, mock_monarch_client
    ):
        await get_transactions(category_group_ids=["grp-1"])
        mock_monarch_client.get_transactions.assert_called_once_with(
            limit=100, offset=0, category_ids=["cat-1", "cat-2"]
        )

    async def test_category_group_filter_merges_category_ids(self, mock_monarch_client):
        await get_transactions(category_ids=["cat-3"], category_group_ids=["grp-1"])
        mock_monarch_client.get_transactions.assert_called_once_with(
            limit=100, offset=0, category_ids=["cat-3", "cat-1", "cat-2"]
        )

    async def test_category_group_filter_with_no_matches_returns_empty(
        self, mock_monarch_client
    ):
        result = await self._transaction_response(category_group_ids=["grp-missing"])
        assert result["count"] == 0
        assert result["truncated"] is False
        assert result["data"] == []
        mock_monarch_client.get_transactions.assert_not_called()

    async def test_server_error_propagates_when_wide_search_off(
        self, mock_monarch_client
    ):
        mock_monarch_client.get_transactions.side_effect = Exception("backend boom")
        result = await self._transaction_response(search="RRSP")
        assert result["error"] is True
        assert "backend boom" in result["message"]

    async def test_empty_search_results_fall_back_to_wide_search(
        self, mock_monarch_client
    ):
        response = mock_monarch_client.get_transactions.return_value
        mock_monarch_client.get_transactions.side_effect = [
            {"allTransactions": {"results": []}},
            response,
        ]
        result = await self._transaction_response(
            search="whole foods", limit=10, wide_search=True
        )
        assert result["count"] == 1
        assert result["data"][0]["id"] == "txn-1"
        assert result["search"]["strategy"] == "wide"
        assert result["search"]["fallback_reason"] == "empty_server_results"
        assert result["search"]["scan_limit"] == 200
        mock_monarch_client.get_transactions.assert_has_calls(
            [
                call(limit=10, offset=0, search="whole foods"),
                call(limit=200, offset=0),
            ]
        )

    async def test_wide_search_off_by_default(self, mock_monarch_client):
        mock_monarch_client.get_transactions.return_value = {
            "allTransactions": {"results": []}
        }
        result = await self._transaction_response(search="whole foods", limit=10)
        assert result["count"] == 0
        assert result["search"]["strategy"] == "server"
        # Only one call: the server-side search. No local-scan fallback.
        assert mock_monarch_client.get_transactions.call_count == 1

    async def test_search_errors_fall_back_to_wide_search(self, mock_monarch_client):
        response = mock_monarch_client.get_transactions.return_value
        mock_monarch_client.get_transactions.side_effect = [
            Exception("server search failed"),
            response,
        ]
        result = await self._transaction_response(
            search="WHOLE", limit=10, wide_search=True
        )
        assert result["count"] == 1
        assert result["data"][0]["id"] == "txn-1"
        assert result["search"]["strategy"] == "wide"
        assert result["search"]["fallback_reason"] == "server_error"
        assert result["search"]["server_error"] == "server search failed"
        mock_monarch_client.get_transactions.assert_has_calls(
            [
                call(limit=10, offset=0, search="WHOLE"),
                call(limit=200, offset=0),
            ]
        )

    async def test_handles_empty_transactions(self, mock_monarch_client):
        mock_monarch_client.get_transactions.return_value = {
            "allTransactions": {"results": []}
        }
        result = await self._transaction_response()
        assert result["count"] == 0
        assert result["truncated"] is False
        assert result["data"] == []

    async def test_truncated_when_total_count_has_more_rows(self, mock_monarch_client):
        mock_monarch_client.get_transactions.return_value["allTransactions"][
            "totalCount"
        ] = 3
        result = await self._transaction_response(limit=2)
        assert result["count"] == 2
        assert result["total_count"] == 3
        assert result["truncated"] is True

    async def test_truncated_when_page_is_full_without_total_count(self):
        result = await self._transaction_response(limit=2)
        assert result["count"] == 2
        assert result["total_count"] is None
        assert result["truncated"] is True

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transactions.side_effect = Exception("Auth expired")
        result = await get_transactions()
        assert "get_transactions" in result

    async def test_handles_blank_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transactions.side_effect = Exception()
        result = await get_transactions()
        assert "Exception()" in result


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

    @pytest.mark.parametrize("owner_user_id", ["user-1", ""])
    async def test_passes_owner(self, mock_monarch_client, owner_user_id):
        result = json.loads(
            await update_transaction("txn-1", owner_user_id=owner_user_id)
        )
        assert result == {"updateTransaction": {"transaction": {"id": "txn-1"}}}
        mock_monarch_client.update_transaction.assert_awaited_once_with(
            transaction_id="txn-1", owner_user_id=owner_user_id
        )

    async def test_none_preserves_owner(self, mock_monarch_client):
        await update_transaction("txn-1", category_id="cat-1", owner_user_id=None)
        mock_monarch_client.update_transaction.assert_called_once_with(
            transaction_id="txn-1", category_id="cat-1"
        )

    @pytest.mark.parametrize("owner_user_id", ["unknown-user", ""])
    async def test_owner_rejection_is_not_success(
        self, mock_monarch_client, owner_user_id
    ):
        mock_monarch_client.update_transaction.return_value = {
            "updateTransaction": {
                "transaction": None,
                "errors": {"message": "Owner update rejected", "code": "INVALID"},
            }
        }
        result = json.loads(
            await update_transaction("txn-1", owner_user_id=owner_user_id)
        )
        assert result["success"] is False
        assert "Owner update rejected" in json.dumps(result)

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
            owner_user_id="user-1",
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
            owner_user_id="user-1",
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


class TestRejectedWritesAreNotReportedAsSuccess:
    """gql_call raises on transport and top level GraphQL errors.

    Monarch refuses a mutation differently: errors come back inside the
    payload of an HTTP 200. Treating "no exception" as success reports writes
    that never happened, which is worse than failing, because the caller marks
    the work done and moves on.
    """

    REJECTION = {
        "updateTransaction": {
            "transaction": None,
            "errors": {"message": "Category not found", "code": "INVALID"},
        }
    }

    async def test_categorize_transaction(self, mock_monarch_client):
        mock_monarch_client.update_transaction.return_value = self.REJECTION
        result = json.loads(await categorize_transaction("txn-1", "bogus"))
        assert result["success"] is False
        assert "Category not found" in json.dumps(result)

    async def test_mark_transaction_reviewed(self, mock_monarch_client):
        mock_monarch_client.update_transaction.return_value = self.REJECTION
        result = json.loads(await mark_transaction_reviewed("txn-1"))
        assert result["success"] is False

    async def test_update_transaction_notes(self, mock_monarch_client):
        mock_monarch_client.update_transaction.return_value = self.REJECTION
        result = json.loads(await update_transaction_notes("txn-1", "note"))
        assert result["success"] is False

    async def test_update_transaction(self, mock_monarch_client):
        mock_monarch_client.update_transaction.return_value = self.REJECTION
        result = json.loads(await update_transaction("txn-1", category_id="x"))
        assert result["success"] is False

    async def test_bulk_categorize_counts_rejections_as_failures(
        self, mock_monarch_client
    ):
        """The whole batch was reported as categorized while nothing was."""
        mock_monarch_client.update_transaction.return_value = self.REJECTION
        result = json.loads(
            await bulk_categorize_transactions(["1", "2", "3"], "bogus")
        )
        assert result["successful"] == 0
        assert result["failed"] == 3
        assert len(result["errors"]) == 3

    async def test_bulk_categorize_still_counts_real_successes(
        self, mock_monarch_client
    ):
        mock_monarch_client.update_transaction.return_value = {
            "updateTransaction": {"transaction": {"id": "1"}, "errors": None}
        }
        result = json.loads(
            await bulk_categorize_transactions(["1", "2"], "cat-1")
        )
        assert result["successful"] == 2
        assert result["failed"] == 0

    async def test_bulk_categorize_error_text_is_never_blank(
        self, mock_monarch_client
    ):
        """Some transport exceptions stringify to the empty string."""

        class Silent(Exception):
            def __str__(self):
                return ""

        mock_monarch_client.update_transaction.side_effect = Silent()
        result = json.loads(await bulk_categorize_transactions(["1"], "cat-1"))
        assert result["failed"] == 1
        assert result["errors"][0]["error"]


class TestReviewQueueFiltersServerSide:
    """The review filter must be Monarch's job, not a local pass over one page.

    Filtering locally meant the tool asked for an arbitrary page of all
    transactions and reported however many of those happened to need review,
    with nothing in the response saying the page was truncated and no offset
    to page past it.
    """

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_needs_review_is_sent_upstream(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {"results": [], "totalCount": 0}
        }
        mock_get_client.return_value = mock_client

        await get_transactions_needing_review()

        assert mock_client.get_transactions.call_args.kwargs["needs_review"] is True

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_needs_review_false_inverts_rather_than_disabling(
        self, mock_get_client
    ):
        """False used to mean "no filter", returning the very rows it excluded."""
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {"results": [], "totalCount": 0}
        }
        mock_get_client.return_value = mock_client

        await get_transactions_needing_review(needs_review=False)

        assert mock_client.get_transactions.call_args.kwargs["needs_review"] is False

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_truncation_is_visible_to_the_caller(self, mock_get_client):
        """A full page against a much larger total must not look complete."""
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {
                "results": [
                    {"id": f"txn_{i}", "date": "2024-01-15", "amount": -1.0}
                    for i in range(3)
                ],
                "totalCount": 5000,
            }
        }
        mock_get_client.return_value = mock_client

        envelope = json.loads(await get_transactions_needing_review(limit=3))

        assert envelope["count"] == 3
        assert envelope["total_count"] == 5000
        assert envelope["truncated"] is True

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_offset_pages_the_queue(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {"results": [], "totalCount": 0}
        }
        mock_get_client.return_value = mock_client

        await get_transactions_needing_review(offset=100)

        assert mock_client.get_transactions.call_args.kwargs["offset"] == 100

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_local_uncategorized_filter_does_not_claim_a_server_total(
        self, mock_get_client
    ):
        """uncategorized_only still shrinks the page after the fact.

        Reporting the server side total next to it would imply the page is
        the complete set of uncategorized rows, which it is not.
        """
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {
                "results": [
                    {"id": "a", "category": None},
                    {"id": "b", "category": {"id": "c1", "name": "Groceries"}},
                ],
                "totalCount": 900,
            }
        }
        mock_get_client.return_value = mock_client

        envelope = json.loads(
            await get_transactions_needing_review(uncategorized_only=True)
        )

        assert envelope["count"] == 1
        assert envelope["total_count"] is None
        assert envelope["search"] == {"local_filter": "uncategorized_only"}


class TestTruncationIsHonestUnderLocalFiltering:
    """uncategorized_only shrinks the page after the fact.

    That drops `count` below `limit`, which defeats the envelope's fallback
    and asserted completeness on a page that was in fact truncated.
    """

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_full_page_trimmed_by_local_filter_is_still_truncated(
        self, mock_get_client
    ):
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {
                "results": [
                    {"id": f"t{i}", "category": None if i < 3 else {"id": "c1"}}
                    for i in range(100)
                ],
                "totalCount": 900,
            }
        }
        mock_get_client.return_value = mock_client

        envelope = json.loads(
            await get_transactions_needing_review(limit=100, uncategorized_only=True)
        )
        assert envelope["count"] == 3
        assert envelope["truncated"] is True, (
            "3 rows kept from a full page against 900 must not read as complete"
        )

    @patch("monarch_mcp_server.tools.transactions.get_monarch_client")
    async def test_short_page_is_not_marked_truncated(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.get_transactions.return_value = {
            "allTransactions": {
                "results": [{"id": "t1", "category": None}],
                "totalCount": 1,
            }
        }
        mock_get_client.return_value = mock_client

        envelope = json.loads(
            await get_transactions_needing_review(limit=100, uncategorized_only=True)
        )
        assert envelope["truncated"] is False


class TestCreateTransactionReportsRejection:
    async def test_refused_creation_is_not_reported_as_success(
        self, mock_monarch_client
    ):
        mock_monarch_client.create_transaction.return_value = {
            "createTransaction": {
                "transaction": None,
                "errors": {"message": "Invalid account", "code": "INVALID"},
            }
        }
        result = json.loads(
            await create_transaction(
                date="2026-01-01",
                account_id="acc-1",
                amount=-5.0,
                merchant_name="X",
                category_id="cat-1",
            )
        )
        assert result["success"] is False
        assert "Invalid account" in json.dumps(result)
