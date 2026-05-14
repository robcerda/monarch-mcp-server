"""Merchant and recurring stream management tools with GraphQL queries."""

import logging
from typing import Any, Dict, Optional

from gql import gql

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_error, json_success

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GraphQL constants
# ---------------------------------------------------------------------------

GET_MERCHANT_QUERY = gql(
    """
query Common_GetEditMerchant($merchantId: ID!) {
  merchant(id: $merchantId) {
    id
    name
    logoUrl
    transactionCount
    ruleCount
    canBeDeleted
    hasActiveRecurringStreams
    recurringTransactionStream {
      id
      frequency
      amount
      baseDate
      isActive
      __typename
    }
    __typename
  }
}
"""
)

UPDATE_MERCHANT_MUTATION = gql(
    """
mutation Common_UpdateMerchant($input: UpdateMerchantInput!) {
  updateMerchant(input: $input) {
    merchant {
      id
      name
      recurringTransactionStream {
        id
        frequency
        amount
        baseDate
        isActive
        __typename
      }
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
"""
)

REVIEW_STREAM_MUTATION = gql(
    """
mutation Web_ReviewStream($input: ReviewRecurringStreamInput!) {
  reviewRecurringStream(input: $input) {
    stream {
      id
      reviewStatus
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
"""
)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_merchant(merchant_id: str) -> str:
    """
    Get a merchant's details including recurring transaction stream configuration.

    Use this to look up a merchant's current recurring stream settings before
    updating them with update_merchant.

    Args:
        merchant_id: The Monarch merchant ID (find via get_transactions or
            get_recurring_transactions, which include merchant IDs in their
            responses).

    Returns:
        Merchant details with name, transaction count, rule count, and
        recurring stream configuration (frequency, amount, base date).

    Example:
        Look up PennyMac merchant details:
            get_merchant(merchant_id="160319777541808781")
    """
    try:
        client = await get_monarch_client()
        result = await client.gql_call(
            operation="Common_GetEditMerchant",
            graphql_query=GET_MERCHANT_QUERY,
            variables={"merchantId": merchant_id},
        )

        merchant = result.get("merchant")
        if not merchant:
            return json_success(
                {
                    "merchant": None,
                    "message": "No merchant found with the given ID",
                }
            )

        stream = merchant.get("recurringTransactionStream")
        merchant_info: Dict[str, Any] = {
            "id": merchant.get("id"),
            "name": merchant.get("name"),
            "logo_url": merchant.get("logoUrl"),
            "transaction_count": merchant.get("transactionCount"),
            "rule_count": merchant.get("ruleCount"),
            "can_be_deleted": merchant.get("canBeDeleted"),
            "has_active_recurring_streams": merchant.get("hasActiveRecurringStreams"),
            "recurring_stream": (
                {
                    "id": stream.get("id"),
                    "frequency": stream.get("frequency"),
                    "amount": stream.get("amount"),
                    "base_date": stream.get("baseDate"),
                    "is_active": stream.get("isActive"),
                }
                if stream
                else None
            ),
        }

        return json_success({"merchant": merchant_info})
    except Exception as e:
        return json_error("get_merchant", e)


@mcp.tool()
async def update_merchant(
    merchant_id: str,
    name: Optional[str] = None,
    is_recurring: Optional[bool] = None,
    frequency: Optional[str] = None,
    base_date: Optional[str] = None,
    amount: Optional[float] = None,
    is_active: Optional[bool] = None,
) -> str:
    """
    Update a merchant's name and/or recurring transaction stream settings.

    This is the only way to modify recurring stream configurations (frequency,
    amount, base date, active status). Use get_merchant first to see current
    settings, then update_merchant to change them.

    Args:
        merchant_id: The Monarch merchant ID.
        name: New merchant display name.
        is_recurring: Whether this merchant has a recurring stream.
        frequency: Recurrence frequency. Known values: "weekly", "biweekly",
            "twice_a_month", "monthly", "quarterly", "semiannually",
            "annually".
        base_date: Anchor date for recurrence in YYYY-MM-DD format.
        amount: Expected recurring amount (negative for expenses, positive
            for income).
        is_active: Whether the recurring stream is actively tracked.

    Returns:
        Updated merchant details with recurring stream configuration.

    Example:
        Fix PennyMac mortgage to $1,460.93 monthly:
            update_merchant(
                merchant_id="160319777541808781",
                is_recurring=True,
                frequency="monthly",
                base_date="2026-05-06",
                amount=-1460.93,
                is_active=True,
            )
    """
    try:
        recurrence_fields: Dict[str, Any] = {
            k: v
            for k, v in {
                "isRecurring": is_recurring,
                "frequency": frequency,
                "baseDate": base_date,
                "amount": amount,
                "isActive": is_active,
            }.items()
            if v is not None
        }

        if name is None and not recurrence_fields:
            return json_success(
                {
                    "success": False,
                    "message": "At least one field (name or recurrence) "
                    "must be provided",
                }
            )

        merchant_input: Dict[str, Any] = {"merchantId": merchant_id}

        if name is not None:
            merchant_input["name"] = name

        if recurrence_fields:
            merchant_input["recurrence"] = recurrence_fields

        client = await get_monarch_client()
        result = await client.gql_call(
            operation="Common_UpdateMerchant",
            graphql_query=UPDATE_MERCHANT_MUTATION,
            variables={"input": merchant_input},
        )

        errors = result.get("updateMerchant", {}).get("errors")
        if errors:
            return json_success({"success": False, "errors": errors})

        merchant = result.get("updateMerchant", {}).get("merchant", {})
        stream = merchant.get("recurringTransactionStream")
        return json_success(
            {
                "success": True,
                "merchant": {
                    "id": merchant.get("id"),
                    "name": merchant.get("name"),
                    "recurring_stream": (
                        {
                            "id": stream.get("id"),
                            "frequency": stream.get("frequency"),
                            "amount": stream.get("amount"),
                            "base_date": stream.get("baseDate"),
                            "is_active": stream.get("isActive"),
                        }
                        if stream
                        else None
                    ),
                },
            }
        )
    except Exception as e:
        return json_error("update_merchant", e)


@mcp.tool()
async def review_recurring_stream(
    stream_id: str,
    review_status: str,
) -> str:
    """
    Set the review status of a recurring transaction stream.

    When Monarch detects new recurring patterns, they appear as pending review.
    Use this to accept, dismiss, or reset them.

    Args:
        stream_id: The recurring stream ID (find via get_recurring_transactions
            or get_merchant, which include stream IDs).
        review_status: The review status to set. Known values: "approved"
            (accept the detected pattern), "ignored" (dismiss it), "pending"
            (reset to pending review).

    Returns:
        Updated stream ID and review status.

    Example:
        Approve a detected Netflix recurring stream:
            review_recurring_stream(
                stream_id="235281502498808806",
                review_status="approved",
            )
    """
    try:
        client = await get_monarch_client()
        result = await client.gql_call(
            operation="Web_ReviewStream",
            graphql_query=REVIEW_STREAM_MUTATION,
            variables={
                "input": {
                    "streamId": stream_id,
                    "reviewStatus": review_status,
                }
            },
        )

        errors = result.get("reviewRecurringStream", {}).get("errors")
        if errors:
            return json_success({"success": False, "errors": errors})

        stream = result.get("reviewRecurringStream", {}).get("stream", {})
        return json_success(
            {
                "success": True,
                "stream_id": stream.get("id"),
                "review_status": stream.get("reviewStatus"),
            }
        )
    except Exception as e:
        return json_error("review_recurring_stream", e)
