"""Tests for category-related MCP tools."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from monarch_mcp_server.tools.categories import (
    get_transaction_categories,
    get_transaction_category_groups,
    create_transaction_category,
    update_category,
    get_category_details,
    get_cashflow_by_month,
)


class TestGetTransactionCategories:
    async def test_returns_categories(self):
        result = json.loads(await get_transaction_categories())
        assert len(result) == 2
        assert result[0]["id"] == "cat-1"
        assert result[0]["name"] == "Groceries"
        assert result[0]["group"] == "Food"

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transaction_categories.side_effect = Exception("boom")
        result = await get_transaction_categories()
        assert "get_transaction_categories" in result


class TestGetTransactionCategoryGroups:
    async def test_returns_groups(self):
        result = json.loads(await get_transaction_category_groups())
        assert len(result) == 2
        assert result[0]["id"] == "grp-1"
        assert result[0]["name"] == "Food"
        assert result[0]["type"] == "expense"

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transaction_category_groups.side_effect = Exception("boom")
        result = await get_transaction_category_groups()
        assert "get_transaction_category_groups" in result


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
            "grp-1", "Coffee", icon="X", rollover_enabled=True, rollover_type="monthly"
        )
        mock_monarch_client.create_transaction_category.assert_called_once_with(
            group_id="grp-1",
            transaction_category_name="Coffee",
            icon="X",
            rollover_enabled=True,
            rollover_type="monthly",
        )

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.create_transaction_category.side_effect = Exception("boom")
        result = await create_transaction_category("grp-1", "Coffee")
        assert "create_transaction_category" in result


class TestUpdateCategory:
    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_update_name_and_icon(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateCategory": {
                "errors": None,
                "category": {
                    "id": "cat-123",
                    "name": "Fitness",
                    "icon": "\U0001f3cb",
                    "budgetVariability": "fixed",
                    "excludeFromBudget": False,
                    "isSystemCategory": False,
                    "isDisabled": False,
                    "isProtected": False,
                    "group": {
                        "id": "grp-1",
                        "type": "expense",
                        "groupLevelBudgetingEnabled": False,
                    },
                    "rolloverPeriod": None,
                },
            }
        }
        mock_get_client.return_value = mock_client

        result = json.loads(
            await update_category(category_id="cat-123", name="Fitness", icon="\U0001f3cb")
        )

        assert result["success"] is True
        assert result["category"]["name"] == "Fitness"
        assert result["category"]["icon"] == "\U0001f3cb"

        call_vars = mock_client.gql_call.call_args.kwargs["variables"]
        assert call_vars["input"]["id"] == "cat-123"
        assert call_vars["input"]["name"] == "Fitness"
        assert call_vars["input"]["icon"] == "\U0001f3cb"

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_update_budget_variability(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateCategory": {
                "errors": None,
                "category": {
                    "id": "cat-123",
                    "name": "Medical",
                    "icon": "\U0001f48a",
                    "budgetVariability": "flexible",
                    "excludeFromBudget": False,
                    "isSystemCategory": True,
                    "isDisabled": False,
                    "isProtected": False,
                    "group": {"id": "grp-2", "type": "expense", "groupLevelBudgetingEnabled": False},
                    "rolloverPeriod": None,
                },
            }
        }
        mock_get_client.return_value = mock_client

        result = json.loads(
            await update_category(category_id="cat-123", budget_variability="flexible")
        )

        assert result["success"] is True
        assert result["category"]["budget_variability"] == "flexible"

        call_vars = mock_client.gql_call.call_args.kwargs["variables"]
        assert call_vars["input"]["budgetVariability"] == "flexible"

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_enable_rollover(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateCategory": {
                "errors": None,
                "category": {
                    "id": "cat-456",
                    "name": "Harper's Birthday",
                    "icon": "\U0001f382",
                    "budgetVariability": "non_monthly",
                    "excludeFromBudget": False,
                    "isSystemCategory": False,
                    "isDisabled": False,
                    "isProtected": False,
                    "group": {"id": "grp-3", "type": "expense", "groupLevelBudgetingEnabled": False},
                    "rolloverPeriod": {
                        "id": "rp-1",
                        "startMonth": "2026-05-01",
                        "startingBalance": 0,
                        "type": "monthly",
                        "frequency": "variable",
                        "targetAmount": None,
                    },
                },
            }
        }
        mock_get_client.return_value = mock_client

        result = json.loads(
            await update_category(
                category_id="cat-456",
                budget_variability="non_monthly",
                rollover_enabled=True,
                rollover_start_month="2026-05-01",
                rollover_starting_balance=0,
                rollover_frequency="variable",
            )
        )

        assert result["success"] is True
        assert result["category"]["rollover_period"] is not None
        assert result["category"]["rollover_period"]["start_month"] == "2026-05-01"
        assert result["category"]["rollover_period"]["frequency"] == "variable"

        call_vars = mock_client.gql_call.call_args.kwargs["variables"]
        assert call_vars["input"]["rolloverEnabled"] is True
        assert call_vars["input"]["rolloverStartMonth"] == "2026-05-01"

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_falsy_values_not_dropped(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateCategory": {
                "errors": None,
                "category": {
                    "id": "cat-123",
                    "name": "Test",
                    "icon": "X",
                    "budgetVariability": "fixed",
                    "excludeFromBudget": False,
                    "isSystemCategory": False,
                    "isDisabled": False,
                    "isProtected": False,
                    "group": {"id": "grp-1", "type": "expense", "groupLevelBudgetingEnabled": False},
                    "rolloverPeriod": None,
                },
            }
        }
        mock_get_client.return_value = mock_client

        await update_category(
            category_id="cat-123",
            exclude_from_budget=False,
            rollover_enabled=False,
            rollover_starting_balance=0,
        )

        call_vars = mock_client.gql_call.call_args.kwargs["variables"]
        assert call_vars["input"]["excludeFromBudget"] is False
        assert call_vars["input"]["rolloverEnabled"] is False
        assert call_vars["input"]["rolloverStartingBalance"] == 0

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_invalid_budget_variability(self, mock_get_client):
        result = json.loads(
            await update_category(category_id="cat-123", budget_variability="bogus")
        )

        assert result["success"] is False
        assert "Invalid budget_variability" in result["message"]
        assert "bogus" in result["message"]
        mock_get_client.assert_not_called()

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_invalid_rollover_frequency(self, mock_get_client):
        result = json.loads(
            await update_category(category_id="cat-123", rollover_frequency="weekly")
        )

        assert result["success"] is False
        assert "Invalid rollover_frequency" in result["message"]
        mock_get_client.assert_not_called()

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_dry_run_returns_current_and_proposed(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "category": {
                "id": "cat-123",
                "order": 1,
                "name": "Fitness Subscriptions",
                "icon": "\U0001f3cb",
                "isSystemCategory": False,
                "systemCategory": None,
                "excludeFromBudget": False,
                "isDisabled": False,
                "group": {"id": "grp-1", "name": "Bills", "type": "expense"},
                "rolloverPeriod": None,
                "budgetAmountsForMonth": None,
            }
        }
        mock_get_client.return_value = mock_client

        result = json.loads(
            await update_category(
                category_id="cat-123",
                budget_variability="non_monthly",
                rollover_enabled=True,
                dry_run=True,
            )
        )

        assert result["dry_run"] is True
        assert result["current"]["name"] == "Fitness Subscriptions"
        assert result["proposed_changes"]["budgetVariability"] == "non_monthly"
        assert result["proposed_changes"]["rolloverEnabled"] is True
        # Mutation should NOT have been called
        assert mock_client.gql_call.call_args.kwargs["operation"] == "GetCategoryDetails"

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_dry_run_category_not_found(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"category": None}
        mock_get_client.return_value = mock_client

        result = json.loads(
            await update_category(
                category_id="nonexistent", name="Test", dry_run=True
            )
        )

        assert result["success"] is False
        assert "No category found" in result["message"]

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_no_fields_provided(self, mock_get_client):
        result = json.loads(await update_category(category_id="cat-123"))

        assert result["success"] is False
        assert "At least one field" in result["message"]
        mock_get_client.assert_not_called()

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_graphql_errors(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateCategory": {
                "errors": {
                    "fieldErrors": [{"field": "name", "messages": ["too long"]}],
                    "message": "Validation failed",
                    "code": "INVALID_INPUT",
                },
                "category": None,
            }
        }
        mock_get_client.return_value = mock_client

        result = json.loads(await update_category(category_id="cat-123", name="x" * 500))

        assert result["success"] is False
        assert result["errors"]["code"] == "INVALID_INPUT"

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_auth_error(self, mock_get_client):
        mock_get_client.side_effect = RuntimeError("Not authenticated")

        result = await update_category(category_id="cat-123", name="Test")
        assert "update_category" in result


class TestGetCategoryDetails:
    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_success_with_budget_amounts(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "category": {
                "id": "cat-groceries",
                "order": 0,
                "name": "Groceries",
                "icon": "\U0001f6d2",
                "isSystemCategory": True,
                "systemCategory": "groceries",
                "excludeFromBudget": False,
                "isDisabled": False,
                "group": {"id": "grp-food", "name": "Food & Dining", "type": "expense"},
                "rolloverPeriod": None,
                "budgetAmountsForMonth": {
                    "month": "2026-05-01",
                    "plannedAmount": 600.0,
                    "actualAmount": 425.50,
                    "remainingAmount": 174.50,
                    "previousMonthRolloverAmount": None,
                    "rolloverType": None,
                },
            }
        }
        mock_get_client.return_value = mock_client

        result = json.loads(
            await get_category_details(category_id="cat-groceries", month="2026-05-01")
        )

        assert result["name"] == "Groceries"
        assert result["budget_amounts"]["planned_amount"] == 600.0
        assert result["budget_amounts"]["actual_amount"] == 425.50
        assert result["budget_amounts"]["remaining_amount"] == 174.50
        assert result["group"]["name"] == "Food & Dining"

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_default_month(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "category": {
                "id": "cat-1",
                "order": 0,
                "name": "Test",
                "icon": "X",
                "isSystemCategory": False,
                "systemCategory": None,
                "excludeFromBudget": False,
                "isDisabled": False,
                "group": {"id": "grp-1", "name": "G", "type": "expense"},
                "rolloverPeriod": None,
                "budgetAmountsForMonth": None,
            }
        }
        mock_get_client.return_value = mock_client

        await get_category_details(category_id="cat-1")

        call_vars = mock_client.gql_call.call_args.kwargs["variables"]
        assert call_vars["includeBudgetAmounts"] is True
        # Month should be current month in YYYY-MM-01 format
        from datetime import datetime

        expected_month = datetime.now().strftime("%Y-%m-01")
        assert call_vars["month"] == expected_month

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_category_not_found(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"category": None}
        mock_get_client.return_value = mock_client

        result = json.loads(await get_category_details(category_id="nonexistent"))

        assert result["category"] is None
        assert "No category found" in result["message"]

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_auth_error(self, mock_get_client):
        mock_get_client.side_effect = RuntimeError("Not authenticated")

        result = await get_category_details(category_id="cat-1")
        assert "get_category_details" in result


class TestGetCashflowByMonth:
    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_success_multiple_categories(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "aggregates": [
                {
                    "groupBy": {"category": {"id": "cat-A"}, "month": "2026-01-01"},
                    "summary": {"sum": -200.0},
                },
                {
                    "groupBy": {"category": {"id": "cat-A"}, "month": "2026-02-01"},
                    "summary": {"sum": -180.0},
                },
                {
                    "groupBy": {"category": {"id": "cat-B"}, "month": "2026-01-01"},
                    "summary": {"sum": -50.0},
                },
                {
                    "groupBy": {"category": {"id": "cat-B"}, "month": "2026-02-01"},
                    "summary": {"sum": -75.0},
                },
            ]
        }
        mock_get_client.return_value = mock_client

        result = json.loads(
            await get_cashflow_by_month(start_date="2026-01-01", end_date="2026-02-28")
        )

        assert result["period"]["start_date"] == "2026-01-01"
        assert len(result["categories"]) == 2
        # cat-A has higher total absolute (380 vs 125), so comes first
        assert result["categories"][0]["category_id"] == "cat-A"
        assert len(result["categories"][0]["monthly_totals"]) == 2
        assert result["categories"][0]["monthly_totals"][0]["sum"] == -200.0

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_empty_results(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"aggregates": []}
        mock_get_client.return_value = mock_client

        result = json.loads(
            await get_cashflow_by_month(start_date="2030-01-01", end_date="2030-01-31")
        )

        assert result["categories"] == []

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_passes_date_variables(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"aggregates": []}
        mock_get_client.return_value = mock_client

        await get_cashflow_by_month(start_date="2025-12-01", end_date="2026-05-31")

        call_vars = mock_client.gql_call.call_args.kwargs["variables"]
        assert call_vars["startDate"] == "2025-12-01"
        assert call_vars["endDate"] == "2026-05-31"

    @patch("monarch_mcp_server.tools.categories.get_monarch_client")
    async def test_auth_error(self, mock_get_client):
        mock_get_client.side_effect = RuntimeError("Not authenticated")

        result = await get_cashflow_by_month(
            start_date="2026-01-01", end_date="2026-01-31"
        )
        assert "get_cashflow_by_month" in result

