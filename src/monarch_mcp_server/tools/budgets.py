"""Budget tools."""

import calendar
import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from gql import gql
from monarchmoney import MonarchMoney

try:  # gql raises this when the server answers but refuses the query itself.
    from gql.transport.exceptions import TransportQueryError
except ImportError:  # pragma: no cover - defensive, gql always ships it today
    TransportQueryError = ()

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

logger = logging.getLogger(__name__)

# The upstream SDK's get_budgets() requests category-group fields (e.g.
# budgetVariability/rolloverPeriod) that Monarch's current API rejects for some
# accounts, so it can fail outright. This narrower query asks only for fields
# the current API still returns.
#
# Both documents below render from this one template. The narrow document
# supplies "" for every extension slot, so it is exactly the selection already
# proven to work; anything added to categoryGroups must go through a slot and
# therefore lands in the extended document only, where the fallback covers it.
_BUDGET_DOCUMENT = """
    query %(operation)s($startDate: Date!, $endDate: Date!) {
      budgetData(startMonth: $startDate, endMonth: $endDate) {
        monthlyAmountsByCategory {
          category {
            id
            __typename
          }
          monthlyAmounts {
            month
            plannedCashFlowAmount
            plannedSetAsideAmount
            actualAmount
            remainingAmount%(category_extra)s
            __typename
          }
          __typename
        }%(flex_selections)s
        __typename
      }
      categoryGroups {
        id
        name
        type%(group_extra)s
        categories {
          id
          name%(category_field_extra)s
          __typename
        }
        __typename
      }%(root_extra)s
    }
"""

# Extended-only additions to the categoryGroups subtree.
#
# This is the subtree the original narrowing was about, so these go in the
# extended document only and the fallback keeps the proven selection. Both are
# already queried successfully elsewhere in this server (tools/categories.py),
# so "the current API rejects them" does not hold at these levels.
#
# - groupLevelBudgetingEnabled: without it, a group row cannot be told apart
#   from a roll-up of its categories, and a caller that adds data[].planned to
#   groups[].planned double-counts.
# - categories.budgetVariability: under fixed_and_flex this is the only way to
#   know which per-category rows sit inside the pooled Flexible bucket, i.e.
#   which `planned` values are not standalone budgets.
_GROUP_EXTRA = """
        groupLevelBudgetingEnabled"""

_CATEGORY_FIELD_EXTRA = """
          budgetVariability"""

# Per-category rollover. Without these, planned - actual does not equal
# remaining for any category with rollover enabled, and the difference is
# unexplainable from the tool's output. Requested only by the extended query:
# the fallback stays byte-for-byte the document already proven to work.
_CATEGORY_EXTRA = """
            previousMonthRolloverAmount
            rolloverType"""

# Root-level extras.
#
# - budgetSystem: which system the account uses ("fixed_and_flex" or otherwise).
#   Lets a caller tell "this account does not do flex budgeting" from "the flex
#   bucket is empty" without inferring it.
# - goalsV2: goal contributions are part of the monthly plan, so a budget
#   answer that ignores them understates what is spoken for. They are a
#   SEPARATE quantity from a category's plannedSetAsideAmount -- goals carry
#   their own plannedContributions, and adding the two together double-counts.
#   Upstream guards this with @include(if: $useV2Goals); requested
#   unconditionally here since the whole document already falls back if
#   Monarch refuses any of it.
_ROOT_EXTRA = """
      budgetSystem
      goalsV2 {
        id
        name
        archivedAt
        completedAt
        priority
        plannedContributions(startMonth: $startDate, endMonth: $endDate) {
          id
          month
          amount
          __typename
        }
        monthlyContributionSummaries(startMonth: $startDate, endMonth: $endDate) {
          month
          sum
          __typename
        }
        __typename
      }"""

# Roll-up amounts Monarch exposes above the per-category level. All live under
# budgetData, so requesting them never widens the categoryGroups selection.
#
# - monthlyAmountsForFlexExpense: under the "fixed_and_flex" system the Flexible
#   section carries a single amount covering every category beneath it. Flexible
#   is the only *pooled* bucket -- Fixed and Non-Monthly are budgeted per
#   category, so their numbers are sums and appear in totalsByMonth (issue #103).
# - monthlyAmountsByCategoryGroup: group-level amounts, for groups budgeted at
#   the group level rather than per category.
# - totalsByMonth: income and overall expense totals alongside the three
#   expense buckets.
#
# Note: `budgetVariability` appears here under monthlyAmountsForFlexExpense,
# a *different* subtree from the CategoryGroup.budgetVariability field
# implicated in the original failure -- that one stays out of both documents,
# as does rolloverPeriod. See _GROUP_EXTRA / _CATEGORY_FIELD_EXTRA for what the
# extended document does add to the categoryGroups subtree.
_EXTENDED_SELECTIONS = """
        monthlyAmountsForFlexExpense {
          budgetVariability
          monthlyAmounts {
            month
            plannedCashFlowAmount
            actualAmount
            remainingAmount
            previousMonthRolloverAmount
            rolloverType
            __typename
          }
          __typename
        }
        monthlyAmountsByCategoryGroup {
          categoryGroup {
            id
            __typename
          }
          monthlyAmounts {
            month
            plannedCashFlowAmount
            actualAmount
            remainingAmount
            previousMonthRolloverAmount
            rolloverType
            __typename
          }
          __typename
        }
        totalsByMonth {
          month
          totalIncome {
            plannedAmount
            actualAmount
            remainingAmount
            previousMonthRolloverAmount
            __typename
          }
          totalExpenses {
            plannedAmount
            actualAmount
            remainingAmount
            previousMonthRolloverAmount
            __typename
          }
          totalFlexibleExpenses {
            plannedAmount
            actualAmount
            remainingAmount
            previousMonthRolloverAmount
            __typename
          }
          totalFixedExpenses {
            plannedAmount
            actualAmount
            remainingAmount
            previousMonthRolloverAmount
            __typename
          }
          totalNonMonthlyExpenses {
            plannedAmount
            actualAmount
            remainingAmount
            previousMonthRolloverAmount
            __typename
          }
          __typename
        }"""

BUDGET_QUERY_OPERATION = "MCPBudgetData"
BUDGET_QUERY_FLEX_OPERATION = "MCPBudgetDataFlex"

BUDGET_QUERY = gql(
    _BUDGET_DOCUMENT
    % {
        "operation": BUDGET_QUERY_OPERATION,
        "flex_selections": "",
        "category_extra": "",
        "group_extra": "",
        "category_field_extra": "",
        "root_extra": "",
    }
)

# Tried first; falls back to BUDGET_QUERY when Monarch refuses these fields.
BUDGET_QUERY_FLEX = gql(
    _BUDGET_DOCUMENT
    % {
        "operation": BUDGET_QUERY_FLEX_OPERATION,
        "flex_selections": _EXTENDED_SELECTIONS,
        "category_extra": _CATEGORY_EXTRA,
        "group_extra": _GROUP_EXTRA,
        "category_field_extra": _CATEGORY_FIELD_EXTRA,
        "root_extra": _ROOT_EXTRA,
    }
)

# Supplementary text match, for transports that surface standard GraphQL
# validation wording. Monarch itself does not -- a rejected field comes back as
# a generic "Something went wrong while processing" -- so exception *type* is
# the primary signal.
#
# Deliberately excludes "did you mean" and "validation error": those match
# CPython's own AttributeError/NameError suggestion text and pydantic's
# ValidationError respectively, so a local programming error would be
# misread as "this account has no flex bucket".
_SCHEMA_REJECTION_MARKERS = (
    "cannot query field",
    "unknown field",
    "no field named",
    "unknown argument",
)


def _safe_text(exc: Exception) -> str:
    """``str(exc)``, but never raising -- some exceptions fail to stringify.

    Classifying a failure must not itself become the failure the caller sees.
    """
    try:
        return str(exc)
    except Exception:  # pragma: no cover - pathological __str__
        return type(exc).__name__


def _is_query_rejection(exc: Exception) -> bool:
    """True when the server answered but refused the query itself.

    ``TransportQueryError`` is what gql raises when a response carries GraphQL
    ``errors``; HTTP failures (401, 5xx) raise ``TransportServerError`` and
    connection problems raise their own types, so those fall through to the
    caller rather than being mistaken for "this account has no flex bucket".
    """
    if TransportQueryError and isinstance(exc, TransportQueryError):
        return True
    return any(
        marker in _safe_text(exc).lower() for marker in _SCHEMA_REJECTION_MARKERS
    )


def current_month_range() -> tuple[str, str]:
    """Return the current month bounds as ISO date strings."""
    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=1).isoformat(), today.replace(day=last_day).isoformat()


async def get_budget_data(
    client: MonarchMoney,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Tuple[Dict[str, Any], bool]:
    """Fetch budget data, preferring the query that includes flex bucket totals.

    Returns ``(raw_response, used_flex_query)``. When Monarch rejects the
    extended selections this falls back to :data:`BUDGET_QUERY`, so accounts
    that do not support them behave exactly as they did before.

    The result is deliberately **not** cached. An earlier version latched
    "unsupported" for the life of the process to save a round-trip, but gql
    raises ``TransportQueryError`` for *any* response carrying a GraphQL
    ``errors`` array -- a rate limit, a resolver hiccup, a partial success --
    so one transient error would permanently strip flex, groups, goals, totals
    and rollover from every later call, and tell the user their account does
    not support flex when it does. Two concurrent calls could also race and
    clobber a known-good probe. The cost of re-probing is one extra round-trip
    per call on accounts that genuinely lack the fields; the cost of a sticky
    wrong answer is silently wrong financial output, so it is not a close call.
    """
    if (start_date is None) != (end_date is None):
        # Filling only one side from the current month can invert the range
        # (start 2026-12-01, end 2026-08-31), which returns nothing and reads
        # as "this account has no budget".
        raise ValueError(
            "start_date and end_date must be given together, or both omitted "
            "to default to the current month."
        )

    default_start, default_end = current_month_range()
    variables = {
        "startDate": start_date or default_start,
        "endDate": end_date or default_end,
    }

    try:
        data = await client.gql_call(
            operation=BUDGET_QUERY_FLEX_OPERATION,
            graphql_query=BUDGET_QUERY_FLEX,
            variables=variables,
        )
        return data, True
    except Exception as exc:
        if not _is_query_rejection(exc):
            raise
        logger.warning(
            "Monarch refused the extended budget fields; retrying with the "
            "narrow query: %s",
            _safe_text(exc),
        )

    # If this fails too the problem was never flex-specific (an expired session
    # refuses both queries), and it propagates rather than being reported as an
    # account that lacks flex budgeting.
    data = await client.gql_call(
        operation=BUDGET_QUERY_OPERATION,
        graphql_query=BUDGET_QUERY,
        variables=variables,
    )
    return data, False


def format_budget_data(budget_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Format Monarch budget data into one row per category/month.

    Every level uses ``or {}`` / ``or []`` rather than ``.get(k, default)``:
    GraphQL returns an explicit ``null`` for a nullable field, which a default
    argument does not catch. One such null used to take out the whole tool.
    """
    category_lookup: Dict[str, Dict[str, Optional[str]]] = {}
    for group in budget_data.get("categoryGroups") or []:
        if not group:
            continue
        for category in group.get("categories") or []:
            if not category:
                continue
            category_id = category.get("id")
            if category_id:
                category_lookup[category_id] = {
                    "name": category.get("name"),
                    "category_group": group.get("name"),
                    "category_type": group.get("type"),
                    "budget_variability": category.get("budgetVariability"),
                }

    budget_rows = []
    monthly_by_category = (
        (budget_data.get("budgetData") or {}).get("monthlyAmountsByCategory") or []
    )
    for category_budget in monthly_by_category:
        if not category_budget:
            continue
        category_id = (category_budget.get("category") or {}).get("id")
        category_info = category_lookup.get(category_id) or {}
        for monthly_amount in category_budget.get("monthlyAmounts") or []:
            if not monthly_amount:
                continue
            budget_rows.append(
                {
                    "id": category_id,
                    "name": category_info.get("name"),
                    "planned": monthly_amount.get("plannedCashFlowAmount"),
                    "actual": monthly_amount.get("actualAmount"),
                    "remaining": monthly_amount.get("remainingAmount"),
                    # planned - actual only equals remaining when rollover is
                    # zero; without these the gap is unexplainable.
                    "set_aside": monthly_amount.get("plannedSetAsideAmount"),
                    "rollover": monthly_amount.get("previousMonthRolloverAmount"),
                    "rollover_type": monthly_amount.get("rolloverType"),
                    "category_group": category_info.get("category_group"),
                    # Income and expense rows are BOTH positive magnitudes, so
                    # summing planned across rows without filtering on this
                    # adds income to spending. See the get_budgets docstring.
                    "category_type": category_info.get("category_type"),
                    "budget_variability": category_info.get("budget_variability"),
                    "month": monthly_amount.get("month"),
                }
            )

    return budget_rows


def _totals_entry(node: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Normalize one of Monarch's planned/actual/remaining total objects."""
    if not node:
        return None
    return {
        "planned": node.get("plannedAmount"),
        "actual": node.get("actualAmount"),
        "remaining": node.get("remainingAmount"),
        "rollover": node.get("previousMonthRolloverAmount"),
    }


def format_flex_budget(
    budget_data: Dict[str, Any], used_flex_query: bool
) -> Dict[str, Any]:
    """Summarize the Flexible bucket, always reporting *why* it may be empty.

    ``status`` separates three cases that would otherwise be indistinguishable
    -- and reading "no flex budget" as "$0" would be wrong:

    - ``unsupported``    Monarch rejected the flex fields; the fallback ran
    - ``not_configured`` the query worked but this account has no flex bucket
    - ``ok``             a flex bucket is present
    """
    if not used_flex_query:
        return {"status": "unsupported", "budget_variability": None, "monthly": []}

    flex = (budget_data.get("budgetData") or {}).get("monthlyAmountsForFlexExpense")
    if isinstance(flex, list):
        entries = flex
    elif flex:
        entries = [flex]
    else:
        entries = []

    # If Monarch ever returns several buckets here, never merge them:
    # concatenating a fixed bucket's months into the flex answer under
    # whichever label came last would report a different bucket's amount as the
    # flexible budget. Prefer the entry actually labelled flexible; failing
    # that, take a single entry rather than combining ambiguous ones.
    if len(entries) > 1:
        flexible_entries = [
            e for e in entries if e and e.get("budgetVariability") == "flexible"
        ]
        if len(flexible_entries) == 1:
            entries = flexible_entries
        else:
            logger.warning(
                "Monarch returned %d flex-expense buckets (%d labelled "
                "flexible); using only the first to avoid merging buckets.",
                len(entries),
                len(flexible_entries),
            )
            entries = (flexible_entries or entries)[:1]

    variability: Optional[str] = None
    monthly: List[Dict[str, Any]] = []
    for entry in entries:
        if not entry:
            continue
        variability = entry.get("budgetVariability") or variability
        for amount in entry.get("monthlyAmounts") or []:
            if not amount:
                continue
            monthly.append(
                {
                    "month": amount.get("month"),
                    "planned": amount.get("plannedCashFlowAmount"),
                    "actual": amount.get("actualAmount"),
                    "remaining": amount.get("remainingAmount"),
                    "rollover": amount.get("previousMonthRolloverAmount"),
                    "rollover_type": amount.get("rolloverType"),
                }
            )

    if not monthly:
        return {
            "status": "not_configured",
            "budget_variability": variability,
            "monthly": [],
        }

    return {"status": "ok", "budget_variability": variability, "monthly": monthly}


def format_budget_totals(
    budget_data: Dict[str, Any], used_flex_query: bool
) -> Optional[List[Dict[str, Any]]]:
    """Per-month totals.

    ``None`` means "could not ask" (the fallback query ran); ``[]`` means the
    query succeeded and there were none. Collapsing those together is the same
    mistake ``flex.status`` exists to avoid.
    """
    if not used_flex_query:
        return None

    totals = (budget_data.get("budgetData") or {}).get("totalsByMonth") or []

    return [
        {
            "month": total.get("month"),
            "income": _totals_entry(total.get("totalIncome")),
            "expenses": _totals_entry(total.get("totalExpenses")),
            "flexible": _totals_entry(total.get("totalFlexibleExpenses")),
            "fixed": _totals_entry(total.get("totalFixedExpenses")),
            "non_monthly": _totals_entry(total.get("totalNonMonthlyExpenses")),
        }
        for total in totals
        if total
    ]


def format_group_budgets(
    budget_data: Dict[str, Any], used_flex_query: bool
) -> Optional[List[Dict[str, Any]]]:
    """One row per category group per month.

    ``None`` means "could not ask"; ``[]`` means none were returned.

    ``group_level_budgeting`` says which level holds the real budget: when True
    the group does and its categories carry none; when False this row is merely
    the roll-up of its categories. Adding ``groups[].planned`` to the matching
    ``data[].planned`` double-counts either way.
    """
    if not used_flex_query:
        return None

    by_group = (budget_data.get("budgetData") or {}).get(
        "monthlyAmountsByCategoryGroup"
    ) or []

    group_info: Dict[str, Dict[str, Any]] = {
        group.get("id"): {
            "name": group.get("name"),
            "category_type": group.get("type"),
            "group_level_budgeting": group.get("groupLevelBudgetingEnabled"),
        }
        for group in budget_data.get("categoryGroups") or []
        if group and group.get("id")
    }

    rows: List[Dict[str, Any]] = []
    for entry in by_group:
        if not entry:
            continue
        group_id = (entry.get("categoryGroup") or {}).get("id")
        info = group_info.get(group_id) or {}
        for amount in entry.get("monthlyAmounts") or []:
            if not amount:
                continue
            rows.append(
                {
                    "id": group_id,
                    "name": info.get("name"),
                    "planned": amount.get("plannedCashFlowAmount"),
                    "actual": amount.get("actualAmount"),
                    "remaining": amount.get("remainingAmount"),
                    "rollover": amount.get("previousMonthRolloverAmount"),
                    "rollover_type": amount.get("rolloverType"),
                    "category_type": info.get("category_type"),
                    "group_level_budgeting": info.get("group_level_budgeting"),
                    "month": amount.get("month"),
                }
            )

    return rows


def format_goals(
    budget_data: Dict[str, Any], used_flex_query: bool
) -> Optional[List[Dict[str, Any]]]:
    """Savings goals with their planned and actual monthly contributions.

    ``None`` means "could not ask"; ``[]`` means the account has no goals.
    Archived and completed goals are included but flagged, so a caller can
    exclude them rather than silently miss that they existed.
    """
    if not used_flex_query:
        return None

    goals = budget_data.get("goalsV2") or []

    rows: List[Dict[str, Any]] = []
    for goal in goals:
        if not goal:
            continue
        rows.append(
            {
                "id": goal.get("id"),
                "name": goal.get("name"),
                "priority": goal.get("priority"),
                "archived": bool(goal.get("archivedAt")),
                "completed": bool(goal.get("completedAt")),
                "planned_contributions": [
                    {"month": c.get("month"), "amount": c.get("amount")}
                    for c in goal.get("plannedContributions") or []
                    if c
                ],
                "actual_contributions": [
                    {"month": s.get("month"), "amount": s.get("sum")}
                    for s in goal.get("monthlyContributionSummaries") or []
                    if s
                ],
            }
        )

    return rows


@mcp.tool()
async def get_budgets(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get budget information from Monarch Money.

    Args:
        start_date: Start month in YYYY-MM-DD format
        end_date: End month in YYYY-MM-DD format

        Pass BOTH or NEITHER. Omitting both defaults to the current month;
        supplying only one is an error rather than being filled in, because
        completing the missing side from today can invert the range and return
        an empty result that reads as "this account has no budget".

    Returns:
        A JSON object as described below.

        IMPORTANT - signs: income and expense amounts are BOTH returned as
        positive magnitudes; the sign does not distinguish them (negatives
        appear only for contra entries, e.g. an income-type group that
        represents money going out). Summing ``planned`` across ``data`` rows
        therefore adds income to spending and produces a meaningless figure.
        Always filter on ``category_type`` first.

        IMPORTANT - missing vs zero: when ``flex.status`` is ``unsupported``
        the extended query was refused, and ``rollover``, ``rollover_type``,
        ``budget_variability``, ``budget_system``, ``groups``, ``goals`` and
        ``totals`` are all null as a result. Null means "not available", never
        zero, and reconciliation is not possible in that state.

        ``budget_system`` - e.g. "fixed_and_flex". Null if the account does not
        report it OR if the extended query was refused (see above).

        ``data`` - one row per budgeted category per month: ``id`` (category
        id), ``name``, ``planned`` (planned cash-flow amount), ``actual``,
        ``remaining``, ``set_aside``, ``rollover``, ``rollover_type``,
        ``category_group``, ``category_type`` (``income`` / ``expense`` /
        ``transfer``), ``budget_variability`` and ``month``.

        ``set_aside`` is Monarch's ``plannedSetAsideAmount``, passed through
        as-is. It is a distinct field from ``planned`` and this server does not
        combine them; whether Monarch intends it as additive to ``planned`` has
        not been confirmed against an account that actually uses it, so do not
        sum the two without checking against Monarch's own figures.

        ``planned`` minus
        ``actual`` equals ``remaining`` only when ``rollover`` is zero; for
        rollover categories the carried balance accounts for the difference.

        ``flex`` - the all-up Flexible bucket for accounts on Monarch's
        "fixed_and_flex" budget system, with ``status`` (``ok``,
        ``not_configured`` or ``unsupported``), ``budget_variability`` and a
        ``monthly`` list. Under flex budgeting a single amount covers every
        category in the Flexible section, so this -- not the per-category rows
        -- is the number to compare spending against. A ``status`` other than
        ``ok`` means no amount is available; do NOT treat that as zero.
        Flexible is the only pooled bucket, so rows whose
        ``budget_variability`` is ``flexible`` do not carry standalone budgets;
        Fixed and Non-Monthly categories do.

        ``groups`` - one row per category group per month (``id``, ``name``,
        ``planned``, ``actual``, ``remaining``, ``rollover``,
        ``rollover_type``, ``category_type``, ``group_level_budgeting``,
        ``month``). ``group_level_budgeting`` says which level holds the real
        budget: when true the group does and its categories carry none; when
        false this row is only the roll-up of its own categories. Never add a
        group's ``planned`` to its categories' ``planned`` -- that
        double-counts either way.

        ``goals`` - savings goals with ``planned_contributions`` and
        ``actual_contributions`` per month. Goal contributions are a SEPARATE
        quantity from a category's ``set_aside``; adding them together
        double-counts. ``archived`` and ``completed`` goals are included but
        flagged.

        ``totals`` - per-month ``income``, ``expenses``, ``flexible``,
        ``fixed`` and ``non_monthly`` totals.

        For ``groups``, ``goals`` and ``totals``: ``null`` means the data could
        not be fetched, while ``[]`` means the query succeeded and there was
        none.
    """
    try:
        client = await get_monarch_client()
        raw, used_flex_query = await get_budget_data(client, start_date, end_date)
        return json_success(
            {
                "tool": "get_budgets",
                "args": {"start_date": start_date, "end_date": end_date},
                "budget_system": raw.get("budgetSystem"),
                "data": format_budget_data(raw),
                "flex": format_flex_budget(raw, used_flex_query),
                "groups": format_group_budgets(raw, used_flex_query),
                "goals": format_goals(raw, used_flex_query),
                "totals": format_budget_totals(raw, used_flex_query),
            }
        )
    except Exception as e:
        return json_error("get_budgets", e)


@mcp.tool()
async def set_budget_amount(
    amount: float,
    category_id: Optional[str] = None,
    category_group_id: Optional[str] = None,
    start_date: Optional[str] = None,
    apply_to_future: bool = False,
) -> str:
    """
    Set or update a budget amount for a category or category group.

    Use get_budgets() first to see current budgets and category IDs.
    Use get_categories() or get_category_groups() to find category/group IDs.

    Note: this cannot set the all-up Flexible bucket amount -- that bucket is
    not a category group. Use set_flexible_budget() for it.

    Args:
        amount: The budget amount to set. Use 0 to clear/unset the budget.
        category_id: The ID of the category to budget (cannot use with category_group_id)
        category_group_id: The ID of the category group to budget (cannot use with category_id)
        start_date: The month to set budget for in YYYY-MM-DD format (defaults to current month)
        apply_to_future: Whether to apply this amount to all future months (default: False)

    Returns:
        Result of the budget update.

    Examples:
        Set grocery budget to $600 for current month:
            set_budget_amount(amount=600, category_id="cat_groceries_123")

        Set dining budget to $200 and apply to all future months:
            set_budget_amount(amount=200, category_id="cat_dining_456", apply_to_future=True)

        Clear a budget (set to 0):
            set_budget_amount(amount=0, category_id="cat_123")
    """
    try:
        if category_id and category_group_id:
            return json_success({
                "success": False,
                "error": "Cannot specify both category_id and category_group_id. Choose one."
            })

        if not category_id and not category_group_id:
            return json_success({
                "success": False,
                "error": "Must specify either category_id or category_group_id."
            })

        client = await get_monarch_client()

        params: Dict[str, Any] = {
            "amount": amount,
            "apply_to_future": apply_to_future,
        }

        if category_id:
            params["category_id"] = category_id
        if category_group_id:
            params["category_group_id"] = category_group_id
        if start_date:
            params["start_date"] = start_date

        result = await client.set_budget_amount(**params)

        return json_success({
            "success": True,
            "message": f"Budget set to ${amount:.2f}" + (" for all future months" if apply_to_future else ""),
            "result": result
        })
    except Exception as e:
        return json_error("set_budget_amount", e)


@mcp.tool()
async def set_flexible_budget(
    amount: float,
    start_date: Optional[str] = None,
    apply_to_future: bool = False,
) -> str:
    """
    Set the all-up Flexible bucket budget (Monarch's "fixed_and_flex" system).

    This is the single amount covering every category in the Flexible section.
    It is not a category or a category group, so set_budget_amount() cannot
    reach it.

    Args:
        amount: The budget amount to set. Use 0 to clear/unset it.
        start_date: The month to set in YYYY-MM-DD format (defaults to current month)
        apply_to_future: Whether to apply this amount to all future months

    Returns:
        Result of the update.
    """
    try:
        # Built before the mutation: a formatting error afterwards would report
        # failure for a write that already applied and invite a retry.
        message = f"Flexible budget set to ${float(amount):.2f}" + (
            " for all future months" if apply_to_future else ""
        )

        client = await get_monarch_client()

        updater = getattr(client, "update_flexible_budget", None)
        if updater is None:
            return json_success({
                "success": False,
                "error": (
                    "The installed monarchmoney client has no "
                    "update_flexible_budget(); upgrade monarchmoneycommunity."
                ),
            })

        result = await updater(
            amount=amount,
            start_date=start_date,
            apply_to_future=apply_to_future,
        )

        # Do not infer success from the absence of an exception: Monarch can
        # return a 200 whose payload node is null. Reporting "$X set" off a
        # no-op would have the model tell the user a number that is not true.
        budget_item = (
            ((result or {}).get("updateOrCreateFlexBudgetItem") or {}).get("budgetItem")
            if isinstance(result, dict)
            else None
        )
        if not budget_item:
            return json_success({
                "success": False,
                "error": (
                    "Monarch did not confirm the update -- the response "
                    "contained no budget item. The amount may not have been "
                    "applied; re-read it with get_budgets before retrying."
                ),
                "result": result,
            })

        return json_success({
            "success": True,
            "message": message,
            "result": result,
        })
    except Exception as e:
        return json_error("set_flexible_budget", e)


@mcp.tool()
async def update_flex_rollover_settings(
    rollover_start_month: str,
    rollover_starting_balance: float,
    rollover_enabled: bool = True,
) -> str:
    """
    Start a new Flex bucket rollover period.

    DESTRUCTIVE: this DISCARDS the rollover balance accumulated so far and
    begins a fresh period. Its main use is fixing a Flex bucket that has built
    up a large negative rollover over many months. Confirm with the user before
    calling, and report the current rollover (get_budgets -> flex.monthly[].
    rollover) so they know what is being discarded.

    Both amounts are required on purpose -- the underlying client defaults to a
    starting balance of 0 for the current month, i.e. a silent full reset, so
    this tool makes the caller state the intent explicitly.

    Args:
        rollover_start_month: First month of the new period, YYYY-MM-DD
            (use the first of the month, e.g. "2026-08-01")
        rollover_starting_balance: Balance to seed the new period with. Pass 0
            to clear accumulated rollover entirely.
        rollover_enabled: Whether flex rollover stays enabled (default True)

    Returns:
        Result of the update, including the new rollover period.
    """
    try:
        # The client does `rollover_start_month or <current month>`, so an
        # empty or malformed value silently becomes "reset from this month" --
        # exactly the no-argument reset the required arguments exist to
        # prevent. Reject it here rather than letting it through.
        try:
            date.fromisoformat(rollover_start_month)
        except (TypeError, ValueError):
            return json_success({
                "success": False,
                "error": (
                    "rollover_start_month must be a YYYY-MM-DD date (use the "
                    f"first of the month, e.g. '2026-08-01'); got "
                    f"{rollover_start_month!r}."
                ),
            })

        client = await get_monarch_client()

        updater = getattr(client, "update_flex_rollover_settings", None)
        if updater is None:
            return json_success({
                "success": False,
                "error": (
                    "The installed monarchmoney client has no "
                    "update_flex_rollover_settings(); upgrade "
                    "monarchmoneycommunity."
                ),
            })

        # The client writes budgetSystem into this mutation's input and
        # defaults it to "fixed_and_flex". Firing it blind on an account using
        # a different system would migrate the household's whole budgeting mode
        # as a side effect of a rollover reset -- a much larger change than the
        # one the user was asked to confirm. So read the real value first and
        # forward it, refusing rather than guessing.
        raw, used_extended = await get_budget_data(client)
        budget_system = raw.get("budgetSystem") if used_extended else None

        if not used_extended:
            return json_success({
                "success": False,
                "error": (
                    "Could not read this account's budget system (Monarch "
                    "refused the extended budget query), so a flex rollover "
                    "reset cannot be performed safely -- it would risk "
                    "switching the account's budgeting mode."
                ),
            })

        if budget_system != "fixed_and_flex":
            described = (
                repr(budget_system)
                if budget_system
                else "not reported by Monarch"
            )
            return json_success({
                "success": False,
                "error": (
                    f"This account's budget system is {described}, not "
                    "'fixed_and_flex'. Refusing: this mutation would rewrite "
                    "the account's budget system as well as the rollover."
                ),
                "budget_system": budget_system,
            })

        result = await updater(
            rollover_start_month=rollover_start_month,
            rollover_starting_balance=rollover_starting_balance,
            rollover_enabled=rollover_enabled,
            budget_system=budget_system,
        )

        # Same reasoning as set_flexible_budget, and it matters more here:
        # falsely confirming a destructive reset is worse than falsely
        # confirming an amount.
        period = (
            ((result or {}).get("updateBudgetSettings") or {}).get(
                "budgetRolloverPeriod"
            )
            if isinstance(result, dict)
            else None
        )
        if not period:
            return json_success({
                "success": False,
                "error": (
                    "Monarch did not confirm the change -- the response "
                    "contained no rollover period. The reset may not have "
                    "been applied; re-read it with get_budgets before "
                    "retrying."
                ),
                "result": result,
            })

        # Report the month Monarch actually applied, not the one requested.
        applied_month = period.get("startMonth") or rollover_start_month
        return json_success({
            "success": True,
            "message": (
                f"Flex rollover period restarted at {applied_month} with a "
                f"starting balance of ${float(rollover_starting_balance):.2f}"
                + ("" if rollover_enabled else " (rollover disabled)")
            ),
            "budget_system": budget_system,
            "result": result,
        })
    except Exception as e:
        return json_error("update_flex_rollover_settings", e)
