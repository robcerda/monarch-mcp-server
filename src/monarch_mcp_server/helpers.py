"""Shared helpers for Monarch MCP Server tools."""

import json
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Monarch's aggregate queries return every bucket they have — a full year runs to
# hundreds of categories and thousands of merchants, which overflows the MCP
# response limit. Rows are only trimmed when a response would actually exceed the
# budget, stepping down this ladder of per-breakdown caps until it fits.
MAX_RESPONSE_CHARS = 45_000
LIMIT_LADDER = (100, 50, 20, 10, 5)


def strip_typenames(value: Any) -> Any:
    """Recursively drop GraphQL ``__typename`` keys from a payload."""
    if isinstance(value, dict):
        return {k: strip_typenames(v) for k, v in value.items() if k != "__typename"}
    if isinstance(value, list):
        return [strip_typenames(item) for item in value]
    return value


def breakdown(rows: List[Dict[str, Any]], limit: Optional[int]) -> Dict[str, Any]:
    """Wrap ranked ``rows`` so any cap applied is visible to the caller."""
    capped = rows[:limit] if limit else rows
    return {
        "total": len(rows),
        "returned": len(capped),
        "truncated": len(capped) < len(rows),
        "rows": capped,
    }


def render_within_budget(
    render: Callable[[Optional[int]], str], limit: Optional[int]
) -> str:
    """Render the largest response that fits under ``MAX_RESPONSE_CHARS``.

    ``render`` takes the per-breakdown cap to apply (None for no cap) and returns
    the serialized response. An explicit *limit* is honoured as-is — including 0,
    which means "never trim" — and otherwise the cap steps down the ladder only
    as far as it must.
    """
    if limit is not None:
        return render(limit or None)

    for applied in (None, *LIMIT_LADDER):
        rendered = render(applied)
        if len(rendered) <= MAX_RESPONSE_CHARS:
            return rendered
    return rendered


def format_exception(exc: Exception) -> str:
    """Best-effort string representation for tool error responses.

    Some exceptions (e.g. certain async/transport errors) stringify to ``""``;
    fall back to ``repr`` and finally the class name so the message is never
    blank.
    """
    message = str(exc).strip()
    if message:
        return message
    rep = repr(exc).strip()
    if rep:
        return rep
    return type(exc).__name__


def first_present(*values: Any) -> Any:
    """Return the first value that is not None and not an empty string."""
    for value in values:
        if value is not None and value != "":
            return value
    return None


def tool_response_envelope(
    tool: str,
    args: Dict[str, Any],
    rows: List[Dict[str, Any]],
    *,
    total_count: Optional[int] = None,
    search_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Wrap a list of rows in a self-describing envelope.

    Lets agents see how much was returned, whether more is available, and which
    search strategy ran without re-asking. ``truncated`` is True when the server
    reports more rows than were returned, or when the page filled exactly to the
    limit and total_count is unknown.
    """
    count = len(rows)
    limit = args.get("limit")
    offset = args.get("offset") or 0
    truncated = (
        offset + count < total_count
        if isinstance(total_count, int)
        else isinstance(limit, int) and count == limit
    )

    return {
        "tool": tool,
        "args": args,
        "count": count,
        "total_count": total_count,
        "truncated": truncated,
        "search": search_info,
        "data": rows,
    }


def format_transaction(txn: Dict[str, Any], extended: bool = False) -> Dict[str, Any]:
    """Format a raw Monarch transaction dict into a consistent output format.

    Args:
        txn: Raw transaction dict from the Monarch API.
        extended: If True, include extra fields like is_split, is_recurring,
                  has_attachments.
    """
    info: Dict[str, Any] = {
        "id": txn.get("id"),
        "date": txn.get("date"),
        "amount": txn.get("amount"),
        "merchant": txn.get("merchant", {}).get("name") if txn.get("merchant") else None,
        "original_name": txn.get("plaidName") or txn.get("originalName"),
        "category": txn.get("category", {}).get("name") if txn.get("category") else None,
        "category_id": txn.get("category", {}).get("id") if txn.get("category") else None,
        "account": txn.get("account", {}).get("displayName") if txn.get("account") else None,
        "account_id": txn.get("account", {}).get("id") if txn.get("account") else None,
        "notes": txn.get("notes"),
        "needs_review": txn.get("needsReview", False),
        "is_pending": txn.get("pending", False),
        "hide_from_reports": txn.get("hideFromReports", False),
        "tags": [
            {"id": tag.get("id"), "name": tag.get("name")}
            for tag in txn.get("tags", [])
        ] if txn.get("tags") else [],
    }

    if extended:
        info["is_split"] = txn.get("isSplitTransaction", False)
        info["is_recurring"] = txn.get("isRecurring", False)
        info["has_attachments"] = bool(txn.get("attachments"))

    return info


def json_success(data: Any) -> str:
    """Serialize *data* to a JSON string for tool responses."""
    return json.dumps(data, indent=2, default=str)


def json_error(tool_name: str, exc: Exception) -> str:
    """Return a consistent JSON error string and log the failure."""
    logger.error(f"Failed in {tool_name}: {exc}")
    return json.dumps(
        {"error": True, "tool": tool_name, "message": format_exception(exc)},
        indent=2,
        default=str,
    )
