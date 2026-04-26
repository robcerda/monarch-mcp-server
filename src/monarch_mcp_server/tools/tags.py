"""Tag management tools."""

import logging
from typing import List

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

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
        details = await client.get_transaction_details(transaction_id)
        txn = details.get("getTransaction") or {}
        existing = [t.get("id") for t in (txn.get("tags") or []) if t.get("id")]
        if tag_id not in existing:
            existing.append(tag_id)
        result = await client.set_transaction_tags(
            transaction_id=transaction_id, tag_ids=existing
        )
        return json_success(result)
    except Exception as e:
        return json_error("add_transaction_tag", e)
