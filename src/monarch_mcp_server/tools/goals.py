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


# The query behind the goal page's timeline, with the optional `startDate`
# argument the page itself never sends. Given a start date, `totalSavings` is
# the running change in the goal's balance since that date (not the balance),
# one row per period with goal events, dated at the period's start. Monarch has
# no history before the household moved to the current goals system.
#
# Rows also carry the period's contributions, withdrawals and spending, for the
# breakdown. Withdrawals and spending come as positive amounts.
_GOAL_HISTORY_TEMPLATE = """
query GetSavingsGoalHistory($id: ID!, $today: Date!, $startDate: Date!) {
  savingsGoal(id: $id) {
    id
    goalEventAggregation(
      today: $today
      groupingPeriod: %s
      excludeEventsNotInBudget: false
      groupEventsAfterToday: false
      startDate: $startDate
    ) {
      dataByPeriod {
        date
        totalSavings
        contributions
        withdrawals
        spending
        __typename
      }
      __typename
    }
    __typename
  }
}
"""

FLOW_FIELDS = ("contributions", "withdrawals", "spending")
BREAKDOWN_FIELDS = FLOW_FIELDS + ("adjustments",)

# The grouping periods Monarch's goal aggregation supports. `groupingPeriod` is
# an enum whose type name the API does not expose, so it cannot be a variable:
# each value gets its own fixed query document, built once here.
HISTORY_GRANULARITIES = ("day", "monthly", "annual")
GOAL_HISTORY_QUERIES = {
    g: gql(_GOAL_HISTORY_TEMPLATE % g) for g in HISTORY_GRANULARITIES
}

# How many periods to show by default (None: all history), and the most days a
# daily view may cover, to keep responses a sensible size.
DEFAULT_HISTORY_PERIODS = {"day": 92, "monthly": 60, "annual": None}
MAX_HISTORY_DAYS = 92

# Parallel history requests; enough to be quick without hammering the API.
_HISTORY_CONCURRENCY = 5

# (opening date, opening balance, [(period start, balance after that period)],
#  {period start: (contributions, withdrawals, spending)})
_History = Tuple[date, float, List[Tuple[date, float]], Dict[date, Tuple[float, ...]]]


def _today() -> date:
    """Indirection so tests can pin "today"."""
    return date.today()


def _created_day(goal: Dict[str, Any]) -> Optional[date]:
    created = goal.get("createdAt")
    return date.fromisoformat(created[:10]) if created else None


def _period_start(d: date, granularity: str) -> date:
    """Start of the day, month or year containing `d`."""
    if granularity == "monthly":
        return d.replace(day=1)
    if granularity == "annual":
        return d.replace(month=1, day=1)
    return d


def _next_period(start: date, granularity: str) -> date:
    """Start of the month or year after the one starting at `start`."""
    if granularity == "monthly":
        return (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start.replace(year=start.year + 1)


def _periods_back(today: date, granularity: str, periods: int) -> date:
    """Start of the period `periods - 1` periods before today's."""
    if granularity == "monthly":
        months = today.year * 12 + today.month - periods
        return date(months // 12, months % 12 + 1, 1)
    if granularity == "annual":
        return date(today.year - periods + 1, 1, 1)
    return today - timedelta(days=periods - 1)


def _balance_on(history: _History, d: date) -> Optional[float]:
    """Balance at the close of `d`, or None before the goal's opening."""
    opening_date, opening, points, _ = history
    if d < opening_date:
        return None
    i = bisect_right(points, (d, float("inf"))) - 1
    return points[i][1] if i >= 0 else opening


def _change(start: float, end: float) -> Dict[str, Any]:
    change = round(end - start, 2)
    return {
        "start_balance": round(start, 2),
        "end_balance": round(end, 2),
        "change": change,
        "change_percent": round(change / start * 100, 2) if start else None,
    }


async def _goal_history(
    client: Any, goal: Dict[str, Any], granularity: str, start: date, today: date
) -> _History:
    """Fetch one goal's history from `start`, as balances.

    Changes are counted from the day after the goal was created: on that day
    Monarch books migrated balances as events, which are not real changes. The
    balance after any period is the current balance less the change since.
    """
    created = _created_day(goal)
    fetch_from = max(start, created + timedelta(days=1)) if created else start
    rows: List[Tuple[date, float, Tuple[float, ...]]] = []
    if fetch_from <= today:
        result = await client.gql_call(
            operation="GetSavingsGoalHistory",
            graphql_query=GOAL_HISTORY_QUERIES[granularity],
            variables={
                "id": goal["id"],
                "today": today.isoformat(),
                "startDate": fetch_from.isoformat(),
            },
        )
        goal_data = result.get("savingsGoal") or {}
        aggregation = goal_data.get("goalEventAggregation") or {}
        rows = sorted(
            (
                date.fromisoformat(row["date"][:10]),
                row["totalSavings"],
                tuple(row.get(f) or 0.0 for f in FLOW_FIELDS),
            )
            for row in aggregation.get("dataByPeriod") or []
            if row.get("date") and row.get("totalSavings") is not None
        )

    opening = (goal.get("currentBalance") or 0.0) - (rows[-1][1] if rows else 0.0)
    points = [(d, opening + change) for d, change, _ in rows]
    flows = {d: f for d, _, f in rows}
    return fetch_from - timedelta(days=1), opening, points, flows


def _add_breakdown(
    rows: List[Dict[str, Any]], opening: float, flows: Dict[date, Tuple[float, ...]]
) -> Dict[str, float]:
    """Split each period row's change; return the totals for the window.

    change = contributions - withdrawals - spending + adjustments, where
    adjustments is whatever the recorded flows do not explain.
    """
    totals = dict.fromkeys(BREAKDOWN_FIELDS, 0.0)
    previous = opening
    for row in rows:
        contributions, withdrawals, spending = flows.get(
            date.fromisoformat(row["date"]), (0.0, 0.0, 0.0)
        )
        change = row["balance"] - previous
        previous = row["balance"]
        parts = {
            "contributions": contributions,
            "withdrawals": withdrawals,
            "spending": spending,
            "adjustments": change - contributions + withdrawals + spending,
        }
        row["change"] = round(change, 2)
        for field, amount in parts.items():
            row[field] = round(amount, 2)
            totals[field] += amount
    return {field: round(amount, 2) for field, amount in totals.items()}


@mcp.tool()
async def get_savings_goal_history(
    goal_name: Optional[str] = None,
    granularity: str = "monthly",
    periods: Optional[int] = None,
    breakdown: bool = False,
) -> str:
    """
    Show how savings goal balances have changed, up to today.

    Uses Monarch's own goal history, which begins when the household moved to
    Monarch's current goals system; there is no history before that. Every goal
    is included, like get_goals -- `archived_at` is not used as a filter.

    Args:
        goal_name: One goal to report on, matched case-insensitively against
            the names from get_goals. Omit for every goal plus a combined total.
        granularity: "day", "monthly", or "annual" (default "monthly").
        periods: How many days, months, or years to show, ending with today's.
            Defaults: 92 days (also the most for "day"), 60 months, or every
            year of history.
        breakdown: Split each period's change into contributions, withdrawals,
            spending and adjustments, so that
            change = contributions - withdrawals - spending + adjustments.
            Withdrawals and spending are positive amounts. Adjustments, as
            Monarch calls them, are everything else: mostly market movement,
            but also any transfer not recorded as a contribution or withdrawal.
            They can lag a flow by a few days, so one may land in a later
            period; by day this is common.

    Returns:
        Per goal: the balance at the start of the window (`start_balance`, as of
        `start_balance_date`), today's balance, the change, and a `series`. For
        "day" the series lists only days the balance changed; for "monthly" and
        "annual" there is a row per period, dated at its start, with the balance
        at its end (today, for the current one). With several goals, a combined
        `total` too, which counts a goal as zero before it was created.

        With breakdown, each series row also has the period's `change` and its
        parts, and each goal and the total have a `breakdown` of the window. The
        total's `new_goals` is the starting balance of goals created during the
        window, which is part of its change but of no goal's.
    """
    try:
        if granularity not in HISTORY_GRANULARITIES:
            return json_success({
                "success": False,
                "error": (
                    f"granularity must be one of {', '.join(HISTORY_GRANULARITIES)}"
                ),
            })
        if periods is not None and (
            periods < 1 or (granularity == "day" and periods > MAX_HISTORY_DAYS)
        ):
            return json_success({
                "success": False,
                "error": (
                    f"periods must be from 1 to {MAX_HISTORY_DAYS} for day, "
                    "or at least 1 otherwise"
                ),
            })
        periods = periods or DEFAULT_HISTORY_PERIODS[granularity]

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

        # The window ends today and starts no earlier than the history does.
        today = _today()
        created_days = [d for d in map(_created_day, goals) if d]
        history_start = min(created_days) if created_days else None
        if periods:
            start = _periods_back(today, granularity, periods)
        else:  # annual, all history
            start = _period_start(history_start or today, granularity)
        if history_start:
            start = max(start, history_start)

        sem = asyncio.Semaphore(_HISTORY_CONCURRENCY)

        async def fetch(goal: Dict[str, Any]) -> _History:
            async with sem:
                return await _goal_history(client, goal, granularity, start, today)

        histories = await asyncio.gather(*(fetch(g) for g in goals))

        # The dates the series report on, as (label, balance as of). A daily
        # series lists the days balances changed; a period series has one row
        # per period, dated at its start, with the balance at its end.
        def checkpoints(hs: List[_History]) -> List[Tuple[date, date]]:
            if granularity == "day":
                days = {d for h in hs for d in [h[0]] + [p for p, _ in h[2]]}
                return [(d, d) for d in sorted(days) if d >= start]
            out = []
            period = _period_start(start, granularity)
            while period <= today:
                nxt = _next_period(period, granularity)
                out.append((period, min(nxt - timedelta(days=1), today)))
                period = nxt
            return out

        def series(hs: List[_History]) -> List[Dict[str, Any]]:
            out = []
            for label, as_of in checkpoints(hs):
                balances = [_balance_on(h, as_of) for h in hs]
                if any(b is not None for b in balances):
                    total = sum(b for b in balances if b is not None)
                    out.append({"date": label.isoformat(), "balance": round(total, 2)})
            return out

        goal_results = []
        for goal, history in zip(goals, histories):
            result_row = {
                "goal_id": goal.get("id"),
                "name": goal.get("name"),
                **_change(history[1], goal.get("currentBalance") or 0.0),
                "start_balance_date": history[0].isoformat(),
                "series": series([history]),
            }
            if breakdown:
                result_row["breakdown"] = _add_breakdown(
                    result_row["series"], history[1], history[3]
                )
            goal_results.append(result_row)

        total = None
        if len(goals) > 1:
            # Goals created after the window starts count from zero.
            total = {
                **_change(
                    sum(h[1] for h in histories if h[0] <= start),
                    sum(g.get("currentBalance") or 0.0 for g in goals),
                ),
                "series": series(histories),
            }
            if breakdown:
                fields = ("change", "new_goals") + BREAKDOWN_FIELDS
                rows = {r["date"]: r for r in total["series"]}
                sums = {r["date"]: dict.fromkeys(fields, 0.0) for r in total["series"]}
                for goal_row in goal_results:
                    for r in goal_row["series"]:
                        for field in ("change",) + BREAKDOWN_FIELDS:
                            sums[r["date"]][field] += r[field]
                for h in histories:
                    if h[0] > start:  # created during the window
                        period = _period_start(h[0], granularity).isoformat()
                        sums[period]["new_goals"] += h[1]
                        sums[period]["change"] += h[1]
                for day, parts in sums.items():
                    rows[day].update({f: round(v, 2) for f, v in parts.items()})
                total["breakdown"] = {
                    f: round(sum(parts[f] for parts in sums.values()), 2)
                    for f in ("new_goals",) + BREAKDOWN_FIELDS
                }

        return json_success({
            "start_date": start.isoformat(),
            "end_date": today.isoformat(),
            "granularity": granularity,
            "goals": goal_results,
            "total": total,
        })
    except Exception as e:
        return json_error("get_savings_goal_history", e)
