"""Shared helpers for Monarch MCP Server tools."""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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


def require_nonblank(value: str, field: str) -> None:
    """Refuse a blank name before it reaches Monarch.

    Monarch makes a merchant out of whatever string it is handed, so a blank
    or whitespace-only name quietly creates a junk merchant record instead of
    failing. Lives here rather than in one tool because the hole belongs to
    the field, not the caller: transactions, merchants and rules all write
    merchant names. Raised, not returned, since every one of those funnels
    exceptions through json_error and a shared validator should not have to
    know which tool called it.
    """
    if not value.strip():
        raise ValueError(f"{field} must not be blank")


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


def payload_errors(
    result: Any, *payload_keys: str
) -> Optional[Dict[str, Any]]:
    """Return a GraphQL payload's ``errors`` object, or None if the write took.

    ``gql_call`` raises on transport errors and on top level GraphQL errors,
    but Monarch rejects a mutation by returning ``errors`` *inside* an HTTP 200
    body. Treating "no exception" as success therefore reports refused writes
    as completed ones, which is worse than an outright failure: the caller
    marks the work done and moves on.

    Pass the payload keys to look under, e.g. ``"updateTransaction"``. With no
    keys, every top level payload in the response is checked.

    Monarch sometimes rejects with an all null error object, which is truthy
    but carries no information, so that is normalised to a readable message.
    """
    if not isinstance(result, dict):
        return None

    candidates = (
        [result.get(key) for key in payload_keys]
        if payload_keys
        else list(result.values())
    )

    for payload in candidates:
        if not isinstance(payload, dict):
            continue
        errors = payload.get("errors")
        if not errors:
            continue
        if isinstance(errors, dict):
            meaningful = {
                k: v
                for k, v in errors.items()
                if k != "__typename" and v is not None
            }
            return meaningful or {"message": "Monarch rejected the request"}
        return {"message": "Monarch rejected the request", "errors": errors}

    return None


def json_rejected(tool_name: str, errors: Dict[str, Any]) -> str:
    """Serialize a payload level rejection as an explicit failure."""
    logger.warning(f"{tool_name} was rejected by Monarch: {errors}")
    return json.dumps(
        {"success": False, "tool": tool_name, "errors": errors},
        indent=2,
        default=str,
    )


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
