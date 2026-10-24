"""Category group management with previews and verified writes."""

from typing import Any, Dict, Optional

from gql import gql

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import (
    json_error,
    json_success,
    payload_errors,
    require_nonblank,
)

# Source evidence: docs/reference/group-api-source.md. Group mutation payloads
# do not expose the category mutation's errors selection. Validate the returned
# entity and a fresh read instead; do not request unsupported rollover fields.
GROUP_DETAILS_QUERY = gql("""
query MCPGetCategoryGroupDetails {
  categoryGroups {
    id name order type groupLevelBudgetingEnabled
    categories { id name }
  }
}
""")
CREATE_GROUP_MUTATION = gql("""
mutation Common_CreateCategoryGroup($input: CreateCategoryGroupInput!) {
  createCategoryGroup(input: $input) {
    categoryGroup { id name order type groupLevelBudgetingEnabled }
  }
}
""")
UPDATE_GROUP_MUTATION = gql("""
mutation Common_UpdateCategoryGroup($input: UpdateCategoryGroupInput!) {
  updateCategoryGroup(input: $input) {
    categoryGroup { id name order type groupLevelBudgetingEnabled }
  }
}
""")


def _view(group: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": group["id"],
        "name": group["name"],
        "type": group["type"],
        "order": group.get("order"),
        "group_level_budgeting_enabled": group.get("groupLevelBudgetingEnabled"),
        "categories": group.get("categories", []),
    }


async def _groups(client: Any) -> list[Dict[str, Any]]:
    result = await client.gql_call(
        operation="MCPGetCategoryGroupDetails",
        graphql_query=GROUP_DETAILS_QUERY,
    )
    groups = result.get("categoryGroups")
    if not isinstance(groups, list):
        raise ValueError("Monarch did not return category groups")
    return groups


def _find(groups: list[Dict[str, Any]], group_id: str) -> Dict[str, Any]:
    matches = [g for g in groups if g.get("id") == group_id]
    if len(matches) != 1:
        raise ValueError(f"Category group {group_id} not found uniquely")
    return matches[0]


def _returned_group(result: Any, key: str) -> Dict[str, Any]:
    errors = payload_errors(result, key)
    if errors:
        raise ValueError(f"Monarch rejected the group change: {errors}")
    group = (
        (result.get(key) or {}).get("categoryGroup")
        if isinstance(result, dict)
        else None
    )
    if not isinstance(group, dict) or not group.get("id"):
        raise ValueError(
            "Monarch did not return the changed group; read groups before retrying"
        )
    return group


@mcp.tool()
async def get_category_group_details(group_id: str) -> str:
    """Read one group's name, categories and group/category budgeting mode."""
    try:
        require_nonblank(group_id, "group_id")
        client = await get_monarch_client()
        return json_success(_view(_find(await _groups(client), group_id.strip())))
    except Exception as exc:
        return json_error("get_category_group_details", exc)


@mcp.tool()
async def create_transaction_category_group(
    name: str,
    group_type: str = "expense",
    dry_run: bool = False,
) -> str:
    """Create an income/expense group and verify it with a fresh read.

    Returns an existing same-name, same-type group without creating a duplicate.
    dry_run previews the input without writing. Does not set budgets, move
    categories or change rollover. After an error or unknown outcome, read groups
    before retrying: a write may have succeeded before readback failed.
    """
    try:
        require_nonblank(name, "name")
        name = name.strip()
        if group_type not in {"expense", "income"}:
            raise ValueError("group_type must be expense or income")
        client = await get_monarch_client()
        existing = [
            g for g in await _groups(client) if g["name"].casefold() == name.casefold()
        ]
        if existing:
            if len(existing) != 1 or existing[0]["type"] != group_type:
                raise ValueError(
                    "An ambiguous or different-type group already uses that name"
                )
            return json_success(
                {
                    "success": True,
                    "created": False,
                    "verified": True,
                    "dry_run": dry_run,
                    "group": _view(existing[0]),
                }
            )
        changes = {"name": name, "type": group_type}
        if dry_run:
            return json_success({"dry_run": True, "planned_changes": changes})
        result = await client.gql_call(
            operation="Common_CreateCategoryGroup",
            graphql_query=CREATE_GROUP_MUTATION,
            variables={"input": changes},
        )
        returned = _returned_group(result, "createCategoryGroup")
        actual = _find(await _groups(client), returned["id"])
        if any(actual.get(k) != v for k, v in changes.items()):
            raise ValueError(
                "Created group readback did not match; inspect groups before retrying"
            )
        return json_success(
            {"success": True, "created": True, "verified": True, "group": _view(actual)}
        )
    except Exception as exc:
        return json_error("create_transaction_category_group", exc)


@mcp.tool()
async def update_transaction_category_group(
    group_id: str,
    name: Optional[str] = None,
    group_level_budgeting_enabled: Optional[bool] = None,
    dry_run: bool = False,
) -> str:
    """Rename a group and/or switch its group/category budgeting mode.

    True budgets the group as a pool; False budgets categories individually.
    Read get_budget_summary first. Switching mode does not reconcile group and
    category amounts: set intended budgets separately and verify totals afterward.
    Only supplied fields change; no category moves, deletes or rollover resets.
    dry_run returns current state and changes without writing. A successful write
    is confirmed with fresh readback. Inspect current state before retrying errors.
    """
    try:
        require_nonblank(group_id, "group_id")
        group_id = group_id.strip()
        if name is None and group_level_budgeting_enabled is None:
            raise ValueError("Provide name or group_level_budgeting_enabled")
        if name is not None:
            require_nonblank(name, "name")
            name = name.strip()
        if group_level_budgeting_enabled is not None and not isinstance(
            group_level_budgeting_enabled, bool
        ):
            raise ValueError("group_level_budgeting_enabled must be a boolean")
        client = await get_monarch_client()
        groups = await _groups(client)
        current = _find(groups, group_id)
        if name is not None and any(
            g["id"] != group_id and g["name"].casefold() == name.casefold()
            for g in groups
        ):
            raise ValueError("Another group already uses that name")
        changes: Dict[str, Any] = {"id": group_id}
        if name is not None and name != current["name"]:
            changes["name"] = name
        if (
            group_level_budgeting_enabled is not None
            and group_level_budgeting_enabled
            != current.get("groupLevelBudgetingEnabled")
        ):
            changes["groupLevelBudgetingEnabled"] = group_level_budgeting_enabled
        if dry_run:
            return json_success(
                {"dry_run": True, "current": _view(current), "planned_changes": changes}
            )
        if len(changes) == 1:
            return json_success(
                {
                    "success": True,
                    "changed": False,
                    "verified": True,
                    "group": _view(current),
                }
            )
        result = await client.gql_call(
            operation="Common_UpdateCategoryGroup",
            graphql_query=UPDATE_GROUP_MUTATION,
            variables={"input": changes},
        )
        returned = _returned_group(result, "updateCategoryGroup")
        if returned["id"] != group_id:
            raise ValueError(
                "Monarch returned a different group; inspect groups before retrying"
            )
        actual = _find(await _groups(client), group_id)
        if any(actual.get(k) != v for k, v in changes.items()):
            raise ValueError(
                "Group change readback did not match; inspect groups before retrying"
            )
        return json_success(
            {"success": True, "changed": True, "verified": True, "group": _view(actual)}
        )
    except Exception as exc:
        return json_error("update_transaction_category_group", exc)
