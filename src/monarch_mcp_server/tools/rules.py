"""Transaction rules tools with GraphQL queries."""

import logging
from typing import Any, Dict, List, Optional

from gql import gql

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import (
    json_error,
    json_rejected,
    json_success,
    payload_errors,
    require_nonblank,
)

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
    setLinkToPaydownBudgetAction
    criteriaOwnerIsJoint
    criteriaOwnerUserIds
    criteriaBusinessEntityIds
    criteriaBusinessEntityIsUnassigned
    criteriaBusinessEntities {
      id
      name
      __typename
    }
    merchantCriteria {
      operator
      value
      __typename
    }
    actionSetOwnerIsJoint
    actionSetOwner {
      id
      displayName
      __typename
    }
    actionSetBusinessEntity {
      id
      name
      __typename
    }
    actionSetBusinessEntityIsUnassigned
    linkSavingsGoalAction {
      id
      name
      __typename
    }
    needsReviewByUserAction {
      id
      displayName
      __typename
    }
    splitTransactionsAction {
      amountType
      splitsInfo {
        categoryId
        merchantName
        amount
        goalId
        savingsGoalId
        tags
        hideFromReports
        reviewStatus
        needsReviewByUserId
        ownerUserId
        ownerIsJoint
        businessEntityId
        businessEntityIsUnassigned
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
    transactionRule {
      id
      order
      __typename
    }
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

UPDATE_TRANSACTION_RULE_MUTATION = gql("""
mutation Common_UpdateTransactionRuleMutationV2($input: UpdateTransactionRuleInput!) {
  updateTransactionRuleV2(input: $input) {
    transactionRule {
      id
      order
      __typename
    }
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
# Helpers
# ---------------------------------------------------------------------------


def _criteria_to_input(criteria: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Convert criteria as returned by the API back into mutation-input shape."""
    return [
        {"operator": c.get("operator"), "value": c.get("value")}
        for c in (criteria or [])
        if c
    ]


def _build_criteria(
    values: Optional[List[str]],
    single: Optional[str],
    operator: Optional[str],
    structured: Optional[List[Dict[str, Any]]],
) -> Optional[List[Dict[str, Any]]]:
    """Build a text-criteria list.

    ``structured`` takes precedence and allows a different operator per value.
    Monarch supports mixed operators within one criterion (e.g. contains
    "netflix" OR eq "apple"), which a single shared operator cannot express.
    """
    if structured:
        return [
            {"operator": c.get("operator") or "contains", "value": c.get("value")}
            for c in structured
            if c.get("value")
        ]
    vals = [v for v in (values or []) if v]
    if not vals and single:
        vals = [single]
    if not vals:
        return None
    op = operator or "contains"
    return [{"operator": op, "value": v} for v in vals]


def _build_amount_criteria(
    operator: Optional[str],
    value: Optional[float],
    is_expense: bool,
    lower: Optional[float],
    upper: Optional[float],
) -> Optional[Dict[str, Any]]:
    """Build amount criteria, including the ``between`` range variant."""
    if operator == "between":
        if lower is None or upper is None:
            raise ValueError(
                "amount_operator='between' requires amount_lower and amount_upper"
            )
        return {
            "operator": "between",
            "isExpense": is_expense,
            "value": None,
            "valueRange": {"lower": lower, "upper": upper},
        }
    if operator and value is not None:
        return {
            "operator": operator,
            "isExpense": is_expense,
            "value": value,
            "valueRange": None,
        }

    # Exactly one half supplied. Dropping the criterion here would create a
    # rule far broader than the caller asked for and still report success: an
    # amount threshold that silently disappears leaves a rule matching every
    # transaction from that merchant, and with apply_to_existing it rewrites
    # the history immediately. A standing policy is worth failing loudly over.
    if operator or value is not None or lower is not None or upper is not None:
        raise ValueError(
            "Incomplete amount criteria "
            f"(amount_operator={operator!r}, amount_value={value!r}, "
            f"amount_lower={lower!r}, amount_upper={upper!r}). "
            "Give amount_operator with amount_value, or "
            "amount_operator='between' with both amount_lower and "
            "amount_upper."
        )
    return None


def _meaningful_errors(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a useful error payload, or None if there was no real error.

    Monarch rejects some inputs with ``{fieldErrors: null, message: null,
    code: null}`` -- truthy, but carrying no information. Reporting that
    verbatim tells the caller nothing, so it is replaced with a plain message.
    """
    if not payload:
        return None
    meaningful = {
        k: v for k, v in payload.items() if k != "__typename" and v is not None
    }
    return meaningful or {
        "message": "Monarch rejected the request without giving a reason"
    }


async def _fetch_rule(client, rule_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single rule by id, or None if it does not exist."""
    result = await client.gql_call(
        operation="GetTransactionRules",
        graphql_query=GET_TRANSACTION_RULES_QUERY,
        variables={},
    )
    for rule in result.get("transactionRules") or []:
        if rule.get("id") == rule_id:
            return rule
    return None


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
                "set_category_action": {
                    "id": rule.get("setCategoryAction", {}).get("id"),
                    "name": rule.get("setCategoryAction", {}).get("name"),
                } if rule.get("setCategoryAction") else None,
                "set_merchant_action": {
                    "id": rule.get("setMerchantAction", {}).get("id"),
                    "name": rule.get("setMerchantAction", {}).get("name"),
                } if rule.get("setMerchantAction") else None,
                "add_tags_action": [
                    {"id": tag.get("id"), "name": tag.get("name")}
                    for tag in rule.get("addTagsAction", [])
                ] if rule.get("addTagsAction") else None,
                "link_goal_action": rule.get("linkGoalAction"),
                "hide_from_reports_action": rule.get("setHideFromReportsAction"),
                "review_status_action": rule.get("reviewStatusAction"),
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
    merchant_criteria_values: Optional[List[str]] = None,
    merchant_criteria: Optional[List[Dict[str, Any]]] = None,
    original_statement_operator: Optional[str] = None,
    original_statement_values: Optional[List[str]] = None,
    original_statement_criteria: Optional[List[Dict[str, Any]]] = None,
    use_original_statement: Optional[bool] = None,
    amount_operator: Optional[str] = None,
    amount_value: Optional[float] = None,
    amount_lower: Optional[float] = None,
    amount_upper: Optional[float] = None,
    amount_is_expense: bool = True,
    set_category_id: Optional[str] = None,
    set_merchant_name: Optional[str] = None,
    add_tag_ids: Optional[List[str]] = None,
    link_goal_id: Optional[str] = None,
    hide_from_reports: Optional[bool] = None,
    review_status: Optional[str] = None,
    account_ids: Optional[List[str]] = None,
    category_ids: Optional[List[str]] = None,
    apply_to_existing: bool = False,
) -> str:
    """
    Create a new transaction auto-categorization rule.

    Rules automatically update transactions as they arrive. Every matching rule
    runs, in order, so a later rule overwrites an earlier one. Conditions inside
    one criterion are OR'd; different criteria are AND'd together.

    Args:
        merchant_criteria_operator: Operator shared by merchant_criteria_values
            ("contains" or "eq"). Defaults to "contains".
        merchant_criteria_value: Single merchant name/pattern to match.
        merchant_criteria_values: Several merchant values, OR'd together.
        merchant_criteria: Merchant criteria with a per-value operator, e.g.
            [{"operator": "contains", "value": "netflix"},
             {"operator": "eq", "value": "apple"}]. Takes precedence over the
            two arguments above.
        original_statement_values: Match against the raw bank statement text
            instead of the merchant name. Monarch recommends this as the more
            stable option, since it does not change when a merchant is
            re-identified.
        original_statement_operator: Operator shared by the values above.
        original_statement_criteria: Original-statement criteria with a
            per-value operator (same shape as merchant_criteria).
        use_original_statement: Apply merchant criteria to the original
            statement text rather than the merchant name.
        amount_operator: "gt", "lt", "eq" or "between".
        amount_value: Threshold for gt/lt/eq.
        amount_lower/amount_upper: Bounds when amount_operator="between".
        amount_is_expense: True for debits, False for credits.
        set_category_id: Category id to assign (see get_transaction_categories).
        set_merchant_name: Merchant name to set on matching transactions.
        add_tag_ids: Tag ids to add (see get_transaction_tags).
        link_goal_id: Goal id to link matching transactions to. Monarch
            requires account_ids to be set as well.
        hide_from_reports: Hide matching transactions from reports.
        review_status: Review status to set, e.g. "needs_review".
        account_ids: Restrict the rule to these accounts. This is a matching
            criterion, not an action.
        category_ids: Restrict the rule to transactions already in these
            categories. Also a matching criterion.
        apply_to_existing: Also apply the rule to existing transactions.

    Returns:
        JSON with the new rule's id on success.

    Example:
        create_transaction_rule(
            merchant_criteria_values=["amazon"],
            set_category_id="cat_123",
        )
    """
    try:
        if set_merchant_name is not None:
            require_nonblank(set_merchant_name, "set_merchant_name")

        client = await get_monarch_client()

        merchant = _build_criteria(
            merchant_criteria_values,
            merchant_criteria_value,
            merchant_criteria_operator,
            merchant_criteria,
        )
        statement = _build_criteria(
            original_statement_values,
            None,
            original_statement_operator,
            original_statement_criteria,
        )
        amount = _build_amount_criteria(
            amount_operator, amount_value, amount_is_expense,
            amount_lower, amount_upper,
        )

        if not (merchant or statement or amount or account_ids or category_ids):
            return json_success({
                "success": False,
                "message": (
                    "A rule needs at least one matching criterion: merchant, "
                    "original statement, amount, accounts or categories."
                ),
            })

        rule_input: Dict[str, Any] = {
            "applyToExistingTransactions": apply_to_existing,
        }
        if merchant:
            rule_input["merchantNameCriteria"] = merchant
        if statement:
            rule_input["originalStatementCriteria"] = statement
        if amount:
            rule_input["amountCriteria"] = amount
        if account_ids:
            rule_input["accountIds"] = account_ids
        if category_ids:
            rule_input["categoryIds"] = category_ids
        if use_original_statement is not None:
            rule_input["merchantCriteriaUseOriginalStatement"] = use_original_statement
        if set_category_id:
            rule_input["setCategoryAction"] = set_category_id
        if set_merchant_name:
            rule_input["setMerchantAction"] = set_merchant_name
        if add_tag_ids is not None:
            rule_input["addTagsAction"] = add_tag_ids
        if link_goal_id:
            rule_input["linkGoalAction"] = link_goal_id
        if hide_from_reports is not None:
            rule_input["setHideFromReportsAction"] = hide_from_reports
        if review_status:
            rule_input["reviewStatusAction"] = review_status

        result = await client.gql_call(
            operation="Common_CreateTransactionRuleMutationV2",
            graphql_query=CREATE_TRANSACTION_RULE_MUTATION,
            variables={"input": rule_input},
        )

        payload = result.get("createTransactionRuleV2") or {}
        errors = _meaningful_errors(payload.get("errors"))
        if errors:
            return json_success({"success": False, "errors": errors})

        rule = payload.get("transactionRule") or {}
        return json_success({
            "success": True,
            "rule_id": rule.get("id"),
            "order": rule.get("order"),
            "message": "Rule created successfully",
        })
    except Exception as e:
        return json_error("create_transaction_rule", e)


@mcp.tool()
async def update_transaction_rule(
    rule_id: str,
    merchant_criteria_operator: Optional[str] = None,
    merchant_criteria_value: Optional[str] = None,
    merchant_criteria_values: Optional[List[str]] = None,
    merchant_criteria: Optional[List[Dict[str, Any]]] = None,
    original_statement_operator: Optional[str] = None,
    original_statement_values: Optional[List[str]] = None,
    original_statement_criteria: Optional[List[Dict[str, Any]]] = None,
    use_original_statement: Optional[bool] = None,
    amount_operator: Optional[str] = None,
    amount_value: Optional[float] = None,
    amount_lower: Optional[float] = None,
    amount_upper: Optional[float] = None,
    amount_is_expense: bool = True,
    set_category_id: Optional[str] = None,
    set_merchant_name: Optional[str] = None,
    add_tag_ids: Optional[List[str]] = None,
    link_goal_id: Optional[str] = None,
    hide_from_reports: Optional[bool] = None,
    review_status: Optional[str] = None,
    account_ids: Optional[List[str]] = None,
    category_ids: Optional[List[str]] = None,
    clear_category: bool = False,
    clear_merchant: bool = False,
    clear_tags: bool = False,
    clear_goal_link: bool = False,
    clear_review_status: bool = False,
    apply_to_existing: bool = False,
) -> str:
    """
    Update an existing transaction rule.

    **This call is non-destructive — omitted fields are preserved
    automatically.** Pass only what you want to change.

    Monarch's update mutation treats criteria and actions asymmetrically, and
    both halves are hostile to a partial update:

    * It ignores the request entirely unless the input carries at least one
      matching criterion, so a call that only changes an action would be
      silently discarded.
    * It CLEARS any action that is absent from the input. Sending only
      `link_goal_id` would silently wipe an existing category and merchant.

    So this reads the rule first and resends its full current state — criteria
    and actions alike — with your changes merged on top. To remove something on
    purpose, use the matching `clear_*` flag; leaving an argument unset always
    means "keep whatever is there".

    Args:
        rule_id: Id of the rule to update (see get_transaction_rules).
        clear_category: Remove the category action.
        clear_merchant: Remove the merchant-rename action.
        clear_tags: Remove all tag actions.
        clear_goal_link: Remove the goal link.
        clear_review_status: Remove the review-status action.
        merchant_criteria_operator: Operator shared by merchant_criteria_values
            ("contains" or "eq"). Defaults to "contains".
        merchant_criteria_value: Single merchant name/pattern to match.
        merchant_criteria_values: Several merchant values, OR'd together.
        merchant_criteria: Merchant criteria with a per-value operator, e.g.
            [{"operator": "contains", "value": "netflix"},
             {"operator": "eq", "value": "apple"}]. Takes precedence over the
            two arguments above.
        original_statement_values: Match against the raw bank statement text
            instead of the merchant name. Monarch recommends this as the more
            stable option, since it does not change when a merchant is
            re-identified.
        original_statement_operator: Operator shared by the values above.
        original_statement_criteria: Original-statement criteria with a
            per-value operator (same shape as merchant_criteria).
        use_original_statement: Apply merchant criteria to the original
            statement text rather than the merchant name.
        amount_operator: "gt", "lt", "eq" or "between".
        amount_value: Threshold for gt/lt/eq.
        amount_lower/amount_upper: Bounds when amount_operator="between".
        amount_is_expense: True for debits, False for credits.
        set_category_id: Category id to assign (see get_transaction_categories).
        set_merchant_name: Merchant name to set on matching transactions.
        add_tag_ids: Tag ids to add (see get_transaction_tags).
        link_goal_id: Goal id to link matching transactions to. Monarch
            requires account_ids to be set as well.
        hide_from_reports: Hide matching transactions from reports.
        review_status: Review status to set, e.g. "needs_review".
        account_ids: Restrict the rule to these accounts. This is a matching
            criterion, not an action.
        category_ids: Restrict the rule to transactions already in these
            categories. Also a matching criterion.
        apply_to_existing: Also apply the rule to existing transactions.

    Returns:
        JSON describing whether the update was applied.
    """
    try:
        if set_merchant_name is not None:
            require_nonblank(set_merchant_name, "set_merchant_name")

        client = await get_monarch_client()

        existing = await _fetch_rule(client, rule_id)
        if existing is None:
            return json_success({
                "success": False,
                "message": f"No transaction rule found with id {rule_id}",
            })

        merchant = _build_criteria(
            merchant_criteria_values,
            merchant_criteria_value,
            merchant_criteria_operator,
            merchant_criteria,
        )
        statement = _build_criteria(
            original_statement_values,
            None,
            original_statement_operator,
            original_statement_criteria,
        )
        amount = _build_amount_criteria(
            amount_operator, amount_value, amount_is_expense,
            amount_lower, amount_upper,
        )

        # Fall back to the rule's current criteria so the mutation is never
        # criteria-less. Criteria that are omitted entirely are preserved by
        # the API, so only these need resending.
        if merchant is None:
            merchant = _criteria_to_input(existing.get("merchantNameCriteria"))
        if statement is None:
            statement = _criteria_to_input(existing.get("originalStatementCriteria"))
        if amount is None and existing.get("amountCriteria"):
            current = existing["amountCriteria"]
            value_range = current.get("valueRange")
            amount = {
                "operator": current.get("operator"),
                "isExpense": current.get("isExpense"),
                "value": current.get("value"),
                "valueRange": (
                    {"lower": value_range.get("lower"),
                     "upper": value_range.get("upper")}
                    if value_range else None
                ),
            }

        if not (merchant or statement or amount):
            return json_success({
                "success": False,
                "message": (
                    "This rule has no merchant, statement or amount criteria to "
                    "resend, and Monarch ignores updates that carry none. Pass "
                    "criteria explicitly to update it."
                ),
            })

        rule_input: Dict[str, Any] = {
            "id": rule_id,
            "applyToExistingTransactions": apply_to_existing,
        }
        if merchant:
            rule_input["merchantNameCriteria"] = merchant
        if statement:
            rule_input["originalStatementCriteria"] = statement
        if amount:
            rule_input["amountCriteria"] = amount
        # Remaining criteria, carried forward on the same principle.
        if account_ids is not None:
            rule_input["accountIds"] = account_ids
        elif existing.get("accountIds"):
            rule_input["accountIds"] = existing["accountIds"]
        if category_ids is not None:
            rule_input["categoryIds"] = category_ids
        elif existing.get("categoryIds"):
            rule_input["categoryIds"] = existing["categoryIds"]
        if use_original_statement is not None:
            rule_input["merchantCriteriaUseOriginalStatement"] = use_original_statement
        elif existing.get("merchantCriteriaUseOriginalStatement") is not None:
            rule_input["merchantCriteriaUseOriginalStatement"] = existing[
                "merchantCriteriaUseOriginalStatement"
            ]

        # Actions. Monarch CLEARS any action missing from the input -- unlike
        # criteria, which it preserves -- so every action must be resent on
        # every update or it is silently destroyed. An unset argument means
        # "keep current"; the clear_* flags are the only way to remove one.
        existing_tags = [
            t.get("id") for t in (existing.get("addTagsAction") or []) if t.get("id")
        ]
        # setMerchantAction is written as a NAME, not an id. Passing the id
        # creates a second merchant literally named with that id string.
        merchant = (
            None if clear_merchant
            else (set_merchant_name
                  or (existing.get("setMerchantAction") or {}).get("name"))
        )
        category = (
            None if clear_category
            else (set_category_id
                  or (existing.get("setCategoryAction") or {}).get("id"))
        )
        tags = (
            None if clear_tags
            else (add_tag_ids if add_tag_ids is not None else existing_tags)
        )
        goal = (
            None if clear_goal_link
            else (link_goal_id or (existing.get("linkGoalAction") or {}).get("id"))
        )
        hide = (
            hide_from_reports if hide_from_reports is not None
            else existing.get("setHideFromReportsAction")
        )
        review = (
            None if clear_review_status
            else (review_status or existing.get("reviewStatusAction"))
        )

        if category:
            rule_input["setCategoryAction"] = category
        if merchant:
            rule_input["setMerchantAction"] = merchant
        if tags:
            rule_input["addTagsAction"] = tags
        if goal:
            rule_input["linkGoalAction"] = goal
        if hide is not None:
            rule_input["setHideFromReportsAction"] = hide
        if review:
            rule_input["reviewStatusAction"] = review

        # Plan-gated and less common fields. These are carried forward but not
        # exposed as arguments: business entities require a paid Monarch plan
        # and owner fields require household collaboration, so on most accounts
        # they are simply absent and these lines are no-ops.
        for field in ("sendNotificationAction", "setLinkToPaydownBudgetAction",
                      "actionSetOwnerIsJoint", "actionSetBusinessEntityIsUnassigned",
                      "criteriaOwnerIsJoint", "criteriaBusinessEntityIsUnassigned"):
            if existing.get(field):
                rule_input[field] = existing[field]
        for field in ("criteriaOwnerUserIds", "criteriaBusinessEntityIds"):
            if existing.get(field):
                rule_input[field] = existing[field]
        if existing.get("merchantCriteria"):
            rule_input["merchantCriteria"] = _criteria_to_input(
                existing["merchantCriteria"]
            )
        if (existing.get("actionSetBusinessEntity") or {}).get("id"):
            rule_input["actionSetBusinessEntity"] = existing[
                "actionSetBusinessEntity"]["id"]
        if (existing.get("actionSetOwner") or {}).get("id"):
            rule_input["actionSetOwner"] = existing["actionSetOwner"]["id"]
        # Savings goals are a separate collection from goalsV2 with their own
        # ids, so linkGoalAction and linkSavingsGoalAction are not interchangeable.
        if (existing.get("linkSavingsGoalAction") or {}).get("id"):
            rule_input["linkSavingsGoalAction"] = existing[
                "linkSavingsGoalAction"]["id"]
        # Monarch rejects needs_review_by_user_action without a review status,
        # so the pair has to travel together.
        reviewer = (existing.get("needsReviewByUserAction") or {}).get("id")
        if reviewer and rule_input.get("reviewStatusAction"):
            rule_input["needsReviewByUserAction"] = reviewer
        split = existing.get("splitTransactionsAction")
        if split and split.get("splitsInfo"):
            rule_input["splitTransactionsAction"] = {
                "amountType": split.get("amountType"),
                "splitsInfo": [
                    {k: v for k, v in info.items() if k != "__typename"}
                    for info in split["splitsInfo"]
                ],
            }

        result = await client.gql_call(
            operation="Common_UpdateTransactionRuleMutationV2",
            graphql_query=UPDATE_TRANSACTION_RULE_MUTATION,
            variables={"input": rule_input},
        )

        payload = result.get("updateTransactionRuleV2") or {}
        errors = _meaningful_errors(payload.get("errors"))
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

        # Monarch's deleteTransactionRule returns an unreliable `deleted` flag:
        # verified against the live API, it comes back `false` even when the rule
        # was in fact removed (and it is sometimes absent entirely). Trusting it
        # made every successful deletion report failure.
        #
        # A genuine failure does not arrive in this payload at all -- deleting a
        # non-existent rule raises TransportQueryError ("Not found") from the
        # GraphQL layer, which the except block below turns into an error result.
        # So the only in-payload failure signal worth honouring is an explicit
        # `errors` object.
        delete_result = result.get("deleteTransactionRule") or {}

        errors = delete_result.get("errors")
        if errors:
            return json_success({"success": False, "errors": errors})

        return json_success({"success": True, "message": "Rule deleted successfully"})
    except Exception as e:
        return json_error("delete_transaction_rule", e)


REORDER_RULE_MUTATION = gql("""
mutation Web_UpdateRuleOrderMutation($id: ID!, $order: Int!) {
  updateTransactionRuleOrderV2(id: $id, order: $order) {
    transactionRules {
      id
      order
      __typename
    }
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


@mcp.tool()
async def reorder_transaction_rule(rule_id: str, new_order: int) -> str:
    """
    Move a transaction rule to a new position in the evaluation order.

    Order is not cosmetic. Every matching rule runs, in order, and a later rule
    overwrites an earlier one, so position decides which rule wins when two
    match the same transaction.

    Monarch renumbers the other rules automatically; the full resulting order
    is returned so the caller can confirm the outcome.

    Args:
        rule_id: Rule to move (see get_transaction_rules).
        new_order: Zero-based target position. 0 runs first.
    """
    try:
        if new_order < 0:
            return json_success({
                "success": False, "message": "new_order must be 0 or greater",
            })
        client = await get_monarch_client()

        current = await client.gql_call(
            operation="GetTransactionRules",
            graphql_query=GET_TRANSACTION_RULES_QUERY,
            variables={},
        )
        existing = next(
            (r for r in current.get("transactionRules") or []
             if r.get("id") == rule_id),
            None,
        )
        if existing is None:
            return json_success({
                "success": False,
                "message": f"No transaction rule found with id {rule_id}",
            })

        result = await client.gql_call(
            operation="Web_UpdateRuleOrderMutation",
            graphql_query=REORDER_RULE_MUTATION,
            variables={"id": rule_id, "order": new_order},
        )
        # Monarch signals a refused mutation with an errors object inside an
        # HTTP 200. Rule order decides which rule wins when two match the same
        # transaction, so a silently ignored reorder must not read as done.
        errors = payload_errors(result, "updateTransactionRuleOrderV2")
        if errors:
            return json_rejected("reorder_transaction_rule", errors)

        payload = result.get("updateTransactionRuleOrderV2") or {}
        rules = payload.get("transactionRules") or []

        # Read the landed position back from the response rather than echoing
        # the argument, so the reported outcome is what Monarch actually did.
        landed = next(
            (r.get("order") for r in rules if r.get("id") == rule_id), None
        )

        return json_success({
            "success": True,
            "rule_id": rule_id,
            "moved_from": existing.get("order"),
            "moved_to": landed if landed is not None else new_order,
            "requested_order": new_order,
            "order": [
                {"rule_id": r.get("id"), "order": r.get("order")}
                for r in sorted(rules, key=lambda r: r.get("order") or 0)
            ],
        })
    except Exception as e:
        return json_error("reorder_transaction_rule", e)
