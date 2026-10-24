"""Budget reads must distinguish overlapping category and group views."""

import copy
import json
from datetime import date

import pytest

from monarch_mcp_server.tools import budgets


@pytest.fixture
def summary_data():
    # A group allowance of 700 and a separate category allowance of 300 make
    # 1,000 total expenses, not 1,300 (the group view includes both groups).
    return {
        "budgetData": {
            "monthlyAmountsByCategory": [
                {
                    "category": {"id": "groceries"},
                    "monthlyAmounts": [
                        {
                            "month": "2026-10-01",
                            "plannedCashFlowAmount": 0,
                            "plannedSetAsideAmount": 0,
                            "actualAmount": 200,
                            "remainingAmount": -200,
                        },
                        {
                            "month": "2026-11-01",
                            "plannedCashFlowAmount": 0,
                            "plannedSetAsideAmount": 0,
                            "actualAmount": 0,
                            "remainingAmount": 0,
                        },
                    ],
                },
                {
                    "category": {"id": "insurance"},
                    "monthlyAmounts": [
                        {
                            "month": "2026-10-01",
                            "plannedCashFlowAmount": 300,
                            "plannedSetAsideAmount": 0,
                            "actualAmount": 280,
                            "remainingAmount": 20,
                        },
                    ],
                },
            ],
            "monthlyAmountsByCategoryGroup": [
                {
                    "categoryGroup": {"id": "family"},
                    "monthlyAmounts": [
                        {
                            "month": "2026-10-01",
                            "plannedCashFlowAmount": 700,
                            "actualAmount": 200,
                            "remainingAmount": 550,
                        },
                        {
                            "month": "2026-11-01",
                            "plannedCashFlowAmount": 700,
                            "actualAmount": 0,
                            "remainingAmount": 700,
                        },
                    ],
                },
                {
                    "categoryGroup": {"id": "core"},
                    "monthlyAmounts": [
                        {
                            "month": "2026-10-01",
                            "plannedCashFlowAmount": 300,
                            "actualAmount": 280,
                            "remainingAmount": 20,
                        },
                    ],
                },
            ],
            "totalsByMonth": [
                {
                    "month": "2026-10-01",
                    "totalIncome": {"plannedAmount": 5000, "actualAmount": 5000},
                    "totalExpenses": {"plannedAmount": 1000, "actualAmount": 480},
                },
            ],
        },
        "categoryGroups": [
            {
                "id": "family",
                "name": "Family",
                "type": "expense",
                "groupLevelBudgetingEnabled": True,
                "categories": [{"id": "groceries", "name": "Groceries"}],
            },
            {
                "id": "core",
                "name": "Core bills",
                "type": "expense",
                "groupLevelBudgetingEnabled": False,
                "categories": [{"id": "insurance", "name": "Insurance"}],
            },
        ],
    }


async def test_preserves_group_allowance_when_child_categories_show_zero(
    mock_monarch_client, summary_data
):
    mock_monarch_client.gql_call.return_value = summary_data
    result = json.loads(await budgets.get_budget_summary("2026-10-01", "2026-11-01"))

    assert result["category_budgets"][0] == {
        "id": "groceries",
        "name": "Groceries",
        "planned": 0,
        "actual": 200,
        "remaining": -200,
        "category_group": "Family",
        "category_group_id": "family",
        "category_group_type": "expense",
        "groupLevelBudgetingEnabled": True,
        "month": "2026-10-01",
    }
    assert result["group_budgets"] == [
        {
            "id": "family",
            "name": "Family",
            "type": "expense",
            "groupLevelBudgetingEnabled": True,
            "month": "2026-10-01",
            "planned": 700,
            "actual": 200,
            "remaining": 550,
        },
        {
            "id": "family",
            "name": "Family",
            "type": "expense",
            "groupLevelBudgetingEnabled": True,
            "month": "2026-11-01",
            "planned": 700,
            "actual": 0,
            "remaining": 700,
        },
        {
            "id": "core",
            "name": "Core bills",
            "type": "expense",
            "groupLevelBudgetingEnabled": False,
            "month": "2026-10-01",
            "planned": 300,
            "actual": 280,
            "remaining": 20,
        },
    ]
    assert len(result["category_budgets"]) == 3


async def test_uses_authoritative_totals_without_adding_overlapping_views(
    mock_monarch_client, summary_data
):
    mock_monarch_client.gql_call.return_value = summary_data
    result = json.loads(await budgets.get_budget_summary())
    assert result["totals_by_month"] == [
        {
            "month": "2026-10-01",
            "totalIncome": {"plannedAmount": 5000, "actualAmount": 5000},
            "totalExpenses": {"plannedAmount": 1000, "actualAmount": 480},
        }
    ]


async def test_requests_group_flags_category_rows_and_authoritative_totals(
    mock_monarch_client, summary_data
):
    mock_monarch_client.gql_call.return_value = summary_data
    await budgets.get_budget_summary("2026-10-01", "2026-11-01")
    request = mock_monarch_client.gql_call.call_args.kwargs
    assert request["variables"] == {"startDate": "2026-10-01", "endDate": "2026-11-01"}
    query = request["graphql_query"]
    document = getattr(query, "document", query)
    fields = {
        field.name.value: field
        for field in document.definitions[0].selection_set.selections
    }
    budget_fields = {
        field.name.value for field in fields["budgetData"].selection_set.selections
    }
    assert budget_fields >= {
        "monthlyAmountsByCategory",
        "monthlyAmountsByCategoryGroup",
        "totalsByMonth",
    }
    group_fields = {
        field.name.value for field in fields["categoryGroups"].selection_set.selections
    }
    assert "groupLevelBudgetingEnabled" in group_fields


async def test_defaults_to_current_month_bounds(mock_monarch_client, monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 2, 17)

    monkeypatch.setattr(budgets, "date", FixedDate)
    await budgets.get_budget_summary()
    assert mock_monarch_client.gql_call.call_args.kwargs["variables"] == {
        "startDate": "2026-02-01",
        "endDate": "2026-02-28",
    }


async def test_preserves_unknown_metadata_and_missing_amounts_as_unknown(
    mock_monarch_client,
):
    mock_monarch_client.gql_call.return_value = {
        "budgetData": {
            "monthlyAmountsByCategory": [
                {
                    "category": {"id": "unknown-cat"},
                    "monthlyAmounts": [{"month": "2026-10-01"}],
                }
            ],
            "monthlyAmountsByCategoryGroup": [
                {
                    "categoryGroup": {"id": "unknown-group"},
                    "monthlyAmounts": [{"month": "2026-10-01"}],
                }
            ],
        }
    }
    result = json.loads(await budgets.get_budget_summary())
    assert result["category_budgets"][0]["planned"] is None
    assert result["category_budgets"][0]["groupLevelBudgetingEnabled"] is None
    assert result["group_budgets"][0]["planned"] is None
    assert result["group_budgets"][0]["groupLevelBudgetingEnabled"] is None
    assert result["totals_by_month"] is None


async def test_reports_summary_failure_without_returning_zero_budget(
    mock_monarch_client,
):
    mock_monarch_client.gql_call.side_effect = RuntimeError("Budget unavailable")
    result = json.loads(await budgets.get_budget_summary())
    assert result == {
        "error": True,
        "tool": "get_budget_summary",
        "message": "Budget unavailable",
    }


async def test_existing_get_budgets_contract_is_unchanged(
    mock_monarch_client, summary_data
):
    original = copy.deepcopy(summary_data)
    mock_monarch_client.gql_call.return_value = summary_data
    result = json.loads(await budgets.get_budgets("2026-10-01", "2026-11-01"))
    assert result[0] == {
        "id": "groceries",
        "name": "Groceries",
        "planned": 0,
        "actual": 200,
        "remaining": -200,
        "category_group": "Family",
        "month": "2026-10-01",
    }
    assert summary_data == original
