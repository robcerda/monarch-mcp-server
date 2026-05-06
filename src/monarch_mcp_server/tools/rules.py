"""Transaction rules tools with GraphQL queries."""

import logging
from typing import Any, Dict, List, Optional

from gql import gql

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GraphQL constants
# ---------------------------------------------------------------------------

GET_TRANSACTION_RULES_QUERY = gql("""
query GetTransactionRules {
  transactionRules {
    id
    order
    merchantCriteriaUseOriginalStatement
    merchantCriteria {
      operator
      value
      __typename
    }
    originalStatementCriteria {
      operator
      value
      __typename
    }
    merchantNameCriteria {
      operator
      value
      __typename
    }
    amountCriteria {
      operator
      isExpense
      value
      valueRange {
        lower
        upper
        __typename
      }
      __typename
    }
    categoryIds
    accountIds
    categories {
      id
      name
      icon
      __typename
    }
    accounts {
      id
      displayName
      __typename
    }
    setMerchantAction {
      id
      name
      __typename
    }
    setCategoryAction {
      id
      name
      icon
      __typename
    }
    addTagsAction {
      id
      name
      color
      __typename
    }
    linkGoalAction {
      id
      name
      __typename
    }
    setHideFromReportsAction
    reviewStatusAction
    sendNotificationAction
    splitTransactionsAction {
      amountType
      splitsInfo {
        amount
        categoryId
        merchantName
        tags
        hideFromReports
        needsReview
        reviewStatus
        goalId
        __typename
      }
      __typename
    }
    recentApplicationCount
    lastAppliedAt
    __typename
  }
}
""")

CREATE_TRANSACTION_RULE_MUTATION = gql("""
mutation Common_CreateTransactionRuleMutationV2($input: CreateTransactionRuleInput!) {
  createTransactionRuleV2(input: $input) {
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    __typename
  }
}
""")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_split_action(
    splits_info: List[Dict[str, Any]],
    amount_type: str,
) -> Dict[str, Any]:
    """Build the splitTransactionsAction GraphQL block from snake_case input.

    Each entry in *splits_info* is a dict with keys:
      amount (float, required), category_id, merchant_name, tag_ids,
      hide_from_reports, needs_review, review_status, goal_id.

    Returns a dict shaped for Monarch's `splitTransactionsAction` input.
    """
    splits_payload: List[Dict[str, Any]] = []
    for split in splits_info:
        if "amount" not in split or split["amount"] is None:
            raise ValueError("each split entry requires an 'amount' field")
        splits_payload.append({
            "amount": split["amount"],
            "categoryId": split.get("category_id"),
            "merchantName": split.get("merchant_name"),
            "tags": split.get("tag_ids") or [],
            "hideFromReports": split.get("hide_from_reports"),
            "needsReview": split.get("needs_review"),
            "reviewStatus": split.get("review_status"),
            "goalId": split.get("goal_id"),
        })
    return {
        "amountType": amount_type,
        "splitsInfo": splits_payload,
    }


def _rule_signature(rule: Dict[str, Any]) -> tuple:
    """Build a hashable identity tuple for matching a freshly-created rule.

    Uses every defining criterion: merchantNameCriteria, merchantCriteria,
    originalStatementCriteria, amountCriteria, accountIds, splitsInfo.
    """
    def _norm_criteria(items):
        if not items:
            return ()
        return tuple(sorted(
            (c.get("operator"), c.get("value"))
            for c in items
        ))

    amt = rule.get("amountCriteria") or {}
    amt_range = amt.get("valueRange") or {}
    splits = (rule.get("splitTransactionsAction") or {}).get("splitsInfo") or []
    splits_sig = tuple(sorted(
        (
            s.get("amount"),
            s.get("categoryId"),
            s.get("merchantName"),
            tuple(s.get("tags") or []),
            s.get("hideFromReports"),
            s.get("needsReview"),
            s.get("reviewStatus"),
            s.get("goalId"),
        )
        for s in splits
    ))

    return (
        _norm_criteria(rule.get("merchantNameCriteria")),
        _norm_criteria(rule.get("merchantCriteria")),
        _norm_criteria(rule.get("originalStatementCriteria")),
        amt.get("operator"),
        amt.get("isExpense"),
        amt.get("value"),
        amt_range.get("lower"),
        amt_range.get("upper"),
        tuple(sorted(rule.get("accountIds") or [])),
        splits_sig,
    )


async def _find_created_rule_id(client, rule_input: Dict[str, Any]) -> Optional[str]:
    """Re-fetch all rules and find the one matching *rule_input* by signature.

    Returns the matched rule id, or the newest id when multiple identical
    rules exist (rare — only when an identical rule already existed).
    Returns None if no match is found.
    """
    target_sig = _rule_signature({
        "merchantNameCriteria": rule_input.get("merchantNameCriteria"),
        "merchantCriteria": rule_input.get("merchantCriteria"),
        "originalStatementCriteria": rule_input.get("originalStatementCriteria"),
        "amountCriteria": rule_input.get("amountCriteria"),
        "accountIds": rule_input.get("accountIds"),
        "splitTransactionsAction": rule_input.get("splitTransactionsAction"),
    })

    rules_result = await client.gql_call(
        operation="GetTransactionRules",
        graphql_query=GET_TRANSACTION_RULES_QUERY,
        variables={},
    )
    matches = [
        r for r in rules_result.get("transactionRules", [])
        if _rule_signature(r) == target_sig
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0].get("id")
    # Multiple matches — return the newest (Monarch ids are time-monotonic).
    return max(matches, key=lambda r: int(r.get("id") or 0)).get("id")

UPDATE_TRANSACTION_RULE_MUTATION = gql("""
mutation Common_UpdateTransactionRuleMutationV2($input: UpdateTransactionRuleInput!) {
  updateTransactionRuleV2(input: $input) {
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    __typename
  }
}
""")

DELETE_TRANSACTION_RULE_MUTATION = gql("""
mutation Common_DeleteTransactionRule($id: ID!) {
  deleteTransactionRule(id: $id) {
    deleted
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    __typename
  }
}
""")

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_transaction_rules() -> str:
    """
    Get all transaction auto-categorization rules from Monarch Money.

    Returns a list of rules with their conditions and actions.
    Rules automatically categorize transactions based on merchant, amount, etc.
    """
    try:
        client = await get_monarch_client()
        result = await client.gql_call(
            operation="GetTransactionRules",
            graphql_query=GET_TRANSACTION_RULES_QUERY,
            variables={},
        )

        rules_list = []
        for rule in result.get("transactionRules", []):
            set_category = rule.get("setCategoryAction")
            set_merchant = rule.get("setMerchantAction")
            add_tags = rule.get("addTagsAction")
            split_action = rule.get("splitTransactionsAction")

            rule_info = {
                "id": rule.get("id"),
                "order": rule.get("order"),
                "merchant_criteria": rule.get("merchantCriteria"),
                "merchant_name_criteria": rule.get("merchantNameCriteria"),
                "original_statement_criteria": rule.get("originalStatementCriteria"),
                "amount_criteria": rule.get("amountCriteria"),
                "category_ids": rule.get("categoryIds"),
                "account_ids": rule.get("accountIds"),
                "use_original_statement": rule.get("merchantCriteriaUseOriginalStatement"),
                # Action keys are ALWAYS present — None when unset — so callers
                # can rely on the contract instead of probing for missing keys.
                "set_category_action": (
                    {"id": set_category.get("id"), "name": set_category.get("name")}
                    if set_category else None
                ),
                "set_merchant_action": (
                    {"id": set_merchant.get("id"), "name": set_merchant.get("name")}
                    if set_merchant else None
                ),
                "add_tags_action": (
                    [{"id": tag.get("id"), "name": tag.get("name")} for tag in add_tags]
                    if add_tags else None
                ),
                "link_goal_action": rule.get("linkGoalAction"),
                "hide_from_reports_action": rule.get("setHideFromReportsAction"),
                "review_status_action": rule.get("reviewStatusAction"),
                "send_notification_action": rule.get("sendNotificationAction"),
                "split_transactions_action": (
                    {
                        "amount_type": split_action.get("amountType"),
                        "splits": [
                            {
                                "amount": s.get("amount"),
                                "category_id": s.get("categoryId"),
                                "merchant_name": s.get("merchantName"),
                                "tags": s.get("tags") or [],
                                "hide_from_reports": s.get("hideFromReports"),
                                "needs_review": s.get("needsReview"),
                                "review_status": s.get("reviewStatus"),
                                "goal_id": s.get("goalId"),
                            }
                            for s in (split_action.get("splitsInfo") or [])
                        ],
                    }
                    if split_action else None
                ),
                "recent_application_count": rule.get("recentApplicationCount"),
                "last_applied_at": rule.get("lastAppliedAt"),
            }
            rules_list.append(rule_info)

        return json_success(rules_list)
    except Exception as e:
        return json_error("get_transaction_rules", e)


@mcp.tool()
async def create_transaction_rule(
    merchant_criteria_operator: Optional[str] = None,
    merchant_criteria_value: Optional[str] = None,
    amount_operator: Optional[str] = None,
    amount_value: Optional[float] = None,
    amount_is_expense: bool = True,
    set_category_id: Optional[str] = None,
    set_merchant_name: Optional[str] = None,
    add_tag_ids: Optional[List[str]] = None,
    hide_from_reports: Optional[bool] = None,
    review_status: Optional[str] = None,
    account_ids: Optional[List[str]] = None,
    splits_info: Optional[List[Dict[str, Any]]] = None,
    splits_amount_type: str = "ABSOLUTE",
    apply_to_existing: bool = False,
) -> str:
    """
    Create a new transaction auto-categorization rule.

    Rules automatically categorize future transactions based on conditions.
    Apply-to-existing transactions is processed synchronously by Monarch — the
    backfill is complete by the time this call returns.

    Args:
        merchant_criteria_operator: How to match merchant ("eq", "contains")
        merchant_criteria_value: Merchant name/pattern to match
        amount_operator: Amount comparison ("gt", "lt", "eq", "between")
        amount_value: Amount threshold value
        amount_is_expense: Whether amount is expense (negative) or income
        set_category_id: Category ID to assign (use get_categories for IDs)
        set_merchant_name: Merchant name to set on matching transactions
        add_tag_ids: List of tag IDs to add (use get_tags for IDs)
        hide_from_reports: Whether to hide matching transactions from reports
        review_status: Review status to set ("needs_review" or null)
        account_ids: Limit rule to specific account IDs
        splits_info: Optional list of split entries to apply via
            ``splitTransactionsAction``. Each entry is a dict with keys:
            ``amount`` (float, required), ``category_id`` (str),
            ``merchant_name`` (str|None), ``tag_ids`` (list[str]|None),
            ``hide_from_reports`` (bool|None), ``needs_review`` (bool|None),
            ``review_status`` (str|None — "reviewed" or null), ``goal_id``
            (str|None). Snake_case keys are mapped to the camelCase shape
            Monarch's API expects.
        splits_amount_type: ``"ABSOLUTE"`` (default) or ``"PERCENTAGE"``.
        apply_to_existing: Whether to apply rule to existing transactions

    Returns:
        Result of rule creation including the new ``rule_id`` recovered by
        re-fetching all rules and matching on the defining criteria.

    Example (single-category rule):
        create_transaction_rule(
            merchant_criteria_operator="contains",
            merchant_criteria_value="amazon",
            set_category_id="cat_123"
        )

    Example (split rule — $99.99 income split into two categories):
        create_transaction_rule(
            merchant_criteria_operator="contains",
            merchant_criteria_value="stripe",
            amount_operator="eq",
            amount_value=99.99,
            amount_is_expense=False,
            splits_info=[
                {"amount": 50.00, "category_id": "cat_a", "tag_ids": ["tag_biz"]},
                {"amount": 49.99, "category_id": "cat_b", "tag_ids": ["tag_biz"]},
            ],
            splits_amount_type="ABSOLUTE",
            apply_to_existing=True,
        )
    """
    try:
        client = await get_monarch_client()

        rule_input: Dict[str, Any] = {
            "applyToExistingTransactions": apply_to_existing,
        }

        if merchant_criteria_operator and merchant_criteria_value:
            rule_input["merchantNameCriteria"] = [{
                "operator": merchant_criteria_operator,
                "value": merchant_criteria_value,
            }]

        if amount_operator and amount_value is not None:
            rule_input["amountCriteria"] = {
                "operator": amount_operator,
                "isExpense": amount_is_expense,
                "value": amount_value,
                "valueRange": None,
            }

        if account_ids:
            rule_input["accountIds"] = account_ids

        if set_category_id:
            rule_input["setCategoryAction"] = set_category_id
        if set_merchant_name:
            rule_input["setMerchantAction"] = set_merchant_name
        if add_tag_ids:
            rule_input["addTagsAction"] = add_tag_ids
        if hide_from_reports is not None:
            rule_input["setHideFromReportsAction"] = hide_from_reports
        if review_status:
            rule_input["reviewStatusAction"] = review_status
        if splits_info:
            rule_input["splitTransactionsAction"] = _build_split_action(
                splits_info, splits_amount_type
            )

        result = await client.gql_call(
            operation="Common_CreateTransactionRuleMutationV2",
            graphql_query=CREATE_TRANSACTION_RULE_MUTATION,
            variables={"input": rule_input},
        )

        errors = result.get("createTransactionRuleV2", {}).get("errors")
        if errors:
            return json_success({"success": False, "errors": errors})

        # createTransactionRuleV2 doesn't return the new id — recover it by
        # re-fetching all rules and matching on the defining criteria.
        new_rule_id = await _find_created_rule_id(client, rule_input)

        return json_success({
            "success": True,
            "rule_id": new_rule_id,
            "message": "Rule created successfully",
        })
    except Exception as e:
        return json_error("create_transaction_rule", e)


@mcp.tool()
async def update_transaction_rule(
    rule_id: str,
    merchant_criteria_operator: Optional[str] = None,
    merchant_criteria_value: Optional[str] = None,
    amount_operator: Optional[str] = None,
    amount_value: Optional[float] = None,
    amount_is_expense: bool = True,
    set_category_id: Optional[str] = None,
    set_merchant_name: Optional[str] = None,
    add_tag_ids: Optional[List[str]] = None,
    hide_from_reports: Optional[bool] = None,
    review_status: Optional[str] = None,
    account_ids: Optional[List[str]] = None,
    splits_info: Optional[List[Dict[str, Any]]] = None,
    splits_amount_type: str = "ABSOLUTE",
    apply_to_existing: bool = False,
) -> str:
    """
    Update an existing transaction rule.

    Apply-to-existing transactions is processed synchronously by Monarch — the
    backfill is complete by the time this call returns.

    Args:
        rule_id: The ID of the rule to update (use get_transaction_rules to find IDs)
        merchant_criteria_operator: How to match merchant ("eq", "contains")
        merchant_criteria_value: Merchant name/pattern to match
        amount_operator: Amount comparison ("gt", "lt", "eq", "between")
        amount_value: Amount threshold value
        amount_is_expense: Whether amount is expense (negative) or income
        set_category_id: Category ID to assign
        set_merchant_name: Merchant name to set
        add_tag_ids: List of tag IDs to add
        hide_from_reports: Whether to hide from reports
        review_status: Review status to set
        account_ids: Limit rule to specific accounts
        splits_info: Optional list of split entries to apply via
            ``splitTransactionsAction``. Same shape as
            :func:`create_transaction_rule`.
        splits_amount_type: ``"ABSOLUTE"`` (default) or ``"PERCENTAGE"``.
        apply_to_existing: Apply changes to existing transactions

    Returns:
        Result of rule update.
    """
    try:
        client = await get_monarch_client()

        rule_input: Dict[str, Any] = {
            "id": rule_id,
            "applyToExistingTransactions": apply_to_existing,
        }

        if merchant_criteria_operator and merchant_criteria_value:
            rule_input["merchantNameCriteria"] = [{
                "operator": merchant_criteria_operator,
                "value": merchant_criteria_value,
            }]

        if amount_operator and amount_value is not None:
            rule_input["amountCriteria"] = {
                "operator": amount_operator,
                "isExpense": amount_is_expense,
                "value": amount_value,
                "valueRange": None,
            }

        if account_ids:
            rule_input["accountIds"] = account_ids

        if set_category_id:
            rule_input["setCategoryAction"] = set_category_id
        if set_merchant_name:
            rule_input["setMerchantAction"] = set_merchant_name
        if add_tag_ids:
            rule_input["addTagsAction"] = add_tag_ids
        if hide_from_reports is not None:
            rule_input["setHideFromReportsAction"] = hide_from_reports
        if review_status:
            rule_input["reviewStatusAction"] = review_status
        if splits_info:
            rule_input["splitTransactionsAction"] = _build_split_action(
                splits_info, splits_amount_type
            )

        result = await client.gql_call(
            operation="Common_UpdateTransactionRuleMutationV2",
            graphql_query=UPDATE_TRANSACTION_RULE_MUTATION,
            variables={"input": rule_input},
        )

        errors = result.get("updateTransactionRuleV2", {}).get("errors")
        if errors:
            return json_success({"success": False, "errors": errors})

        return json_success({
            "success": True,
            "rule_id": rule_id,
            "message": "Rule updated successfully",
        })
    except Exception as e:
        return json_error("update_transaction_rule", e)


@mcp.tool()
async def delete_transaction_rule(rule_id: str) -> str:
    """
    Delete a transaction rule.

    Args:
        rule_id: The ID of the rule to delete (use get_transaction_rules to find IDs)

    Returns:
        Confirmation of deletion.
    """
    try:
        client = await get_monarch_client()

        result = await client.gql_call(
            operation="Common_DeleteTransactionRule",
            graphql_query=DELETE_TRANSACTION_RULE_MUTATION,
            variables={"id": rule_id},
        )

        delete_result = result.get("deleteTransactionRule", {})
        if delete_result.get("deleted"):
            return json_success({"success": True, "message": "Rule deleted successfully"})

        errors = delete_result.get("errors")
        if errors:
            return json_success({"success": False, "errors": errors})

        return json_success({"success": False, "message": "Unknown error"})
    except Exception as e:
        return json_error("delete_transaction_rule", e)
