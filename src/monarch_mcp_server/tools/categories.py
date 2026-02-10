"""Category tools."""

import logging

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

logger = logging.getLogger(__name__)


@mcp.tool()
async def get_categories() -> str:
    """
    Get all transaction categories from Monarch Money.

    Returns a list of categories with their groups, icons, and metadata.
    Useful for selecting a category when categorizing transactions.
    """
    try:
        client = await get_monarch_client()
        categories_data = await client.get_transaction_categories()

        category_list = []
        for cat in categories_data.get("categories", []):
            category_info = {
                "id": cat.get("id"),
                "name": cat.get("name"),
                "icon": cat.get("icon"),
                "group": cat.get("group", {}).get("name") if cat.get("group") else None,
                "group_id": cat.get("group", {}).get("id") if cat.get("group") else None,
                "is_system_category": cat.get("isSystemCategory", False),
                "is_disabled": cat.get("isDisabled", False),
            }
            category_list.append(category_info)

        return json_success(category_list)
    except Exception as e:
        return json_error("get_categories", e)


@mcp.tool()
async def get_category_groups() -> str:
    """
    Get all transaction category groups from Monarch Money.

    Returns groups like Income, Expenses, etc. with their associated categories.
    """
    try:
        client = await get_monarch_client()
        groups_data = await client.get_transaction_category_groups()

        group_list = []
        for group in groups_data.get("categoryGroups", []):
            group_info = {
                "id": group.get("id"),
                "name": group.get("name"),
                "type": group.get("type"),
                "budget_variability": group.get("budgetVariability"),
                "group_level_budgeting_enabled": group.get("groupLevelBudgetingEnabled", False),
                "categories": [
                    {
                        "id": cat.get("id"),
                        "name": cat.get("name"),
                        "icon": cat.get("icon"),
                    }
                    for cat in group.get("categories", [])
                ],
            }
            group_list.append(group_info)

        return json_success(group_list)
    except Exception as e:
        return json_error("get_category_groups", e)
