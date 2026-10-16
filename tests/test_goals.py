"""Tests for goals MCP tools."""

import json
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from monarch_mcp_server.tools.goals import (
    get_goals, update_savings_goal, get_goal_contributions,
    set_goal_contribution, get_savings_goal_history,
)


def _goal(**overrides):
    goal = {
        "id": "sg_1",
        "name": "Rainy Day Fund",
        "type": "emergency_fund",
        "priority": 2,
        "progress": 0.24,
        "currentBalance": 1782.13,
        "targetAmount": 7500.0,
        "targetDate": "2026-12-31",
        "plannedMonthlyContribution": 100.0,
        "archivedAt": None,
        "completedAt": None,
    }
    goal.update(overrides)
    return goal


def _client(goals):
    c = AsyncMock()
    c.gql_call.return_value = {"savingsGoals": goals}
    return c


class TestGetGoals:
    """Tests for get_goals tool."""

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_reads_savings_goals_not_goalsv2(self, mock_get_client):
        """The tool must query savingsGoals.

        goalsV2 is the superseded collection and serves pre-migration numbers.
        """
        client = _client([_goal()])
        mock_get_client.return_value = client

        data = json.loads(await get_goals())

        assert data["count"] == 1
        assert data["goals"][0]["target_amount"] == 7500.0
        assert data["goals"][0]["target_date"] == "2026-12-31"
        assert data["goals"][0]["current_balance"] == 1782.13
        # progress arrives as a 0..1 fraction and is surfaced as a percentage
        assert data["goals"][0]["progress_percent"] == 24.0
        # The operation name is the accessible signal that the right
        # collection was queried; the query itself is a parsed DocumentNode.
        assert client.gql_call.call_args.kwargs["operation"] == "GetSavingsGoals"

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_goalsv2_payload_yields_nothing(self, mock_get_client):
        """Guards against silently reading the wrong collection."""
        c = AsyncMock()
        c.gql_call.return_value = {"goalsV2": [_goal()]}
        mock_get_client.return_value = c

        assert json.loads(await get_goals())["count"] == 0

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_archived_at_is_raw_and_never_filtered(self, mock_get_client):
        """archivedAt is passed through; nothing is hidden from the caller."""
        mock_get_client.return_value = _client([
            _goal(), _goal(id="sg_2", archivedAt="2026-01-01T00:00:00+00:00"),
        ])

        data = json.loads(await get_goals())

        assert data["count"] == 2
        assert "archived" not in data["goals"][0]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_error_handling(self, mock_get_client):
        """Transport failures are reported as tool errors."""
        c = AsyncMock()
        c.gql_call.side_effect = Exception("boom")
        mock_get_client.return_value = c

        data = json.loads(await get_goals())

        assert data["error"] is True
        assert data["tool"] == "get_goals"


def _update_client(errors=None, goal=None):
    c = AsyncMock()
    c.gql_call.return_value = {
        "updateSavingsGoal": {
            "savingsGoal": goal or {
                "id": "sg_1", "name": "Rainy Day Fund", "targetAmount": 7500.0,
                "targetDate": "2026-12-31", "plannedMonthlyContribution": 250.0,
                "priority": 2,
            },
            "errors": errors,
        }
    }
    return c


class TestUpdateSavingsGoal:
    """Tests for update_savings_goal tool."""

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_updates_target(self, mock_get_client):
        client = _update_client()
        mock_get_client.return_value = client

        data = json.loads(await update_savings_goal("sg_1", target_amount=8000.0))

        assert data["success"] is True
        sent = client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent == {"id": "sg_1", "targetAmount": 8000.0}

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_only_supplied_fields_are_sent(self, mock_get_client):
        """Omitted fields are preserved by Monarch, so they must not be sent.

        Sending an unset field as null would clear it.
        """
        client = _update_client()
        mock_get_client.return_value = client

        await update_savings_goal("sg_1", target_amount=8000.0)

        sent = client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent == {"id": "sg_1", "targetAmount": 8000.0}
        assert "targetDate" not in sent
        assert "name" not in sent

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_no_fields_is_rejected_without_a_call(self, mock_get_client):
        client = _update_client()
        mock_get_client.return_value = client

        data = json.loads(await update_savings_goal("sg_1"))

        assert data["success"] is False
        client.gql_call.assert_not_called()

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_reports_errors(self, mock_get_client):
        mock_get_client.return_value = _update_client(
            errors={"message": "bad", "code": None, "fieldErrors": None})

        data = json.loads(await update_savings_goal("sg_1", target_amount=1.0))

        assert data["success"] is False
        assert data["errors"]["message"] == "bad"

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_blank_error_payload_is_readable(self, mock_get_client):
        """An all-null PayloadError becomes a real message, not an empty dict."""
        mock_get_client.return_value = _update_client(
            errors={"message": None, "code": None, "fieldErrors": None})

        data = json.loads(await update_savings_goal("sg_1", target_amount=1.0))

        assert data["success"] is False
        assert data["errors"]["message"]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_error_handling(self, mock_get_client):
        c = AsyncMock()
        c.gql_call.side_effect = Exception("boom")
        mock_get_client.return_value = c

        data = json.loads(await update_savings_goal("sg_1", target_amount=1.0))

        assert data["error"] is True
        assert data["tool"] == "update_savings_goal"

    async def test_contribution_is_not_settable(self):
        """The monthly contribution must not be exposed.

        Monarch accepts plannedMonthlyContribution on this input and reports
        success, but the value does not persist -- verified against the live
        API. Accepting the argument would report a change that never happened.
        """
        import inspect
        from monarch_mcp_server.tools.goals import update_savings_goal as fn
        params = inspect.signature(fn).parameters
        assert "planned_monthly_contribution" not in params

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_type_and_sinking_fund_are_settable(self, mock_get_client):
        """Both persist on the live API, so both are exposed."""
        client = _update_client()
        mock_get_client.return_value = client

        await update_savings_goal("sg_1", goal_type="sinking_fund",
                                  is_sinking_fund=True)

        sent = client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent == {"id": "sg_1", "type": "sinking_fund",
                        "isSinkingFund": True}

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_false_is_honoured_not_treated_as_unset(self, mock_get_client):
        """is_sinking_fund=False must be sent, not dropped as falsy."""
        client = _update_client()
        mock_get_client.return_value = client

        await update_savings_goal("sg_1", is_sinking_fund=False)

        sent = client.gql_call.call_args.kwargs["variables"]["input"]
        assert sent == {"id": "sg_1", "isSinkingFund": False}


class TestGoalContributions:
    """Tests for goal contribution tools."""

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_get_contributions_breaks_down_by_account(self, mock_get_client):
        c = AsyncMock()
        c.gql_call.return_value = {"savingsGoal": {
            "id": "sg_1", "name": "Rainy Day Fund",
            "monthlyBudgetAmounts": [{
                "month": "2026-08-01", "totalPlannedAmount": 1143.0,
                "totalActualAmount": 0.0, "totalRemainingAmount": 1143.0,
                "accountBreakdown": [
                    {"account": {"id": "a1", "displayName": "Savings"},
                     "plannedAmount": 143.0, "actualAmount": 0.0,
                     "remainingAmount": 143.0},
                ],
            }],
        }}
        mock_get_client.return_value = c

        data = json.loads(await get_goal_contributions("sg_1", month="2026-08"))

        assert data["months"][0]["accounts"][0]["planned"] == 143.0
        sent = c.gql_call.call_args.kwargs["variables"]
        assert sent["startMonth"] == "2026-08-01"
        assert sent["endMonth"] == "2026-08-31"

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_set_contribution_sends_only_that_account(self, mock_get_client):
        """Unmentioned accounts are preserved by Monarch, so only one is sent.

        Resending the whole allocation risks duplicate-account errors and would
        overwrite concurrent edits to other accounts.
        """
        c = AsyncMock()
        c.gql_call.return_value = {"updateSavingsGoal": {
            "savingsGoal": {"id": "sg_1"}, "errors": None}}
        mock_get_client.return_value = c

        data = json.loads(await set_goal_contribution("sg_1", "a1", 175.0))

        assert data["success"] is True
        sent = c.gql_call.call_args.kwargs["variables"]["input"]
        assert sent == {"id": "sg_1",
                        "accountBudgetAmounts": [{"accountId": "a1", "amount": 175.0}]}

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_set_contribution_zero_is_sent(self, mock_get_client):
        """0 removes the contribution and must not be dropped as falsy."""
        c = AsyncMock()
        c.gql_call.return_value = {"updateSavingsGoal": {
            "savingsGoal": {"id": "sg_1"}, "errors": None}}
        mock_get_client.return_value = c

        await set_goal_contribution("sg_1", "a1", 0.0)

        sent = c.gql_call.call_args.kwargs["variables"]["input"]
        assert sent["accountBudgetAmounts"][0]["amount"] == 0.0

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_set_contribution_reports_errors(self, mock_get_client):
        c = AsyncMock()
        c.gql_call.return_value = {"updateSavingsGoal": {
            "savingsGoal": None,
            "errors": {"message": "Duplicate account_id", "fieldErrors": None}}}
        mock_get_client.return_value = c

        data = json.loads(await set_goal_contribution("sg_1", "a1", 1.0))

        assert data["success"] is False
        assert "Duplicate" in data["errors"]["message"]


TODAY = date(2026, 6, 15)
CREATED = "2026-03-02T00:00:00+00:00"

# A goal created Mar 2 with events on scattered days, ending at today's balance.
HISTORY_ROWS = [
    ("2026-03-02", 100.0),
    ("2026-03-03", 110.0),
    ("2026-03-05", 105.0),
    ("2026-03-20", 130.0),
    ("2026-04-03", 125.0),
    ("2026-04-10", 90.0),
    ("2026-05-02", 95.0),
    ("2026-06-15", 120.0),
]


def _history_goal(goal_id="sg_1", name="Rainy Day Fund", current=120.0,
                  created=CREATED, **overrides):
    return _goal(id=goal_id, name=name, currentBalance=current,
                 createdAt=created, **overrides)


def _history_client(goals, rows_by_goal):
    """Serve the goal list and each goal's history rows.

    rows_by_goal: {goal_id: [(date, total) or (date, total, previous_total)]},
    or an Exception to raise for that goal.
    """
    async def gql_call(operation, graphql_query, variables=None):
        if operation == "GetSavingsGoals":
            return {"savingsGoals": goals}
        rows = rows_by_goal.get(variables["id"], [])
        if isinstance(rows, Exception):
            raise rows
        return {"savingsGoal": {"goalEventAggregation": {"dataByPeriod": [
            {"date": r[0], "totalSavings": r[1],
             "previousTotalSavings": r[2] if len(r) > 2 else None}
            for r in rows]}}}

    c = AsyncMock()
    c.gql_call.side_effect = gql_call
    return c


class TestSavingsGoalHistory:
    """Tests for get_savings_goal_history tool."""

    @pytest.fixture(autouse=True)
    def _pin_today(self):
        with patch('monarch_mcp_server.tools.goals._today', return_value=TODAY):
            yield

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_day_series_uses_native_rows(self, mock_get_client):
        c = _history_client([_history_goal()], {"sg_1": HISTORY_ROWS})
        mock_get_client.return_value = c

        data = json.loads(await get_savings_goal_history(granularity="day"))

        goal = data["goals"][0]
        assert data["start_date"] == "2026-03-02"  # default: history start
        assert [p["date"] for p in goal["series"]] == [d for d, _ in HISTORY_ROWS]
        assert goal["start_balance"] == 100.0 and goal["end_balance"] == 120.0
        assert goal["change"] == 20.0 and goal["change_percent"] == 20.0
        assert goal["reconciliation_diff"] == 0.0
        assert goal["warnings"] == [] and data["warnings"] == []
        assert data["total"] is None  # single goal: no combined total
        history_call = c.gql_call.call_args_list[1].kwargs
        assert history_call["operation"] == "GetSavingsGoalHistory"
        assert history_call["variables"] == {"id": "sg_1", "today": "2026-06-15"}

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_start_between_rows_carries_last_balance(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal()], {"sg_1": HISTORY_ROWS})

        data = json.loads(await get_savings_goal_history(
            start_date="2026-03-04", granularity="day"))

        goal = data["goals"][0]
        assert goal["start_balance"] == 110.0  # Mar 3's close
        assert goal["series"][0]["date"] == "2026-03-05"

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_start_before_history_is_moved_up(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal()], {"sg_1": HISTORY_ROWS})

        data = json.loads(await get_savings_goal_history(start_date="2026-01-01"))

        assert data["start_date"] == "2026-03-02"
        assert data["goals"][0]["start_balance"] == 100.0
        assert "requested start 2026-01-01 was moved" in data["warnings"][0]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_end_before_history_is_an_error(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal()], {"sg_1": HISTORY_ROWS})

        data = json.loads(await get_savings_goal_history(
            start_date="2026-01-01", end_date="2026-02-28"))

        assert data["success"] is False
        assert "is after end_date 2026-02-28" in data["error"]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_monthly_rows_are_dated_at_period_start(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal()], {"sg_1": HISTORY_ROWS})

        data = json.loads(await get_savings_goal_history())  # monthly default

        assert data["granularity"] == "monthly"
        assert data["goals"][0]["series"] == [
            {"date": "2026-03-01", "balance": 130.0},
            {"date": "2026-04-01", "balance": 90.0},
            {"date": "2026-05-01", "balance": 95.0},
            {"date": "2026-06-01", "balance": 120.0},
        ]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_last_period_stops_at_end_date(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal()], {"sg_1": HISTORY_ROWS})

        data = json.loads(await get_savings_goal_history(end_date="2026-04-05"))

        goal = data["goals"][0]
        assert goal["series"] == [
            {"date": "2026-03-01", "balance": 130.0},
            {"date": "2026-04-01", "balance": 125.0},  # Apr 5, not Apr 30
        ]
        assert goal["end_balance"] == 125.0
        # Only checked against the reported balance when the end is today.
        assert goal["reconciliation_diff"] is None

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_annual(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal(current=70.0, created=None)],
            {"sg_1": [("2025-12-20", 50.0), ("2026-03-01", 70.0)]})

        data = json.loads(await get_savings_goal_history(granularity="annual"))

        assert data["goals"][0]["series"] == [
            {"date": "2025-01-01", "balance": 50.0},
            {"date": "2026-01-01", "balance": 70.0},
        ]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_opening_balance_when_creation_day_has_no_events(
            self, mock_get_client):
        # First event Mar 11: that row's opening balance is the balance
        # from creation (Mar 2) until then.
        mock_get_client.return_value = _history_client(
            [_history_goal()],
            {"sg_1": [("2026-03-11", 102.5, 102.0), ("2026-06-15", 120.0, 102.5)]})

        data = json.loads(await get_savings_goal_history(granularity="day"))

        goal = data["goals"][0]
        assert data["start_date"] == "2026-03-02"
        assert goal["start_balance"] == 102.0
        assert goal["series"][0] == {"date": "2026-03-02", "balance": 102.0}
        assert goal["warnings"] == []

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_creation_day_opening_figure_is_ignored(self, mock_get_client):
        # On the creation day itself, previousTotalSavings is pre-migration
        # bookkeeping, not a balance.
        mock_get_client.return_value = _history_client(
            [_history_goal()],
            {"sg_1": [("2026-03-02", 100.0, 3.0), ("2026-06-15", 120.0, 100.0)]})

        data = json.loads(await get_savings_goal_history(granularity="day"))

        goal = data["goals"][0]
        assert goal["start_balance"] == 100.0
        assert [p["date"] for p in goal["series"]] == ["2026-03-02", "2026-06-15"]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_goal_starting_later_has_no_early_balance(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal(),
             _history_goal("sg_2", "Vacation", 40.0,
                           created="2026-04-01T00:00:00+00:00")],
            {"sg_1": HISTORY_ROWS,
             "sg_2": [("2026-04-01", 30.0), ("2026-06-15", 40.0)]})

        data = json.loads(await get_savings_goal_history(granularity="day"))

        late = next(g for g in data["goals"] if g["name"] == "Vacation")
        assert data["start_date"] == "2026-03-02"
        assert late["start_balance"] is None and late["change"] is None
        assert any("starts 2026-04-01" in w for w in late["warnings"])
        # The total counts the later goal from when its history begins.
        assert data["total"]["start_balance"] == 100.0
        assert data["total"]["end_balance"] == 160.0

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_goal_without_history(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal(), _history_goal("sg_2", "New Car", 0.0)],
            {"sg_1": HISTORY_ROWS, "sg_2": []})

        data = json.loads(await get_savings_goal_history())

        new = next(g for g in data["goals"] if g["name"] == "New Car")
        assert new["series"] == [] and new["end_balance"] is None
        assert new["warnings"] == ["Monarch has no history for this goal yet."]
        assert data["total"]["end_balance"] == 120.0

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_archived_at_is_not_a_filter(self, mock_get_client):
        """Same convention as get_goals: archived_at is never used to filter."""
        mock_get_client.return_value = _history_client(
            [_history_goal(archivedAt="2026-01-01T00:00:00+00:00")],
            {"sg_1": HISTORY_ROWS})

        data = json.loads(await get_savings_goal_history())

        assert [g["goal_id"] for g in data["goals"]] == ["sg_1"]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_total_across_goals(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal(current=11.0, created=None),
             _history_goal("sg_2", "Vacation", 22.0, created=None)],
            {"sg_1": [("2026-06-13", 10.0), ("2026-06-15", 11.0)],
             "sg_2": [("2026-06-13", 20.0), ("2026-06-14", 22.0)]})

        data = json.loads(await get_savings_goal_history(granularity="day"))

        total = data["total"]
        assert total["series"] == [
            {"date": "2026-06-13", "balance": 30.0},
            {"date": "2026-06-14", "balance": 32.0},
            {"date": "2026-06-15", "balance": 33.0},
        ]
        assert total["change"] == 3.0

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_reconciliation_flags_drift(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal(current=125.0)], {"sg_1": HISTORY_ROWS})

        data = json.loads(await get_savings_goal_history())

        assert data["goals"][0]["reconciliation_diff"] == -5.0

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_name_match_ignores_case_and_whitespace(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal(name="College Fund "), _history_goal("sg_2", "Vacation")],
            {"sg_1": HISTORY_ROWS, "sg_2": HISTORY_ROWS})

        data = json.loads(await get_savings_goal_history(goal_name="  college fund"))

        assert [g["goal_id"] for g in data["goals"]] == ["sg_1"]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_unknown_goal_lists_available(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal(), _history_goal("sg_2", "Vacation")], {})

        data = json.loads(await get_savings_goal_history(goal_name="Nope"))

        assert data["success"] is False
        assert data["available_goals"] == ["Rainy Day Fund", "Vacation"]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_history_failure_is_an_error(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal()], {"sg_1": RuntimeError("boom")})

        data = json.loads(await get_savings_goal_history())

        assert data["error"] is True
        assert data["tool"] == "get_savings_goal_history"
        assert "boom" in data["message"]

    @pytest.mark.parametrize("kwargs, message", [
        # Only Monarch's native grouping periods are accepted.
        ({"granularity": "weekly"},
         "granularity must be one of day, monthly, annual"),
        ({"granularity": "daily"}, "granularity must be one of"),
        ({"start_date": "2026-13-01"}, "Invalid date"),
        ({"start_date": "2026-06-20", "end_date": "2026-06-10"},
         "is after end_date"),
    ])
    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_bad_arguments(self, mock_get_client, kwargs, message):
        mock_get_client.return_value = _history_client(
            [_history_goal()], {"sg_1": HISTORY_ROWS})

        data = json.loads(await get_savings_goal_history(**kwargs))

        assert data["success"] is False
        assert message in data["error"]
