"""Tag management tools."""

import logging
from typing import List

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

logger = logging.getLogger(__name__)


@mcp.tool()
async def get_tags() -> str:
    """
    Get all transaction tags from Monarch Money.

    Returns a list of tags with their colors and transaction counts.
    Use this to see available tags before applying them to transactions.
    """
    try:
        client = await get_monarch_client()
        tags_data = await client.get_transaction_tags()

        tag_list = []
        for tag in tags_data.get("householdTransactionTags", []):
            tag_info = {
                "id": tag.get("id"),
                "name": tag.get("name"),
                "color": tag.get("color"),
                "order": tag.get("order"),
                "transaction_count": tag.get("transactionCount", 0),
            }
            tag_list.append(tag_info)

        return json_success(tag_list)
    except Exception as e:
        return json_error("get_tags", e)


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
async def create_tag(
    name: str,
    color: str = "#19D2A5",
) -> str:
    """
    Create a new transaction tag.

    Args:
        name: Name for the new tag
        color: Hex color code for the tag (default: "#19D2A5" - teal)
               Examples: "#FF5733" (red-orange), "#3498DB" (blue), "#9B59B6" (purple)

    Returns:
        The created tag details including its ID.
    """
    try:
        client = await get_monarch_client()
        result = await client.create_transaction_tag(
            name=name,
            color=color,
        )
        return json_success(result)
    except Exception as e:
        return json_error("create_tag", e)
