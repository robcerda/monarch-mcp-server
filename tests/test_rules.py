"""Tests for transaction rules MCP tools."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from monarch_mcp_server.tools.rules import (
    get_transaction_rules,
    create_transaction_rule,
    update_transaction_rule,
    delete_transaction_rule,
)


class TestGetTransactionRules:
    """Tests for get_transaction_rules tool."""

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_get_rules_success(self, mock_get_client):
        """Test successful retrieval of transaction rules."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "transactionRules": [
                {
                    "id": "rule_1",
                    "order": 0,
                    "merchantCriteriaUseOriginalStatement": False,
                    "merchantCriteria": [
                        {"operator": "contains", "value": "amazon"}
                    ],
                    "merchantNameCriteria": None,
                    "originalStatementCriteria": None,
                    "amountCriteria": None,
                    "categoryIds": None,
                    "accountIds": None,
                    "setCategoryAction": {
                        "id": "cat_123",
                        "name": "Shopping",
                    },
                    "setMerchantAction": None,
                    "addTagsAction": [
                        {"id": "tag_1", "name": "Online", "color": "#FF0000"}
                    ],
                    "linkGoalAction": None,
                    "setHideFromReportsAction": False,
                    "reviewStatusAction": None,
                    "recentApplicationCount": 5,
                    "lastAppliedAt": "2024-01-15T10:00:00Z",
                },
            ]
        }
        mock_get_client.return_value = mock_client

        result = await get_transaction_rules()

        rules = json.loads(result)
        assert len(rules) == 1
        assert rules[0]["id"] == "rule_1"
        assert rules[0]["merchant_criteria"][0]["value"] == "amazon"
        assert rules[0]["set_category_action"]["name"] == "Shopping"
        assert rules[0]["add_tags_action"][0]["name"] == "Online"

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_get_rules_empty(self, mock_get_client):
        """Test when no rules exist."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"transactionRules": []}
        mock_get_client.return_value = mock_client

        result = await get_transaction_rules()

        rules = json.loads(result)
        assert len(rules) == 0

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_get_rules_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("Auth needed")

        result = await get_transaction_rules()

        data = json.loads(result)
        assert data["error"] is True
        assert "Auth needed" in data["message"]


class TestCreateTransactionRule:
    """Tests for create_transaction_rule tool."""

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_create_rule_simple(self, mock_get_client):
        """Test creating a simple merchant-to-category rule."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "createTransactionRuleV2": {"errors": None}
        }
        mock_get_client.return_value = mock_client

        result = await create_transaction_rule(
            merchant_criteria_operator="contains",
            merchant_criteria_value="amazon",
            set_category_id="cat_123"
        )

        data = json.loads(result)
        assert data["success"] is True

        # Verify the call
        call_args = mock_client.gql_call.call_args
        variables = call_args.kwargs["variables"]
        assert variables["input"]["merchantNameCriteria"][0]["operator"] == "contains"
        assert variables["input"]["merchantNameCriteria"][0]["value"] == "amazon"
        assert variables["input"]["setCategoryAction"] == "cat_123"

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_create_rule_with_amount(self, mock_get_client):
        """Test creating a rule with amount criteria."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "createTransactionRuleV2": {"errors": None}
        }
        mock_get_client.return_value = mock_client

        result = await create_transaction_rule(
            merchant_criteria_operator="contains",
            merchant_criteria_value="uber",
            amount_operator="lt",
            amount_value=50.0,
            amount_is_expense=True,
            set_category_id="cat_transport"
        )

        data = json.loads(result)
        assert data["success"] is True

        call_args = mock_client.gql_call.call_args
        variables = call_args.kwargs["variables"]
        assert variables["input"]["amountCriteria"]["operator"] == "lt"
        assert variables["input"]["amountCriteria"]["value"] == 50.0
        assert variables["input"]["amountCriteria"]["isExpense"] is True

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_create_rule_with_tags(self, mock_get_client):
        """Test creating a rule that adds tags."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "createTransactionRuleV2": {"errors": None}
        }
        mock_get_client.return_value = mock_client

        result = await create_transaction_rule(
            merchant_criteria_operator="eq",
            merchant_criteria_value="netflix",
            add_tag_ids=["tag_1", "tag_2"]
        )

        data = json.loads(result)
        assert data["success"] is True

        call_args = mock_client.gql_call.call_args
        variables = call_args.kwargs["variables"]
        assert variables["input"]["addTagsAction"] == ["tag_1", "tag_2"]

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_create_rule_error(self, mock_get_client):
        """Test error handling when creation fails."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "createTransactionRuleV2": {
                "errors": {
                    "message": "Invalid category ID",
                    "code": "INVALID_INPUT"
                }
            }
        }
        mock_get_client.return_value = mock_client

        result = await create_transaction_rule(
            merchant_criteria_operator="contains",
            merchant_criteria_value="test",
            set_category_id="invalid_cat"
        )

        data = json.loads(result)
        assert data["success"] is False
        assert data["errors"] is not None

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_create_rule_with_multiple_merchant_values(self, mock_get_client):
        """Test creating a rule that matches multiple merchants in one rule."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "createTransactionRuleV2": {"errors": None}
        }
        mock_get_client.return_value = mock_client

        result = await create_transaction_rule(
            merchant_criteria_operator="contains",
            merchant_criteria_values=["american education services", "origin aes"],
            set_category_id="cat_student_loans"
        )

        data = json.loads(result)
        assert data["success"] is True

        call_args = mock_client.gql_call.call_args
        criteria = call_args.kwargs["variables"]["input"]["merchantNameCriteria"]
        assert len(criteria) == 2
        assert criteria[0] == {"operator": "contains", "value": "american education services"}
        assert criteria[1] == {"operator": "contains", "value": "origin aes"}

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_create_rule_multiple_values_default_operator(self, mock_get_client):
        """merchant_criteria_values should default to the 'contains' operator."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "createTransactionRuleV2": {"errors": None}
        }
        mock_get_client.return_value = mock_client

        result = await create_transaction_rule(
            merchant_criteria_values=["fnbo", "slice"]
        )

        data = json.loads(result)
        assert data["success"] is True

        call_args = mock_client.gql_call.call_args
        criteria = call_args.kwargs["variables"]["input"]["merchantNameCriteria"]
        assert [c["value"] for c in criteria] == ["fnbo", "slice"]
        assert all(c["operator"] == "contains" for c in criteria)


class TestUpdateTransactionRule:
    """Tests for update_transaction_rule tool."""

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_update_rule_success(self, mock_get_client):
        """Test successful rule update."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateTransactionRuleV2": {"errors": None}
        }
        mock_get_client.return_value = mock_client

        result = await update_transaction_rule(
            rule_id="rule_123",
            merchant_criteria_operator="contains",
            merchant_criteria_value="amazon prime",
            set_category_id="cat_456"
        )

        data = json.loads(result)
        assert data["success"] is True

        call_args = mock_client.gql_call.call_args
        variables = call_args.kwargs["variables"]
        assert variables["input"]["id"] == "rule_123"

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_update_rule_error(self, mock_get_client):
        """Test error handling when update fails."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateTransactionRuleV2": {
                "errors": {"message": "Rule not found"}
            }
        }
        mock_get_client.return_value = mock_client

        result = await update_transaction_rule(
            rule_id="invalid_rule",
            merchant_criteria_operator="eq",
            merchant_criteria_value="test"
        )

        data = json.loads(result)
        assert data["success"] is False

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_update_rule_with_multiple_merchant_values(self, mock_get_client):
        """Test updating a rule to match multiple merchants in one rule."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateTransactionRuleV2": {"errors": None}
        }
        mock_get_client.return_value = mock_client

        result = await update_transaction_rule(
            rule_id="rule_123",
            merchant_criteria_operator="contains",
            merchant_criteria_values=["courtyard", "hotel"],
            set_category_id="cat_hotel"
        )

        data = json.loads(result)
        assert data["success"] is True

        call_args = mock_client.gql_call.call_args
        criteria = call_args.kwargs["variables"]["input"]["merchantNameCriteria"]
        assert [c["value"] for c in criteria] == ["courtyard", "hotel"]


class TestDeleteTransactionRule:
    """Tests for delete_transaction_rule tool."""

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_delete_rule_success(self, mock_get_client):
        """Test successful rule deletion."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "deleteTransactionRule": {
                "deleted": True,
                "errors": None
            }
        }
        mock_get_client.return_value = mock_client

        result = await delete_transaction_rule(rule_id="rule_123")

        data = json.loads(result)
        assert data["success"] is True
        assert "deleted" in data["message"].lower()

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_delete_rule_not_found(self, mock_get_client):
        """Test deletion when rule doesn't exist."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "deleteTransactionRule": {
                "deleted": False,
                "errors": {"message": "Rule not found"}
            }
        }
        mock_get_client.return_value = mock_client

        result = await delete_transaction_rule(rule_id="invalid_rule")

        data = json.loads(result)
        assert data["success"] is False

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_delete_rule_error(self, mock_get_client):
        """Test error handling."""
        mock_get_client.side_effect = RuntimeError("API error")

        result = await delete_transaction_rule(rule_id="rule_123")

        data = json.loads(result)
        assert data["error"] is True
        assert "API error" in data["message"]

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_delete_rule_success_without_deleted_flag(self, mock_get_client):
        """Monarch omits the `deleted` flag on success; absence of errors
        should be treated as a successful deletion, not 'Unknown error'."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "deleteTransactionRule": {"errors": None}
        }
        mock_get_client.return_value = mock_client

        result = await delete_transaction_rule(rule_id="rule_123")

        data = json.loads(result)
        assert data["success"] is True
        assert "deleted" in data["message"].lower()
