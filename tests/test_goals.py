"""Tests for goals MCP tools."""

import json
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from monarch_mcp_server.tools.goals import (
    get_goals, update_savings_goal, get_goal_contributions,
    set_goal_contribution, get_savings_goal_history, GOAL_HISTORY_QUERIES,
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
CREATED = "2026-04-01T00:00:00+00:00"

# A goal's true closing balance on each day it had events. It was created on
# Apr 1, and today's balance is 120.
HISTORY = [
    ("2026-04-01", 100.0),
    ("2026-04-02", 110.0),
    ("2026-04-04", 105.0),
    ("2026-04-19", 130.0),
    ("2026-05-03", 125.0),
    ("2026-05-10", 90.0),
    ("2026-06-01", 95.0),
    ("2026-06-15", 120.0),
]


def _history_goal(goal_id="sg_1", name="Rainy Day Fund", current=120.0,
                  created=CREATED, **overrides):
    return _goal(id=goal_id, name=name, currentBalance=current,
                 createdAt=created, **overrides)


def _period_key(d, granularity):
    if granularity == "monthly":
        return d.replace(day=1)
    if granularity == "annual":
        return d.replace(month=1, day=1)
    return d


def _history_client(goals, history_by_goal):
    """Serve the goal list and Monarch's history for each goal.

    history_by_goal maps a goal id to its true closing balances on days with
    events ([(date, balance)]), or to an Exception to raise. Like Monarch, a
    request with startDate returns the running change since that date, one
    row per period with events, dated at the period's start.
    """
    created = {g["id"]: g.get("createdAt") for g in goals}

    async def gql_call(operation, graphql_query, variables=None):
        if operation == "GetSavingsGoals":
            return {"savingsGoals": goals}
        period = next(g for g, q in GOAL_HISTORY_QUERIES.items()
                      if q is graphql_query)
        history = history_by_goal.get(variables["id"], [])
        if isinstance(history, Exception):
            raise history
        start = date.fromisoformat(variables["startDate"])
        if created[variables["id"]]:
            # The creation day carries migration bookkeeping, not real change.
            assert start > date.fromisoformat(created[variables["id"]][:10])
        days = [(date.fromisoformat(d), b) for d, b in history]
        before = [b for d, b in days if d < start]
        base = before[-1] if before else 0.0
        rows = {}
        for d, b in days:
            if d >= start:
                rows[_period_key(d, period)] = b - base
        return {"savingsGoal": {"goalEventAggregation": {"dataByPeriod": [
            {"date": d.isoformat(), "totalSavings": v}
            for d, v in sorted(rows.items())]}}}

    c = AsyncMock()
    c.gql_call.side_effect = gql_call
    return c


def _history_requests(client):
    """(grouping period, startDate) of each history request, in order."""
    return [
        (next(g for g, q in GOAL_HISTORY_QUERIES.items()
              if q is call.kwargs["graphql_query"]),
         call.kwargs["variables"]["startDate"])
        for call in client.gql_call.call_args_list
        if call.kwargs["operation"] == "GetSavingsGoalHistory"
    ]


def _balances(series):
    return [(p["date"], p["balance"]) for p in series]


class TestSavingsGoalHistory:
    """Tests for get_savings_goal_history tool."""

    @pytest.fixture(autouse=True)
    def _pin_today(self):
        with patch('monarch_mcp_server.tools.goals._today', return_value=TODAY):
            yield

    # -- day ------------------------------------------------------------------

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_day_default_starts_at_history_start(self, mock_get_client):
        c = _history_client([_history_goal()], {"sg_1": HISTORY})
        mock_get_client.return_value = c

        data = json.loads(await get_savings_goal_history(granularity="day"))

        goal = data["goals"][0]
        # 92 days back is Mar 16; the history starts at creation, Apr 1.
        assert data["start_date"] == "2026-04-01"
        assert data["end_date"] == "2026-06-15"
        assert _balances(goal["series"]) == HISTORY
        assert goal["start_balance"] == 100.0
        assert goal["start_balance_date"] == "2026-04-01"
        assert goal["end_balance"] == 120.0
        assert goal["change"] == 20.0 and goal["change_percent"] == 20.0
        assert data["total"] is None  # single goal: no combined total
        # One request, counting changes from the day after creation.
        assert _history_requests(c) == [("day", "2026-04-02")]
        variables = c.gql_call.call_args_list[1].kwargs["variables"]
        assert variables["today"] == "2026-06-15"

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_day_window_after_history_start(self, mock_get_client):
        c = _history_client([_history_goal()], {"sg_1": HISTORY})
        mock_get_client.return_value = c

        data = json.loads(await get_savings_goal_history(
            granularity="day", periods=30))

        goal = data["goals"][0]
        assert data["start_date"] == "2026-05-17"
        assert goal["start_balance"] == 90.0  # May 10's close, unchanged since
        assert goal["start_balance_date"] == "2026-05-16"
        assert _balances(goal["series"]) == [
            ("2026-06-01", 95.0), ("2026-06-15", 120.0)]
        assert goal["change"] == 30.0
        assert _history_requests(c) == [("day", "2026-05-17")]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_day_window_without_changes(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal(current=130.0)],
            {"sg_1": [("2026-04-01", 100.0), ("2026-04-19", 130.0)]})

        data = json.loads(await get_savings_goal_history(
            granularity="day", periods=10))

        goal = data["goals"][0]
        assert goal["series"] == []
        assert goal["start_balance"] == 130.0 and goal["change"] == 0.0

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_day_total_across_goals(self, mock_get_client):
        created = "2026-06-12T00:00:00+00:00"
        mock_get_client.return_value = _history_client(
            [_history_goal(current=11.0, created=created),
             _history_goal("sg_2", "Vacation", 22.0, created=created)],
            {"sg_1": [("2026-06-12", 9.0), ("2026-06-13", 10.0),
                      ("2026-06-15", 11.0)],
             "sg_2": [("2026-06-12", 19.0), ("2026-06-13", 20.0),
                      ("2026-06-14", 22.0)]})

        data = json.loads(await get_savings_goal_history(
            granularity="day", periods=3))

        total = data["total"]
        assert _balances(total["series"]) == [
            ("2026-06-13", 30.0), ("2026-06-14", 32.0), ("2026-06-15", 33.0)]
        assert total["start_balance"] == 28.0  # both goals' Jun 12 closes
        assert total["change"] == 5.0

    # -- monthly and annual ---------------------------------------------------

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_monthly_default(self, mock_get_client):
        c = _history_client([_history_goal()], {"sg_1": HISTORY})
        mock_get_client.return_value = c

        data = json.loads(await get_savings_goal_history())  # monthly default

        goal = data["goals"][0]
        assert data["granularity"] == "monthly"
        assert data["start_date"] == "2026-04-01"  # 60 months back is before it
        assert _balances(goal["series"]) == [
            ("2026-04-01", 130.0), ("2026-05-01", 90.0), ("2026-06-01", 120.0)]
        assert goal["start_balance"] == 100.0
        assert goal["start_balance_date"] == "2026-04-01"
        assert _history_requests(c) == [("monthly", "2026-04-02")]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_monthly_periods(self, mock_get_client):
        c = _history_client([_history_goal()], {"sg_1": HISTORY})
        mock_get_client.return_value = c

        data = json.loads(await get_savings_goal_history(periods=2))

        goal = data["goals"][0]
        assert data["start_date"] == "2026-05-01"
        assert goal["start_balance"] == 130.0  # April's close
        assert goal["start_balance_date"] == "2026-04-30"
        assert _balances(goal["series"]) == [
            ("2026-05-01", 90.0), ("2026-06-01", 120.0)]
        assert goal["change"] == -10.0
        assert _history_requests(c) == [("monthly", "2026-05-01")]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_month_without_events_carries_balance(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal()],
            {"sg_1": [("2026-04-01", 100.0), ("2026-04-19", 130.0),
                      ("2026-06-01", 95.0), ("2026-06-15", 120.0)]})

        data = json.loads(await get_savings_goal_history())

        assert _balances(data["goals"][0]["series"]) == [
            ("2026-04-01", 130.0), ("2026-05-01", 130.0), ("2026-06-01", 120.0)]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_annual_defaults_to_all_history(self, mock_get_client):
        c = _history_client(
            [_history_goal(current=70.0, created="2025-12-20T00:00:00+00:00")],
            {"sg_1": [("2025-12-20", 50.0), ("2025-12-28", 55.0),
                      ("2026-03-01", 70.0)]})
        mock_get_client.return_value = c

        data = json.loads(await get_savings_goal_history(granularity="annual"))

        goal = data["goals"][0]
        assert data["start_date"] == "2025-12-20"
        assert _balances(goal["series"]) == [
            ("2025-01-01", 55.0), ("2026-01-01", 70.0)]
        assert goal["start_balance"] == 50.0
        assert _history_requests(c) == [("annual", "2025-12-21")]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_annual_periods(self, mock_get_client):
        c = _history_client(
            [_history_goal(current=70.0, created="2025-12-20T00:00:00+00:00")],
            {"sg_1": [("2025-12-20", 50.0), ("2025-12-28", 55.0),
                      ("2026-03-01", 70.0)]})
        mock_get_client.return_value = c

        data = json.loads(await get_savings_goal_history(
            granularity="annual", periods=1))

        goal = data["goals"][0]
        assert data["start_date"] == "2026-01-01"
        assert _balances(goal["series"]) == [("2026-01-01", 70.0)]
        assert goal["start_balance"] == 55.0  # 2025's close
        assert goal["start_balance_date"] == "2025-12-31"
        assert _history_requests(c) == [("annual", "2026-01-01")]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_goal_created_after_window_start(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal(),
             _history_goal("sg_2", "Vacation", 40.0,
                           created="2026-05-01T00:00:00+00:00")],
            {"sg_1": HISTORY,
             "sg_2": [("2026-05-01", 30.0), ("2026-06-15", 40.0)]})

        data = json.loads(await get_savings_goal_history())

        late = next(g for g in data["goals"] if g["name"] == "Vacation")
        assert late["start_balance"] == 30.0
        assert late["start_balance_date"] == "2026-05-01"
        assert _balances(late["series"]) == [
            ("2026-05-01", 30.0), ("2026-06-01", 40.0)]
        # The total counts the later goal as zero before it was created.
        total = data["total"]
        assert total["start_balance"] == 100.0 and total["end_balance"] == 160.0
        assert _balances(total["series"]) == [
            ("2026-04-01", 130.0), ("2026-05-01", 120.0), ("2026-06-01", 160.0)]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_goal_created_today_needs_no_request(self, mock_get_client):
        c = _history_client(
            [_history_goal(current=50.0, created="2026-06-15T00:00:00+00:00")],
            {"sg_1": [("2026-06-15", 50.0)]})
        mock_get_client.return_value = c

        data = json.loads(await get_savings_goal_history(granularity="day"))

        goal = data["goals"][0]
        assert _balances(goal["series"]) == [("2026-06-15", 50.0)]
        assert goal["start_balance"] == 50.0 and goal["change"] == 0.0
        assert _history_requests(c) == []

    # -- shared behaviour -----------------------------------------------------

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_archived_at_is_not_a_filter(self, mock_get_client):
        """Same convention as get_goals: archived_at is never used to filter."""
        mock_get_client.return_value = _history_client(
            [_history_goal(archivedAt="2026-01-01T00:00:00+00:00")],
            {"sg_1": HISTORY})

        data = json.loads(await get_savings_goal_history())

        assert [g["goal_id"] for g in data["goals"]] == ["sg_1"]

    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_name_match_ignores_case_and_whitespace(self, mock_get_client):
        mock_get_client.return_value = _history_client(
            [_history_goal(name="College Fund "), _history_goal("sg_2", "Vacation")],
            {"sg_1": HISTORY, "sg_2": HISTORY})

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
        ({"granularity": "day", "periods": 93}, "periods must be from 1 to 92"),
        ({"periods": 0}, "periods must be"),
    ])
    @patch('monarch_mcp_server.tools.goals.get_monarch_client')
    async def test_bad_arguments(self, mock_get_client, kwargs, message):
        mock_get_client.return_value = _history_client(
            [_history_goal()], {"sg_1": HISTORY})

        data = json.loads(await get_savings_goal_history(**kwargs))

        assert data["success"] is False
        assert message in data["error"]
