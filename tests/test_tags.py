"""Tests for tag-related MCP tools."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from monarch_mcp_server.tools.tags import get_tags, set_transaction_tags, create_tag


class TestGetTags:
    """Tests for get_tags tool."""

    @patch('monarch_mcp_server.tools.tags.get_monarch_client')
    async def test_get_tags_success(self, mock_get_client):
        """Test successful retrieval of tags."""
        mock_client = AsyncMock()
        mock_client.get_transaction_tags.return_value = {
            "householdTransactionTags": [
                {
                    "id": "tag_1",
                    "name": "Tax Deductible",
                    "color": "#FF5733",
                    "order": 1,
                    "transactionCount": 42,
                },
                {
                    "id": "tag_2",
                    "name": "Reimbursable",
                    "color": "#3498DB",
                    "order": 2,
                    "transactionCount": 15,
                },
            ]
        }
        mock_get_client.return_value = mock_client

        result = await get_tags()

        tags = json.loads(result)
        assert len(tags) == 2
        assert tags[0]["id"] == "tag_1"
        assert tags[0]["name"] == "Tax Deductible"
        assert tags[0]["color"] == "#FF5733"
        assert tags[0]["transaction_count"] == 42
        assert tags[1]["name"] == "Reimbursable"

    @patch('monarch_mcp_server.tools.tags.get_monarch_client')
    async def test_get_tags_empty(self, mock_get_client):
        """Test retrieval when no tags exist."""
        mock_client = AsyncMock()
        mock_client.get_transaction_tags.return_value = {
            "householdTransactionTags": []
        }
        mock_get_client.return_value = mock_client

        result = await get_tags()

        tags = json.loads(result)
        assert len(tags) == 0

    @patch('monarch_mcp_server.tools.tags.get_monarch_client')
    async def test_get_tags_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("Auth needed")

        result = await get_tags()

        data = json.loads(result)
        assert data["error"] is True
        assert "Auth needed" in data["message"]


class TestSetTransactionTags:
    """Tests for set_transaction_tags tool."""

    @patch('monarch_mcp_server.tools.tags.get_monarch_client')
    async def test_set_tags_success(self, mock_get_client):
        """Test setting tags on a transaction."""
        mock_client = AsyncMock()
        mock_client.set_transaction_tags.return_value = {
            "setTransactionTags": {
                "transaction": {
                    "id": "txn_123",
                    "tags": [
                        {"id": "tag_1", "name": "Tax Deductible"},
                        {"id": "tag_2", "name": "Reimbursable"},
                    ]
                }
            }
        }
        mock_get_client.return_value = mock_client

        result = await set_transaction_tags(
            transaction_id="txn_123",
            tag_ids=["tag_1", "tag_2"]
        )

        # Verify API called correctly
        mock_client.set_transaction_tags.assert_called_once_with(
            transaction_id="txn_123",
            tag_ids=["tag_1", "tag_2"]
        )

        data = json.loads(result)
        assert "setTransactionTags" in data

    @patch('monarch_mcp_server.tools.tags.get_monarch_client')
    async def test_set_tags_empty_list(self, mock_get_client):
        """Test removing all tags by passing empty list."""
        mock_client = AsyncMock()
        mock_client.set_transaction_tags.return_value = {
            "setTransactionTags": {
                "transaction": {"id": "txn_123", "tags": []}
            }
        }
        mock_get_client.return_value = mock_client

        result = await set_transaction_tags(
            transaction_id="txn_123",
            tag_ids=[]
        )

        mock_client.set_transaction_tags.assert_called_once_with(
            transaction_id="txn_123",
            tag_ids=[]
        )

    @patch('monarch_mcp_server.tools.tags.get_monarch_client')
    async def test_set_tags_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = await set_transaction_tags("txn_123", ["tag_1"])

        data = json.loads(result)
        assert data["error"] is True
        assert "API error" in data["message"]


class TestCreateTag:
    """Tests for create_tag tool."""

    @patch('monarch_mcp_server.tools.tags.get_monarch_client')
    async def test_create_tag_success(self, mock_get_client):
        """Test successful tag creation."""
        mock_client = AsyncMock()
        mock_client.create_transaction_tag.return_value = {
            "createTransactionTag": {
                "tag": {
                    "id": "tag_new",
                    "name": "Business Expense",
                    "color": "#9B59B6",
                }
            }
        }
        mock_get_client.return_value = mock_client

        result = await create_tag(
            name="Business Expense",
            color="#9B59B6"
        )

        mock_client.create_transaction_tag.assert_called_once_with(
            name="Business Expense",
            color="#9B59B6"
        )

        data = json.loads(result)
        assert "createTransactionTag" in data

    @patch('monarch_mcp_server.tools.tags.get_monarch_client')
    async def test_create_tag_default_color(self, mock_get_client):
        """Test tag creation with default color."""
        mock_client = AsyncMock()
        mock_client.create_transaction_tag.return_value = {"createTransactionTag": {}}
        mock_get_client.return_value = mock_client

        await create_tag(name="My Tag")

        mock_client.create_transaction_tag.assert_called_once_with(
            name="My Tag",
            color="#19D2A5"
        )

    @patch('monarch_mcp_server.tools.tags.get_monarch_client')
    async def test_create_tag_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = await create_tag("Test Tag")

        data = json.loads(result)
        assert data["error"] is True
        assert "API error" in data["message"]
