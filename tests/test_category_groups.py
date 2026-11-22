"""Group mutations must validate inputs, preserve omitted settings and verify writes."""

import copy
import importlib
import json

import pytest


@pytest.fixture
def group_api(monkeypatch):
    module = importlib.import_module("monarch_mcp_server.tools.category_groups")

    class Client:
        def __init__(self):
            self.groups = [
                {
                    "id": "g1",
                    "name": "Household",
                    "order": 1,
                    "type": "expense",
                    "groupLevelBudgetingEnabled": True,
                    "categories": [{"id": "c1", "name": "Groceries"}],
                }
            ]
            self.writes = []
            self.reject = False
            self.lose_write = False
            self.wrong_id = False

        async def gql_call(self, *, operation, graphql_query, variables=None):
            if operation == "MCPGetCategoryGroupDetails":
                return {"categoryGroups": copy.deepcopy(self.groups)}
            inp = copy.deepcopy(variables["input"])
            self.writes.append(inp)
            key = (
                "createCategoryGroup"
                if operation == "Common_CreateCategoryGroup"
                else "updateCategoryGroup"
            )
            if self.reject:
                return {key: {"categoryGroup": None}}
            if key == "createCategoryGroup":
                entity = {
                    "id": "g2",
                    "name": inp["name"],
                    "type": inp["type"],
                    "order": 2,
                    "groupLevelBudgetingEnabled": False,
                    "categories": [],
                }
                if not self.lose_write:
                    self.groups.append(copy.deepcopy(entity))
            else:
                entity = copy.deepcopy(self.groups[0])
                entity.update(inp)
                if not self.lose_write:
                    self.groups[0] = copy.deepcopy(entity)
            if self.wrong_id:
                entity["id"] = "wrong"
            return {key: {"categoryGroup": entity}}

    client = Client()

    async def get_client():
        return client

    monkeypatch.setattr(module, "get_monarch_client", get_client)
    return module, client


async def test_read_group_includes_budgeting_mode_and_children(group_api):
    api, _ = group_api
    data = json.loads(await api.get_category_group_details("g1"))
    assert data["id"] == "g1"
    assert data["group_level_budgeting_enabled"] is True
    assert data["categories"] == [{"id": "c1", "name": "Groceries"}]


async def test_unknown_group_is_an_error_without_mutation(group_api):
    api, client = group_api
    data = json.loads(
        await api.update_transaction_category_group("missing", name="Core bills")
    )
    assert data["error"] is True
    assert client.writes == []


@pytest.mark.parametrize("name", ["", "   "])
async def test_blank_create_name_cannot_write(group_api, name):
    api, client = group_api
    data = json.loads(await api.create_transaction_category_group(name))
    assert data["error"] is True
    assert client.writes == []


async def test_create_rejects_unsupported_type(group_api):
    api, client = group_api
    data = json.loads(
        await api.create_transaction_category_group("Dogs", group_type="bogus")
    )
    assert data["error"] is True
    assert client.writes == []


async def test_create_trims_name_and_returns_verified_entity(group_api):
    api, client = group_api
    data = json.loads(await api.create_transaction_category_group(" Dogs "))
    assert data["success"] is True and data["verified"] is True
    assert data["created"] is True and data["group"]["name"] == "Dogs"
    assert client.writes == [{"name": "Dogs", "type": "expense"}]


async def test_duplicate_creation_is_idempotent(group_api):
    api, client = group_api
    data = json.loads(await api.create_transaction_category_group("household"))
    assert data["success"] is True and data["created"] is False
    assert data["group"]["id"] == "g1"
    assert client.writes == []


async def test_same_name_different_type_does_not_create_ambiguous_group(group_api):
    api, client = group_api
    data = json.loads(
        await api.create_transaction_category_group("Household", group_type="income")
    )
    assert data["error"] is True
    assert client.writes == []


async def test_create_dry_run_never_mutates(group_api):
    api, client = group_api
    data = json.loads(await api.create_transaction_category_group("Dogs", dry_run=True))
    assert data["dry_run"] is True
    assert data["planned_changes"] == {"name": "Dogs", "type": "expense"}
    assert client.writes == []


async def test_update_sends_false_and_preserves_unspecified_fields(group_api):
    api, client = group_api
    data = json.loads(
        await api.update_transaction_category_group(
            "g1", name=" Core bills ", group_level_budgeting_enabled=False
        )
    )
    assert data["success"] is True and data["verified"] is True
    assert data["group"]["name"] == "Core bills"
    assert data["group"]["group_level_budgeting_enabled"] is False
    assert client.writes == [
        {"id": "g1", "name": "Core bills", "groupLevelBudgetingEnabled": False}
    ]
    assert data["group"]["type"] == "expense"
    assert data["group"]["categories"] == [{"id": "c1", "name": "Groceries"}]


async def test_rename_does_not_reset_budgeting_mode(group_api):
    api, client = group_api
    data = json.loads(
        await api.update_transaction_category_group("g1", name="Core bills")
    )
    assert data["group"]["group_level_budgeting_enabled"] is True
    assert client.writes == [{"id": "g1", "name": "Core bills"}]


async def test_update_preview_and_noop_do_not_write(group_api):
    api, client = group_api
    preview = json.loads(
        await api.update_transaction_category_group(
            "g1", name="Core bills", dry_run=True
        )
    )
    assert preview["dry_run"] is True
    assert preview["current"]["name"] == "Household"
    assert preview["planned_changes"] == {"id": "g1", "name": "Core bills"}
    noop = json.loads(
        await api.update_transaction_category_group("g1", name="Household")
    )
    assert noop["changed"] is False
    assert client.writes == []


async def test_update_requires_a_change_parameter(group_api):
    api, client = group_api
    data = json.loads(await api.update_transaction_category_group("g1"))
    assert data["error"] is True
    assert client.writes == []


async def test_rename_collision_rejected_before_mutation(group_api):
    api, client = group_api
    client.groups.append(dict(client.groups[0], id="g2", name="Family"))
    data = json.loads(await api.update_transaction_category_group("g1", name="Family"))
    assert data["error"] is True
    assert client.writes == []


@pytest.mark.parametrize("action", ["create", "update"])
@pytest.mark.parametrize("failure", ["reject", "lose_write", "wrong_id"])
async def test_rejected_or_unverified_write_never_reports_success(
    group_api, action, failure
):
    api, client = group_api
    setattr(client, failure, True)
    result = await (
        api.create_transaction_category_group("Dogs")
        if action == "create"
        else api.update_transaction_category_group("g1", name="Core bills")
    )
    data = json.loads(result)
    assert data.get("success") is not True
    assert data["error"] is True
