"""Tests for Monarch MCP Server tools."""

import json
from unittest.mock import AsyncMock

from monarch_mcp_server.server import (
    get_accounts,
    get_transactions,
    get_budgets,
    get_cashflow,
    get_account_holdings,
    create_transaction,
    update_transaction,
    refresh_accounts,
    check_auth_status,
    get_transaction_categories,
    get_transaction_tags,
    set_transaction_tags,
    create_transaction_tag,
    categorize_transaction,
)


class TestGetAccounts:
    def test_returns_formatted_account_list(self):
        result = json.loads(get_accounts())
        assert len(result) == 2
        assert result[0]["id"] == "acc-1"
        assert result[0]["name"] == "Checking Account"
        assert result[0]["type"] == "checking"
        assert result[0]["balance"] == 1500.00
        assert result[0]["institution"] == "Test Bank"
        assert result[0]["is_active"] is True
        assert result[0]["is_hidden"] is False

    def test_hidden_account_flagged(self):
        result = json.loads(get_accounts())
        assert result[1]["is_hidden"] is True

    def test_handles_null_type(self, mock_monarch_client):
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
        result = json.loads(get_accounts())
        assert result[0]["type"] is None
        assert result[0]["institution"] is None

    def test_handles_empty_accounts(self, mock_monarch_client):
        mock_monarch_client.get_accounts.return_value = {"accounts": []}
        result = json.loads(get_accounts())
        assert result == []

    def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_accounts.side_effect = Exception("API timeout")
        result = get_accounts()
        assert "Error getting accounts" in result
        assert "API timeout" in result


class TestGetTransactions:
    def test_returns_formatted_transactions(self):
        result = json.loads(get_transactions())
        assert len(result) == 2
        assert result[0]["id"] == "txn-1"
        assert result[0]["amount"] == -42.50
        assert result[0]["category"] == "Groceries"
        assert result[0]["merchant"] == "Whole Foods"

    def test_handles_null_merchant(self):
        result = json.loads(get_transactions())
        assert result[1]["merchant"] is None

    def test_handles_null_category(self, mock_monarch_client):
        mock_monarch_client.get_transactions.return_value = {
            "allTransactions": {
                "results": [
                    {
                        "id": "txn-3",
                        "date": "2026-03-03",
                        "amount": -10.00,
                        "description": "ATM",
                        "category": None,
                        "account": {"displayName": "Checking"},
                        "merchant": None,
                        "isPending": True,
                    }
                ]
            }
        }
        result = json.loads(get_transactions())
        assert result[0]["category"] is None
        assert result[0]["is_pending"] is True

    def test_passes_filters_to_client(self, mock_monarch_client):
        get_transactions(
            limit=10, offset=5, start_date="2026-03-01", account_id="acc-1"
        )
        mock_monarch_client.get_transactions.assert_called_once_with(
            limit=10,
            offset=5,
            start_date="2026-03-01",
            account_id="acc-1",
        )

    def test_handles_empty_transactions(self, mock_monarch_client):
        mock_monarch_client.get_transactions.return_value = {
            "allTransactions": {"results": []}
        }
        result = json.loads(get_transactions())
        assert result == []

    def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transactions.side_effect = Exception("Auth expired")
        result = get_transactions()
        assert "Error getting transactions" in result


class TestGetBudgets:
    def test_returns_raw_budget_data(self):
        result = json.loads(get_budgets())
        assert "budgetData" in result
        categories = result["budgetData"]["monthlyAmountsByCategory"]
        assert len(categories) == 2
        assert categories[0]["category"]["name"] == "Groceries"

    def test_passes_date_params(self, mock_monarch_client):
        get_budgets(start_date="2026-03-01", end_date="2026-03-31")
        mock_monarch_client.get_budgets.assert_called_once_with(
            start_date="2026-03-01", end_date="2026-03-31"
        )

    def test_passes_none_dates_by_default(self, mock_monarch_client):
        get_budgets()
        mock_monarch_client.get_budgets.assert_called_once_with(
            start_date=None, end_date=None
        )

    def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_budgets.side_effect = Exception("Budget error")
        result = get_budgets()
        assert "Error getting budgets" in result


class TestGetCashflow:
    def test_returns_cashflow_data(self):
        result = json.loads(get_cashflow())
        assert result["cashflow"]["income"] == 5000.00
        assert result["cashflow"]["expenses"] == -3200.00

    def test_passes_date_params(self, mock_monarch_client):
        get_cashflow(start_date="2026-01-01", end_date="2026-01-31")
        mock_monarch_client.get_cashflow.assert_called_once_with(
            start_date="2026-01-01", end_date="2026-01-31"
        )

    def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_cashflow.side_effect = Exception("Cashflow error")
        result = get_cashflow()
        assert "Error getting cashflow" in result


class TestGetAccountHoldings:
    def test_returns_holdings(self):
        result = json.loads(get_account_holdings("acc-1"))
        assert result["holdings"][0]["name"] == "VTI"
        assert result["holdings"][0]["value"] == 25000.00

    def test_passes_account_id(self, mock_monarch_client):
        get_account_holdings("acc-99")
        mock_monarch_client.get_account_holdings.assert_called_once_with("acc-99")

    def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_account_holdings.side_effect = Exception("Not found")
        result = get_account_holdings("bad-id")
        assert "Error getting account holdings" in result


class TestCreateTransaction:
    def test_creates_transaction(self):
        result = json.loads(
            create_transaction(
                date="2026-03-15",
                account_id="acc-1",
                amount=-25.00,
                merchant_name="Coffee Shop",
                category_id="cat-1",
            )
        )
        assert "createTransaction" in result

    def test_passes_all_params(self, mock_monarch_client):
        create_transaction(
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

    def test_omits_optional_params_when_not_set(self, mock_monarch_client):
        create_transaction(
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

    def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.create_transaction.side_effect = Exception("Bad request")
        result = create_transaction(
            date="2026-03-15",
            account_id="acc-1",
            amount=-25.00,
            merchant_name="Store",
            category_id="cat-1",
        )
        assert "Error creating transaction" in result


class TestUpdateTransaction:
    def test_updates_transaction(self):
        result = json.loads(update_transaction("txn-1", category_id="cat-2"))
        assert "updateTransaction" in result

    def test_passes_only_provided_fields(self, mock_monarch_client):
        update_transaction("txn-1", amount=99.99, notes="Updated")
        mock_monarch_client.update_transaction.assert_called_once_with(
            transaction_id="txn-1", amount=99.99, notes="Updated"
        )

    def test_passes_all_fields(self, mock_monarch_client):
        update_transaction(
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

    def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.update_transaction.side_effect = Exception("Not found")
        result = update_transaction("bad-id")
        assert "Error updating transaction" in result


class TestGetTransactionCategories:
    def test_returns_categories(self):
        result = json.loads(get_transaction_categories())
        assert len(result) == 2
        assert result[0]["id"] == "cat-1"
        assert result[0]["name"] == "Groceries"
        assert result[0]["group"] == "Food"

    def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transaction_categories.side_effect = Exception("boom")
        result = get_transaction_categories()
        assert "Error getting transaction categories" in result


class TestGetTransactionTags:
    def test_returns_tags(self):
        result = json.loads(get_transaction_tags())
        assert len(result) == 2
        assert result[0]["id"] == "tag-1"
        assert result[0]["name"] == "business"
        assert result[0]["color"] == "#ff0000"

    def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transaction_tags.side_effect = Exception("boom")
        result = get_transaction_tags()
        assert "Error getting transaction tags" in result


class TestSetTransactionTags:
    def test_sets_tags(self):
        result = json.loads(set_transaction_tags("txn-1", ["tag-1", "tag-2"]))
        assert "setTransactionTags" in result

    def test_passes_args(self, mock_monarch_client):
        set_transaction_tags("txn-1", ["tag-1"])
        mock_monarch_client.set_transaction_tags.assert_called_once_with(
            transaction_id="txn-1", tag_ids=["tag-1"]
        )

    def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.set_transaction_tags.side_effect = Exception("boom")
        result = set_transaction_tags("txn-1", [])
        assert "Error setting transaction tags" in result


class TestCreateTransactionTag:
    def test_creates_tag(self):
        result = json.loads(create_transaction_tag("new", "#0000ff"))
        assert "createTransactionTag" in result

    def test_passes_args(self, mock_monarch_client):
        create_transaction_tag("vacation", "#00ff00")
        mock_monarch_client.create_transaction_tag.assert_called_once_with(
            name="vacation", color="#00ff00"
        )

    def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.create_transaction_tag.side_effect = Exception("boom")
        result = create_transaction_tag("x", "#fff")
        assert "Error creating transaction tag" in result


class TestCategorizeTransaction:
    def test_categorizes(self, mock_monarch_client):
        result = json.loads(categorize_transaction("txn-1", "cat-2"))
        assert "updateTransaction" in result
        mock_monarch_client.update_transaction.assert_called_once_with(
            transaction_id="txn-1", category_id="cat-2"
        )

    def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.update_transaction.side_effect = Exception("boom")
        result = categorize_transaction("txn-1", "cat-2")
        assert "Error categorizing transaction" in result


class TestRefreshAccounts:
    def test_refreshes_accounts(self):
        result = json.loads(refresh_accounts())
        assert result["requestAccountsRefresh"]["success"] is True

    def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.request_accounts_refresh.side_effect = Exception("Timeout")
        result = refresh_accounts()
        assert "Error refreshing accounts" in result
