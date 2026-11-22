"""Tests for account identity tools."""

import json
from unittest.mock import AsyncMock, patch

from monarch_mcp_server.tools.identity import get_household_members, monarch_whoami


def _payload(**sub_overrides):
    sub = {
        "id": "sub_1",
        "entitlements": ["premium"],
        "hasPremiumEntitlement": True,
        "isOnFreeTrial": False,
        "billingPeriod": "YEARLY",
        "currentPeriodEndsAt": "2026-09-10T00:28:55+00:00",
        "trialEndsAt": None,
        "willCancelAtPeriodEnd": False,
        "paymentSource": "STRIPE",
        "nextPaymentAmount": 144.01,
    }
    sub.update(sub_overrides)
    return {
        "me": {
            "id": "u1", "name": "Test User", "email": "t@example.com",
            "timezone": "America/Chicago", "hasPassword": True,
            "externalAuthProviderNames": ["google"],
        },
        "subscription": sub,
    }


def _client(payload, entities=None, entities_fail=False):
    """First call is whoami; the second is the business-entity probe."""
    c = AsyncMock()

    async def side_effect(*a, **kw):
        if kw.get("operation") == "GetWhoAmI":
            return payload
        if entities_fail:
            raise Exception("Something went wrong")
        return {"businessEntities": entities or []}

    c.gql_call.side_effect = side_effect
    return c


class TestMonarchWhoami:
    """Tests for monarch_whoami tool."""

    @patch('monarch_mcp_server.tools.identity.get_monarch_client')
    async def test_reports_user_and_subscription(self, mock_get_client):
        mock_get_client.return_value = _client(_payload())

        data = json.loads(await monarch_whoami())

        assert data["user"]["timezone"] == "America/Chicago"
        assert data["subscription"]["billing_period"] == "YEARLY"

    @patch('monarch_mcp_server.tools.identity.get_monarch_client')
    async def test_business_entities_available(self, mock_get_client):
        """A working probe reports the feature and the ids it needs."""
        mock_get_client.return_value = _client(
            _payload(), entities=[{"id": "b1", "name": "Acme", "color": "#fff"}])

        caps = json.loads(await monarch_whoami())["capabilities"]

        assert caps["business_entities"]["available"] is True
        assert caps["business_entities"]["items"][0]["id"] == "b1"

    @patch('monarch_mcp_server.tools.identity.get_monarch_client')
    async def test_business_entities_gated_off(self, mock_get_client):
        """On a plan without the feature the probe errors; that IS the answer.

        Monarch removes gated fields from the schema and masks the failure as a
        generic error, so an exception must be reported as 'not available'
        rather than failing the whole tool.
        """
        mock_get_client.return_value = _client(_payload(), entities_fail=True)

        data = json.loads(await monarch_whoami())

        assert data.get("error") is None
        assert data["capabilities"]["business_entities"]["available"] is False
        assert data["capabilities"]["business_entities"]["items"] == []

    @patch('monarch_mcp_server.tools.identity.get_monarch_client')
    async def test_trial_entitlements_flagged(self, mock_get_client):
        """A trial-granted feature can disappear, so it is called out."""
        mock_get_client.return_value = _client(
            _payload(entitlements=["premium", "premium_plus_trial"]))

        data = json.loads(await monarch_whoami())

        assert data["trial_entitlements"] == ["premium_plus_trial"]
        assert "lapse" in data["note"]

    @patch('monarch_mcp_server.tools.identity.get_monarch_client')
    async def test_no_trial_entitlements_no_warning(self, mock_get_client):
        mock_get_client.return_value = _client(_payload())

        data = json.loads(await monarch_whoami())

        assert data["trial_entitlements"] == []
        assert "lapse" not in data["note"]

    @patch('monarch_mcp_server.tools.identity.get_monarch_client')
    async def test_pii_is_not_returned(self, mock_get_client):
        """birthday and profile picture are deliberately not selected."""
        mock_get_client.return_value = _client(_payload())

        blob = await monarch_whoami()

        assert "birthday" not in blob
        assert "profilePictureUrl" not in blob

    @patch('monarch_mcp_server.tools.identity.get_monarch_client')
    async def test_error_handling(self, mock_get_client):
        c = AsyncMock()
        c.gql_call.side_effect = Exception("boom")
        mock_get_client.return_value = c

        data = json.loads(await monarch_whoami())

        assert data["error"] is True
        assert data["tool"] == "monarch_whoami"


class TestGetHouseholdMembers:
    """Tests for get_household_members tool."""

    @patch('monarch_mcp_server.tools.identity.get_monarch_client')
    async def test_returns_members(self, mock_get_client):
        users = [
            {"id": "u1", "name": "Alex", "displayName": "Alex", "householdRole": "OWNER"},
            {"id": "u2", "name": "Sam", "displayName": "Sam", "householdRole": "MEMBER"},
        ]
        client = AsyncMock()
        client.get_household_members.return_value = {"myHousehold": {"users": users}}
        mock_get_client.return_value = client

        data = json.loads(await get_household_members())

        assert data == {"myHousehold": {"users": users}}
        client.get_household_members.assert_awaited_once_with()

    @patch('monarch_mcp_server.tools.identity.get_monarch_client')
    async def test_returns_empty_members(self, mock_get_client):
        client = AsyncMock()
        client.get_household_members.return_value = {"myHousehold": {"users": []}}
        mock_get_client.return_value = client

        data = json.loads(await get_household_members())

        assert data == {"myHousehold": {"users": []}}
        client.get_household_members.assert_awaited_once_with()

    @patch('monarch_mcp_server.tools.identity.get_monarch_client')
    async def test_error_handling(self, mock_get_client):
        client = AsyncMock()
        client.get_household_members.side_effect = Exception("Request failed")
        mock_get_client.return_value = client

        data = json.loads(await get_household_members())

        assert data["error"] is True
        assert data["tool"] == "get_household_members"
        assert data["message"] == "Request failed"
