"""Tag management tools."""

import logging
from typing import List

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import (
    json_error,
    json_rejected,
    json_success,
    payload_errors,
)

logger = logging.getLogger(__name__)


@mcp.tool()
async def set_transaction_tags(
    transaction_id: str,
    tag_ids: List[str],
) -> str:
    """
    Set tags on a transaction.

    Note: This REPLACES all existing tags on the transaction.
    To add a tag, include both existing and new tag IDs.
    To remove all tags, pass an empty list.

    Args:
        transaction_id: The ID of the transaction to tag
        tag_ids: List of tag IDs to apply (use get_tags to find IDs)

    Returns:
        Updated transaction details.
    """
    try:
        client = await get_monarch_client()
        result = await client.set_transaction_tags(
            transaction_id=transaction_id,
            tag_ids=tag_ids,
        )
        errors = payload_errors(result, "setTransactionTags")
        if errors:
            return json_rejected("set_transaction_tags", errors)
        return json_success(result)
    except Exception as e:
        return json_error("set_transaction_tags", e)


@mcp.tool()
async def get_transaction_tags() -> str:
    """Get all available transaction tags from Monarch Money."""
    try:
        client = await get_monarch_client()
        data = await client.get_transaction_tags()
        raw_tags = data.get("householdTransactionTags") or data.get("tags") or []
        tags = [
            {"id": t.get("id"), "name": t.get("name"), "color": t.get("color")}
            for t in raw_tags
        ]
        return json_success(tags)
    except Exception as e:
        return json_error("get_transaction_tags", e)


@mcp.tool()
async def create_transaction_tag(name: str, color: str) -> str:
    """
    Create a new transaction tag.

    Args:
        name: Name of the new tag
        color: Hex color code for the tag (e.g. "#ff0000")
    """
    try:
        client = await get_monarch_client()
        result = await client.create_transaction_tag(name=name, color=color)
        errors = payload_errors(result, "createTransactionTag")
        if errors:
            return json_rejected("create_transaction_tag", errors)
        return json_success(result)
    except Exception as e:
        return json_error("create_transaction_tag", e)


@mcp.tool()
async def add_transaction_tag(transaction_id: str, tag_id: str) -> str:
    """
    Add a tag to a transaction, preserving any tags already on it.

    Args:
        transaction_id: The ID of the transaction
        tag_id: The tag ID to add
    """
    try:
        client = await get_monarch_client()
        # redirect_posted defaults to True upstream, which answers a query for
        # a pending transaction with its posted counterpart. Since this is a
        # read modify replace, that would write the twin's tag set over the
        # pending transaction's own, silently dropping tags.
        details = await client.get_transaction_details(
            transaction_id, redirect_posted=False
        )
        txn = details.get("getTransaction") if isinstance(details, dict) else None

        # A missing or mismatched payload must not be treated as "no tags".
        # set_transaction_tags is a full replacement, so degrading to an empty
        # list turns this documented additive operation into a wipe.
        if not isinstance(txn, dict):
            return json_rejected(
                "add_transaction_tag",
                {
                    "message": (
                        f"Could not read transaction {transaction_id}; refusing "
                        "to replace its tags with an unverified set."
                    )
                },
            )
        returned_id = txn.get("id")
        if returned_id is not None and str(returned_id) != str(transaction_id):
            return json_rejected(
                "add_transaction_tag",
                {
                    "message": (
                        f"Monarch returned transaction {returned_id} for a "
                        f"request for {transaction_id}; refusing to write one "
                        "transaction's tags onto another."
                    )
                },
            )

        existing = [t.get("id") for t in (txn.get("tags") or []) if t.get("id")]
        if tag_id not in existing:
            existing.append(tag_id)
        result = await client.set_transaction_tags(
            transaction_id=transaction_id, tag_ids=existing
        )
        errors = payload_errors(result, "setTransactionTags")
        if errors:
            return json_rejected("add_transaction_tag", errors)
        return json_success(result)
    except Exception as e:
        return json_error("add_transaction_tag", e)
