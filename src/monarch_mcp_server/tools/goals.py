"""Goals tools with GraphQL queries."""

from __future__ import annotations

import asyncio
import calendar
import logging
from bisect import bisect_right
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from gql import gql

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import (
    json_error,
    json_rejected,
    json_success,
    payload_errors,
)

logger = logging.getLogger(__name__)

# Monarch disables GraphQL introspection for non-admin users and masks unknown
# field errors as a generic "Something went wrong", so this selection set was
# established field-by-field against the live API, then reconciled against the
# web app's own GoalSummaryFields fragment. Note the balance field is
# `currentBalance`, not `currentAmount`, and progress is served directly as a
# 0..1 fraction rather than being computed client-side.
#
# There are TWO goal collections. `savingsGoals` is the current one and matches
# what the app shows. `goalsV2` is the superseded collection: on a real account
# every goalsV2 record carried an identical archivedAt to the microsecond (the
# migration timestamp) while the same goals showed as active in the app, and
# their targets were stale -- a goal reading 10000 in goalsV2 was 7500 in
# savingsGoals. Query savingsGoals; goalsV2 will quietly serve pre-migration
# numbers.
#
# The two also have separate ids for the same goal, which is why a transaction
# rule has both linkGoalAction and linkSavingsGoalAction and they are NOT
# interchangeable.
GET_GOALS_QUERY = gql("""
query GetSavingsGoals {
  savingsGoals {
    id
    name
    type
    status
    priority
    progress
    currentBalance
    targetAmount
    targetDate
    plannedMonthlyContribution
    estimatedMonthsUntilCompletion
    forecastedCompletionDate
    isSinkingFund
    createdAt
    archivedAt
    completedAt
    __typename
  }
}
""")


@mcp.tool()
async def get_goals() -> str:
    """
    List Monarch savings and debt-paydown goals.

    Use this to find a goal id for `link_goal_id` on a transaction rule, or to
    report on goal progress.

    `name` is user-editable while `default_name` is the template the goal was
    created from -- a goal renamed "End Game" still reports default_name
    "Retirement" and objective "retirement", which is the reliable thing to
    match on programmatically.

    Every goal is returned. `archived_at` is passed through raw and should not
    be read as the app's archive state -- see the comment above the query.

    Returns:
        JSON list of goals with progress and the accounts allocated to each.
    """
    try:
        client = await get_monarch_client()
        result = await client.gql_call(
            operation="GetSavingsGoals", graphql_query=GET_GOALS_QUERY, variables={}
        )

        goals = []
        for g in result.get("savingsGoals") or []:
            goals.append({
                "id": g.get("id"),
                "name": g.get("name"),
                "type": g.get("type"),
                "status": g.get("status"),
                "priority": g.get("priority"),
                "current_balance": g.get("currentBalance"),
                "progress_percent": (
                    round(g["progress"] * 100, 1)
                    if isinstance(g.get("progress"), (int, float)) else None
                ),
                "target_amount": g.get("targetAmount"),
                "target_date": g.get("targetDate"),
                "planned_monthly_contribution": g.get("plannedMonthlyContribution"),
                "estimated_months_until_completion": g.get(
                    "estimatedMonthsUntilCompletion"),
                "forecasted_completion_date": g.get("forecastedCompletionDate"),
                "is_sinking_fund": g.get("isSinkingFund"),
                "created_at": g.get("createdAt"),
                "archived_at": g.get("archivedAt"),
                "completed_at": g.get("completedAt"),
            })

        return json_success({
            "count": len(goals),
            "note": (
                "Goals track allocated ACCOUNT BALANCES, not categorized "
                "transactions. A transaction rule only touches a goal via "
                "link_goal_id, which Monarch requires account_ids alongside. "
                "`archived_at` is raw and does not match the app's archive "
                "state -- do not filter on it."
            ),
            "goals": goals,
        })
    except Exception as e:
        return json_error("get_goals", e)


UPDATE_SAVINGS_GOAL_MUTATION = gql("""
mutation Common_UpdateSavingsGoal($input: UpdateSavingsGoalInput!) {
  updateSavingsGoal(input: $input) {
    savingsGoal {
      id
      name
      targetAmount
      targetDate
      plannedMonthlyContribution
      priority
      __typename
    }
    errors {
      message
      code
      fieldErrors {
        field
        messages
        __typename
      }
      __typename
    }
    __typename
  }
}
""")


@mcp.tool()
async def update_savings_goal(
    goal_id: str,
    target_amount: Optional[float] = None,
    target_date: Optional[str] = None,
    name: Optional[str] = None,
    priority: Optional[int] = None,
    goal_type: Optional[str] = None,
    is_sinking_fund: Optional[bool] = None,
) -> str:
    """
    Update a savings goal's target or monthly contribution.

    Unlike the transaction-rule mutation, this is a genuine partial update:
    omitted fields are preserved, verified against the live API. Pass only what
    you want to change.

    NOTE: the monthly contribution is not set here. `plannedMonthlyContribution`
    is a read-only rollup -- the input accepts it and reports success, but the
    value never persists. Contributions are budgeted per funding account; use
    `set_goal_contribution`.

    Args:
        goal_id: Goal to update. Use get_goals -- and note these are
            `savingsGoals` ids, which differ from the legacy goalsV2 ids.
        target_amount: Total amount the goal is aiming at.
        target_date: Target completion date, "YYYY-MM-DD". Optional on a goal.
        name: Rename the goal.
        priority: Ordering among goals, lower first.
        goal_type: Goal category, e.g. "emergency_fund", "retirement",
            "sinking_fund". Changes how Monarch treats the goal, so it is not
            merely a label.
        is_sinking_fund: Whether the goal is spent down and refilled rather
            than accumulated.

    Not exposed: the image fields (`imageStorageProvider` /
    `imageStorageProviderId`) are settable but purely cosmetic. Everything else
    on the input either is not accepted (`archivedAt`, `completedAt`, `icon`,
    `color`, `accountIds`) or does not persist (see the note above).

    Returns:
        JSON with the goal's state after the update.
    """
    try:
        changes: Dict[str, Any] = {}
        if target_amount is not None:
            changes["targetAmount"] = target_amount
        if target_date is not None:
            changes["targetDate"] = target_date
        if name is not None:
            changes["name"] = name
        if priority is not None:
            changes["priority"] = priority
        if goal_type is not None:
            changes["type"] = goal_type
        if is_sinking_fund is not None:
            changes["isSinkingFund"] = is_sinking_fund

        if not changes:
            return json_success({
                "success": False,
                "message": "Nothing to update -- pass at least one field.",
            })

        client = await get_monarch_client()
        result = await client.gql_call(
            operation="Common_UpdateSavingsGoal",
            graphql_query=UPDATE_SAVINGS_GOAL_MUTATION,
            variables={"input": {"id": goal_id, **changes}},
        )

        errors = payload_errors(result, "updateSavingsGoal")
        if errors:
            return json_rejected("update_savings_goal", errors)

        payload = result.get("updateSavingsGoal") or {}

        goal = payload.get("savingsGoal") or {}
        return json_success({
            "success": True,
            "goal_id": goal_id,
            "changed": sorted(changes),
            "goal": {
                "id": goal.get("id"),
                "name": goal.get("name"),
                "target_amount": goal.get("targetAmount"),
                "target_date": goal.get("targetDate"),
                "planned_monthly_contribution": goal.get(
                    "plannedMonthlyContribution"),
                "priority": goal.get("priority"),
            },
        })
    except Exception as e:
        return json_error("update_savings_goal", e)


GOAL_CONTRIBUTIONS_QUERY = gql("""
query GetSavingsGoalContributions($id: ID!, $startMonth: Date!, $endMonth: Date!) {
  savingsGoal(id: $id) {
    id
    name
    monthlyBudgetAmounts(startMonth: $startMonth, endMonth: $endMonth) {
      month
      totalPlannedAmount
      totalActualAmount
      totalRemainingAmount
      accountBreakdown {
        account {
          id
          displayName
          __typename
        }
        plannedAmount
        actualAmount
        remainingAmount
        __typename
      }
      __typename
    }
    __typename
  }
}
""")


def _month_bounds(month: Optional[str]) -> Tuple[str, str]:
    """(first, last) day of *month* ("YYYY-MM-DD" or "YYYY-MM"), default current."""
    if month:
        parts = month.split("-")
        year, mon = int(parts[0]), int(parts[1])
    else:
        today = date.today()
        year, mon = today.year, today.month
    last = calendar.monthrange(year, mon)[1]
    return f"{year:04d}-{mon:02d}-01", f"{year:04d}-{mon:02d}-{last:02d}"


@mcp.tool()
async def get_goal_contributions(goal_id: str, month: Optional[str] = None) -> str:
    """
    Show a goal's budgeted contributions, broken down by funding account.

    A goal's contribution is not one number -- it is budgeted per account, and
    the goal-level `plannedMonthlyContribution` is a rollup. Use this to see the
    per-account amounts and to get the `account_id` values that
    `set_goal_contribution` needs.

    Args:
        goal_id: A `savingsGoals` id (see get_goals).
        month: "YYYY-MM" or "YYYY-MM-DD". Defaults to the current month.

    Returns:
        JSON with the month's planned/actual totals and the per-account split.
    """
    try:
        start, end = _month_bounds(month)
        client = await get_monarch_client()
        result = await client.gql_call(
            operation="GetSavingsGoalContributions",
            graphql_query=GOAL_CONTRIBUTIONS_QUERY,
            variables={"id": goal_id, "startMonth": start, "endMonth": end},
        )
        goal = result.get("savingsGoal") or {}
        months = []
        for m in goal.get("monthlyBudgetAmounts") or []:
            months.append({
                "month": m.get("month"),
                "total_planned": m.get("totalPlannedAmount"),
                "total_actual": m.get("totalActualAmount"),
                "total_remaining": m.get("totalRemainingAmount"),
                "accounts": [
                    {
                        "account_id": (a.get("account") or {}).get("id"),
                        "name": (a.get("account") or {}).get("displayName"),
                        "planned": a.get("plannedAmount"),
                        "actual": a.get("actualAmount"),
                        "remaining": a.get("remainingAmount"),
                    }
                    for a in (m.get("accountBreakdown") or [])
                ],
            })
        return json_success({
            "goal_id": goal.get("id"),
            "name": goal.get("name"),
            "months": months,
        })
    except Exception as e:
        return json_error("get_goal_contributions", e)


@mcp.tool()
async def set_goal_contribution(
    goal_id: str, account_id: str, amount: float
) -> str:
    """
    Set the budgeted monthly contribution to a goal from one funding account.

    Contributions are budgeted per account, not per goal, which is why the
    goal-level `plannedMonthlyContribution` cannot be written to directly.

    Accounts you do not mention are left alone -- verified against the live API,
    so there is no need to resend the whole allocation. Use
    `get_goal_contributions` to find `account_id` values.

    Args:
        goal_id: A `savingsGoals` id (see get_goals).
        account_id: The funding account to budget from.
        amount: Monthly amount. 0 removes this account's contribution.
    """
    try:
        client = await get_monarch_client()
        result = await client.gql_call(
            operation="Common_UpdateSavingsGoal",
            graphql_query=UPDATE_SAVINGS_GOAL_MUTATION,
            variables={"input": {
                "id": goal_id,
                "accountBudgetAmounts": [
                    {"accountId": account_id, "amount": amount}
                ],
            }},
        )
        errors = payload_errors(result, "updateSavingsGoal")
        if errors:
            return json_rejected("set_goal_contribution", errors)

        payload = result.get("updateSavingsGoal") or {}
        return json_success({
            "success": True,
            "goal_id": goal_id,
            "account_id": account_id,
            "amount": amount,
            "note": "Other funding accounts for this goal were left unchanged.",
        })
    except Exception as e:
        return json_error("set_goal_contribution", e)


# The query behind the goal page's timeline: Monarch's own record of a goal's
# balance. Rows exist only on days with goal events, and the series begins when
# the household moved to the current goals system. `today` does not bound the
# series, so callers trim to their end date.
#
# We always ask for `day` and group months and years ourselves. Native `monthly`
# gives the same end-of-period balances, but its first month also folds in
# migration events from before the daily series starts.
GOAL_HISTORY_QUERY = gql("""
query GetSavingsGoalHistory($id: ID!, $today: Date!) {
  savingsGoal(id: $id) {
    id
    goalEventAggregation(
      today: $today
      groupingPeriod: day
      excludeEventsNotInBudget: false
      groupEventsAfterToday: false
    ) {
      dataByPeriod {
        date
        totalSavings
        previousTotalSavings
        __typename
      }
      __typename
    }
    __typename
  }
}
""")

# The grouping periods Monarch's goal aggregation supports.
HISTORY_GRANULARITIES = ("day", "monthly", "annual")

# Parallel history requests; enough to be quick without hammering the API.
_HISTORY_CONCURRENCY = 5

_Points = List[Tuple[date, float]]


def _today() -> date:
    """Indirection so tests can pin "today"."""
    return date.today()


def _balance_at(points: _Points, d: date) -> Optional[float]:
    """Balance at the close of day `d`: the last point on or before it."""
    i = bisect_right(points, (d, float("inf"))) - 1
    return points[i][1] if i >= 0 else None


def _period_start(d: date, granularity: str) -> date:
    if granularity == "monthly":
        return d.replace(day=1)
    if granularity == "annual":
        return d.replace(month=1, day=1)
    return d


def _period_end(start: date, granularity: str) -> date:
    if granularity == "monthly":
        nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return nxt - timedelta(days=1)
    if granularity == "annual":
        return start.replace(month=12, day=31)
    return start


def _build_series(
    points: _Points, start: date, end: date, granularity: str
) -> List[Dict[str, Any]]:
    """Shape points into Monarch's period convention.

    `day`: only days whose balance has a point (days in between are unchanged).
    `monthly`/`annual`: one row per period, dated at the period's start, with
    the balance at the period's close (or at `end` for the last period).
    """
    if granularity == "day":
        return [
            {"date": d.isoformat(), "balance": round(v, 2)}
            for d, v in points
            if start <= d <= end
        ]

    series: List[Dict[str, Any]] = []
    period = _period_start(start, granularity)
    while period <= end:
        close = _period_end(period, granularity)
        balance = _balance_at(points, min(close, end))
        if balance is not None:
            series.append({"date": period.isoformat(), "balance": round(balance, 2)})
        period = close + timedelta(days=1)
    return series


def _summarize(
    start_balance: Optional[float], end_balance: Optional[float]
) -> Dict[str, Any]:
    if start_balance is None or end_balance is None:
        return {
            "start_balance": start_balance,
            "end_balance": end_balance,
            "change": None,
            "change_percent": None,
        }
    change = round(end_balance - start_balance, 2)
    return {
        "start_balance": round(start_balance, 2),
        "end_balance": round(end_balance, 2),
        "change": change,
        "change_percent": (
            round(change / start_balance * 100, 2) if start_balance else None
        ),
    }


async def _history_points(client: Any, goal: Dict[str, Any], today: date) -> _Points:
    result = await client.gql_call(
        operation="GetSavingsGoalHistory",
        graphql_query=GOAL_HISTORY_QUERY,
        variables={"id": goal["id"], "today": today.isoformat()},
    )
    aggregation = (result.get("savingsGoal") or {}).get("goalEventAggregation") or {}
    rows = sorted(
        (
            date.fromisoformat(row["date"][:10]),
            row["totalSavings"],
            row.get("previousTotalSavings"),
        )
        for row in aggregation.get("dataByPeriod") or []
        if row.get("date") and row.get("totalSavings") is not None
    )
    points: _Points = [(d, total) for d, total, _ in rows]

    # The series begins on the goal's creation date, but rows exist only on
    # days with events. If nothing happened that day, the first row's opening
    # balance is the balance since creation. (When the creation day does have
    # a row, its opening figure is pre-migration bookkeeping, not a balance.)
    created = goal.get("createdAt")
    if created and rows and rows[0][2] is not None:
        created_day = date.fromisoformat(created[:10])
        if rows[0][0] > created_day:
            points.insert(0, (created_day, rows[0][2]))
    return points


@mcp.tool()
async def get_savings_goal_history(
    goal_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    granularity: str = "monthly",
) -> str:
    """
    Show how savings goal balances have changed over time.

    Uses Monarch's own goal balance history, which begins when the household
    moved to Monarch's current goals system; there is no history before that.
    The latest balance is checked against the goal's reported current balance
    (`reconciliation_diff`, normally 0).

    Like get_goals, every goal is included -- `archived_at` is not used as a
    filter.

    Args:
        goal_name: One goal to report on, matched case-insensitively against
            the names from get_goals. Omit for every goal plus a combined total.
        start_date: Start date, "YYYY-MM-DD". Defaults to the start of Monarch's
            goal history; an earlier date is moved up to it.
        end_date: End date, "YYYY-MM-DD". Defaults to today.
        granularity: "day", "monthly", or "annual" (default "monthly"). `day`
            lists only days when the balance changed. `monthly` and `annual`
            give one row per period, dated at the period's start, with the
            balance at the period's end (or at end_date for the last one).

    Returns:
        Per goal: start/end balance and change for start_date..end_date, the
        `series`, and `warnings`. With several goals, a combined `total` too.
        Top-level `warnings` say when the start date was moved.
    """
    try:
        if granularity not in HISTORY_GRANULARITIES:
            return json_success({
                "success": False,
                "error": (
                    f"granularity must be one of {', '.join(HISTORY_GRANULARITIES)}"
                ),
            })

        today = _today()
        try:
            end = date.fromisoformat(end_date) if end_date else today
            requested_start = date.fromisoformat(start_date) if start_date else None
        except ValueError as e:
            return json_success({"success": False, "error": f"Invalid date: {e}"})

        client = await get_monarch_client()
        result = await client.gql_call(
            operation="GetSavingsGoals", graphql_query=GET_GOALS_QUERY, variables={}
        )
        all_goals = result.get("savingsGoals") or []
        goals = all_goals

        if goal_name:
            wanted = goal_name.strip().lower()
            # Stored names can carry stray whitespace (e.g. "College fund ").
            goals = [
                g for g in all_goals if (g.get("name") or "").strip().lower() == wanted
            ]
            if not goals:
                return json_success({
                    "success": False,
                    "error": f"No goal named '{goal_name}'",
                    "available_goals": sorted(g.get("name") or "" for g in all_goals),
                })

        sem = asyncio.Semaphore(_HISTORY_CONCURRENCY)

        async def fetch(goal: Dict[str, Any]) -> Tuple[str, _Points]:
            async with sem:
                return goal["id"], await _history_points(client, goal, today)

        points_by_goal = dict(await asyncio.gather(*(fetch(g) for g in goals)))

        warnings: List[str] = []
        starts = [p[0][0] for p in points_by_goal.values() if p]
        history_start = min(starts) if starts else None
        if requested_start and history_start and requested_start < history_start:
            warnings.append(
                f"Monarch's goal history starts {history_start}; the requested "
                f"start {requested_start} was moved to that date."
            )
            start = history_start
        else:
            start = requested_start or history_start or end
        if start > end:
            return json_success({
                "success": False,
                "error": f"start_date {start} is after end_date {end}",
            })

        goal_results: List[Dict[str, Any]] = []
        all_points: List[_Points] = []
        for goal in goals:
            points = points_by_goal[goal["id"]]
            all_points.append(points)

            goal_warnings: List[str] = []
            if not points:
                goal_warnings.append("Monarch has no history for this goal yet.")
            elif points[0][0] > start:
                goal_warnings.append(
                    f"Monarch's history for this goal starts {points[0][0]}; "
                    "it has no balance before then."
                )

            start_balance = _balance_at(points, start)
            end_balance = _balance_at(points, end)
            reported = goal.get("currentBalance")
            reconciliation = None
            if end == today and end_balance is not None and reported is not None:
                reconciliation = round(end_balance - reported, 2)

            goal_results.append({
                "goal_id": goal.get("id"),
                "name": goal.get("name"),
                **_summarize(start_balance, end_balance),
                "reported_current_balance": reported,
                "reconciliation_diff": reconciliation,
                "series": _build_series(points, start, end, granularity),
                "warnings": goal_warnings,
            })

        total = None
        if len(goal_results) > 1:

            def total_at(d: date) -> float:
                return sum(_balance_at(p, d) or 0.0 for p in all_points)

            merged_days = sorted({d for p in all_points for d, _ in p})
            merged: _Points = [(d, total_at(d)) for d in merged_days]
            total = {
                **_summarize(total_at(start), total_at(end)),
                "series": _build_series(merged, start, end, granularity),
            }

        return json_success({
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "granularity": granularity,
            "goals": goal_results,
            "total": total,
            "warnings": warnings,
        })
    except Exception as e:
        return json_error("get_savings_goal_history", e)
