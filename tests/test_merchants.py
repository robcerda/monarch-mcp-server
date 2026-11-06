"""Tests for merchant and recurring stream MCP tools."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from monarch_mcp_server.tools.merchants import (
    get_merchant,
    merge_merchants,
    review_recurring_stream,
    update_merchant,
)


class TestGetMerchant:
    """Tests for get_merchant tool."""

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_get_merchant_success(self, mock_get_client):
        """Test successful retrieval of merchant with recurring stream."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "merchant": {
                "id": "160319777541808781",
                "name": "PennyMac",
                "logoUrl": "https://example.com/logo.png",
                "transactionCount": 24,
                "ruleCount": 1,
                "canBeDeleted": False,
                "hasActiveRecurringStreams": True,
                "recurringTransactionStream": {
                    "id": "stream_123",
                    "frequency": "monthly",
                    "amount": -1460.93,
                    "baseDate": "2026-05-06",
                    "isActive": True,
                },
            }
        }
        mock_get_client.return_value = mock_client

        result = await get_merchant(merchant_id="160319777541808781")

        data = json.loads(result)
        assert data["merchant"]["id"] == "160319777541808781"
        assert data["merchant"]["name"] == "PennyMac"
        assert data["merchant"]["transaction_count"] == 24
        assert data["merchant"]["rule_count"] == 1
        assert data["merchant"]["can_be_deleted"] is False
        assert data["merchant"]["has_active_recurring_streams"] is True
        assert data["merchant"]["recurring_stream"]["frequency"] == "monthly"
        assert data["merchant"]["recurring_stream"]["amount"] == -1460.93
        assert data["merchant"]["recurring_stream"]["base_date"] == "2026-05-06"
        assert data["merchant"]["recurring_stream"]["is_active"] is True

        call_args = mock_client.gql_call.call_args
        assert call_args.kwargs["variables"]["merchantId"] == "160319777541808781"

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_get_merchant_no_recurring_stream(self, mock_get_client):
        """Test merchant that exists but has no recurring stream."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "merchant": {
                "id": "999",
                "name": "One-Time Shop",
                "logoUrl": None,
                "transactionCount": 2,
                "ruleCount": 0,
                "canBeDeleted": True,
                "hasActiveRecurringStreams": False,
                "recurringTransactionStream": None,
            }
        }
        mock_get_client.return_value = mock_client

        result = await get_merchant(merchant_id="999")

        data = json.loads(result)
        assert data["merchant"]["id"] == "999"
        assert data["merchant"]["name"] == "One-Time Shop"
        assert data["merchant"]["recurring_stream"] is None

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_get_merchant_not_found(self, mock_get_client):
        """Test when merchant ID does not exist."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"merchant": None}
        mock_get_client.return_value = mock_client

        result = await get_merchant(merchant_id="nonexistent")

        data = json.loads(result)
        assert data["merchant"] is None
        assert "message" in data

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_get_merchant_auth_error(self, mock_get_client):
        """Test error handling when not authenticated."""
        mock_get_client.side_effect = RuntimeError("Authentication needed")

        result = await get_merchant(merchant_id="123")

        data = json.loads(result)
        assert data["error"] is True
        assert "Authentication needed" in data["message"]


class TestUpdateMerchant:
    """Tests for update_merchant tool."""

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_update_name_only(self, mock_get_client):
        """Test updating only the merchant name."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateMerchant": {
                "merchant": {
                    "id": "123",
                    "name": "New Name",
                    "recurringTransactionStream": None,
                },
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        result = await update_merchant(merchant_id="123", name="New Name")

        data = json.loads(result)
        assert data["success"] is True
        assert data["merchant"]["name"] == "New Name"

        call_args = mock_client.gql_call.call_args
        variables = call_args.kwargs["variables"]
        assert variables["input"]["name"] == "New Name"
        assert "recurrence" not in variables["input"]

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_update_recurrence_only(self, mock_get_client):
        """Test updating only recurrence settings."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateMerchant": {
                "merchant": {
                    "id": "123",
                    "name": "PennyMac",
                    "recurringTransactionStream": {
                        "id": "stream_123",
                        "frequency": "monthly",
                        "amount": -1460.93,
                        "baseDate": "2026-06-01",
                        "isActive": True,
                    },
                },
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        result = await update_merchant(
            merchant_id="123",
            is_recurring=True,
            frequency="monthly",
            base_date="2026-06-01",
            amount=-1460.93,
            is_active=True,
        )

        data = json.loads(result)
        assert data["success"] is True
        assert data["merchant"]["recurring_stream"]["frequency"] == "monthly"
        assert data["merchant"]["recurring_stream"]["amount"] == -1460.93

        call_args = mock_client.gql_call.call_args
        variables = call_args.kwargs["variables"]
        assert "name" not in variables["input"]
        assert variables["input"]["recurrence"]["isRecurring"] is True
        assert variables["input"]["recurrence"]["frequency"] == "monthly"
        assert variables["input"]["recurrence"]["baseDate"] == "2026-06-01"
        assert variables["input"]["recurrence"]["amount"] == -1460.93
        assert variables["input"]["recurrence"]["isActive"] is True

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_update_both(self, mock_get_client):
        """Test updating name and recurrence together."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateMerchant": {
                "merchant": {
                    "id": "123",
                    "name": "Updated Name",
                    "recurringTransactionStream": {
                        "id": "stream_123",
                        "frequency": "biweekly",
                        "amount": 2038.37,
                        "baseDate": "2025-07-04",
                        "isActive": True,
                    },
                },
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        result = await update_merchant(
            merchant_id="123",
            name="Updated Name",
            frequency="biweekly",
            amount=2038.37,
        )

        data = json.loads(result)
        assert data["success"] is True
        assert data["merchant"]["name"] == "Updated Name"

        call_args = mock_client.gql_call.call_args
        variables = call_args.kwargs["variables"]
        assert variables["input"]["name"] == "Updated Name"
        assert "recurrence" in variables["input"]
        assert variables["input"]["recurrence"]["frequency"] == "biweekly"

    async def test_update_no_fields(self):
        """Test that calling with no updatable fields returns an error."""
        result = await update_merchant(merchant_id="123")

        data = json.loads(result)
        assert data["success"] is False
        assert "At least one field" in data["message"]

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_update_graphql_error(self, mock_get_client):
        """Test handling of GraphQL-level errors."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateMerchant": {
                "merchant": None,
                "errors": {
                    "message": "Merchant not found",
                    "code": "NOT_FOUND",
                    "fieldErrors": [],
                },
            }
        }
        mock_get_client.return_value = mock_client

        result = await update_merchant(
            merchant_id="invalid",
            name="Test",
        )

        data = json.loads(result)
        assert data["success"] is False
        assert data["errors"]["message"] == "Merchant not found"

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_update_auth_error(self, mock_get_client):
        """Test error handling when not authenticated."""
        mock_get_client.side_effect = RuntimeError("Auth needed")

        result = await update_merchant(
            merchant_id="123",
            name="Test",
        )

        data = json.loads(result)
        assert data["error"] is True
        assert "Auth needed" in data["message"]


class TestReviewRecurringStream:
    """Tests for review_recurring_stream tool."""

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_review_approve(self, mock_get_client):
        """Test approving a recurring stream."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "reviewRecurringStream": {
                "stream": {
                    "id": "stream_456",
                    "reviewStatus": "approved",
                },
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        result = await review_recurring_stream(
            stream_id="stream_456",
            review_status="approved",
        )

        data = json.loads(result)
        assert data["success"] is True
        assert data["stream_id"] == "stream_456"
        assert data["review_status"] == "approved"

        call_args = mock_client.gql_call.call_args
        variables = call_args.kwargs["variables"]
        assert variables["input"]["streamId"] == "stream_456"
        assert variables["input"]["reviewStatus"] == "approved"

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_review_ignore(self, mock_get_client):
        """Test ignoring a recurring stream."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "reviewRecurringStream": {
                "stream": {
                    "id": "stream_789",
                    "reviewStatus": "ignored",
                },
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        result = await review_recurring_stream(
            stream_id="stream_789",
            review_status="ignored",
        )

        data = json.loads(result)
        assert data["success"] is True
        assert data["review_status"] == "ignored"

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_review_graphql_error(self, mock_get_client):
        """Test handling of GraphQL-level errors."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "reviewRecurringStream": {
                "stream": None,
                "errors": {
                    "message": "Stream not found",
                    "code": "NOT_FOUND",
                    "fieldErrors": [],
                },
            }
        }
        mock_get_client.return_value = mock_client

        result = await review_recurring_stream(
            stream_id="invalid",
            review_status="approved",
        )

        data = json.loads(result)
        assert data["success"] is False
        assert data["errors"]["message"] == "Stream not found"

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_review_auth_error(self, mock_get_client):
        """Test error handling when not authenticated."""
        mock_get_client.side_effect = RuntimeError("Auth needed")

        result = await review_recurring_stream(
            stream_id="stream_123",
            review_status="approved",
        )

        data = json.loads(result)
        assert data["error"] is True
        assert "Auth needed" in data["message"]


class TestUpdateMerchantRejectsBlankName:
    """A whitespace rename would corrupt the record every transaction points at."""

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_a_blank_name_is_refused(self, mock_get_client):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        data = json.loads(await update_merchant(merchant_id="m_1", name="   "))
        assert data["error"] is True
        mock_client.gql_call.assert_not_called()


class TestUpdateMerchantFrequency:
    """Monarch refuses "annually" with an opaque error, so it is sent as "yearly"."""

    @staticmethod
    def _sent_frequency(mock_client):
        variables = mock_client.gql_call.call_args.kwargs["variables"]
        return variables["input"]["recurrence"]["frequency"]

    @pytest.mark.parametrize("given", ["annually", "Annually", " ANNUALLY "])
    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_annually_is_sent_as_yearly(self, mock_get_client, given):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateMerchant": {"merchant": {"id": "m_1"}, "errors": None}
        }
        mock_get_client.return_value = mock_client

        await update_merchant(merchant_id="m_1", frequency=given)

        assert self._sent_frequency(mock_client) == "yearly"

    @pytest.mark.parametrize(
        "given", ["weekly", "biweekly", "monthly", "quarterly", "yearly"]
    )
    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_verified_values_pass_through(self, mock_get_client, given):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateMerchant": {"merchant": {"id": "m_1"}, "errors": None}
        }
        mock_get_client.return_value = mock_client

        await update_merchant(merchant_id="m_1", frequency=given)

        assert self._sent_frequency(mock_client) == given

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_unverified_values_are_not_blocked(self, mock_get_client):
        """No allow-list: Monarch may accept values nobody has verified yet."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateMerchant": {"merchant": {"id": "m_1"}, "errors": None}
        }
        mock_get_client.return_value = mock_client

        await update_merchant(merchant_id="m_1", frequency="twice_a_month")

        assert self._sent_frequency(mock_client) == "twice_a_month"


class TestMergeMerchants:
    """Tests for merge_merchants tool."""

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_merges_source_into_target(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.delete_merchant.return_value = {"deleteMerchant": {"success": True}}
        mock_get_client.return_value = mock_client

        data = json.loads(
            await merge_merchants(source_merchant_id="1", target_merchant_id="2")
        )

        assert data == {
            "success": True,
            "source_merchant_id": "1",
            "target_merchant_id": "2",
        }
        mock_client.delete_merchant.assert_awaited_once_with(
            "1", move_to_merchant_id="2"
        )

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    @pytest.mark.parametrize(
        "response", [{"deleteMerchant": {"success": False}}, {"deleteMerchant": None}]
    )
    async def test_a_refusal_is_not_reported_as_success(
        self, mock_get_client, response
    ):
        mock_client = AsyncMock()
        mock_client.delete_merchant.return_value = response
        mock_get_client.return_value = mock_client

        data = json.loads(
            await merge_merchants(source_merchant_id="1", target_merchant_id="2")
        )

        assert data["success"] is False

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    @pytest.mark.parametrize(
        "source, target",
        [("1", "1"), ("1 ", "1"), ("1", ""), ("1", "   "), ("", "2")],
    )
    async def test_bad_ids_never_reach_monarch(self, mock_get_client, source, target):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        data = json.loads(
            await merge_merchants(source_merchant_id=source, target_merchant_id=target)
        )

        assert data["error"] is True
        mock_client.delete_merchant.assert_not_called()

    @patch("monarch_mcp_server.tools.merchants.get_monarch_client")
    async def test_padded_ids_are_trimmed(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.delete_merchant.return_value = {"deleteMerchant": {"success": True}}
        mock_get_client.return_value = mock_client

        await merge_merchants(source_merchant_id=" 1 ", target_merchant_id=" 2 ")

        mock_client.delete_merchant.assert_awaited_once_with(
            "1", move_to_merchant_id="2"
        )
