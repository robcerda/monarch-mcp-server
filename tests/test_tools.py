"""Tests for Monarch MCP Server tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from monarch_mcp_server.server import (
    NotAuthenticated,
    _get_client,
    add_transaction_tag,
    categorize_transaction,
    check_auth_status,
    create_transaction,
    create_transaction_category,
    create_transaction_tag,
    get_account_holdings,
    get_accounts,
    get_budgets,
    get_cashflow,
    get_transaction_categories,
    get_transaction_category_groups,
    get_transaction_tags,
    get_transactions,
    monarch_login,
    monarch_login_with_token,
    monarch_logout,
    refresh_accounts,
    set_transaction_tags,
    update_transaction,
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

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.get_accounts.side_effect = Exception("API timeout")
        with pytest.raises(Exception, match="API timeout"):
            await get_accounts()


class TestGetTransactions:
    async def test_returns_formatted_transactions(self):
        result = json.loads(await get_transactions())
        assert len(result) == 2
        assert result[0]["id"] == "txn-1"
        assert result[0]["amount"] == -42.50
        assert result[0]["category"] == "Groceries"
        assert result[0]["merchant"] == "Whole Foods"

    async def test_handles_null_merchant(self):
        result = json.loads(await get_transactions())
        assert result[1]["merchant"] is None

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
                        "account": {"displayName": "Checking"},
                        "merchant": None,
                        "isPending": True,
                    }
                ]
            }
        }
        result = json.loads(await get_transactions())
        assert result[0]["category"] is None
        assert result[0]["is_pending"] is True

    async def test_passes_filters_to_client(self, mock_monarch_client):
        await get_transactions(
            limit=10, offset=5, start_date="2026-03-01", account_id="acc-1"
        )
        mock_monarch_client.get_transactions.assert_called_once_with(
            limit=10,
            offset=5,
            start_date="2026-03-01",
            account_id="acc-1",
        )

    async def test_handles_empty_transactions(self, mock_monarch_client):
        mock_monarch_client.get_transactions.return_value = {
            "allTransactions": {"results": []}
        }
        result = json.loads(await get_transactions())
        assert result == []

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transactions.side_effect = Exception("Auth expired")
        with pytest.raises(Exception, match="Auth expired"):
            await get_transactions()


class TestGetBudgets:
    async def test_returns_raw_budget_data(self):
        result = json.loads(await get_budgets())
        assert "budgetData" in result
        categories = result["budgetData"]["monthlyAmountsByCategory"]
        assert len(categories) == 2
        assert categories[0]["category"]["name"] == "Groceries"

    async def test_passes_date_params(self, mock_monarch_client):
        await get_budgets(start_date="2026-03-01", end_date="2026-03-31")
        mock_monarch_client.get_budgets.assert_called_once_with(
            start_date="2026-03-01", end_date="2026-03-31"
        )

    async def test_passes_none_dates_by_default(self, mock_monarch_client):
        await get_budgets()
        mock_monarch_client.get_budgets.assert_called_once_with(
            start_date=None, end_date=None
        )

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.get_budgets.side_effect = Exception("Budget error")
        with pytest.raises(Exception, match="Budget error"):
            await get_budgets()


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

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.get_cashflow.side_effect = Exception("Cashflow error")
        with pytest.raises(Exception, match="Cashflow error"):
            await get_cashflow()


class TestGetAccountHoldings:
    async def test_returns_holdings(self):
        result = json.loads(await get_account_holdings("acc-1"))
        assert result["holdings"][0]["name"] == "VTI"
        assert result["holdings"][0]["value"] == 25000.00

    async def test_passes_account_id(self, mock_monarch_client):
        await get_account_holdings("acc-99")
        mock_monarch_client.get_account_holdings.assert_called_once_with("acc-99")

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.get_account_holdings.side_effect = Exception("Not found")
        with pytest.raises(Exception, match="Not found"):
            await get_account_holdings("bad-id")


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

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.create_transaction.side_effect = Exception("Bad request")
        with pytest.raises(Exception, match="Bad request"):
            await create_transaction(
                date="2026-03-15",
                account_id="acc-1",
                amount=-25.00,
                merchant_name="Store",
                category_id="cat-1",
            )


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

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.update_transaction.side_effect = Exception("Not found")
        with pytest.raises(Exception, match="Not found"):
            await update_transaction("bad-id")


class TestGetTransactionCategories:
    async def test_returns_categories(self):
        result = json.loads(await get_transaction_categories())
        assert len(result) == 2
        assert result[0]["id"] == "cat-1"
        assert result[0]["name"] == "Groceries"
        assert result[0]["group"] == "Food"

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transaction_categories.side_effect = Exception("boom")
        with pytest.raises(Exception, match="boom"):
            await get_transaction_categories()


class TestGetTransactionTags:
    async def test_returns_tags(self):
        result = json.loads(await get_transaction_tags())
        assert len(result) == 2
        assert result[0]["id"] == "tag-1"
        assert result[0]["name"] == "business"
        assert result[0]["color"] == "#ff0000"

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transaction_tags.side_effect = Exception("boom")
        with pytest.raises(Exception, match="boom"):
            await get_transaction_tags()


class TestSetTransactionTags:
    async def test_sets_tags(self):
        result = json.loads(await set_transaction_tags("txn-1", ["tag-1", "tag-2"]))
        assert "setTransactionTags" in result

    async def test_passes_args(self, mock_monarch_client):
        await set_transaction_tags("txn-1", ["tag-1"])
        mock_monarch_client.set_transaction_tags.assert_called_once_with(
            transaction_id="txn-1", tag_ids=["tag-1"]
        )

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.set_transaction_tags.side_effect = Exception("boom")
        with pytest.raises(Exception, match="boom"):
            await set_transaction_tags("txn-1", [])


class TestCreateTransactionTag:
    async def test_creates_tag(self):
        result = json.loads(await create_transaction_tag("new", "#0000ff"))
        assert "createTransactionTag" in result

    async def test_passes_args(self, mock_monarch_client):
        await create_transaction_tag("vacation", "#00ff00")
        mock_monarch_client.create_transaction_tag.assert_called_once_with(
            name="vacation", color="#00ff00"
        )

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.create_transaction_tag.side_effect = Exception("boom")
        with pytest.raises(Exception, match="boom"):
            await create_transaction_tag("x", "#fff")


class TestCategorizeTransaction:
    async def test_categorizes(self, mock_monarch_client):
        result = json.loads(await categorize_transaction("txn-1", "cat-2"))
        assert "updateTransaction" in result
        mock_monarch_client.update_transaction.assert_called_once_with(
            transaction_id="txn-1", category_id="cat-2"
        )

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.update_transaction.side_effect = Exception("boom")
        with pytest.raises(Exception, match="boom"):
            await categorize_transaction("txn-1", "cat-2")


class TestGetTransactionCategoryGroups:
    async def test_returns_groups(self):
        result = json.loads(await get_transaction_category_groups())
        assert len(result) == 2
        assert result[0]["id"] == "grp-1"
        assert result[0]["name"] == "Food"
        assert result[0]["type"] == "expense"

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transaction_category_groups.side_effect = Exception(
            "boom"
        )
        with pytest.raises(Exception, match="boom"):
            await get_transaction_category_groups()


class TestCreateTransactionCategory:
    async def test_creates_category(self):
        result = json.loads(await create_transaction_category("grp-1", "Coffee"))
        assert "createCategory" in result

    async def test_passes_required_args(self, mock_monarch_client):
        await create_transaction_category("grp-1", "Coffee")
        mock_monarch_client.create_transaction_category.assert_called_once_with(
            group_id="grp-1", transaction_category_name="Coffee"
        )

    async def test_passes_optional_args(self, mock_monarch_client):
        await create_transaction_category(
            "grp-1",
            "Coffee",
            icon="COFFEE",
            rollover_enabled=True,
            rollover_type="monthly",
        )
        mock_monarch_client.create_transaction_category.assert_called_once_with(
            group_id="grp-1",
            transaction_category_name="Coffee",
            icon="COFFEE",
            rollover_enabled=True,
            rollover_type="monthly",
        )

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.create_transaction_category.side_effect = Exception("boom")
        with pytest.raises(Exception, match="boom"):
            await create_transaction_category("grp-1", "Coffee")


class TestAddTransactionTag:
    async def test_appends_to_existing_tags(self, mock_monarch_client):
        result = json.loads(await add_transaction_tag("txn-1", "tag-2"))
        assert "setTransactionTags" in result
        mock_monarch_client.set_transaction_tags.assert_called_once_with(
            transaction_id="txn-1", tag_ids=["tag-1", "tag-2"]
        )

    async def test_no_duplicate_when_already_present(self, mock_monarch_client):
        await add_transaction_tag("txn-1", "tag-1")
        mock_monarch_client.set_transaction_tags.assert_called_once_with(
            transaction_id="txn-1", tag_ids=["tag-1"]
        )

    async def test_handles_no_existing_tags(self, mock_monarch_client):
        mock_monarch_client.get_transaction_details.return_value = {
            "getTransaction": {"id": "txn-1", "tags": []}
        }
        await add_transaction_tag("txn-1", "tag-2")
        mock_monarch_client.set_transaction_tags.assert_called_once_with(
            transaction_id="txn-1", tag_ids=["tag-2"]
        )

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transaction_details.side_effect = Exception("boom")
        with pytest.raises(Exception, match="boom"):
            await add_transaction_tag("txn-1", "tag-2")


class TestRefreshAccounts:
    async def test_refreshes_accounts(self):
        result = json.loads(await refresh_accounts())
        assert result["requestAccountsRefresh"]["success"] is True

    async def test_propagates_api_error(self, mock_monarch_client):
        mock_monarch_client.request_accounts_refresh.side_effect = Exception("Timeout")
        with pytest.raises(Exception, match="Timeout"):
            await refresh_accounts()


# --- authentication surface ---------------------------------------------------
#
# The autouse `patch_monarch_client` fixture in conftest.py replaces
# `server._get_client` with an always-succeeding mock. Tests below that need
# to exercise the real `_get_client` raise-path or `check_auth_status` go
# through the imported reference directly (bound at module import before the
# autouse patch is applied per-test), or patch `secure_session` functions.


class TestGetClient:
    def test_raises_when_no_session(self):
        with patch(
            "monarch_mcp_server.server.secure_session.get_authenticated_client",
            return_value=None,
        ):
            with pytest.raises(NotAuthenticated, match="monarch_login"):
                _get_client()

    def test_returns_client_when_session_present(self):
        mock_client = MagicMock()
        with patch(
            "monarch_mcp_server.server.secure_session.get_authenticated_client",
            return_value=mock_client,
        ):
            assert _get_client() is mock_client


class TestCheckAuthStatus:
    async def test_not_authenticated(self):
        with patch(
            "monarch_mcp_server.server.secure_session.load_token", return_value=None
        ):
            result = await check_auth_status()
        assert "Not authenticated" in result
        assert "monarch_login" in result

    async def test_authenticated_and_live(self):
        mock_mm = AsyncMock()
        mock_mm.get_subscription_details = AsyncMock(return_value={"ok": True})
        with patch(
            "monarch_mcp_server.server.secure_session.load_token", return_value="tkn"
        ), patch("monarch_mcp_server.server.MonarchMoney", return_value=mock_mm):
            result = await check_auth_status()
        assert "session is live" in result

    async def test_token_present_but_invalid(self):
        mock_mm = AsyncMock()
        mock_mm.get_subscription_details = AsyncMock(side_effect=Exception("401"))
        with patch(
            "monarch_mcp_server.server.secure_session.load_token", return_value="tkn"
        ), patch("monarch_mcp_server.server.MonarchMoney", return_value=mock_mm):
            result = await check_auth_status()
        assert "invalid" in result.lower()
        assert "monarch_login" in result


class TestAuthToolWrappers:
    """The auth tools are thin delegates to `auth.py` — verify the wiring."""

    async def test_monarch_login_delegates(self):
        ctx = MagicMock()
        with patch(
            "monarch_mcp_server.server.auth.login_interactive",
            new_callable=AsyncMock,
            return_value="ok",
        ) as mock_fn:
            result = await monarch_login(ctx)
        mock_fn.assert_awaited_once_with(ctx)
        assert result == "ok"

    async def test_monarch_login_with_token_delegates(self):
        ctx = MagicMock()
        with patch(
            "monarch_mcp_server.server.auth.login_with_token_interactive",
            new_callable=AsyncMock,
            return_value="ok",
        ) as mock_fn:
            result = await monarch_login_with_token(ctx)
        mock_fn.assert_awaited_once_with(ctx)
        assert result == "ok"

    async def test_monarch_logout_delegates(self):
        with patch(
            "monarch_mcp_server.server.auth.logout",
            new_callable=AsyncMock,
            return_value="cleared",
        ) as mock_fn:
            result = await monarch_logout()
        mock_fn.assert_awaited_once_with()
        assert result == "cleared"
