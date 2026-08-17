from monarch_mcp_server.tools.budgets import (
    BUDGET_QUERY,
    BUDGET_QUERY_FLEX,
    BUDGET_QUERY_FLEX_OPERATION,
    BUDGET_QUERY_OPERATION,
    _CATEGORY_FIELD_EXTRA,
    _GROUP_EXTRA,
    format_budget_data,
    format_budget_totals,
    format_flex_budget,
)


def query_text(query):
    # gql 4.x returns a GraphQLRequest wrapping the parsed DocumentNode, with
    # the source on document.loc; gql 3.x exposed .loc directly on the gql()
    # return value. pyproject allows both, so support both.
    node = getattr(query, "document", query)
    return node.loc.source.body


def test_budget_query_avoids_stale_category_group_fields():
    text = query_text(BUDGET_QUERY)

    assert "budgetVariability" not in text
    assert "rolloverPeriod" not in text


def test_fallback_query_requests_nothing_beyond_the_proven_set():
    # The narrow query is the safety net: it must stay exactly the document
    # already known to work, so none of the extended fields may leak into it.
    text = query_text(BUDGET_QUERY)

    for field in (
        "monthlyAmountsForFlexExpense",
        "monthlyAmountsByCategoryGroup",
        "totalsByMonth",
        "previousMonthRolloverAmount",
        "rolloverType",
        "budgetSystem",
    ):
        assert field not in text, f"{field} leaked into the fallback query"


def test_flex_query_adds_the_extended_selections():
    text = query_text(BUDGET_QUERY_FLEX)

    for field in (
        "monthlyAmountsForFlexExpense",
        "monthlyAmountsByCategoryGroup",
        "totalsByMonth",
        "totalIncome",
        "goalsV2",
        "budgetSystem",
    ):
        assert field in text


def test_flex_query_does_not_reintroduce_the_rejected_group_fields():
    # The #15 failure was CategoryGroup.budgetVariability / rolloverPeriod.
    # The extended query may widen categoryGroups with groupLevelBudgetingEnabled
    # and add budgetVariability on *categories* (both proven to work elsewhere
    # in this server), but must not bring back the two fields that broke.
    text = query_text(BUDGET_QUERY_FLEX)

    assert "rolloverPeriod" not in text
    # budgetVariability is legitimate under monthlyAmountsForFlexExpense and on
    # categories; assert it never appears as a direct CategoryGroup field by
    # checking the exact fragments the document is assembled from.
    assert _GROUP_EXTRA.strip() == "groupLevelBudgetingEnabled"
    assert _CATEGORY_FIELD_EXTRA.strip() == "budgetVariability"


def test_documents_carry_the_operation_names_they_are_sent_under():
    # get_budget_data passes `operation=` alongside `graphql_query=`, and the
    # client forwards it as operation_name. A mismatch makes the server reject
    # the request, which _is_query_rejection reads as "no flex here" -- so a
    # swapped document would degrade silently instead of failing loudly.
    assert f"query {BUDGET_QUERY_OPERATION}(" in query_text(BUDGET_QUERY)
    assert f"query {BUDGET_QUERY_FLEX_OPERATION}(" in query_text(BUDGET_QUERY_FLEX)
    assert BUDGET_QUERY_OPERATION != BUDGET_QUERY_FLEX_OPERATION


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
            "set_aside": 0,
            "rollover": None,
            "rollover_type": None,
            "category_group": "Food",
            "category_type": None,
            "budget_variability": None,
            "month": "2026-06-01",
        }
    ]


def test_format_budget_data_carries_the_income_expense_marker():
    # Income and expense amounts are both positive magnitudes, so without
    # category_type a caller summing planned adds income to spending.
    raw = {
        "budgetData": {
            "monthlyAmountsByCategory": [
                {
                    "category": {"id": "inc-1"},
                    "monthlyAmounts": [
                        {"month": "2026-06-01", "plannedCashFlowAmount": 8000}
                    ],
                },
                {
                    "category": {"id": "exp-1"},
                    "monthlyAmounts": [
                        {"month": "2026-06-01", "plannedCashFlowAmount": 500}
                    ],
                },
            ]
        },
        "categoryGroups": [
            {
                "id": "g1",
                "name": "Income",
                "type": "income",
                "categories": [{"id": "inc-1", "name": "Paycheck"}],
            },
            {
                "id": "g2",
                "name": "Food",
                "type": "expense",
                "categories": [
                    {"id": "exp-1", "name": "Groceries",
                     "budget_variability": None, "budgetVariability": "flexible"}
                ],
            },
        ],
    }

    rows = {r["id"]: r for r in format_budget_data(raw)}

    assert rows["inc-1"]["category_type"] == "income"
    assert rows["exp-1"]["category_type"] == "expense"
    assert rows["exp-1"]["budget_variability"] == "flexible"
    spending = sum(
        r["planned"] for r in rows.values() if r["category_type"] == "expense"
    )
    assert spending == 500


def test_format_budget_data_tolerates_explicit_nulls():
    for raw in (
        {"budgetData": None, "categoryGroups": None},
        {"budgetData": {"monthlyAmountsByCategory": None}, "categoryGroups": []},
        {"budgetData": {"monthlyAmountsByCategory": [None]}, "categoryGroups": [None]},
        {
            "budgetData": {"monthlyAmountsByCategory": []},
            "categoryGroups": [{"id": "g", "name": "G", "categories": None}],
        },
    ):
        assert format_budget_data(raw) == []


class TestFormatFlexBudget:
    def test_unsupported_when_fallback_query_was_used(self):
        assert format_flex_budget({"budgetData": {}}, used_flex_query=False) == {
            "status": "unsupported",
            "budget_variability": None,
            "monthly": [],
        }

    def test_not_configured_when_field_absent(self):
        assert (
            format_flex_budget({"budgetData": {}}, used_flex_query=True)["status"]
            == "not_configured"
        )

    def test_not_configured_when_field_is_null(self):
        raw = {"budgetData": {"monthlyAmountsForFlexExpense": None}}
        assert format_flex_budget(raw, used_flex_query=True)["status"] == "not_configured"

    def test_never_merges_multiple_buckets(self):
        # Merging a fixed bucket's months into the flex answer would report a
        # different bucket's amount as the flexible budget.
        def bucket(variability, planned):
            return {
                "budgetVariability": variability,
                "monthlyAmounts": [
                    {"month": "2026-06-01", "plannedCashFlowAmount": planned}
                ],
            }

        raw = {
            "budgetData": {
                "monthlyAmountsForFlexExpense": [
                    bucket("fixed", 7000),
                    bucket("flexible", 900),
                ]
            }
        }

        result = format_flex_budget(raw, used_flex_query=True)

        assert result["budget_variability"] == "flexible"
        assert [m["planned"] for m in result["monthly"]] == [900]

    def test_falls_back_to_one_bucket_when_none_is_labelled_flexible(self):
        # Ambiguous labelling must not collapse into a merged total either.
        raw = {
            "budgetData": {
                "monthlyAmountsForFlexExpense": [
                    {
                        "monthlyAmounts": [
                            {"month": "2026-06-01", "plannedCashFlowAmount": 100}
                        ]
                    },
                    {
                        "monthlyAmounts": [
                            {"month": "2026-06-01", "plannedCashFlowAmount": 200}
                        ]
                    },
                ]
            }
        }

        result = format_flex_budget(raw, used_flex_query=True)

        assert [m["planned"] for m in result["monthly"]] == [100]

    def test_accepts_a_bare_object_or_a_list(self):
        block = {
            "budgetVariability": "flexible",
            "monthlyAmounts": [
                {
                    "month": "2026-06-01",
                    "plannedCashFlowAmount": 900,
                    "actualAmount": 400,
                    "remainingAmount": 500,
                    "previousMonthRolloverAmount": 0,
                    "rolloverType": "monthly",
                }
            ],
        }

        as_object = format_flex_budget(
            {"budgetData": {"monthlyAmountsForFlexExpense": block}},
            used_flex_query=True,
        )
        as_list = format_flex_budget(
            {"budgetData": {"monthlyAmountsForFlexExpense": [block]}},
            used_flex_query=True,
        )

        assert as_object == as_list
        assert as_object["status"] == "ok"
        assert as_object["monthly"][0]["planned"] == 900

    def test_tolerates_partially_populated_amounts(self):
        raw = {
            "budgetData": {
                "monthlyAmountsForFlexExpense": {
                    "monthlyAmounts": [{"month": "2026-06-01"}]
                }
            }
        }

        result = format_flex_budget(raw, used_flex_query=True)

        assert result["status"] == "ok"
        assert result["budget_variability"] is None
        assert result["monthly"] == [
            {
                "month": "2026-06-01",
                "planned": None,
                "actual": None,
                "remaining": None,
                "rollover": None,
                "rollover_type": None,
            }
        ]

    def test_empty_amount_entries_are_ignored(self):
        raw = {
            "budgetData": {
                "monthlyAmountsForFlexExpense": {"monthlyAmounts": [{}, None]}
            }
        }

        # Nothing usable came back, so report that rather than inventing a row.
        assert format_flex_budget(raw, used_flex_query=True)["status"] == "not_configured"


class TestFormatBudgetTotals:
    def test_none_when_fallback_query_was_used(self):
        assert format_budget_totals({"budgetData": {}}, used_flex_query=False) is None

    def test_empty_list_when_query_ran_but_returned_none(self):
        # [] means "asked, none there"; None means "could not ask". Collapsing
        # them is the ambiguity flex.status exists to avoid.
        assert format_budget_totals({"budgetData": {}}, used_flex_query=True) == []

    def test_maps_each_bucket(self):
        raw = {
            "budgetData": {
                "totalsByMonth": [
                    {
                        "month": "2026-06-01",
                        "totalFlexibleExpenses": {
                            "plannedAmount": 1,
                            "actualAmount": 2,
                            "remainingAmount": 3,
                            "previousMonthRolloverAmount": 4,
                        },
                        "totalFixedExpenses": None,
                    }
                ]
            }
        }

        assert format_budget_totals(raw, used_flex_query=True) == [
            {
                "month": "2026-06-01",
                "income": None,
                "expenses": None,
                "flexible": {
                    "planned": 1,
                    "actual": 2,
                    "remaining": 3,
                    "rollover": 4,
                },
                "fixed": None,
                "non_monthly": None,
            }
        ]
