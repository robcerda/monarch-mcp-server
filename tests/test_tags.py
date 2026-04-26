"""Tests for tag-related MCP tools."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from monarch_mcp_server.tools.tags import (
    set_transaction_tags,
    get_transaction_tags,
    create_transaction_tag,
    add_transaction_tag,
)


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


class TestGetTransactionTags:
    async def test_returns_tags(self):
        result = json.loads(await get_transaction_tags())
        assert len(result) == 2
        assert result[0]["id"] == "tag-1"
        assert result[0]["name"] == "business"
        assert result[0]["color"] == "#ff0000"

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transaction_tags.side_effect = Exception("boom")
        result = await get_transaction_tags()
        assert "get_transaction_tags" in result


class TestSetTransactionTagsFromFixture:
    async def test_sets_tags(self):
        result = json.loads(await set_transaction_tags("txn-1", ["tag-1", "tag-2"]))
        assert "setTransactionTags" in result

    async def test_passes_args(self, mock_monarch_client):
        await set_transaction_tags("txn-1", ["tag-1"])
        mock_monarch_client.set_transaction_tags.assert_called_once_with(
            transaction_id="txn-1", tag_ids=["tag-1"]
        )

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.set_transaction_tags.side_effect = Exception("boom")
        result = await set_transaction_tags("txn-1", [])
        assert "set_transaction_tags" in result


class TestCreateTransactionTag:
    async def test_creates_tag(self):
        result = json.loads(await create_transaction_tag("new", "#0000ff"))
        assert "createTransactionTag" in result

    async def test_passes_args(self, mock_monarch_client):
        await create_transaction_tag("vacation", "#00ff00")
        mock_monarch_client.create_transaction_tag.assert_called_once_with(
            name="vacation", color="#00ff00"
        )

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.create_transaction_tag.side_effect = Exception("boom")
        result = await create_transaction_tag("x", "#fff")
        assert "create_transaction_tag" in result


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

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_transaction_details.side_effect = Exception("boom")
        result = await add_transaction_tag("txn-1", "tag-2")
        assert "add_transaction_tag" in result
