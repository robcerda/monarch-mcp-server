"""Transaction splitting tools."""

import logging
from typing import Any, Dict, List

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

logger = logging.getLogger(__name__)


@mcp.tool()
async def get_transaction_splits(transaction_id: str) -> str:
    """
    Get the splits for a transaction.

    Returns the split details if the transaction has been split into multiple parts.

    Args:
        transaction_id: The ID of the transaction to get splits for

    Returns:
        Split information for the transaction, or empty if not split.
    """
    try:
        client = await get_monarch_client()
        result = await client.get_transaction_splits(transaction_id=transaction_id)
        return json_success(result)
    except Exception as e:
        return json_error("get_transaction_splits", e)


@mcp.tool()
async def split_transaction(
    transaction_id: str,
    splits: List[Dict[str, Any]],
) -> str:
    """
    Split a transaction into multiple parts with different categories/merchants.

    The sum of all split amounts must equal the original transaction amount.
    Pass an empty list to remove all splits and restore the original transaction.

    Args:
        transaction_id: The ID of the transaction to split
        splits: List of split objects. Each split should have:
            - amount: The amount for this split (negative for expenses, positive for income)
            - categoryId: (optional) The category ID for this split
            - merchantName: (optional) The merchant name for this split

    Returns:
        The updated split information for the transaction.
    """
    try:
        client = await get_monarch_client()
        result = await client.update_transaction_splits(
            transaction_id=transaction_id,
            split_data=splits,
        )

        return json_success({
            "success": True,
            "message": f"Transaction split into {len(splits)} parts" if splits else "Splits removed from transaction",
            "splits": result,
        })
    except Exception as e:
        return json_error("split_transaction", e)
