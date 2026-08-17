"""Tests for budget-related MCP tools."""

import calendar
import json
from datetime import date

import pytest
from gql.transport.exceptions import TransportQueryError, TransportServerError

from monarch_mcp_server.tools import budgets as budgets_module
from monarch_mcp_server.tools.budgets import (
    get_budgets,
    set_flexible_budget,
    update_flex_rollover_settings,
)

FLEX_BLOCK = {
    "budgetVariability": "flexible",
    "monthlyAmounts": [
        {
            "month": "2026-03-01",
            "plannedCashFlowAmount": 2000.00,
            "actualAmount": 1250.00,
            "remainingAmount": 750.00,
            "previousMonthRolloverAmount": 0.00,
            "rolloverType": "monthly",
        }
    ],
}

GROUPS_BLOCK = [
    {
        "categoryGroup": {"id": "grp-1"},
        "monthlyAmounts": [
            {
                "month": "2026-03-01",
                "plannedCashFlowAmount": 700.00,
                "actualAmount": 505.00,
                "remainingAmount": 195.00,
                "previousMonthRolloverAmount": 0.00,
                "rolloverType": "monthly",
            }
        ],
    }
]

TOTALS_BLOCK = [
    {
        "month": "2026-03-01",
        "totalIncome": {
            "plannedAmount": 8000.00,
            "actualAmount": 8000.00,
            "remainingAmount": 0.00,
            "previousMonthRolloverAmount": 0.00,
        },
        "totalExpenses": {
            "plannedAmount": 3800.00,
            "actualAmount": 2850.00,
            "remainingAmount": 950.00,
            "previousMonthRolloverAmount": 0.00,
        },
        "totalFlexibleExpenses": {
            "plannedAmount": 2000.00,
            "actualAmount": 1250.00,
            "remainingAmount": 750.00,
            "previousMonthRolloverAmount": 0.00,
        },
        "totalFixedExpenses": {
            "plannedAmount": 1500.00,
            "actualAmount": 1500.00,
            "remainingAmount": 0.00,
            "previousMonthRolloverAmount": 0.00,
        },
        "totalNonMonthlyExpenses": {
            "plannedAmount": 300.00,
            "actualAmount": 100.00,
            "remainingAmount": 200.00,
            "previousMonthRolloverAmount": 0.00,
        },
    }
]


def with_flex(base_response):
    """Copy the default fixture response, adding flex + totals selections."""
    enriched = json.loads(json.dumps(base_response))
    enriched["budgetData"]["monthlyAmountsForFlexExpense"] = FLEX_BLOCK
    enriched["budgetData"]["monthlyAmountsByCategoryGroup"] = GROUPS_BLOCK
    enriched["budgetData"]["totalsByMonth"] = TOTALS_BLOCK
    return enriched


def monarch_rejection():
    """The error Monarch actually returns for a refused field.

    Deliberately *not* standard GraphQL wording ("Cannot query field ..."):
    Monarch answers with a generic message, so detection keys on the exception
    type rather than the text. Using the real shape here keeps the test honest.
    """
    return TransportQueryError(
        {"message": "Something went wrong while processing: None on request_id: None."}
    )


def reject_flex_only(base_response):
    """side_effect that rejects the flex query but serves the narrow one."""

    def _side_effect(*args, **kwargs):
        if kwargs.get("operation") == "MCPBudgetDataFlex":
            raise monarch_rejection()
        return base_response

    return _side_effect


class TestGetBudgets:
    async def test_returns_formatted_category_rows(self):
        result = json.loads(await get_budgets())
        assert result["tool"] == "get_budgets"
        rows = result["data"]
        assert len(rows) == 2
        groceries = next(row for row in rows if row["id"] == "cat-1")
        assert groceries == {
            "id": "cat-1",
            "name": "Groceries",
            "planned": 500.00,
            "actual": 320.00,
            "remaining": 180.00,
            "set_aside": 0.00,
            "rollover": None,
            "rollover_type": None,
            "category_group": "Food",
            "category_type": "expense",
            "budget_variability": None,
            "month": "2026-03-01",
        }

    async def test_passes_explicit_date_params(self, mock_monarch_client):
        await get_budgets(start_date="2026-03-01", end_date="2026-03-31")
        _, kwargs = mock_monarch_client.gql_call.call_args
        assert kwargs["variables"] == {
            "startDate": "2026-03-01",
            "endDate": "2026-03-31",
        }

    async def test_defaults_to_current_month(self, mock_monarch_client):
        # Deliberately does NOT call current_month_range() to build the
        # expectation -- that would restate the implementation. Pin the shape
        # independently instead.
        await get_budgets()
        _, kwargs = mock_monarch_client.gql_call.call_args
        start = kwargs["variables"]["startDate"]
        end = kwargs["variables"]["endDate"]

        today = date.today()
        assert start == today.replace(day=1).isoformat()
        assert start.endswith("-01")
        last_day = calendar.monthrange(today.year, today.month)[1]
        assert end == today.replace(day=last_day).isoformat()
        assert start <= end

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.gql_call.side_effect = Exception("Budget error")

        result = json.loads(await get_budgets())

        # Must be a real error envelope. Asserting only `"get_budgets" in
        # result` would also match the SUCCESS payload, which carries
        # "tool": "get_budgets" -- so a regression rendering an outage as an
        # empty-but-successful budget would pass.
        assert result["error"] is True
        assert result["tool"] == "get_budgets"
        assert "data" not in result

    @pytest.mark.parametrize(
        "kwargs",
        [{"start_date": "2026-12-01"}, {"end_date": "2026-03-31"}],
    )
    async def test_rejects_a_half_specified_date_range(
        self, kwargs, mock_monarch_client
    ):
        # Filling the missing side from the current month can invert the range,
        # which returns nothing and reads as "this account has no budget".
        # Both directions matter: either one can produce start > end.
        result = json.loads(await get_budgets(**kwargs))

        assert result["error"] is True
        assert "together" in result["message"]
        # Rejected before any request went out.
        mock_monarch_client.gql_call.assert_not_awaited()

    async def test_get_budget_data_raises_on_a_half_specified_range(
        self, mock_monarch_client
    ):
        # Pin the helper's contract directly, not just the envelope the tool
        # wraps it in -- and pin the exception type.
        with pytest.raises(ValueError):
            await budgets_module.get_budget_data(
                mock_monarch_client, start_date="2026-12-01"
            )
        with pytest.raises(ValueError):
            await budgets_module.get_budget_data(
                mock_monarch_client, end_date="2026-12-31"
            )

    async def test_survives_explicit_nulls_in_the_response(
        self, mock_monarch_client
    ):
        # GraphQL returns explicit null for nullable fields; `.get(k, default)`
        # does not catch that, and one such null used to take out the tool.
        for response in (
            {"budgetData": None, "categoryGroups": None},
            {"budgetData": {"monthlyAmountsByCategory": None}, "categoryGroups": []},
            {
                "budgetData": {"monthlyAmountsByCategory": [None]},
                "categoryGroups": [None],
            },
            {
                "budgetData": {"monthlyAmountsByCategory": []},
                "categoryGroups": [{"id": "g", "name": "G", "categories": None}],
            },
        ):
            mock_monarch_client.gql_call.return_value = response
            result = json.loads(await get_budgets())
            assert result.get("error") is not True, response
            assert result["data"] == []


class TestFlexBucket:
    async def test_reports_flex_bucket_when_present(self, mock_monarch_client):
        mock_monarch_client.gql_call.return_value = with_flex(
            mock_monarch_client.gql_call.return_value
        )

        result = json.loads(await get_budgets())

        assert result["flex"] == {
            "status": "ok",
            "budget_variability": "flexible",
            "monthly": [
                {
                    "month": "2026-03-01",
                    "planned": 2000.00,
                    "actual": 1250.00,
                    "remaining": 750.00,
                    "rollover": 0.00,
                    "rollover_type": "monthly",
                }
            ],
        }
        assert result["totals"][0]["flexible"]["planned"] == 2000.00
        assert result["totals"][0]["fixed"]["remaining"] == 0.00
        assert result["totals"][0]["non_monthly"]["actual"] == 100.00

    async def test_reports_income_and_overall_expense_totals(
        self, mock_monarch_client
    ):
        mock_monarch_client.gql_call.return_value = with_flex(
            mock_monarch_client.gql_call.return_value
        )

        totals = json.loads(await get_budgets())["totals"][0]

        assert totals["income"] == {
            "planned": 8000.00,
            "actual": 8000.00,
            "remaining": 0.00,
            "rollover": 0.00,
        }
        assert totals["expenses"]["planned"] == 3800.00

    async def test_reports_group_level_budgets(self, mock_monarch_client):
        mock_monarch_client.gql_call.return_value = with_flex(
            mock_monarch_client.gql_call.return_value
        )

        groups = json.loads(await get_budgets())["groups"]

        assert groups == [
            {
                "id": "grp-1",
                "name": "Food",
                "planned": 700.00,
                "actual": 505.00,
                "remaining": 195.00,
                "rollover": 0.00,
                "rollover_type": "monthly",
                "category_type": "expense",
                "group_level_budgeting": None,
                "month": "2026-03-01",
            }
        ]

    async def test_groups_empty_when_query_ran_but_returned_none(self):
        # Default fixture omits the group selection: the query succeeded, so
        # [] (asked, none there) rather than null (could not ask).
        assert json.loads(await get_budgets())["groups"] == []

    async def test_group_rows_flag_authoritative_group_budgets(
        self, mock_monarch_client
    ):
        enriched = with_flex(mock_monarch_client.gql_call.return_value)
        enriched["categoryGroups"][0]["groupLevelBudgetingEnabled"] = True
        mock_monarch_client.gql_call.return_value = enriched

        groups = json.loads(await get_budgets())["groups"]

        # True => the group holds the budget; False/None => it is a roll-up of
        # its categories, and adding both double-counts.
        assert groups[0]["group_level_budgeting"] is True

    async def test_surfaces_rollover_so_remaining_reconciles(
        self, mock_monarch_client
    ):
        enriched = with_flex(mock_monarch_client.gql_call.return_value)
        amounts = enriched["budgetData"]["monthlyAmountsByCategory"][0][
            "monthlyAmounts"
        ][0]
        # A rollover category: planned - actual (180) != remaining (430).
        amounts["remainingAmount"] = 430.00
        amounts["previousMonthRolloverAmount"] = 250.00
        amounts["rolloverType"] = "monthly"
        mock_monarch_client.gql_call.return_value = enriched

        row = next(
            r for r in json.loads(await get_budgets())["data"] if r["id"] == "cat-1"
        )

        assert row["rollover"] == 250.00
        assert row["rollover_type"] == "monthly"
        # The gap is now explainable rather than looking like bad data.
        assert row["planned"] - row["actual"] + row["rollover"] == row["remaining"]

    async def test_reports_budget_system(self, mock_monarch_client):
        enriched = with_flex(mock_monarch_client.gql_call.return_value)
        enriched["budgetSystem"] = "fixed_and_flex"
        mock_monarch_client.gql_call.return_value = enriched

        assert json.loads(await get_budgets())["budget_system"] == "fixed_and_flex"

    async def test_budget_system_null_when_absent(self):
        assert json.loads(await get_budgets())["budget_system"] is None

    async def test_reports_goals_with_planned_and_actual_contributions(
        self, mock_monarch_client
    ):
        enriched = with_flex(mock_monarch_client.gql_call.return_value)
        enriched["goalsV2"] = [
            {
                "id": "goal-1",
                "name": "Emergency Fund",
                "priority": 1,
                "archivedAt": None,
                "completedAt": None,
                "plannedContributions": [
                    {"id": "pc-1", "month": "2026-03-01", "amount": 400.00}
                ],
                "monthlyContributionSummaries": [
                    {"month": "2026-03-01", "sum": 250.00}
                ],
            },
            {
                "id": "goal-2",
                "name": "Old Goal",
                "priority": 2,
                "archivedAt": "2026-01-01",
                "completedAt": None,
                "plannedContributions": [],
                "monthlyContributionSummaries": [],
            },
        ]
        mock_monarch_client.gql_call.return_value = enriched

        goals = json.loads(await get_budgets())["goals"]

        assert goals[0] == {
            "id": "goal-1",
            "name": "Emergency Fund",
            "priority": 1,
            "archived": False,
            "completed": False,
            "planned_contributions": [{"month": "2026-03-01", "amount": 400.00}],
            "actual_contributions": [{"month": "2026-03-01", "amount": 250.00}],
        }
        # Archived goals are surfaced but flagged, not silently dropped.
        assert goals[1]["archived"] is True

    async def test_flags_completed_goals(self, mock_monarch_client):
        enriched = with_flex(mock_monarch_client.gql_call.return_value)
        enriched["goalsV2"] = [
            {
                "id": "goal-3",
                "name": "Car Fund",
                "priority": 1,
                "archivedAt": None,
                "completedAt": "2026-02-01",
                "plannedContributions": [],
                "monthlyContributionSummaries": [],
            }
        ]
        mock_monarch_client.gql_call.return_value = enriched

        goal = json.loads(await get_budgets())["goals"][0]

        assert goal["completed"] is True
        assert goal["archived"] is False

    async def test_goals_empty_when_account_has_none(self):
        assert json.loads(await get_budgets())["goals"] == []

    async def test_everything_extended_is_null_on_the_fallback_path(
        self, mock_monarch_client
    ):
        # When the extended query is refused, null must mean "not available"
        # across the board -- never zero, and never "the account has none".
        base = mock_monarch_client.gql_call.return_value
        mock_monarch_client.gql_call.side_effect = reject_flex_only(base)

        result = json.loads(await get_budgets())

        assert result["flex"]["status"] == "unsupported"
        assert result["groups"] is None
        assert result["goals"] is None
        assert result["totals"] is None
        assert result["budget_system"] is None
        assert all(row["rollover"] is None for row in result["data"])

    async def test_prefers_the_flex_query(self, mock_monarch_client):
        await get_budgets()
        _, kwargs = mock_monarch_client.gql_call.call_args
        assert kwargs["operation"] == "MCPBudgetDataFlex"

    @staticmethod
    def _assert_operation_matches_document(call):
        """The operation name must be the one inside the document sent with it.

        The client forwards `operation` as operation_name, so a mismatched pair
        is rejected by the real server -- which _is_query_rejection reads as
        "no flex here", permanently degrading every account. Checking each
        document in isolation cannot catch a swap at the call site.
        """
        operation = call.kwargs["operation"]
        document = call.kwargs["graphql_query"]
        node = getattr(document, "document", document)
        assert f"query {operation}(" in node.loc.source.body, (
            f"operation {operation!r} was sent with a document that does not "
            f"declare it"
        )

    async def test_each_call_pairs_its_operation_with_the_right_document(
        self, mock_monarch_client
    ):
        base = mock_monarch_client.gql_call.return_value
        mock_monarch_client.gql_call.side_effect = reject_flex_only(base)

        # Exercises both the extended call and the narrow fallback.
        await get_budgets()

        calls = mock_monarch_client.gql_call.call_args_list
        assert len(calls) == 2
        for call in calls:
            self._assert_operation_matches_document(call)

    async def test_not_configured_when_account_has_no_flex_bucket(self):
        # The default fixture response omits the flex selections entirely.
        result = json.loads(await get_budgets())
        assert result["flex"]["status"] == "not_configured"
        assert result["flex"]["monthly"] == []
        assert result["totals"] == []
        # Category rows are unaffected.
        assert len(result["data"]) == 2

    async def test_falls_back_to_narrow_query_when_flex_rejected(
        self, mock_monarch_client
    ):
        base = mock_monarch_client.gql_call.return_value
        mock_monarch_client.gql_call.side_effect = reject_flex_only(base)

        result = json.loads(await get_budgets())

        assert result["flex"]["status"] == "unsupported"
        assert result["totals"] is None
        assert result["groups"] is None
        # The whole tool still works -- this is the no-regression guarantee.
        assert len(result["data"]) == 2
        operations = [
            call.kwargs["operation"]
            for call in mock_monarch_client.gql_call.call_args_list
        ]
        assert operations == ["MCPBudgetDataFlex", "MCPBudgetData"]

    async def test_a_transient_rejection_does_not_stick(self, mock_monarch_client):
        # gql raises TransportQueryError for ANY GraphQL `errors` array --
        # a rate limit, a resolver hiccup, a partial success. Caching
        # "unsupported" off one of those would strip flex, groups, goals,
        # totals and rollover from every later call for the whole process.
        base = mock_monarch_client.gql_call.return_value
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise monarch_rejection()
            if kwargs.get("operation") == "MCPBudgetDataFlex":
                return with_flex(base)
            return base

        mock_monarch_client.gql_call.side_effect = flaky

        first = json.loads(await get_budgets())
        second = json.loads(await get_budgets())

        assert first["flex"]["status"] == "unsupported"
        # Recovered rather than staying degraded.
        assert second["flex"]["status"] == "ok"

    async def test_retries_flex_on_every_call_when_rejected(
        self, mock_monarch_client
    ):
        base = mock_monarch_client.gql_call.return_value
        mock_monarch_client.gql_call.side_effect = reject_flex_only(base)

        await get_budgets()
        await get_budgets()

        operations = [
            call.kwargs["operation"]
            for call in mock_monarch_client.gql_call.call_args_list
        ]
        # Each call re-probes: one extra round-trip is the price of never
        # reporting a transient failure as a permanent account limitation.
        assert operations == [
            "MCPBudgetDataFlex",
            "MCPBudgetData",
            "MCPBudgetDataFlex",
            "MCPBudgetData",
        ]

    async def test_fallback_reuses_the_callers_date_range(
        self, mock_monarch_client
    ):
        base = mock_monarch_client.gql_call.return_value
        mock_monarch_client.gql_call.side_effect = reject_flex_only(base)

        await get_budgets(start_date="2026-03-01", end_date="2026-03-31")

        variables = [
            call.kwargs["variables"]
            for call in mock_monarch_client.gql_call.call_args_list
        ]
        assert variables[0] == variables[1] == {
            "startDate": "2026-03-01",
            "endDate": "2026-03-31",
        }

    async def test_auth_error_propagates_rather_than_degrading(
        self, mock_monarch_client
    ):
        mock_monarch_client.gql_call.side_effect = TransportServerError(
            "401 Unauthorized", code=401
        )

        result = json.loads(await get_budgets())

        # Surfaced as an error rather than silently degraded to a partial answer.
        assert result["error"] is True
        assert result["tool"] == "get_budgets"

    async def test_propagates_when_the_fallback_also_fails(
        self, mock_monarch_client
    ):
        # An expired session refuses BOTH queries. That is not evidence the
        # account lacks flex, so it must surface as an error.
        mock_monarch_client.gql_call.side_effect = monarch_rejection()

        result = json.loads(await get_budgets())

        assert result["error"] is True

    @pytest.mark.parametrize(
        "exc,expected",
        [
            # What Monarch really sends -- no GraphQL validation wording at all.
            (
                TransportQueryError(
                    {"message": "Something went wrong while processing: None"}
                ),
                True,
            ),
            # Other transports that do use standard wording still match.
            (Exception("Cannot query field 'totalsByMonth'"), True),
            (Exception("Unknown field monthlyAmountsForFlexExpense"), True),
            # Transport-level failures must not be read as "no flex bucket".
            (TransportServerError("401 Unauthorized", code=401), False),
            (Exception("Connection reset by peer"), False),
            (Exception(""), False),
        ],
    )
    def test_query_rejection_detection(self, exc, expected):
        assert budgets_module._is_query_rejection(exc) is expected


class TestSetFlexibleBudget:
    async def test_sets_amount(self, mock_monarch_client):
        mock_monarch_client.update_flexible_budget.return_value = {
            "updateOrCreateFlexBudgetItem": {"budgetItem": {"id": "flex-1"}}
        }

        result = json.loads(await set_flexible_budget(amount=2000, apply_to_future=True))

        assert result["success"] is True
        mock_monarch_client.update_flexible_budget.assert_awaited_once_with(
            amount=2000, start_date=None, apply_to_future=True
        )

    async def test_does_not_claim_success_without_confirmation(
        self, mock_monarch_client
    ):
        # A 200 whose payload node is null is not a successful write. Reporting
        # "$2000 set" off a no-op would have the model state a false number.
        mock_monarch_client.update_flexible_budget.return_value = {
            "updateOrCreateFlexBudgetItem": {"budgetItem": None}
        }

        result = json.loads(await set_flexible_budget(amount=2000))

        assert result["success"] is False
        assert "did not confirm" in result["error"]

    async def test_reports_missing_client_method(self, mock_monarch_client):
        del mock_monarch_client.update_flexible_budget

        result = json.loads(await set_flexible_budget(amount=100))

        assert result["success"] is False
        assert "update_flexible_budget" in result["error"]

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.update_flexible_budget.side_effect = Exception("boom")
        result = json.loads(await set_flexible_budget(amount=100))
        assert result["error"] is True
        assert result["tool"] == "set_flexible_budget"


class TestUpdateFlexRolloverSettings:
    @staticmethod
    def _on_flex_account(mock_monarch_client, system="fixed_and_flex"):
        enriched = with_flex(mock_monarch_client.gql_call.return_value)
        enriched["budgetSystem"] = system
        mock_monarch_client.gql_call.return_value = enriched

    async def test_passes_explicit_values_through(self, mock_monarch_client):
        self._on_flex_account(mock_monarch_client)
        mock_monarch_client.update_flex_rollover_settings.return_value = {
            "updateBudgetSettings": {"budgetRolloverPeriod": {"id": "rp-1"}}
        }

        result = json.loads(
            await update_flex_rollover_settings(
                rollover_start_month="2026-08-01", rollover_starting_balance=0
            )
        )

        assert result["success"] is True
        # budget_system MUST be forwarded: the client defaults it to
        # "fixed_and_flex" and writes it into the mutation input, so omitting
        # it would stamp that system onto whatever account this runs against.
        mock_monarch_client.update_flex_rollover_settings.assert_awaited_once_with(
            rollover_start_month="2026-08-01",
            rollover_starting_balance=0,
            rollover_enabled=True,
            budget_system="fixed_and_flex",
        )

    async def test_does_not_claim_success_without_confirmation(
        self, mock_monarch_client
    ):
        # The highest-stakes claim in this module: falsely confirming a
        # DESTRUCTIVE rollover reset is worse than falsely confirming an
        # amount, so the guard must not be silently removable.
        self._on_flex_account(mock_monarch_client)
        mock_monarch_client.update_flex_rollover_settings.return_value = {
            "updateBudgetSettings": {"budgetRolloverPeriod": None}
        }

        result = json.loads(
            await update_flex_rollover_settings(
                rollover_start_month="2026-08-01", rollover_starting_balance=0
            )
        )

        assert result["success"] is False
        assert "did not confirm" in result["error"]

    async def test_reports_the_month_monarch_applied(self, mock_monarch_client):
        self._on_flex_account(mock_monarch_client)
        mock_monarch_client.update_flex_rollover_settings.return_value = {
            "updateBudgetSettings": {
                "budgetRolloverPeriod": {"id": "rp-1", "startMonth": "2026-09-01"}
            }
        }

        result = json.loads(
            await update_flex_rollover_settings(
                rollover_start_month="2026-08-01", rollover_starting_balance=0
            )
        )

        # Echoing the requested month would misreport what actually happened.
        assert "2026-09-01" in result["message"]

    @pytest.mark.parametrize("bad", ["", "not-a-date", "2026-13-01"])
    async def test_rejects_a_malformed_start_month(self, bad, mock_monarch_client):
        # The client does `rollover_start_month or <current month>`, so an
        # empty string would become a silent full reset -- the exact thing the
        # required arguments exist to prevent.
        self._on_flex_account(mock_monarch_client)

        result = json.loads(
            await update_flex_rollover_settings(
                rollover_start_month=bad, rollover_starting_balance=0
            )
        )

        assert result["success"] is False
        mock_monarch_client.update_flex_rollover_settings.assert_not_awaited()

    async def test_refuses_on_a_non_flex_account(self, mock_monarch_client):
        # The mutation rewrites budgetSystem as a side effect. On an account
        # using another system that would migrate the whole budgeting mode --
        # far more than the rollover reset the user confirmed.
        self._on_flex_account(mock_monarch_client, system="category_groups")

        result = json.loads(
            await update_flex_rollover_settings(
                rollover_start_month="2026-08-01", rollover_starting_balance=0
            )
        )

        assert result["success"] is False
        assert "category_groups" in result["error"]
        mock_monarch_client.update_flex_rollover_settings.assert_not_awaited()

    async def test_refuses_when_budget_system_cannot_be_read(
        self, mock_monarch_client
    ):
        base = mock_monarch_client.gql_call.return_value
        mock_monarch_client.gql_call.side_effect = reject_flex_only(base)

        result = json.loads(
            await update_flex_rollover_settings(
                rollover_start_month="2026-08-01", rollover_starting_balance=0
            )
        )

        assert result["success"] is False
        mock_monarch_client.update_flex_rollover_settings.assert_not_awaited()

    def test_destructive_arguments_are_required(self):
        # The client defaults to "balance 0, current month" -- a silent full
        # reset. The tool must force the caller to state both explicitly.
        import inspect

        params = inspect.signature(update_flex_rollover_settings).parameters
        assert params["rollover_start_month"].default is inspect.Parameter.empty
        assert params["rollover_starting_balance"].default is inspect.Parameter.empty

    async def test_reports_missing_client_method(self, mock_monarch_client):
        self._on_flex_account(mock_monarch_client)
        del mock_monarch_client.update_flex_rollover_settings

        result = json.loads(
            await update_flex_rollover_settings(
                rollover_start_month="2026-08-01", rollover_starting_balance=0
            )
        )

        assert result["success"] is False
        assert "update_flex_rollover_settings" in result["error"]

    async def test_handles_api_error(self, mock_monarch_client):
        self._on_flex_account(mock_monarch_client)
        mock_monarch_client.update_flex_rollover_settings.side_effect = Exception(
            "boom"
        )

        result = json.loads(
            await update_flex_rollover_settings(
                rollover_start_month="2026-08-01", rollover_starting_balance=0
            )
        )

        assert result["error"] is True
        assert result["tool"] == "update_flex_rollover_settings"
