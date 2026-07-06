from monarch_mcp_server.tools.budgets import (
    BUDGET_QUERY,
    format_budget_data,
    format_flex_bucket,
    format_section_totals,
)


def test_budget_query_avoids_stale_category_group_fields():
    # gql 4.0 returns a GraphQLRequest wrapping the parsed DocumentNode;
    # the source string lives on document.loc.source.body. Earlier gql 3.x
    # exposed .loc directly on the gql() return value.
    query_text = BUDGET_QUERY.document.loc.source.body

    assert "budgetVariability" not in query_text
    assert "rolloverPeriod" not in query_text


def test_budget_query_includes_flex_and_section_totals():
    # Flex-budget context lives on budgetData (safe fields), so it must be
    # requested for the flexible-budget analysis to be correct.
    query_text = BUDGET_QUERY.document.loc.source.body

    assert "monthlyAmountsForFlexExpense" in query_text
    assert "totalsByMonth" in query_text
    assert "totalFlexibleExpenses" in query_text


def test_format_budget_data_returns_current_month_category_rows():
    raw_budget_data = {
        "budgetData": {
            "monthlyAmountsByCategory": [
                {
                    "category": {"id": "cat-1"},
                    "monthlyAmounts": [
                        {
                            "month": "2026-06-01",
                            "plannedCashFlowAmount": -100,
                            "plannedSetAsideAmount": 0,
                            "actualAmount": -25,
                            "remainingAmount": -75,
                        }
                    ],
                }
            ]
        },
        "categoryGroups": [
            {
                "name": "Food",
                "categories": [{"id": "cat-1", "name": "Groceries"}],
            }
        ],
    }

    assert format_budget_data(raw_budget_data) == [
        {
            "id": "cat-1",
            "name": "Groceries",
            "planned": -100,
            "actual": -25,
            "remaining": -75,
            "category_group": "Food",
            "month": "2026-06-01",
        }
    ]


def test_format_flex_bucket_extracts_monthly_totals():
    raw = {
        "budgetData": {
            "monthlyAmountsForFlexExpense": {
                "budgetVariability": "flexible",
                "monthlyAmounts": [
                    {
                        "month": "2026-06-01",
                        "plannedCashFlowAmount": 2650.0,
                        "actualAmount": 5302.75,
                        "remainingAmount": -2652.75,
                    }
                ],
            }
        }
    }
    assert format_flex_bucket(raw) == [
        {
            "month": "2026-06-01",
            "planned": 2650.0,
            "actual": 5302.75,
            "remaining": -2652.75,
        }
    ]


def test_format_flex_bucket_handles_missing():
    assert format_flex_bucket({"budgetData": {}}) == []


def test_format_section_totals_extracts_rollups():
    raw = {
        "budgetData": {
            "totalsByMonth": [
                {
                    "month": "2026-06-01",
                    "totalIncome": {
                        "plannedAmount": 100,
                        "actualAmount": 90,
                        "remainingAmount": 10,
                    },
                    "totalExpenses": {
                        "plannedAmount": 80,
                        "actualAmount": 70,
                        "remainingAmount": 10,
                    },
                    "totalFixedExpenses": {
                        "plannedAmount": 40,
                        "actualAmount": 38,
                        "remainingAmount": 2,
                    },
                    "totalNonMonthlyExpenses": {
                        "plannedAmount": 10,
                        "actualAmount": 12,
                        "remainingAmount": -2,
                    },
                    "totalFlexibleExpenses": {
                        "plannedAmount": 30,
                        "actualAmount": 20,
                        "remainingAmount": 10,
                    },
                }
            ]
        }
    }
    assert format_section_totals(raw) == [
        {
            "month": "2026-06-01",
            "income": {"planned": 100, "actual": 90, "remaining": 10},
            "total_expenses": {"planned": 80, "actual": 70, "remaining": 10},
            "fixed": {"planned": 40, "actual": 38, "remaining": 2},
            "non_monthly": {"planned": 10, "actual": 12, "remaining": -2},
            "flexible": {"planned": 30, "actual": 20, "remaining": 10},
        }
    ]
