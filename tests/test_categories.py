"""Tests for category-related MCP tools."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from monarch_mcp_server.tools.categories import (
    get_transaction_categories,
    get_transaction_category_groups,
    create_transaction_category,
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

