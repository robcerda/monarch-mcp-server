"""Tests for transaction rules MCP tools."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from monarch_mcp_server.tools.rules import (
    get_transaction_rules,
    reorder_transaction_rule,
    create_transaction_rule,
    update_transaction_rule,
    delete_transaction_rule,
)


def _existing_rule(**overrides):
    """A rule as GetTransactionRules returns it, for update tests.

    update_transaction_rule reads the rule before writing it, so its mock needs
    to answer the fetch first and the mutation second.
    """
    rule = {
        "id": "rule_123",
        "order": 0,
        "merchantCriteriaUseOriginalStatement": False,
        "merchantNameCriteria": [{"operator": "contains", "value": "amazon"}],
        "originalStatementCriteria": None,
        "amountCriteria": None,
        "categoryIds": None,
        "accountIds": None,
        "setCategoryAction": {"id": "cat_old", "name": "Old"},
        "setMerchantAction": {"id": "merch_1", "name": "Existing Merchant"},
        "addTagsAction": [{"id": "tag_1", "name": "Existing Tag"}],
        "linkGoalAction": {"id": "goal_1", "name": "Existing Goal"},
        "setHideFromReportsAction": True,
        "reviewStatusAction": "needs_review",
        "actionSetBusinessEntity": {"id": "biz_1", "name": "Acme"},
        "actionSetOwner": {"id": "user_1", "displayName": "Sam"},
        "linkSavingsGoalAction": {"id": "sg_1", "name": "Rainy Day"},
        "needsReviewByUserAction": {"id": "user_1", "displayName": "Sam"},
        "sendNotificationAction": True,
        "criteriaBusinessEntityIds": ["biz_1"],
        "splitTransactionsAction": {
            "amountType": "PERCENTAGE",
            "splitsInfo": [
                {"categoryId": "c1", "amount": 60.0, "__typename": "SplitsInfo"},
                {"categoryId": "c2", "amount": 40.0, "__typename": "SplitsInfo"},
            ],
        },
    }
    rule.update(overrides)
    return rule


def _update_mock(rule=None, errors=None):
    """Mock client answering the fetch, then the update mutation."""
    client = AsyncMock()
    client.gql_call.side_effect = [
        {"transactionRules": [rule if rule is not None else _existing_rule()]},
        {"updateTransactionRuleV2": {"transactionRule": {"id": "rule_123"},
                                     "errors": errors}},
    ]
    return client

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

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_create_rule_returns_id(self, mock_get_client):
        """The created rule's id is returned so callers can chain on it."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "createTransactionRuleV2": {
                "transactionRule": {"id": "rule_new", "order": 3},
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        result = await create_transaction_rule(
            merchant_criteria_values=["amazon"], set_category_id="cat_1"
        )

        data = json.loads(result)
        assert data["success"] is True
        assert data["rule_id"] == "rule_new"

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_create_rule_with_original_statement(self, mock_get_client):
        """Original-statement criteria are sent through to the API."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "createTransactionRuleV2": {"transactionRule": {"id": "r"},
                                        "errors": None}
        }
        mock_get_client.return_value = mock_client

        await create_transaction_rule(
            original_statement_values=["klarna"], set_category_id="cat_1"
        )

        sent = mock_client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent["originalStatementCriteria"] == [
            {"operator": "contains", "value": "klarna"}
        ]

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_create_rule_with_per_value_operators(self, mock_get_client):
        """Each merchant value can carry its own operator."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "createTransactionRuleV2": {"transactionRule": {"id": "r"},
                                        "errors": None}
        }
        mock_get_client.return_value = mock_client

        await create_transaction_rule(
            merchant_criteria=[
                {"operator": "contains", "value": "netflix"},
                {"operator": "eq", "value": "apple"},
            ],
            set_category_id="cat_1",
        )

        sent = mock_client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent["merchantNameCriteria"] == [
            {"operator": "contains", "value": "netflix"},
            {"operator": "eq", "value": "apple"},
        ]

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_create_rule_amount_between(self, mock_get_client):
        """`between` populates valueRange rather than a scalar value."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "createTransactionRuleV2": {"transactionRule": {"id": "r"},
                                        "errors": None}
        }
        mock_get_client.return_value = mock_client

        await create_transaction_rule(
            amount_operator="between", amount_lower=10.0, amount_upper=50.0,
            set_category_id="cat_1",
        )

        sent = mock_client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent["amountCriteria"]["valueRange"] == {"lower": 10.0, "upper": 50.0}

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_create_rule_requires_criteria(self, mock_get_client):
        """A rule with no criteria is rejected before hitting the API."""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await create_transaction_rule(set_category_id="cat_1")

        assert json.loads(result)["success"] is False
        mock_client.gql_call.assert_not_called()

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_create_rule_blank_error_payload(self, mock_get_client):
        """An all-null PayloadError is reported as a real, readable failure."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "createTransactionRuleV2": {
                "transactionRule": None,
                "errors": {"fieldErrors": None, "message": None, "code": None},
            }
        }
        mock_get_client.return_value = mock_client

        result = await create_transaction_rule(
            merchant_criteria_values=["x"], set_category_id="cat_1"
        )

        data = json.loads(result)
        assert data["success"] is False
        assert data["errors"]["message"]


class TestUpdateTransactionRule:
    """Tests for update_transaction_rule tool."""

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_update_rule_success(self, mock_get_client):
        """Test successful rule update."""
        mock_client = _update_mock()
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
        mock_client = _update_mock(
            rule=_existing_rule(id="invalid_rule"),
            errors={"message": "Rule not found"},
        )
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
        mock_client = _update_mock()
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

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_update_action_only_resends_existing_criteria(self, mock_get_client):
        """Changing only an action must still send the rule's criteria.

        Monarch ignores an update whose input carries no matching criteria, so
        a category-only change used to be accepted by the tool and silently
        dropped by the API.
        """
        mock_client = _update_mock(rule=_existing_rule(
            merchantNameCriteria=[{"operator": "contains", "value": "amazon"}],
            originalStatementCriteria=[{"operator": "contains", "value": "amzn"}],
        ))
        mock_get_client.return_value = mock_client

        result = await update_transaction_rule(
            rule_id="rule_123", set_category_id="cat_new"
        )

        data = json.loads(result)
        assert data["success"] is True

        sent = mock_client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent["merchantNameCriteria"] == [
            {"operator": "contains", "value": "amazon"}
        ]
        assert sent["originalStatementCriteria"] == [
            {"operator": "contains", "value": "amzn"}
        ]
        assert sent["setCategoryAction"] == "cat_new"

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_update_preserves_existing_amount_criteria(self, mock_get_client):
        """A rule matching only on amount is still updatable."""
        mock_client = _update_mock(rule=_existing_rule(
            merchantNameCriteria=None,
            amountCriteria={"operator": "gt", "isExpense": True,
                            "value": 10.0, "valueRange": None},
        ))
        mock_get_client.return_value = mock_client

        result = await update_transaction_rule(
            rule_id="rule_123", set_category_id="cat_new"
        )

        assert json.loads(result)["success"] is True
        sent = mock_client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent["amountCriteria"]["value"] == 10.0

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_update_rule_not_found(self, mock_get_client):
        """Updating an unknown id reports failure rather than writing blindly."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"transactionRules": []}
        mock_get_client.return_value = mock_client

        result = await update_transaction_rule(
            rule_id="missing", set_category_id="cat_new"
        )

        data = json.loads(result)
        assert data["success"] is False
        assert "missing" in data["message"]

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_update_preserves_actions_it_was_not_given(self, mock_get_client):
        """Regression: changing one action must not wipe the others.

        Monarch clears any action absent from the mutation input, so a caller
        passing only link_goal_id previously destroyed the rule's category and
        merchant silently, with a success response and no warning.
        """
        mock_client = _update_mock()
        mock_get_client.return_value = mock_client

        result = await update_transaction_rule(rule_id="rule_123",
                                               link_goal_id="goal_new")

        assert json.loads(result)["success"] is True
        sent = mock_client.gql_call.call_args.kwargs["variables"]["input"]

        assert sent["linkGoalAction"] == "goal_new"       # the requested change
        assert sent["setCategoryAction"] == "cat_old"     # preserved
        assert sent["addTagsAction"] == ["tag_1"]         # preserved
        assert sent["setHideFromReportsAction"] is True   # preserved
        assert sent["reviewStatusAction"] == "needs_review"
        # Carried forward as a NAME. The id would create a new merchant named
        # with that id string.
        assert sent["setMerchantAction"] == "Existing Merchant"

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_update_category_preserves_goal_link(self, mock_get_client):
        """The reverse direction of the same bug."""
        mock_client = _update_mock()
        mock_get_client.return_value = mock_client

        await update_transaction_rule(rule_id="rule_123", set_category_id="cat_new")

        sent = mock_client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent["setCategoryAction"] == "cat_new"
        assert sent["linkGoalAction"] == "goal_1"
        assert sent["setMerchantAction"] == "Existing Merchant"

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_clear_flags_remove_actions(self, mock_get_client):
        """clear_* is the only way to remove an action deliberately."""
        mock_client = _update_mock()
        mock_get_client.return_value = mock_client

        await update_transaction_rule(
            rule_id="rule_123",
            clear_category=True, clear_merchant=True,
            clear_tags=True, clear_goal_link=True, clear_review_status=True,
        )

        sent = mock_client.gql_call.call_args.kwargs["variables"]["input"]
        for field in ("setCategoryAction", "setMerchantAction", "addTagsAction",
                      "linkGoalAction", "reviewStatusAction"):
            assert field not in sent

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_update_preserves_account_and_category_criteria(self, mock_get_client):
        """Criteria restrictions are carried forward on the same principle."""
        mock_client = _update_mock(rule=_existing_rule(
            accountIds=["acc_1"], categoryIds=["cat_filter"],
        ))
        mock_get_client.return_value = mock_client

        await update_transaction_rule(rule_id="rule_123", set_category_id="cat_new")

        sent = mock_client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent["accountIds"] == ["acc_1"]
        assert sent["categoryIds"] == ["cat_filter"]

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_update_preserves_plan_gated_and_nested_actions(self, mock_get_client):
        """Regression: business entity, owner, savings goal, notification,
        review assignee and split action must all survive a partial update.

        These were invisible to the merge because the read query did not select
        them, so a category-only update silently deleted a rule's business
        entity -- verified against a live account before the fix.
        """
        mock_client = _update_mock()
        mock_get_client.return_value = mock_client

        await update_transaction_rule(rule_id="rule_123", set_category_id="cat_new")

        sent = mock_client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent["actionSetBusinessEntity"] == "biz_1"
        assert sent["actionSetOwner"] == "user_1"
        assert sent["linkSavingsGoalAction"] == "sg_1"
        assert sent["sendNotificationAction"] is True
        assert sent["criteriaBusinessEntityIds"] == ["biz_1"]
        # needs_review_by_user_action is rejected without a review status, so
        # the pair travels together.
        assert sent["needsReviewByUserAction"] == "user_1"
        assert sent["reviewStatusAction"] == "needs_review"
        # splitsInfo is rebuilt without the __typename the read adds.
        assert sent["splitTransactionsAction"]["amountType"] == "PERCENTAGE"
        assert sent["splitTransactionsAction"]["splitsInfo"] == [
            {"categoryId": "c1", "amount": 60.0},
            {"categoryId": "c2", "amount": 40.0},
        ]

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_reviewer_dropped_when_review_status_cleared(self, mock_get_client):
        """Clearing the review status must not leave an orphan assignee.

        Monarch rejects needs_review_by_user_action without review_status_action.
        """
        mock_client = _update_mock()
        mock_get_client.return_value = mock_client

        await update_transaction_rule(rule_id="rule_123", clear_review_status=True)

        sent = mock_client.gql_call.call_args.kwargs["variables"]["input"]
        assert "reviewStatusAction" not in sent
        assert "needsReviewByUserAction" not in sent


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

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_delete_rule_success_with_false_deleted_flag(self, mock_get_client):
        """Monarch returns `deleted: false` with no errors even when the rule
        was successfully removed (verified against the live API). The flag must
        not be treated as a failure signal, or every real deletion is reported
        as having failed."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "deleteTransactionRule": {"deleted": False, "errors": None}
        }
        mock_get_client.return_value = mock_client

        result = await delete_transaction_rule(rule_id="rule_123")

        data = json.loads(result)
        assert data["success"] is True
        assert "deleted" in data["message"].lower()


class TestAmountCriterionIsNeverSilentlyDropped:
    """A rule is standing policy, so a lost criterion is not a small thing.

    The amount criterion was built behind a two part guard and omitted
    entirely when only one half was supplied, with the tool still reporting
    that the rule was created.
    """

    @patch("monarch_mcp_server.tools.rules.get_monarch_client")
    async def test_value_without_operator_is_rejected(self, mock_get_client):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = json.loads(
            await create_transaction_rule(
                merchant_criteria_value="Costco",
                amount_value=500.0,
                set_category_id="cat_travel",
                apply_to_existing=True,
            )
        )

        assert result.get("error") or result.get("success") is False
        assert "amount_operator" in json.dumps(result)
        # Nothing may reach the API: the rule would match every Costco
        # transaction and apply_to_existing rewrites history immediately.
        mock_client.gql_call.assert_not_called()

    @patch("monarch_mcp_server.tools.rules.get_monarch_client")
    async def test_operator_without_value_is_rejected(self, mock_get_client):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = json.loads(
            await create_transaction_rule(
                merchant_criteria_value="Costco",
                amount_operator="gt",
                set_category_id="cat_travel",
            )
        )

        assert result.get("error") or result.get("success") is False
        mock_client.gql_call.assert_not_called()

    @patch("monarch_mcp_server.tools.rules.get_monarch_client")
    async def test_both_halves_together_still_work(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "createTransactionRuleV2": {"errors": None, "transactionRule": {"id": "r1"}}
        }
        mock_get_client.return_value = mock_client

        result = json.loads(
            await create_transaction_rule(
                merchant_criteria_value="Costco",
                amount_operator="gt",
                amount_value=500.0,
                set_category_id="cat_travel",
            )
        )

        assert result["success"] is True
        sent = mock_client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent["amountCriteria"]["operator"] == "gt"
        assert sent["amountCriteria"]["value"] == 500.0

    @patch("monarch_mcp_server.tools.rules.get_monarch_client")
    async def test_no_amount_arguments_at_all_is_fine(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "createTransactionRuleV2": {"errors": None, "transactionRule": {"id": "r1"}}
        }
        mock_get_client.return_value = mock_client

        result = json.loads(
            await create_transaction_rule(
                merchant_criteria_value="Costco", set_category_id="cat_x"
            )
        )
        assert result["success"] is True


class TestReorderTransactionRule:
    """Tests for reorder_transaction_rule tool."""

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_reorder_success(self, mock_get_client):
        """Moving a rule returns the resulting order of every rule."""
        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = [
            {"transactionRules": [{"id": "rule_1", "order": 3}]},
            {"updateTransactionRuleOrderV2": {"transactionRules": [
                {"id": "rule_1", "order": 0}, {"id": "rule_2", "order": 1},
            ]}},
        ]
        mock_get_client.return_value = mock_client

        data = json.loads(await reorder_transaction_rule("rule_1", 0))

        assert data["success"] is True
        assert data["moved_from"] == 3
        assert data["moved_to"] == 0
        assert data["order"][0] == {"rule_id": "rule_1", "order": 0}

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_reorder_unknown_rule(self, mock_get_client):
        """An unknown id fails before the mutation is sent."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"transactionRules": []}
        mock_get_client.return_value = mock_client

        data = json.loads(await reorder_transaction_rule("missing", 0))

        assert data["success"] is False
        assert mock_client.gql_call.call_count == 1

    @patch('monarch_mcp_server.tools.rules.get_monarch_client')
    async def test_negative_order_rejected(self, mock_get_client):
        """A negative position is rejected without any API call."""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        data = json.loads(await reorder_transaction_rule("rule_1", -1))

        assert data["success"] is False
        mock_client.gql_call.assert_not_called()


class TestRangeCriteriaAreNotSilentlyDropped:
    """The range half of the same hole the amount guard was added to close.

    amount_lower/amount_upper without an operator produced no amountCriteria
    at all, so the rule matched every transaction from the merchant and, with
    apply_to_existing, rewrote history immediately while reporting success.
    """

    @patch("monarch_mcp_server.tools.rules.get_monarch_client")
    async def test_range_without_operator_is_rejected(self, mock_get_client):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = json.loads(
            await create_transaction_rule(
                merchant_criteria_value="Costco",
                amount_lower=10,
                amount_upper=50,
                set_category_id="cat_x",
                apply_to_existing=True,
            )
        )
        assert result.get("error") or result.get("success") is False
        mock_client.gql_call.assert_not_called()

    @patch("monarch_mcp_server.tools.rules.get_monarch_client")
    async def test_lone_upper_bound_is_rejected(self, mock_get_client):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = json.loads(
            await create_transaction_rule(
                merchant_criteria_value="Costco", amount_upper=50
            )
        )
        assert result.get("error") or result.get("success") is False
        mock_client.gql_call.assert_not_called()

    @patch("monarch_mcp_server.tools.rules.get_monarch_client")
    async def test_a_valid_between_rule_still_works(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "createTransactionRuleV2": {
                "errors": None,
                "transactionRule": {"id": "r1"},
            }
        }
        mock_get_client.return_value = mock_client

        result = json.loads(
            await create_transaction_rule(
                merchant_criteria_value="Costco",
                amount_operator="between",
                amount_lower=10,
                amount_upper=50,
                set_category_id="cat_x",
            )
        )
        assert result["success"] is True
        sent = mock_client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent["amountCriteria"]["valueRange"] == {"lower": 10, "upper": 50}


class TestReorderReportsRejection:
    @patch("monarch_mcp_server.tools.rules.get_monarch_client")
    async def test_refused_reorder_is_not_reported_as_success(self, mock_get_client):
        """Rule order decides which rule wins, so a silent no-op mis-categorizes."""
        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = [
            {"transactionRules": [{"id": "r1", "order": 5}]},
            {
                "updateTransactionRuleOrderV2": {
                    "transactionRules": [],
                    "errors": {"message": "not allowed", "code": "FORBIDDEN"},
                }
            },
        ]
        mock_get_client.return_value = mock_client

        result = json.loads(await reorder_transaction_rule("r1", 0))
        assert result["success"] is False
        assert "not allowed" in json.dumps(result)

    @patch("monarch_mcp_server.tools.rules.get_monarch_client")
    async def test_landed_position_is_read_back_not_echoed(self, mock_get_client):
        """Monarch renumbers, so the landed order can differ from the request."""
        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = [
            {"transactionRules": [{"id": "r1", "order": 5}]},
            {
                "updateTransactionRuleOrderV2": {
                    "transactionRules": [
                        {"id": "r1", "order": 2},
                        {"id": "r2", "order": 0},
                    ],
                    "errors": None,
                }
            },
        ]
        mock_get_client.return_value = mock_client

        result = json.loads(await reorder_transaction_rule("r1", 99))
        assert result["success"] is True
        assert result["moved_to"] == 2
        assert result["requested_order"] == 99


class TestRulesRejectBlankMerchantName:
    """A rule setting a whitespace merchant renames every match to junk.

    `if set_merchant_name:` filtered "" but not "   ", so this was the one
    merchant-name write path that looked guarded and was not.
    """

    @patch("monarch_mcp_server.tools.rules.get_monarch_client")
    async def test_create_refuses_a_blank_merchant_name(self, mock_get_client):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        data = json.loads(
            await create_transaction_rule(
                merchant_criteria_values=["amazon"],
                set_merchant_name="   ",
            )
        )
        assert data["error"] is True
        mock_client.gql_call.assert_not_called()

    @patch("monarch_mcp_server.tools.rules.get_monarch_client")
    async def test_update_refuses_a_blank_merchant_name(self, mock_get_client):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        data = json.loads(
            await update_transaction_rule(rule_id="rule_1", set_merchant_name="   ")
        )
        assert data["error"] is True
        mock_client.gql_call.assert_not_called()
