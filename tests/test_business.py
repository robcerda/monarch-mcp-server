"""Tests for business entity tools."""

import json
from unittest.mock import AsyncMock, patch

from monarch_mcp_server.tools.business import (
    get_business_entities,
    set_business_entity,
)
from monarch_mcp_server.tools.transactions import bulk_update_transactions


class TestGetBusinessEntities:
    @patch("monarch_mcp_server.tools.business.get_monarch_client")
    async def test_lists_entities(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "businessEntities": [{"id": "biz_1", "name": "Studio"}]
        }
        mock_get_client.return_value = mock_client

        data = json.loads(await get_business_entities())

        assert data == [{"id": "biz_1", "name": "Studio"}]

    @patch("monarch_mcp_server.tools.business.get_monarch_client")
    async def test_no_entities_returns_empty_list(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"businessEntities": None}
        mock_get_client.return_value = mock_client

        assert json.loads(await get_business_entities()) == []


class TestSetBusinessEntity:
    @patch("monarch_mcp_server.tools.business.get_monarch_client")
    async def test_sets_entity(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateTransaction": {
                "transaction": {
                    "id": "txn_1",
                    "businessEntity": {"id": "biz_1", "name": "Studio"},
                },
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        data = json.loads(
            await set_business_entity(transaction_id="txn_1", business_entity_id="biz_1")
        )

        variables = mock_client.gql_call.call_args.kwargs["variables"]
        assert variables == {"input": {"id": "txn_1", "businessEntityId": "biz_1"}}
        assert data["businessEntity"]["id"] == "biz_1"

    @patch("monarch_mcp_server.tools.business.get_monarch_client")
    async def test_none_clears_entity(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateTransaction": {
                "transaction": {"id": "txn_1", "businessEntity": None},
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        await set_business_entity(transaction_id="txn_1", business_entity_id="none")

        variables = mock_client.gql_call.call_args.kwargs["variables"]
        assert variables["input"]["businessEntityId"] is None

    @patch("monarch_mcp_server.tools.business.get_monarch_client")
    async def test_payload_errors_are_rejected(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateTransaction": {
                "transaction": None,
                "errors": {"message": "Business not found", "fieldErrors": []},
            }
        }
        mock_get_client.return_value = mock_client

        result = await set_business_entity(
            transaction_id="txn_1", business_entity_id="missing"
        )

        assert "Business not found" in result


class TestBulkUpdateBusinessEntity:
    async def test_dry_run_maps_to_business_entity_id(self):
        data = json.loads(
            await bulk_update_transactions(
                transaction_ids=["txn_1", "txn_2"],
                business_entity_id="biz_1",
                dry_run=True,
            )
        )

        assert data["updates"] == {"businessEntityId": "biz_1"}

    async def test_dry_run_none_clears(self):
        data = json.loads(
            await bulk_update_transactions(
                transaction_ids=["txn_1"], business_entity_id="none", dry_run=True
            )
        )

        assert data["updates"] == {"businessEntityId": None}
