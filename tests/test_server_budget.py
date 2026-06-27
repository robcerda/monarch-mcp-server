from monarch_mcp_server.tools.budgets import BUDGET_QUERY, format_budget_data


def test_budget_query_avoids_stale_category_group_fields():
    # gql 4.0 returns a GraphQLRequest wrapping the parsed DocumentNode;
    # the source string lives on document.loc.source.body. Earlier gql 3.x
    # exposed .loc directly on the gql() return value.
    query_text = BUDGET_QUERY.document.loc.source.body

    assert "budgetVariability" not in query_text
    assert "rolloverPeriod" not in query_text


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
