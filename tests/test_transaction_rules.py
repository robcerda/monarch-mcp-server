"""Tests for create_transaction_rule tool."""
# pylint: disable=missing-function-docstring

import json


# ===================================================================
# 1 – happy path: merchant name "contains"
# ===================================================================


async def test_create_rule_merchant_contains(mcp_write_client, mock_monarch_client):
    mock_monarch_client.gql_call.return_value = {
        "createTransactionRuleV2": {"errors": []}
    }

    result = json.loads(
        (await mcp_write_client.call_tool(
            "create_transaction_rule",
            {
                "set_category_id": "cat-123",
                "merchant_name_value": "Amazon",
            },
        )).content[0].text
    )

    assert result["created"] is True
    call_kwargs = mock_monarch_client.gql_call.call_args[1]
    assert call_kwargs["operation"] == "Common_CreateTransactionRuleMutationV2"
    variables = call_kwargs["variables"]
    assert variables["input"]["merchantNameCriteria"] == [
        {"operator": "contains", "value": "Amazon"}
    ]
    assert variables["input"]["setCategoryAction"] == "cat-123"
    assert variables["input"]["applyToExistingTransactions"] is False


# ===================================================================
# 2 – happy path: merchant name "eq"
# ===================================================================


async def test_create_rule_merchant_eq(mcp_write_client, mock_monarch_client):
    mock_monarch_client.gql_call.return_value = {
        "createTransactionRuleV2": {"errors": []}
    }

    result = json.loads(
        (await mcp_write_client.call_tool(
            "create_transaction_rule",
            {
                "set_category_id": "cat-456",
                "merchant_name_value": "contribution",
                "merchant_name_operator": "eq",
            },
        )).content[0].text
    )

    assert result["created"] is True
    variables = mock_monarch_client.gql_call.call_args[1]["variables"]
    assert variables["input"]["merchantNameCriteria"] == [
        {"operator": "eq", "value": "contribution"}
    ]


# ===================================================================
# 3 – happy path: original statement criteria
# ===================================================================


async def test_create_rule_original_statement(mcp_write_client, mock_monarch_client):
    mock_monarch_client.gql_call.return_value = {
        "createTransactionRuleV2": {"errors": []}
    }

    result = json.loads(
        (await mcp_write_client.call_tool(
            "create_transaction_rule",
            {
                "set_category_id": "cat-789",
                "original_statement_value": "ROLLOVER CASH",
                "original_statement_operator": "contains",
            },
        )).content[0].text
    )

    assert result["created"] is True
    variables = mock_monarch_client.gql_call.call_args[1]["variables"]
    assert variables["input"]["originalStatementCriteria"] == [
        {"operator": "contains", "value": "ROLLOVER CASH"}
    ]


# ===================================================================
# 4 – happy path: account_ids scoping
# ===================================================================


async def test_create_rule_with_account_ids(mcp_write_client, mock_monarch_client):
    mock_monarch_client.gql_call.return_value = {
        "createTransactionRuleV2": {"errors": []}
    }

    result = json.loads(
        (await mcp_write_client.call_tool(
            "create_transaction_rule",
            {
                "set_category_id": "cat-123",
                "merchant_name_value": "Fidelity",
                "account_ids": ["acct-1", "acct-2"],
            },
        )).content[0].text
    )

    assert result["created"] is True
    variables = mock_monarch_client.gql_call.call_args[1]["variables"]
    assert variables["input"]["accountIds"] == ["acct-1", "acct-2"]


# ===================================================================
# 5 – happy path: apply_to_existing_transactions = True
# ===================================================================


async def test_create_rule_apply_to_existing(mcp_write_client, mock_monarch_client):
    mock_monarch_client.gql_call.return_value = {
        "createTransactionRuleV2": {"errors": []}
    }

    result = json.loads(
        (await mcp_write_client.call_tool(
            "create_transaction_rule",
            {
                "set_category_id": "cat-123",
                "merchant_name_value": "Whole Foods",
                "apply_to_existing_transactions": True,
            },
        )).content[0].text
    )

    assert result["created"] is True
    variables = mock_monarch_client.gql_call.call_args[1]["variables"]
    assert variables["input"]["applyToExistingTransactions"] is True


# ===================================================================
# 6 – validation: no criteria provided
# ===================================================================


async def test_create_rule_no_criteria(mcp_write_client, mock_monarch_client):
    result = json.loads(
        (await mcp_write_client.call_tool(
            "create_transaction_rule",
            {"set_category_id": "cat-123"},
        )).content[0].text
    )

    assert "error" in result
    mock_monarch_client.gql_call.assert_not_called()


# ===================================================================
# 7 – validation: invalid merchant_name_operator
# ===================================================================


async def test_create_rule_invalid_merchant_operator(mcp_write_client, mock_monarch_client):
    result = json.loads(
        (await mcp_write_client.call_tool(
            "create_transaction_rule",
            {
                "set_category_id": "cat-123",
                "merchant_name_value": "Amazon",
                "merchant_name_operator": "startswith",
            },
        )).content[0].text
    )

    assert "error" in result
    mock_monarch_client.gql_call.assert_not_called()


# ===================================================================
# 8 – validation: invalid original_statement_operator
# ===================================================================


async def test_create_rule_invalid_statement_operator(mcp_write_client, mock_monarch_client):
    result = json.loads(
        (await mcp_write_client.call_tool(
            "create_transaction_rule",
            {
                "set_category_id": "cat-123",
                "original_statement_value": "ROLLOVER",
                "original_statement_operator": "regex",
            },
        )).content[0].text
    )

    assert "error" in result
    mock_monarch_client.gql_call.assert_not_called()


# ===================================================================
# 9 – API-level error surfaced from mutation payload
# ===================================================================


async def test_create_rule_api_error(mcp_write_client, mock_monarch_client):
    mock_monarch_client.gql_call.return_value = {
        "createTransactionRuleV2": {
            "errors": [{"message": "Category not found"}]
        }
    }

    result = json.loads(
        (await mcp_write_client.call_tool(
            "create_transaction_rule",
            {
                "set_category_id": "cat-bad",
                "merchant_name_value": "Amazon",
            },
        )).content[0].text
    )

    assert "error" in result
    assert "Category not found" in result["error"]


# ===================================================================
# 10 – transport error handled by decorator
# ===================================================================


async def test_create_rule_transport_error(mcp_write_client, mock_monarch_client):
    mock_monarch_client.gql_call.side_effect = Exception("Network failure")

    result = (await mcp_write_client.call_tool(
        "create_transaction_rule",
        {
            "set_category_id": "cat-123",
            "merchant_name_value": "Amazon",
        },
    )).content[0].text

    assert "Error" in result
    assert "Network failure" in result


# ===================================================================
# 11 – both merchant name and original statement provided together
# ===================================================================


async def test_create_rule_both_criteria(mcp_write_client, mock_monarch_client):
    mock_monarch_client.gql_call.return_value = {
        "createTransactionRuleV2": {"errors": []}
    }

    result = json.loads(
        (await mcp_write_client.call_tool(
            "create_transaction_rule",
            {
                "set_category_id": "cat-123",
                "merchant_name_value": "Fidelity",
                "original_statement_value": "ROLLOVER CASH",
            },
        )).content[0].text
    )

    assert result["created"] is True
    variables = mock_monarch_client.gql_call.call_args[1]["variables"]
    assert "merchantNameCriteria" in variables["input"]
    assert "originalStatementCriteria" in variables["input"]
